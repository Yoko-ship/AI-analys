"""fundamentals.py — validated statements and ISSUER-level multiples.

ТЗ v1.2 §7/§8. Two rules govern everything here.

**A multiple belongs to the issuer, not to a share class.** Capitalisation is the
sum over every class an issuer has listed; profit and equity are the issuer's.
Dividing ONE class's capitalisation by the WHOLE issuer's profit is what let KFSK
show P/E 203.6 and KFSKP 0.19 off one profit of 96.7 bn. The catalog here has 16
such two-class issuers (AGBA/AGBAP, UZMK/UZMKP, SQBN/SQBNP…), and by construction
no pair of them could agree. Price, change, volume and the class's own
capitalisation stay class-specific; P/E, P/B, ROE, ROA, margin and D/E do not.

**A number that cannot be true is not displayed as a number.** Statements are
checked for internal consistency before anything divides by them: 7 of 89 cached
rows fail (TGPG reports gross profit −1.5 bn on revenue 615 mn and a net loss of
3.25 bn; KSCM and UZNGP report gross 30 and net 270 on revenue 10). Those rows
are marked and shown as «данные проверяются», never as a figure.

Everything is a pure function of its arguments — no database, no HTTP — so the
market screen, the company card and the export share one implementation.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Iterable, Sequence

from formulas import _metric, _num, thresholds

logger = logging.getLogger(__name__)

# Statuses a multiple can carry instead of a value (ТЗ §10.4.3).
STATUS_OK = "ok"
STATUS_LOSS = "loss_making"
STATUS_OUT_OF_RANGE = "out_of_range"
STATUS_STALE = "stale_period"
STATUS_NO_FINANCIALS = "no_financials"
STATUS_UNVERIFIED = "unverified"          # «данные проверяются»
STATUS_INCONSISTENT = "shares_inconsistent"


# ---------------------------------------------------------------------------
# Reporting periods
# ---------------------------------------------------------------------------

def period_months(fin: dict[str, Any] | None) -> int | None:
    """Months of activity a P&L row covers. NSBU quarterlies accumulate from
    1 January, so Q2 is six months of trading, not three."""
    if not fin:
        return None
    months = _num(fin.get("period_months"))
    if months and months > 0:
        return int(months)
    quarter = _num(fin.get("quarter"))
    if quarter and quarter > 0:
        return int(quarter) * 3
    return 12 if fin.get("year") else None


def period_label(fin: dict[str, Any] | None) -> str | None:
    if not fin or not fin.get("year"):
        return None
    quarter = _num(fin.get("quarter"))
    return f"{int(fin['year'])}Q{int(quarter)}" if quarter else f"{int(fin['year'])}A"


def parse_period(text: Any) -> tuple[int, int] | None:
    """"2025", "2025A", "2025Q2", "2026-Q1" -> (year, months)."""
    s = str(text or "").strip().upper()
    m = re.match(r"^(\d{4})[-\s]?Q([1-4])$", s)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3
    m = re.match(r"^(\d{4})A?$", s)
    if m:
        return int(m.group(1)), 12
    return None


def annualise(value: float | None, months: int | None) -> float | None:
    """A cumulative flow scaled to twelve months.

    Only ever used to make a SORT comparable (ТЗ §7); the displayed figure keeps
    its own period and label. Sorting raw cumulative quarters against annuals is
    how a column ordered "by revenue" put a full year above a peer's four
    quarters for no reason a reader could see.
    """
    if value is None or not months or months <= 0:
        return None
    return value * 12.0 / months


def comparable_period(financials: dict[str, dict[str, Any]]) -> tuple[int, int] | None:
    """The latest (year, months) every issuer in the set can report.

    ТЗ §7: one period for the whole column when such a period exists. Across the
    cached catalog the rows span twelve distinct (year, months) combinations, so
    in practice this returns None and each cell carries its own period label
    while the sort runs on the 12-month normalisation.
    """
    combos: list[set[tuple[int, int]]] = []
    for fin in financials.values():
        if not fin or not fin.get("year"):
            continue
        available = {(int(fin["year"]), period_months(fin) or 12)}
        annual = fin.get("annual")
        if annual and annual.get("year"):
            available.add((int(annual["year"]), 12))
        combos.append(available)
    if not combos:
        return None
    shared = set.intersection(*combos) if len(combos) > 1 else combos[0]
    return max(shared) if shared else None


# ---------------------------------------------------------------------------
# Statement validation (ТЗ §7)
# ---------------------------------------------------------------------------

def validate_statement(fin: dict[str, Any] | None,
                       ratio: dict[str, Any] | None = None) -> dict[str, Any]:
    """Is this statement internally consistent enough to publish?

    Returns ``{"valid": bool, "status": str, "reasons": [...], "fields": {...}}``
    where ``fields`` names the individual lines that failed, so the table can
    suppress one cell rather than the whole row where that is enough.
    """
    cfg = thresholds()["financials"]
    reasons: list[str] = []
    fields: dict[str, list[str]] = {}
    if not fin:
        return {"valid": False, "status": STATUS_NO_FINANCIALS, "reasons": [], "fields": {}}

    revenue = _num(fin.get("revenue"))
    gross = _num(fin.get("gross_profit"))
    net = _num(fin.get("net_income"))
    liabilities = _num(fin.get("total_liabilities"))
    assets = _num((ratio or {}).get("total_assets"))
    equity = _num((ratio or {}).get("total_equity"))
    months = period_months(fin)

    if revenue is not None and revenue < 0:
        reasons.append("выручка отрицательна")
        fields.setdefault("revenue", []).append("negative_revenue")

    if revenue is not None and gross is not None and revenue > 0:
        if abs(gross) > abs(revenue) * float(cfg["gross_profit_vs_revenue_max"]):
            reasons.append("валовая прибыль больше выручки")
            fields.setdefault("gross_profit", []).append("gross_gt_revenue")

    if revenue is not None and net is not None and revenue > 0:
        if abs(net) > abs(revenue) * float(cfg["net_income_vs_revenue_max"]):
            reasons.append("чистая прибыль больше выручки в 1,5 раза")
            fields.setdefault("net_income", []).append("net_gt_revenue")

    # Liabilities and assets come from two different filings — the NSBU statement
    # and openinfo's financial_indicators — and the second is often a different
    # year. Comparing across periods flags healthy issuers (ALKB's 2025 statement
    # against 2025 indicators is fine; its 2019 ones are not), so the check only
    # runs when both describe the SAME year.
    ratio_period = parse_period((ratio or {}).get("period"))
    same_period = bool(ratio_period and fin.get("year") and ratio_period[0] == int(fin["year"]))
    if same_period and assets is not None and liabilities is not None and assets > 0:
        if liabilities > assets * float(cfg["liabilities_vs_assets_max"]):
            reasons.append("обязательства превышают активы")
            fields.setdefault("total_liabilities", []).append("liab_gt_assets")

    if equity is not None and equity <= 0:
        reasons.append("собственный капитал не положителен")
        fields.setdefault("total_equity", []).append("equity_not_positive")

    # The strongest available cross-check on units: the profit in the statement,
    # divided by the published equity, must land near the published ROE. ALKB's
    # stored net income implies a 3 038 % return against a reported 6.54 % — a
    # factor-of-1000 parsing error, exactly the class of defect ТЗ §2.2 opens
    # with. Period differences move this by a few times, never by hundreds, so
    # the bound is deliberately loose.
    # Only a full year against the SAME year's indicators: a Q1 profit measured
    # against an annual ROE differs by four for a perfectly healthy issuer, and
    # against a three-year-old ROE by anything at all. Gated this way the check
    # fires on ALKB (465x), GRBK (44x), AGBA (34x), TNBN (21x) and TNGB (9x) and
    # leaves sound issuers alone (HMKB 2.3x, QZSM 0.9x).
    published_roe = _num((ratio or {}).get("roe"))
    if (same_period and months == 12
            and net is not None and equity is not None and equity > 0
            and published_roe is not None and abs(published_roe) >= 0.5):
        implied = net / equity * 100.0
        scale = float(cfg["roe_implied_vs_published_max"])
        if implied != 0 and (abs(implied / published_roe) > scale
                             or abs(published_roe / implied) > scale):
            reasons.append("прибыль не согласуется с капиталом и опубликованной ROE")
            fields.setdefault("net_income", []).append("net_vs_equity_roe")

    # A cumulative period scaled to a year must land near the issuer's own annual.
    annual = fin.get("annual")
    if annual and months and months < 12:
        annual_net = _num(annual.get("net_income"))
        scaled = annualise(net, months)
        if annual_net and scaled and annual_net != 0:
            ratio_ = abs(scaled / annual_net)
            limit = float(cfg["half_year_vs_annual_max"])
            if ratio_ > limit or ratio_ < 1.0 / limit:
                reasons.append("период не согласуется с годовым отчётом")
                fields.setdefault("net_income", []).append("period_vs_annual")

    valid = not reasons
    return {
        "valid": valid,
        "status": STATUS_OK if valid else STATUS_UNVERIFIED,
        "reasons": reasons,
        "fields": fields,
        "period": period_label(fin),
        "months": months,
    }


# ---------------------------------------------------------------------------
# Issuers and share classes
# ---------------------------------------------------------------------------

_LEGAL_NOISE = re.compile(
    r"\b(a[oj]|оаo|оао|аo|ао|мчj|мчж|ооо|оoо|ndj|ajl|pjsc|jsc|llc|atb|aj|ndm)\b", re.I)


def issuer_key(security: dict[str, Any]) -> str:
    """Which issuer a listed security belongs to.

    The legal name is the join key: it is the only field both share classes of an
    issuer actually share (their tickers, ISINs and registry ids all differ).
    Punctuation, legal-form words and the Latin/Cyrillic spelling of the same name
    are normalised away, because the registry writes them inconsistently.
    """
    name = str(security.get("name") or "").strip().lower()
    name = name.replace("ʻ", "'").replace("‘", "'").replace("’", "'").replace("`", "'")
    name = _LEGAL_NOISE.sub(" ", name)
    name = re.sub(r"[^a-zа-яё0-9]+", "", name)
    if name:
        return name
    ticker = str(security.get("ticker") or "").upper()
    # Fall back to the ticker convention: a preferred class is the ordinary
    # ticker plus P.
    return ticker[:-1] if ticker.endswith("P") and len(ticker) > 1 else ticker


def group_by_issuer(securities: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """{issuer_key: [class rows]}, bonds excluded — a bond is not equity and
    carries no claim on earnings, so it may not enter a capitalisation."""
    out: dict[str, list[dict[str, Any]]] = {}
    for sec in securities:
        if str(sec.get("type") or "").lower() == "bond":
            continue
        out.setdefault(issuer_key(sec), []).append(sec)
    return out


def market_cap_issuer(classes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Capitalisation summed over every share class of one issuer (ТЗ §8).

    Null when any class's capitalisation is unknown: a partial sum divided into
    a whole issuer's profit is a wrong P/E, not an approximate one.
    """
    total = 0.0
    missing: list[str] = []
    for cls in classes:
        cap = _num(cls.get("market_cap"))
        if cap is None or cap <= 0:
            missing.append(str(cls.get("ticker") or "?"))
        else:
            total += cap
    if missing:
        return _metric(None, "incomplete", missing_classes=missing,
                       note="капитализация известна не по всем классам")
    return _metric(total, STATUS_OK, classes=[str(c.get("ticker")) for c in classes])


def bvps_issuer(classes: Sequence[dict[str, Any]], equity: float | None) -> dict[str, Any]:
    """Book value per share — ONE figure per issuer, over every class's shares.

    ТЗ §8 observes that BVPS "computed from total equity" differs between the
    classes of one issuer (ALKB 1.05 against ALKBP 1042.5) and treats the gap as
    the defect. The gap is real but the arithmetic that produced it is not: total
    equity divided by ONE class's share count is not that class's book value, and
    it differs between classes whenever the classes differ in size — which is
    ordinary, not a fault. Equity backs every share the issuer has issued, so the
    denominator is every share. That is also the only form the ratio is
    comparable across issuers in.
    """
    total = 0.0
    missing: list[str] = []
    for cls in classes:
        shares = _num(cls.get("shares_outstanding"))
        if shares and shares > 0:
            total += shares
        else:
            missing.append(str(cls.get("ticker") or "?"))
    if missing or total <= 0 or not equity or equity <= 0:
        return _metric(None, "no_share_count" if missing else STATUS_NO_FINANCIALS,
                       missing_classes=missing or None)
    return _metric(equity / total, STATUS_OK, shares_outstanding=total)


def share_count_consistency(classes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Does each class's capitalisation equal its price times its share count?

    This is the check that actually catches what ТЗ §8 saw. A capitalisation and
    a share count that disagree with the quoted price by a factor of a thousand
    are a units error — the registry recording "thousands of shares" — and any
    multiple built on either number inherits it. Comparing the two figures the
    exchange itself publishes needs no external reference and cannot be confused
    by one class simply being larger than another.
    """
    cfg = thresholds()["multiples"]
    tolerance = float(cfg["cap_vs_price_shares_max"])
    findings: list[dict[str, Any]] = []
    for cls in classes:
        cap = _num(cls.get("market_cap"))
        price = _num(cls.get("last_price"))
        shares = _num(cls.get("shares_outstanding"))
        if not (cap and price and shares) or min(cap, price, shares) <= 0:
            continue
        implied = price * shares
        ratio = cap / implied
        if ratio > tolerance or ratio < 1.0 / tolerance:
            findings.append({
                "ticker": str(cls.get("ticker")), "ratio": ratio,
                "market_cap": cap, "price_times_shares": implied,
                # The pathology ТЗ names by number: "ровно тысячекратно".
                "looks_like_thousands": abs(math.log10(ratio)) > 2.5,
            })
    return {"consistent": not findings, "findings": findings}


# ---------------------------------------------------------------------------
# Multiples (ТЗ §8)
# ---------------------------------------------------------------------------

def _ranged(value: float | None, low: float, high: float, **extra: Any) -> dict[str, Any]:
    if value is None:
        return _metric(None, STATUS_NO_FINANCIALS)
    if not (low <= value <= high):
        return _metric(None, STATUS_OUT_OF_RANGE, computed=value,
                       allowed=[low, high], **extra)
    return _metric(value, STATUS_OK, **extra)


def issuer_multiples(classes: Sequence[dict[str, Any]],
                     fin: dict[str, Any] | None,
                     ratio: dict[str, Any] | None,
                     earnings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every multiple for one issuer — identical for all of its share classes.

    ``earnings`` lets the caller pass the 12-month profit it selected (the last
    complete fiscal year when the latest filing is a cumulative quarter); without
    it the row's own net income is used and its period is reported as-is.
    """
    cfg = thresholds()["multiples"]
    ratio = ratio or {}
    validation = validate_statement(fin, ratio)

    cap = market_cap_issuer(classes)
    equity = _num(ratio.get("total_equity"))
    net_income = _num((earnings or {}).get("net_income"))
    base_period = (earnings or {}).get("period") or period_label(fin)
    base_months = (earnings or {}).get("months") or period_months(fin)
    if net_income is None:
        net_income = _num((fin or {}).get("net_income"))

    bvps = bvps_issuer(classes, equity)
    shares_check = share_count_consistency(classes)

    # A statement that failed validation may not feed a multiple at all: the
    # multiple would inherit the impossible figure without inheriting the doubt.
    if fin is not None and not validation["valid"]:
        blocked = _metric(None, STATUS_UNVERIFIED, reasons=validation["reasons"])
        return {
            "market_cap_issuer": cap, "base_period": base_period, "base_months": base_months,
            "pe": dict(blocked), "pb": dict(blocked), "roe": dict(blocked),
            "roa": dict(blocked), "net_margin": dict(blocked), "debt_to_equity": dict(blocked),
            "bvps": bvps, "shares_check": shares_check, "validation": validation,
        }

    if not shares_check["consistent"]:
        worst = max(shares_check["findings"], key=lambda f: abs(math.log10(f["ratio"])))
        note = (f"капитализация {worst['ticker']} расходится с ценой на акцию "
                f"в {worst['ratio']:.0f} раз")
        blocked = _metric(None, STATUS_INCONSISTENT, note=note)
        return {
            "market_cap_issuer": cap, "base_period": base_period, "base_months": base_months,
            "pe": dict(blocked), "pb": dict(blocked),
            "roe": _ranged(_num(ratio.get("roe")), -float(cfg["roe_abs_max"]), float(cfg["roe_abs_max"])),
            "roa": _ranged(_num(ratio.get("roa")), -float(cfg["roe_abs_max"]), float(cfg["roe_abs_max"])),
            "net_margin": _metric(_num(ratio.get("net_profit_margin")), STATUS_OK)
            if ratio.get("net_profit_margin") is not None else _metric(None, STATUS_NO_FINANCIALS),
            "debt_to_equity": _metric(_num(ratio.get("debt_to_equity")), STATUS_OK)
            if ratio.get("debt_to_equity") is not None else _metric(None, STATUS_NO_FINANCIALS),
            "bvps": bvps, "shares_check": shares_check, "validation": validation,
        }

    cap_value = cap["value"]
    pe_range = cfg["pe_range"]
    pb_range = cfg["pb_range"]

    if cap_value is None:
        pe = _metric(None, "no_market_cap")
        pb = _metric(None, "no_market_cap")
    elif net_income is None:
        pe = _metric(None, STATUS_NO_FINANCIALS)
        pb = _metric(None, STATUS_NO_FINANCIALS)
    elif net_income <= 0:
        # ТЗ §8: at a loss the cell says «убыток», it does not print a negative
        # multiple that sorts beside positive ones as if it were cheap.
        pe = _metric(None, STATUS_LOSS, base_period=base_period)
        pb = _ranged(cap_value / equity if equity and equity > 0 else None,
                     float(pb_range[0]), float(pb_range[1]), base_period=base_period)
    else:
        pe = _ranged(cap_value / net_income, float(pe_range[0]), float(pe_range[1]),
                     base_period=base_period, base_months=base_months)
        pb = _ranged(cap_value / equity if equity and equity > 0 else None,
                     float(pb_range[0]), float(pb_range[1]), base_period=base_period)

    roe_max = float(cfg["roe_abs_max"])
    return {
        "market_cap_issuer": cap,
        "base_period": base_period,
        "base_months": base_months,
        "pe": pe,
        "pb": pb,
        "roe": _ranged(_num(ratio.get("roe")), -roe_max, roe_max, base_period=ratio.get("period")),
        "roa": _ranged(_num(ratio.get("roa")), -roe_max, roe_max, base_period=ratio.get("period")),
        "net_margin": (_metric(_num(ratio.get("net_profit_margin")), STATUS_OK)
                       if ratio.get("net_profit_margin") is not None
                       else _metric(None, STATUS_NO_FINANCIALS)),
        "debt_to_equity": (_metric(_num(ratio.get("debt_to_equity")), STATUS_OK)
                           if ratio.get("debt_to_equity") is not None
                           else _metric(None, STATUS_NO_FINANCIALS)),
        "bvps": bvps,
        "shares_check": shares_check,
        "validation": validation,
    }


# ---------------------------------------------------------------------------
# Market-wide aggregates (ТЗ §8)
# ---------------------------------------------------------------------------

def market_capitalisation(board: Sequence[dict[str, Any]],
                          securities: dict[str, dict[str, Any]] | None = None,
                          inactive_after_days: int | None = None) -> dict[str, Any]:
    """Total capitalisation of the market, and what was deliberately left out.

    ТЗ §8: active shares only. Bonds carry no ownership and 9 of them had a
    capitalisation computed anyway; 23 inactive listings contributed 29 088 bn to
    a headline number describing "the market". Both are now reported as separate
    lines instead of silently inflating one figure.
    """
    securities = securities or {}
    included = 0.0
    bonds = 0.0
    inactive = 0.0
    n_included = n_bonds = n_inactive = 0
    for row in board:
        cap = _num(row.get("market_cap"))
        ticker = str(row.get("ticker") or "").upper()
        meta = securities.get(ticker) or {}
        is_bond = (str(row.get("type") or meta.get("type") or "").lower() == "bond")
        is_inactive = bool(row.get("inactive")) or meta.get("is_active") is False
        if cap is None or cap <= 0:
            continue
        if is_bond:
            bonds += cap
            n_bonds += 1
        elif is_inactive:
            inactive += cap
            n_inactive += 1
        else:
            included += cap
            n_included += 1
    return {
        "value": included,
        "unit": "sum",
        "scope": "stocks_listed_active",
        "instruments": n_included,
        "excluded": {
            "bonds": {"amount": bonds, "instruments": n_bonds},
            "inactive_listings": {"amount": inactive, "instruments": n_inactive},
        },
        "note": "без облигаций и неактивных листингов",
    }
