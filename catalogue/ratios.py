"""Read ratio evidence and manage its short-lived cache."""
from __future__ import annotations
import catalogue.codecs as catalogue_codecs
import catalogue.snapshots as catalogue_snapshots
import re
import sqlite3

from entity_resolver import ORG_OVERRIDES
from entity_resolver import UNRELIABLE_FINANCIALS
from typing import Any
import catalogue.fields as catalogue_fields
import catalogue.filings as catalogue_filings
import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import os
import threading
import time


def _ticker_org_map(conn: sqlite3.Connection) -> dict[str, str]:
    """ticker → org_id for fact-store joins.

    Precedence: catalog_companies (available before any collector push) →
    pushed collector map (facts dataset ``org_map`` — the same org IDs the
    facts were landed under, and the only map that covers secondary lines like
    a bank's SQB2/HMBK1 issues) → ORG_OVERRIDES on top.
    """
    out: dict[str, str] = {}
    try:
        for r in conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall():
            out[str(r["ticker"]).upper()] = str(r["org_id"])
    except Exception:
        catalogue_settings.logger.exception("catalog_companies org-map read failed")
    try:
        for r in conn.execute(
            "SELECT entity_id, value_num, value_text FROM facts "
            "WHERE dataset='org_map' AND field='org_id'"
        ).fetchall():
            org = (r["value_text"] or "").strip()
            if not org and r["value_num"] is not None:
                org = str(int(r["value_num"]))
            if org:
                out[str(r["entity_id"]).upper()] = org
    except Exception:
        catalogue_settings.logger.exception("org_map facts read failed")
    for ticker, org in ORG_OVERRIDES.items():
        out[ticker] = org
    return out


def _derived_equity(fields: dict[str, float]) -> float | None:
    """Equity for issuers that don't publish it, from one period's indicators.

    The balance identity (assets − liabilities) is the primary source. When the
    period also carries ROE + net_profit, the source's own ROE identity
    (equity = net_profit/ROE·100) must agree within 25%, else the ROE identity
    wins — banks publish indicator "liabilities" that exclude deposits, so an
    unchecked balance difference can overstate their equity ~10×. Validated
    against every issuer that does publish equity: 155/155 periods within 5%.
    """
    bal = None
    assets, liab = fields.get("total_assets"), fields.get("total_liabilities")
    if assets is not None and liab is not None and assets - liab > 0:
        bal = assets - liab
    roe_eq = None
    roe, npf = fields.get("roe"), fields.get("net_profit")
    # |ROE| < 0.1%: the published 2-decimal rounding dominates the estimate.
    if roe and npf is not None and abs(roe) >= 0.1 and npf / roe > 0:
        roe_eq = npf / roe * 100.0
    if bal is not None and roe_eq is not None:
        return bal if abs(bal - roe_eq) / roe_eq <= 0.25 else roe_eq
    return bal if bal is not None else roe_eq


def get_all_ratios() -> dict[str, dict[str, Any]]:
    """Latest per-ticker financial ratios and equity from the fact store
    (openinfo ``financial_indicators``), keyed by ticker.

    Feeds the market-wide multiplier columns (P/E, P/B) and ratio coefficients
    (ТЗ §3.8). Ratios are served exactly as openinfo reports them; equity/assets
    are absolute sums used to derive P/B (= market_cap / equity), with equity
    derived from the same-period balance/ROE identities for the majority of
    issuers that never publish it directly. Unreliable ticker→org matches are
    skipped, mirroring the financials enrichment.
    """
    fetch_fields = tuple(dict.fromkeys(catalogue_fields._RATIO_FIELDS + ("total_liabilities", "net_profit")))
    conn = catalogue_storage.get_catalog_conn()
    try:
        ticker_org = _ticker_org_map(conn)
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(fetch_fields))})",
            fetch_fields,
        ).fetchall()
    except Exception:
        conn.close()
        return {}
    # Долг/Активы also comes off the filings this platform parses itself, and for
    # a BANK that is the only place it exists: the indicator feed publishes no
    # debt_ratio for them, while the company page has shown one for years — from
    # this table. Read it here so the board's column and that page cannot differ
    # on a number they both have. Same precedence as the company page: the
    # filing wins when it covers a year at least as recent as the feed's.
    filed_debt: dict[str, tuple[str, float]] = {}
    try:
        for r in conn.execute(
            "SELECT ticker, year, debt_ratio FROM catalog_ratios "
            "WHERE quarter=0 AND form='NSBU' AND debt_ratio IS NOT NULL"
        ).fetchall():
            t = str(r["ticker"] or "").upper()
            period = str(r["year"])
            cur = filed_debt.get(t)
            if t and (cur is None or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(cur[0])):
                filed_debt[t] = (period, float(r["debt_ratio"]))
    except Exception:
        catalogue_settings.logger.exception("filed debt_ratio read failed")
    # LIQUIDITY AND TURNOVER OFF THE FILINGS. The indicator feed publishes a
    # current ratio and an asset turnover for 56 of the 95 issuers on the board
    # and nothing for the other 39, so three of the four «Коэффициенты» columns
    # were empty for two issuers in five while every one of them files the lines
    # the ratios are made of.
    #
    # These three identities are the source's own, MEASURED against it: over the
    # issuer-years where the feed publishes a value and this platform has parsed
    # the same year's filing (2026-08-17),
    #
    #   current_ratio        = current assets / current liabilities   35 of 38 exact
    #   quick_ratio          = (current assets − stocks) / same       35 of 38 exact
    #   total_asset_turnover = revenue / total assets                 34 of 37 exact
    #
    # to the two decimals the feed publishes. All three misses are BIOK, QZSM and
    # UQEQ, the issuers whose filing years the platform already flags as
    # disagreeing with the feed — not a disagreement about the formula.
    #
    # ROCE is NOT derived. «EBIT / (assets − current liabilities)», the textbook
    # base, reproduces the feed's figure 7 times in 42 — the feed computes it on
    # something it does not name, so it stays exactly as published, blank where
    # the source is silent, rather than being replaced by our own different number
    # under the source's label.
    filed_ratios: dict[str, dict[str, tuple[str, float]]] = {}
    try:
        for r in conn.execute(
            "SELECT ticker, year, quarter, revenue, total_assets, current_assets, "
            "       current_liabilities, inventories "
            "FROM catalog_financials WHERE form='NSBU' "
            "  AND (current_assets IS NOT NULL OR total_assets IS NOT NULL)"
        ).fetchall():
            t = str(r["ticker"] or "").upper()
            if not t:
                continue
            period = _row_period({"year": r["year"], "quarter": r["quarter"]})
            if not period:
                continue
            ca, cl = r["current_assets"], r["current_liabilities"]
            inv, assets, revenue = r["inventories"], r["total_assets"], r["revenue"]
            derived: dict[str, float] = {}
            if ca is not None and cl:
                derived["current_ratio"] = round(ca / cl, 2)
                # Stocks withheld as contradicting their own formula are not
                # nought: the quick ratio is left to the period that states them.
                if inv is not None:
                    derived["quick_ratio"] = round((ca - inv) / cl, 2)
            # A cumulative quarter is three, six or nine months of revenue; over
            # a full-year balance it would read as a business a third the size it
            # is. The turnover comes off ANNUAL rows only — the balance ratios
            # above are point-in-time and any period states them.
            if not r["quarter"] and revenue is not None and assets:
                derived["total_asset_turnover"] = round(revenue / assets, 2)
            for field, value in derived.items():
                slot = filed_ratios.setdefault(t, {})
                if (field not in slot
                        or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(slot[field][0])):
                    slot[field] = (period, value)
    except Exception:
        catalogue_settings.logger.exception("filed liquidity/turnover read failed")
    best: dict[tuple[str, str], tuple[str, float]] = {}
    by_period: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if catalogue_periods._period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period — never a candidate
        # A premature current-year annual (openinfo's in-progress placeholder)
        # must not win "latest period" over a real completed period; _fact_period_rank
        # demotes it so it only surfaces when it is an issuer's sole datum.
        if best.get(key) is None or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(best[key][0]):
            best[key] = (period, r["value_num"])
        by_period.setdefault((str(r["entity_id"]), period), {})[r["field"]] = r["value_num"]
    # Latest derivable equity per org, for issuers with no published figure.
    derived_eq: dict[str, tuple[str, float]] = {}
    # openinfo publishes debt_to_equity_ratio = 0 for many issuers whose own
    # balance figures say otherwise (UTYK: 98.1B liabilities on 222.8B equity,
    # published 0). Derive liabilities/equity per period, but only when the
    # balance identity (assets − liabilities ≈ equity within 25%) holds — for
    # banks the indicator "liabilities" excludes deposits, so a failed identity
    # means the inputs can't be trusted for this (banks publish real D/E anyway).
    derived_de: dict[str, tuple[str, float]] = {}
    for (org, period), fields in by_period.items():
        eq = _derived_equity(fields)
        if eq is None:
            continue
        cur = derived_eq.get(org)
        if cur is None or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(cur[0]):
            derived_eq[org] = (period, eq)
        liab = fields.get("total_liabilities")
        assets = fields.get("total_assets")
        eq_pub = fields.get("total_equity") or eq
        if (liab is not None and liab >= 0 and assets and eq_pub and eq_pub > 0
                and abs((assets - liab) - eq_pub) / eq_pub <= 0.25):
            cur = derived_de.get(org)
            if cur is None or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(cur[0]):
                derived_de[org] = (period, round(liab / eq_pub, 2))
    out: dict[str, dict[str, Any]] = {}
    for ticker, org in ticker_org.items():
        if ticker in UNRELIABLE_FINANCIALS:
            continue
        entry: dict[str, Any] = {}
        latest_period = None
        # Per-FIELD periods, not only the newest one across them: an issuer can
        # publish its liquidity for 2023 and its ROE for 2025, and a single
        # label over both would state a year the store never said.
        field_periods: dict[str, str] = {}
        for field in catalogue_fields._RATIO_FIELDS:
            hit = best.get((org, field))
            if hit is not None:
                entry[field] = hit[1]
                field_periods[field] = hit[0]
                if latest_period is None or catalogue_periods._fact_period_rank(hit[0]) > catalogue_periods._fact_period_rank(latest_period):
                    latest_period = hit[0]
        if entry and entry.get("total_equity") is None:
            hit = derived_eq.get(org)
            if hit is not None:
                entry["total_equity"] = hit[1]
                field_periods["total_equity"] = hit[0]
                if latest_period is None or catalogue_periods._fact_period_rank(hit[0]) > catalogue_periods._fact_period_rank(latest_period):
                    latest_period = hit[0]
        if entry and not entry.get("debt_to_equity"):
            hit = derived_de.get(org)
            if hit is not None:
                entry["debt_to_equity"] = hit[1]
                field_periods["debt_to_equity"] = hit[0]
        if entry:
            # A filing lands under whichever share class it was catalogued
            # under, so a preferred line reads its ordinary sibling's — the
            # same fallback the annual series and the company page apply.
            sibling = ticker[:-1] if ticker.endswith("P") else f"{ticker}P"
            hit = filed_debt.get(ticker) or filed_debt.get(sibling)
            filed_wins = hit is not None and (
                "debt_ratio" not in field_periods
                or catalogue_periods._fact_period_rank(hit[0]) >= catalogue_periods._fact_period_rank(field_periods["debt_ratio"]))
            if filed_wins:
                entry["debt_ratio"] = hit[1]
                field_periods["debt_ratio"] = hit[0]
            # Liquidity and turnover, same precedence and same sibling fallback:
            # the filing wins when it covers a period at least as recent as the
            # feed's, and fills the field outright where the feed has nothing.
            for field, hit in (filed_ratios.get(ticker)
                               or filed_ratios.get(sibling) or {}).items():
                if (field not in field_periods
                        or catalogue_periods._fact_period_rank(hit[0]) >= catalogue_periods._fact_period_rank(field_periods[field])):
                    entry[field] = hit[1]
                    field_periods[field] = hit[0]
                    if (latest_period is None
                            or catalogue_periods._fact_period_rank(hit[0]) > catalogue_periods._fact_period_rank(latest_period)):
                        latest_period = hit[0]
        if entry:
            entry["period"] = latest_period
            entry["periods"] = field_periods
            out[ticker] = entry
    conn.close()
    return out


def _row_period(fin: dict[str, Any]) -> str | None:
    """The fact-store period string a financials row is labelled with.

    ``{'year': 2024, 'quarter': 0}`` -> ``'2024'`` (annual); quarter 1-4 ->
    ``'2024Q1'``. Returns None when the row carries no usable year.
    """
    year = fin.get("year")
    if not isinstance(year, int) or year <= 0:
        return None
    quarter = fin.get("quarter") or 0
    return f"{year}Q{quarter}" if 1 <= quarter <= 4 else str(year)


def get_sector_averages(sector_tickers: list[str], form: str, year: int) -> dict[str, Any]:
    if not sector_tickers:
        return {}
    conn = catalogue_storage.get_catalog_conn()
    placeholders = ",".join("?" * len(sector_tickers))
    row = conn.execute(
        f"""
        SELECT AVG(roa) as roa, AVG(roe) as roe, AVG(net_margin) as net_margin,
               AVG(debt_ratio) as debt_ratio, AVG(debt_to_equity) as debt_to_equity,
               COUNT(*) as n
        FROM catalog_ratios
        WHERE ticker IN ({placeholders}) AND form=? AND year=? AND quarter=0
        """,
        (*sector_tickers, form, year),
    ).fetchone()
    conn.close()
    if not row or not row["n"]:
        return {}
    return {
        "ROA": round(row["roa"], 2) if row["roa"] is not None else None,
        "ROE": round(row["roe"], 2) if row["roe"] is not None else None,
        "net_margin": round(row["net_margin"], 2) if row["net_margin"] is not None else None,
        "debt_ratio": round(row["debt_ratio"], 2) if row["debt_ratio"] is not None else None,
        "debt_to_equity": round(row["debt_to_equity"], 2) if row["debt_to_equity"] is not None else None,
        "n": row["n"],
    }


def get_company_ratios_cached(ticker: str) -> dict[str, Any]:
    """Return most recent cached ratios for a ticker."""
    conn = catalogue_storage.get_catalog_conn()
    # Same period ranking as get_all_financials / _period_key: an annual is stored
    # with quarter = 0 but ranks as the year's FINAL figure, so plain
    # "ORDER BY quarter DESC" handed Q1 the win over its own completed annual.
    row = conn.execute("""
        SELECT year, quarter, form, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at
        FROM catalog_ratios
        WHERE ticker = ?
          AND quarter BETWEEN 0 AND 4
          AND NOT (quarter = 0 AND year > ?)
        ORDER BY year DESC,
                 CASE WHEN quarter = 0 THEN 5 ELSE quarter END DESC,
                 updated_at DESC
        LIMIT 1
    """, (ticker, catalogue_periods._latest_complete_fiscal_year())).fetchone()
    conn.close()
    if not row:
        return {}
    metrics = {}
    if row["roa"] is not None:
        metrics["ROA"] = row["roa"]
    if row["roe"] is not None:
        metrics["ROE"] = row["roe"]
    if row["net_margin"] is not None:
        metrics["net_margin"] = row["net_margin"]
    if row["debt_ratio"] is not None:
        metrics["debt_ratio"] = row["debt_ratio"]
    if row["debt_to_equity"] is not None:
        metrics["debt_to_equity"] = row["debt_to_equity"]
    # Book equity for P/B. catalog_ratios stores only the coefficients, so this
    # comes from the same fact-store logic the market-wide endpoint uses — the
    # company page previously had no equity feed at all and fell back to the
    # P/E x ROE identity, which is undefined for loss-makers and therefore
    # disagreed with the market table on exactly those issuers.
    return {
        "year": row["year"], "quarter": row["quarter"], "form": row["form"],
        "metrics": metrics,
        "total_equity": _company_equity(ticker),
    }


def _company_equity(ticker: str) -> float | None:
    """Latest book equity for one ticker, in full UZS.

    Deliberately reuses :func:`get_all_ratios` rather than re-deriving equity from
    a narrower query: the derivation (published figure, else the balance identity,
    else the ROE identity, all per-period) is subtle, and a second copy of it is
    how the P/E–P/B divergence happened in the first place. The result is memoized
    so a per-company call does not repeat the scan.
    """
    try:
        entry = _ratios_cached().get(str(ticker or "").upper()) or {}
    except Exception:
        catalogue_settings.logger.exception("equity lookup failed for %s", ticker)
        return None
    equity = entry.get("total_equity")
    if not isinstance(equity, (int, float)):
        return None
    return float(equity) * catalogue_fields.NSBU_THOUSANDS_UZS


_RATIOS_CACHE_TTL_SECONDS = int(os.getenv("RATIOS_CACHE_TTL_SECONDS", "60"))


_ratios_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


_ratios_cache_lock = threading.Lock()


def _ratios_cached() -> dict[str, dict[str, Any]]:
    global _ratios_cache
    now = time.monotonic()
    with _ratios_cache_lock:
        if _ratios_cache is not None and now - _ratios_cache[0] < _RATIOS_CACHE_TTL_SECONDS:
            return _ratios_cache[1]
    fresh = get_all_ratios()
    with _ratios_cache_lock:
        _ratios_cache = (now, fresh)
    return fresh


def invalidate_ratios_cache() -> None:
    """Drop the memo — called after any write that changes the fact store."""
    global _ratios_cache
    with _ratios_cache_lock:
        _ratios_cache = None


def _cached_balance(balance_period: Any, total_assets: Any,
                    total_equity: Any) -> dict[str, Any] | None:
    """Return the latest period's balance, including legacy top-level totals.

    Older collector rows (and OpenInfo's indicator-backed bank rows) stored the
    closing assets/equity in dedicated columns before ``balance_period`` was
    introduced.  Ignoring those same-period official values made P/B, BVPS,
    ROE and ROA appear missing even though the database already held them.
    Opening values stay unknown; we never copy a closing value into the start.
    """
    balance = dict(catalogue_codecs._decode_balance_period(balance_period) or {})
    if catalogue_codecs._financials_num(balance.get("assets_end")) is None:
        balance["assets_end"] = catalogue_codecs._financials_num(total_assets)
    if catalogue_codecs._financials_num(balance.get("equity_end")) is None:
        balance["equity_end"] = catalogue_codecs._financials_num(total_equity)
    for key in catalogue_codecs._BALANCE_BASE_KEYS:
        balance.setdefault(key, None)
    return balance if any(value is not None for value in balance.values()) else None


def get_all_ratios_cached() -> dict[str, dict[str, Any]]:
    """`get_all_ratios` through the short memo that every fact-store and
    catalog_ratios write invalidates. Callers must not mutate the result."""
    return _ratios_cached()


_CATALOG_ANALYSIS_VALUE_KEYS = (
    "revenue", "net_income", "total_assets", "total_equity",
    "total_liabilities", "gross_profit", "operating_income", "operating_expenses",
    "cash", "current_assets", "current_liabilities", "inventories",
)

# The statement lines a period's validity and identity are judged on.
_CATALOG_MONEY_KEYS = (
    "revenue", "net_income", "total_assets", "total_equity", "total_liabilities",
    "gross_profit", "operating_income", "operating_expenses", "cash",
)


def catalog_period_months(quarter: int | None) -> int:
    """Months a period's flows cover: NSBU and IFRS interims are cumulative YTD."""
    quarter = int(quarter or 0)
    return quarter * 3 if 1 <= quarter <= 4 else 12


def catalog_period_problem(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Why a stored period must not be analysed, or None when it can be.

    Three shapes of a filing that carries no usable statement, each seen in the
    catalogue: every line nought (UZNGP's «2025» workbook is an empty form);
    a balance whose total is nought or negative (SQBN's 2024 annual states
    «Итого активов 0»); and the form's line numbers typed into the amount
    column (the same SQBN filing: «Итого процентных доходов 1», «Чистая прибыль
    13») — every amount below the plausibility floor the fact store already
    applies to such rows.
    """
    if not row:
        return {"code": "missing"}
    money = [catalogue_codecs._financials_num(row.get(key)) for key in _CATALOG_MONEY_KEYS]
    money = [value for value in money if value is not None]
    if not money or not any(money):
        return {"code": "empty_filing"}
    assets = catalogue_codecs._financials_num(row.get("total_assets"))
    if assets is not None and assets <= 0:
        return {"code": "no_balance"}
    if max(abs(value) for value in money) < catalogue_fields._MIN_PLAUSIBLE:
        return {"code": "implausible_scale"}
    return None


def catalog_duplicate_periods(series: dict[str, dict[str, Any]],
                              filed: set[str] | None = None) -> dict[str, str]:
    """Periods whose figures are another period's copy: ``{copy: original}``.

    A filing catalogued under one year and later under another leaves its
    figures behind under the first label, so two «years» agree to the sum on
    every line (the company page drops the same ghosts; UZNGP's «2025» carries
    another year's statement). Two real reporting periods do not agree on three
    or more lines at once. Which of the pair is the copy: the one without a
    filing of its own when the registry can tell (``filed``), otherwise the
    later label — a statement cannot describe a year before that year existed.
    """
    usable = {period: row for period, row in (series or {}).items()
              if catalog_period_problem(row) is None}
    ordered = sorted(usable)
    copies: dict[str, str] = {}
    for index, first in enumerate(ordered):
        if first in copies:
            continue
        for second in ordered[index + 1:]:
            if second in copies:
                continue
            pairs = [(catalogue_codecs._financials_num(usable[first].get(key)),
                      catalogue_codecs._financials_num(usable[second].get(key)))
                     for key in _CATALOG_MONEY_KEYS]
            both = [(a, b) for a, b in pairs if a is not None and b is not None]
            if len(both) < 3 or not all(a == b for a, b in both) or not any(a for a, _ in both):
                continue
            if filed is not None and (first in filed) != (second in filed):
                copy, original = (second, first) if first in filed else (first, second)
            else:
                copy, original = second, first
            copies[copy] = original
            if copy == first:
                break
    return copies


def _filed_periods(ticker: str, form: str) -> set[str] | None:
    """Periods with a filing of their own in the report registry."""
    try:
        reports = catalogue_filings.get_company_reports(ticker) or []
    except Exception:  # noqa: BLE001 — without the registry the later label is the copy
        catalogue_settings.logger.exception("catalog: report registry read failed for %s", ticker)
        return None
    filed: set[str] = set()
    for report in reports:
        if report.get("report_form") != form or not report.get("year"):
            continue
        quarter = int(report.get("quarter") or 0)
        filed.add(f"{report['year']}Q{quarter}" if quarter else str(report["year"]))
    return filed


def _cached_catalog_ratio_payload(row: dict[str, Any] | None, months: int = 12) -> dict[str, Any]:
    """Build the legacy catalog ratio shape from one cached filing row.

    The catalog UI predates the filing cache and expects ``metrics`` plus
    ``source_values``.  Keeping that response contract lets analysis use the
    already-collected, source-linked figures instead of downloading the same
    OpenInfo workbook on every button click (which is blocked from production
    datacenter IPs).

    Interim flows are year-to-date, so a return on assets or equity built from
    a half-year is half a year's return. Both are stated per year
    (× 12 / months) and the payload says so; margins divide a flow by a flow
    and need no scaling.
    """
    row = dict(row or {})
    values = {key: catalogue_codecs._financials_num(row.get(key)) for key in _CATALOG_ANALYSIS_VALUE_KEYS}
    balance = row.get("balance") if isinstance(row.get("balance"), dict) else {}
    assets = values.get("total_assets")
    equity = values.get("total_equity")
    liabilities = values.get("total_liabilities")
    if assets is None:
        assets = catalogue_codecs._financials_num(balance.get("assets_end"))
    if equity is None:
        equity = catalogue_codecs._financials_num(balance.get("equity_end"))
    if equity is None and assets is not None and liabilities is not None:
        equity = assets - liabilities
    if liabilities is None and assets is not None and equity is not None:
        liabilities = assets - equity
    values["total_assets"] = assets
    values["total_equity"] = equity
    values["total_liabilities"] = liabilities
    months = months if months in (3, 6, 9, 12) else 12
    scale = 12 / months

    def pct(numerator: float | None, denominator: float | None, factor: float = 1.0) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        return round(numerator / denominator * 100 * factor, 2)

    def multiple(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        return round(numerator / denominator, 4)

    def stored(key: str) -> float | None:
        # A stored coefficient is the annual filing's own; an interim one would
        # be a year-to-date return and is recomputed from the sums instead.
        return catalogue_codecs._financials_num(row.get(key)) if months == 12 else None

    net_income = values.get("net_income")
    revenue = values.get("revenue")
    roa = pct(net_income, assets, scale)
    roe = pct(net_income, equity, scale) if equity is None or equity > 0 else None
    metrics = {
        "ROA": roa if roa is not None else stored("roa"),
        "ROE": roe if roe is not None else stored("roe"),
        "net_margin": pct(net_income, revenue),
        "debt_ratio": pct(liabilities, assets) if pct(liabilities, assets) is not None else stored("debt_ratio"),
        "debt_to_equity": (multiple(liabilities, equity) if equity is not None and equity > 0
                           else stored("debt_to_equity")),
    }
    source_values = {
        "revenue": revenue,
        "net_income": net_income,
        "total_assets": assets,
        "equity": equity,
        "total_liabilities": liabilities,
    }
    return {"metrics": metrics, "source_values": source_values,
            "all_values": values, "period_months": months, "annualized": months != 12,
            "has_data": any(value is not None for value in values.values())}


def _catalog_series(ticker: str, form: str, quarterly: bool) -> dict[str, dict[str, Any]]:
    return (catalogue_snapshots.get_financials_series_quarterly(ticker, form)
            if quarterly else catalogue_snapshots.get_financials_series(ticker, form)) or {}


def get_cached_catalog_period(ticker: str, form: str, year: int,
                              quarter: int = 0) -> dict[str, Any]:
    """Return one exact filing period from the local financial cache.

    A period the store holds but which carries no usable statement — an empty
    or line-number filing, a balance without assets, another period's copy —
    comes back with ``has_data`` False and the reason, so no lens can publish
    it as that period's figures.
    """
    empty = {"metrics": {}, "source_values": {}, "all_values": {}, "has_data": False}
    if form not in {"NSBU", "MSFO"}:
        return empty
    quarter = int(quarter or 0)
    period = f"{int(year)}Q{quarter}" if quarter else str(int(year))
    series = _catalog_series(ticker, form, bool(quarter))
    row = series.get(period)
    payload = {"period": period, **_cached_catalog_ratio_payload(row, catalog_period_months(quarter))}
    if row is None:
        return payload
    problem = catalog_period_problem(row)
    if problem is None:
        original = catalog_duplicate_periods(series, _filed_periods(ticker, form)).get(period)
        if original:
            problem = {"code": "duplicate_period", "duplicate_of": original}
    if problem:
        catalogue_settings.logger.info("catalog: %s %s %s withheld — %s", ticker, form, period, problem)
        return {**payload, "has_data": False, "unavailable": problem}
    return payload


def latest_cached_catalog_period(ticker: str, form: str, *, annual_only: bool = False,
                                 not_after: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """(year, quarter) of the newest usable period, optionally capped."""
    candidates: list[tuple[int, int]] = []
    sources = [(False, _catalog_series(ticker, form, False))]
    if not annual_only:
        sources.append((True, _catalog_series(ticker, form, True)))
    for quarterly, series in sources:
        copies = catalog_duplicate_periods(series)
        for period, row in series.items():
            match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", str(period))
            if not match or period in copies or catalog_period_problem(row) is not None:
                continue
            key = (int(match.group(1)), int(match.group(2) or 0))
            if quarterly and key[1] == 0:
                continue
            candidates.append(key)
    rank = lambda key: (key[0], key[1] or 5)  # noqa: E731 — an annual closes its year
    if not_after is not None:
        candidates = [key for key in candidates if rank(key) <= rank(not_after)]
    return max(candidates, key=rank, default=None)


def build_cached_catalog_dynamics(ticker: str, form: str = "NSBU") -> dict[str, Any]:
    """Build annual and quarterly catalog dynamics without upstream I/O.

    Periods with no usable statement and copies of another period are left out
    of the series and listed in ``excluded_periods`` with the reason; a year of
    zeros or line numbers drawn into a chart is a fabricated collapse.
    """
    if form not in {"NSBU", "MSFO"}:
        return {"ticker": ticker, "form": form, "years": [], "series": {},
                "quarterly": [], "excluded_periods": [],
                "seasonality": {"metric": "revenue", "years_covered": 0,
                                "insufficient": True, "quarter_avg": {}}}
    excluded: list[dict[str, Any]] = []
    filed = _filed_periods(ticker, form)

    def usable(series: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        copies = catalog_duplicate_periods(series, filed)
        kept = {}
        for period, row in series.items():
            problem = catalog_period_problem(row)
            if problem is None and period in copies:
                problem = {"code": "duplicate_period", "duplicate_of": copies[period]}
            if problem:
                excluded.append({"period": str(period), **problem})
            else:
                kept[period] = row
        return kept

    annual_source = usable(catalogue_snapshots.get_financials_series(ticker, form) or {})
    annual_items = sorted(
        ((int(year), _cached_catalog_ratio_payload(row))
         for year, row in annual_source.items() if str(year).isdigit()),
        key=lambda item: item[0],
    )
    annual_items = [(year, payload) for year, payload in annual_items if payload["has_data"]]
    years = [year for year, _ in annual_items]
    series = {
        key: [payload["source_values"].get(key) for _, payload in annual_items]
        for key in ("revenue", "net_income", "total_assets", "equity", "total_liabilities")
    }

    quarterly_source = usable(catalogue_snapshots.get_financials_series_quarterly(ticker, form) or {})
    parsed_quarters: list[tuple[int, int, dict[str, Any]]] = []
    for period, row in quarterly_source.items():
        match = re.fullmatch(r"(\d{4})Q([1-4])", str(period))
        if not match:
            continue
        payload = _cached_catalog_ratio_payload(row, catalog_period_months(int(match.group(2))))
        if payload["has_data"]:
            parsed_quarters.append((int(match.group(1)), int(match.group(2)), payload))
    parsed_quarters.sort(key=lambda item: (item[0], item[1]))
    parsed_quarters = parsed_quarters[-16:]
    quarterly: list[dict[str, Any]] = []
    ytd: dict[tuple[int, int], dict[str, float | None]] = {}
    for year, quarter, payload in parsed_quarters:
        values = payload["source_values"]
        entry: dict[str, Any] = {"label": f"Q{quarter} {year}", "year": year, "quarter": quarter}
        for key in ("revenue", "net_income", "total_assets", "equity", "total_liabilities"):
            entry[key] = values.get(key)
        for key in ("revenue", "net_income"):
            entry[f"{key}_ytd"] = entry.get(key)
        ytd[(year, quarter)] = {key: entry.get(f"{key}_ytd") for key in ("revenue", "net_income")}
        quarterly.append(entry)
    for entry in quarterly:
        for key in ("revenue", "net_income"):
            value = entry.get(f"{key}_ytd")
            if not isinstance(value, (int, float)):
                entry[key] = None
            elif entry["quarter"] > 1:
                prior = ytd.get((entry["year"], entry["quarter"] - 1), {}).get(key)
                entry[key] = round(value - prior, 2) if isinstance(prior, (int, float)) else None

    by_quarter: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    covered_years: set[int] = set()
    for entry in quarterly:
        value = entry.get("revenue")
        if isinstance(value, (int, float)):
            by_quarter[entry["quarter"]].append(float(value))
            covered_years.add(entry["year"])
    seasonality = {
        "metric": "revenue",
        "years_covered": len(covered_years),
        "insufficient": len(covered_years) < 3,
        "quarter_avg": {
            quarter: (round(sum(values) / len(values), 2) if values else None)
            for quarter, values in by_quarter.items()
        },
    }
    excluded.sort(key=lambda item: item["period"])
    return {"ticker": ticker, "form": form, "years": years, "series": series,
            "quarterly": quarterly, "seasonality": seasonality,
            "excluded_periods": excluded}
