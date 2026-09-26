"""Prepare current, annual, and prior-period financial snapshots for readers."""
from __future__ import annotations
import catalogue.sources as catalogue_sources
import dbx
import re
from typing import Any
import sqlite3

from company_catalog import COMPANY_SECTORS
from entity_resolver import ORG_OVERRIDES
from entity_resolver import UNRELIABLE_FINANCIALS
from financial_corrections import correction_periods_for
from financial_corrections import corrections_for
import catalogue.codecs as catalogue_codecs
import catalogue.fields as catalogue_fields
import catalogue.filings as catalogue_filings
import catalogue.financial_store as catalogue_financial_store
import catalogue.periods as catalogue_periods
import catalogue.ratios as catalogue_ratios
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import os


def _financials_enrich_enabled() -> bool:
    """Whether to apply org/fact enrichment when reading financials.

    Enrichment (fact-store corrections, cross-ticker inheritance) must run in the
    collector — where openinfo is reachable and the org mapping is fresh — before
    it pushes the final values. It must NOT run when serving on the deployment:
    prod's catalog_companies/org map is stale (openinfo is blocked there, so it
    never re-syncs), and re-enriching would re-inject a *different* entity's
    numbers over the clean pushed values (the org-1001 → OCBK/MNGM bug). Default
    off; the collector sets FINANCIALS_ENRICH_ON_READ=1.
    """
    return os.getenv("FINANCIALS_ENRICH_ON_READ", "0").strip().lower() in {"1", "true", "yes", "on"}


_CORRECTION_BALANCE_KEYS = {

    "total_assets": "assets_end",

    "total_equity": "equity_end",

    "total_liabilities": "liabilities_end",

}


def _correction_period(row: dict[str, Any]) -> str | None:
    """The register's quarter label for a cached financials row."""
    try:
        year = int(row.get("year"))
        quarter = int(row.get("quarter") or 0)
    except (TypeError, ValueError):
        return None
    if quarter not in range(0, 5):
        return None
    return f"{year}Q{quarter or 4}"


def _apply_registered_financial_corrections(

        ticker: str, period: str | None, row: dict[str, Any], *,

        form: str | None = None, quarter: int | None = None) -> dict[str, Any]:

    """Overlay reviewed OpenInfo values on one in-memory catalog row.



    The overlay deliberately runs on reads, after feed/fact enrichment.  A

    collector refresh can therefore replace the underlying cache without

    silently reintroducing a value the reviewed register already rejected.

    Balance totals are mirrored into the filed-balance block because that block

    is the authority for P/B, ROE and ROA as well as for the Finance table.

    """

    if not period:

        return row

    standard = str(form or row.get("form") or "NSBU").strip().upper()

    registered = corrections_for(ticker, period) if standard == "NSBU" else {}

    for field, correction in registered.items():

        row[field] = correction.value_thousands_uzs

        balance_key = _CORRECTION_BALANCE_KEYS.get(field)

        if balance_key:

            balance = dict(row.get("balance") or {})

            balance[balance_key] = correction.value_thousands_uzs

            row["balance"] = balance

        field_periods = row.get("field_periods")

        if isinstance(field_periods, dict):

            field_periods.pop(field, None)

    # The bundled register is the baseline for corrections already reviewed

    # before the admin workflow existed. New approvals live in the catalogue

    # database and intentionally win, while the raw imported row remains

    # untouched in both cases.

    try:

        import data_quality

        year, display_quarter = int(period[:4]), int(period[-1])

        stored_quarter = (quarter if quarter is not None else

                          0 if display_quarter == 4 and int(row.get("quarter") or 0) == 0

                          else display_quarter)

        approved = data_quality.approved_corrections_for(

            ticker, standard, year, stored_quarter)

    except Exception:  # a quality overlay must never make a financial read fail

        catalogue_settings.logger.exception("financial corrections: quality overlay lookup failed for %s %s", ticker, period)

        approved = {}

    for field, value in approved.items():

        row[field] = value

        balance_key = _CORRECTION_BALANCE_KEYS.get(field)

        if balance_key:

            balance = dict(row.get("balance") or {})

            balance[balance_key] = value

            row["balance"] = balance

        field_periods = row.get("field_periods")

        if isinstance(field_periods, dict):

            field_periods.pop(field, None)

    if approved:

        # Internal marker: a corrected P&L line means the comparative column

        # parsed from that same workbook can carry the same unit defect.

        row["_reviewed_correction_fields"] = sorted(approved)

    return row


def get_all_financials(form: str = "NSBU") -> dict[str, dict[str, Any]]:

    """Return the most recent cached indicators per ticker: {ticker: {...}}.



    Picks the latest period (year, then quarter) available for each ticker. Org/

    fact enrichment runs only when ``_financials_enrich_enabled()`` (collector),

    so the deployment serves exactly what the collector pushed.

    """

    conn = catalogue_storage.get_catalog_conn()

    catalogue_financial_store._maybe_seed_financials(conn, form)

    # Period ranking, in SQL, matching _period_key() exactly. Three things this

    # has to get right and the old `MAX(year * 10 + quarter)` did not:

    #

    #  1. An ANNUAL row is stored with quarter = 0, so it ranked BELOW every

    #     quarter of its own year — a completed FY2025 annual lost to 2025 Q1.

    #     _period_key ranks an annual as 5 (the complete, final figure for that

    #     year); the CASE below does the same, so the two orderings agree.

    #  2. A premature annual (fiscal year not yet ended) is openinfo's in-progress

    #     placeholder and must never win. Quarterly periods of the current year

    #     stay eligible — they are real point-in-time filings.

    #  3. A quarter outside 1-4 is a corrupt source period ('2025Q7'); at

    #     quarter = 7 it outranked every real period. Excluded outright.

    #  4. A period stamped beyond the current calendar year cannot be a filing

    #     that exists yet, quarterly or not. A single mis-stamped row (openinfo

    #     does mis-stamp period-ends) otherwise wins "latest" forever and shadows

    #     the issuer's real figures.

    last_fy = catalogue_periods._latest_complete_fiscal_year()

    this_year = last_fy + 1

    period_rank = "(f.year * 10 + CASE WHEN f.quarter = 0 THEN 5 ELSE f.quarter END)"

    eligible = (

        "f.form = :form "

        "AND f.year IS NOT NULL "

        "AND f.quarter BETWEEN 0 AND 4 "

        "AND f.year <= :this_year "

        "AND NOT (f.quarter = 0 AND f.year > :last_fy)"

    )

    rows = conn.execute(

        f"""

        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.cash,

               f.total_liabilities, f.net_income, f.operating_income, f.operating_expenses,

               f.noninterest_income, f.org_type, f.balance_period,

               f.total_assets, f.total_equity,

               f.field_periods, f.prior_period, f.report_id, f.updated_at

        FROM catalog_financials f

        JOIN (

            SELECT f.ticker AS ticker, MAX{period_rank} AS rank

            FROM catalog_financials f

            WHERE {eligible}

            GROUP BY f.ticker

        ) latest

          ON latest.ticker = f.ticker AND {period_rank} = latest.rank

        WHERE {eligible}

        """,

        {"form": form, "last_fy": last_fy, "this_year": this_year},

    ).fetchall()

    out: dict[str, dict[str, Any]] = {}

    for r in rows:

        out[r["ticker"]] = {

            "year": r["year"],

            "quarter": r["quarter"],

            # Quarterly NSBU flows are cumulative from Jan 1 — flag it so the

            # client can label a Q2 figure as "6 months" rather than pass a

            # part-year number off as a full-year one next to annual rows.

            "is_ytd": bool(r["quarter"]),

            "period_months": catalogue_periods._period_months(r["year"], r["quarter"]),

            "revenue": r["revenue"],

            "gross_profit": r["gross_profit"],

            "cash": r["cash"],

            "total_liabilities": r["total_liabilities"],

            "net_income": r["net_income"],

            "operating_income": r["operating_income"],

            "operating_expenses": r["operating_expenses"],

            # Bank total income's second half; None on every other form.

            "noninterest_income": r["noninterest_income"],

            # The NSBU form the figures were read from (jsc/bank/insurance/

            # microfinance) — the display rules key off the form, not a guess.

            "org_type": r["org_type"],

            # The filed balance for THIS period: equity/assets at start and end,

            # the denominators P/B and averaged ROE/ROA are built from.

            "balance": catalogue_ratios._cached_balance(r["balance_period"], r["total_assets"],

                                       r["total_equity"]),

            # {field: period} for any value that does NOT belong to (year, quarter)

            # — a bank's revenue is only published as an annual indicator, so the

            # cell must say which period it describes rather than borrow the row's.

            "field_periods": catalogue_codecs._decode_field_periods(r["field_periods"]),

            # The comparative the SAME filing prints for the year before — P&L

            # only, labelled with its own period, so a year-on-year change is

            # struck against the issuer's own restated figure rather than against

            # a separately-filed report that may have been restated since.

            "prior": catalogue_codecs._decode_prior_period(r["prior_period"]),

            # The report this row was read from (ТЗ Дополнение 1 §Б.2). Every

            # figure carries its first source, so a disagreement about a number

            # is settled by opening the filing rather than by argument.

            "report_id": r["report_id"],

            "updated_at": r["updated_at"],

        }

    _attach_annual_companion(conn, out, form)

    _attach_prior_interim_companion(conn, out, form)

    if form == "NSBU" and _financials_enrich_enabled():

        _inherit_financials_by_org(conn, out)

        _enrich_financials_from_facts(conn, out)

    # Reviewed, source-linked corrections are the final authority.  Apply them

    # after every automated enrichment so the next collector run cannot put a

    # known-bad parsed/feed value back on the site.

    for ticker, row in out.items():

        _apply_registered_financial_corrections(ticker, _correction_period(row), row, form=form)

        annual = row.get("annual")

        if isinstance(annual, dict):

            _apply_registered_financial_corrections(

                ticker, _correction_period(annual), annual, form=form)

    # Corrections are overlaid after the first companion attachment. Re-run it

    # so a corrected statement can replace a stale embedded comparative before

    # TTM, ROE and ROA are assembled.

    _attach_prior_interim_companion(conn, out, form)

    for ticker, row in out.items():

        prior = row.get("prior")

        if isinstance(prior, dict):

            _apply_registered_financial_corrections(

                ticker, _correction_period(prior), prior, form=form)

        # Implementation details must never escape as public financial fields.

        row.pop("_reviewed_correction_fields", None)

        for nested in (row.get("annual"), prior):

            if isinstance(nested, dict):

                nested.pop("_reviewed_correction_fields", None)

    conn.close()

    if form == "MSFO":

        from financial_ingestion.publication import latest

        company_conn = catalogue_storage.get_catalog_conn()

        try:

            company_tickers = ([r[0] for r in company_conn.execute(

                "SELECT DISTINCT c.ticker FROM catalog_companies c JOIN ingest_heads h ON h.org_id=c.org_id WHERE h.standard='MSFO'"

            ).fetchall()] if "ingest_heads" in dbx.tables(company_conn) else [])

        finally:

            company_conn.close()

        for ticker in company_tickers:

            published = latest(ticker)

            if published is not None:

                out[ticker] = published

    return out


def _attach_annual_companion(conn: sqlite3.Connection, out: dict[str, dict[str, Any]],

                             form: str) -> None:

    """Hang the last complete fiscal year off each row as ``annual``.



    The latest period is the freshest figure but usually a cumulative quarter, and

    every ratio built on a P&L line then divides by 3, 6 or 9 months of earnings

    while the issuer next to it divides by 12 — the same P/E column measuring

    different things. The companion is the comparable denominator: a real filed

    12-month period, not a quarter multiplied up. It is absent (None) when the row

    already IS an annual, and when no complete year has been collected.



    A Q4 quarterly stands in when no annual was ever filed: NSBU quarters are

    cumulative from 1 January, so a Q4 filing IS twelve months of activity with a

    31 December balance (ТЗ мультипликаторов: KSCM's newest annual is 2022 while

    its quarters are current). A real annual of the same year still outranks it —

    the audited annual is the year's final word.

    """

    last_fy = catalogue_periods._latest_complete_fiscal_year()

    rank = "(f.year * 10 + CASE WHEN f.quarter = 0 THEN 5 ELSE 4 END)"

    rows = conn.execute(

        f"""

        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.cash,

               f.total_liabilities, f.net_income, f.operating_income, f.operating_expenses,

               f.noninterest_income, f.org_type, f.balance_period, f.field_periods,

               f.total_assets, f.total_equity

        FROM catalog_financials f

        JOIN (

            SELECT f.ticker AS ticker, MAX{rank} AS rank

            FROM catalog_financials f

            WHERE f.form = :form AND f.quarter IN (0, 4)

              AND f.year IS NOT NULL AND f.year <= :last_fy

            GROUP BY f.ticker

        ) latest ON latest.ticker = f.ticker AND {rank} = latest.rank

        WHERE f.form = :form AND f.quarter IN (0, 4)

        """,

        {"form": form, "last_fy": last_fy},

    ).fetchall()

    annuals = {

        r["ticker"]: {

            "year": r["year"], "quarter": r["quarter"],

            "is_ytd": bool(r["quarter"]), "period_months": 12,

            "revenue": r["revenue"], "gross_profit": r["gross_profit"], "cash": r["cash"],

            "total_liabilities": r["total_liabilities"], "net_income": r["net_income"],

            "operating_income": r["operating_income"],

            "operating_expenses": r["operating_expenses"],

            "noninterest_income": r["noninterest_income"],

            "org_type": r["org_type"],

            "balance": catalogue_ratios._cached_balance(r["balance_period"], r["total_assets"],

                                       r["total_equity"]),

            "field_periods": catalogue_codecs._decode_field_periods(r["field_periods"]),

            "total_assets": r["total_assets"], "total_equity": r["total_equity"],

        }

        for r in rows

    }

    for ticker, row in out.items():

        annual = annuals.get(ticker)

        if (annual is None or not row.get("quarter")

                or (annual["year"] == row.get("year")

                    and annual["quarter"] == row.get("quarter"))):

            # No 12-month base, the row is annual itself, or the base IS the row

            # (a Q4 latest period is already twelve cumulative months).

            row["annual"] = None

        else:

            row["annual"] = annual


_TTM_COMPANION_KEYS = ("revenue", "gross_profit", "net_income", "operating_income",
                       "noninterest_income")


def _attach_prior_interim_companion(conn: sqlite3.Connection, out: dict[str, dict[str, Any]],

                                    form: str) -> None:

    """Fill ``prior`` from the stored filing of the same interim a year earlier.



    The TTM base is ``annual(Y−1) + YTD(Y) − YTD(Y−1)`` and its subtrahend is

    normally the comparative the SAME form prints beside each P&L line. The BANK

    form prints no comparative — its P&L is a single column — so every bank sat

    with ``prior = None``, the TTM branch could not close, and fourteen issuers

    (ALKB, HMKB, SQBN, TRSB, IPKY, IPTB, AGBA, MCBA, BRBN, TNBN, UNVB, GRBK,

    TGBK…) were valued off a twelve-month profit that ended seven months before

    the balance it was divided by. The same-quarter filing of the year before is

    already in this cache — it is the issuer's own published figure for exactly

    the period the arithmetic subtracts.



    It is the fallback and never the winner: a comparative printed inside the

    filing is netted against the issuer's own restatement, which a separately

    filed report cannot be. ``source`` says which one a row got.

    """

    targets = {

        ticker: (int(row["year"]) - 1, int(row["quarter"]))

        for ticker, row in out.items()

        if row.get("quarter") and row.get("year")

        and (not _prior_matches(row.get("prior"), int(row["year"]) - 1, int(row["quarter"]))

             or bool(set(row.get("_reviewed_correction_fields") or ())

                     & set(_TTM_COMPANION_KEYS)))

    }

    if not targets:

        return

    years = {y for y, _ in targets.values()}

    rows = conn.execute(

        """

        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.net_income,

               f.operating_income, f.noninterest_income

        FROM catalog_financials f

        WHERE f.form = :form AND f.quarter BETWEEN 1 AND 4

          AND f.year BETWEEN :lo AND :hi

        """,

        {"form": form, "lo": min(years), "hi": max(years)},

    ).fetchall()

    stored = {(r["ticker"], r["year"], r["quarter"]): r for r in rows}

    for ticker, (year, quarter) in targets.items():

        # A filing may have been collected under another listed class of the

        # same issuer. The requested ticker wins, then its dynamic siblings.

        candidates = [ticker, *[s for s in catalogue_filings._org_siblings(conn, ticker) if s != ticker]]

        r = next((stored.get((candidate, year, quarter)) for candidate in candidates

                  if stored.get((candidate, year, quarter)) is not None), None)

        if r is None:

            continue

        prior = {"year": year, "quarter": quarter, "is_ytd": True,

                 "period_months": catalogue_periods._period_months(year, quarter), "source": "catalog"}

        for key in _TTM_COMPANION_KEYS:

            prior[key] = catalogue_codecs._financials_num(r[key])

        if any(prior[key] is not None for key in _TTM_COMPANION_KEYS):

            out[ticker]["prior"] = prior


def _prior_matches(prior: Any, year: int, quarter: int) -> bool:
    """Whether a stored comparative already IS the interim the TTM subtracts."""
    if not isinstance(prior, dict):
        return False
    if int(prior.get("year") or 0) != year or int(prior.get("quarter") or 0) != quarter:
        return False
    return any(prior.get(key) is not None for key in _TTM_COMPANION_KEYS)


def _enrich_financials_from_facts(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Conservatively correct NSBU headline figures from the fact store.

    openinfo's financial_indicators are cleaner than the NSBU form-2 parse, but the
    ticker→org resolution is ambiguous for some issuers (openinfo carries duplicate
    org records and UZSE names fuzzy-match unrelated entities), so a fact could be
    for the *wrong* company. We therefore only apply changes we can trust:
      - banks (null NSBU revenue): fill revenue and take net_profit;
      - sign flips: NSBU net_income of the same magnitude but opposite sign to the
        fact — unambiguously the same company, a parser sign error;
      - fill genuinely-null revenue / total_liabilities;
      - blank implausibly small NSBU values (clear parse errors).
    Large magnitude disagreements are left as flags (see audit_financials_consistency)
    rather than "corrected" with possibly-wrong-org data.

    PERIOD DISCIPLINE. A row carries one (year, quarter) label, and every value in
    it must belong to that period or say which period it does belong to. The fact
    store's "latest indicator on file" is frequently a *different, older* period
    than the parsed NSBU row, so:

      - a fact for the row's OWN period may overwrite the parsed value (same
        period, cleaner source — this is the intended correction);
      - a fact for any other period may only FILL A NULL, never overwrite, and the
        period it came from is recorded in ``fin['field_periods']``.

    Without that rule the enrichment wrote FY2024 revenue into a row labelled
    "Q1 2026 (3 months)" — a ~5.5x overstatement on UZMK that also destroyed the
    fresher quarterly figure underneath it. Every finance-sector and ORG_OVERRIDES
    issuer was exposed.
    """
    srcs = ("net_revenue", "net_profit", "total_liabilities",
            "gross_profit_margin", "ebit_margin")
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(srcs))})",
            srcs,
        ).fetchall()
    except Exception:
        return
    ticker_org = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    # Field-level fills verified by hand against the issuer's actual filings —
    # used only where the automated chain cannot reach a figure the source
    # publishes. Each entry cites its provenance.
    curated: dict[str, dict[str, float]] = {
        # National Investment Fund: openinfo net_revenue is literally 0.0 (a
        # fund has no sales revenue) — a true published zero, not a gap.
        "UZNF": {"revenue": 0.0},
        # Muborakneftgazmontaj: form 2 publishes Валовая прибыль = 0 (стр.030;
        # a dividend-income holding with no product sales) — a true zero.
        "MNGM": {"gross_profit": 0.0},
        # O'zbekiston neftgaz: 2021+ NSBU filings are zero stubs; the 2020
        # annual (same year as the indicator facts shown for it) publishes
        # year-end cash 2,291,908,931 th UZS (form 1, стр.320). The alias step
        # copies it onto the sibling UZNG line.
        "UZNGP": {"cash": 2291908931.0},
    }
    best: dict[tuple[str, str], tuple[str, float]] = {}
    # Every (org, field) indexed by its exact period, so a fill can prefer the fact
    # that belongs to the period the row is labelled with.
    by_period: dict[tuple[str, str, str], float] = {}
    # net_profit indexed by annual year, so a sign-flip check compares against the
    # SAME year the board displays — not merely the newest indicator on file (which
    # can be a later annual than the parsed NSBU set, defeating the magnitude test).
    npf_by_year: dict[tuple[str, int], float] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if catalogue_periods._period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period — never a candidate
        if not r["value_num"]:
            # openinfo publishes all-zero indicator years for non-filers
            # (O'zbekneftgaz 2021-2024) — a zero is "no report", not a figure.
            # Letting it win "latest period" would shadow the last real year.
            continue
        if catalogue_periods._is_premature_annual_period(period):
            continue  # openinfo's in-progress current-year placeholder — not a real annual
        if best.get(key) is None or catalogue_periods._fact_period_rank(period) > catalogue_periods._fact_period_rank(best[key][0]):
            best[key] = (period, r["value_num"])
        by_period[(str(r["entity_id"]), r["field"], period)] = r["value_num"]
        if r["field"] == "net_profit" and period.isdigit() and len(period) == 4:
            npf_by_year[(str(r["entity_id"]), int(period))] = r["value_num"]
    for ticker, fin in out.items():
        # Tickers whose only openinfo match is a different company: blank rather
        # than show another entity's figures.
        if ticker in UNRELIABLE_FINANCIALS:
            for key in catalogue_fields._FIN_FIELDS:
                fin[key] = None
            continue
        # is_bank is judged on the issuer's sector — a stable signal. (Using
        # "revenue is None" would misfire after blanking or on a re-read of already
        # enriched-and-pushed data, making a blanked value look like a bank.)
        is_bank = COMPANY_SECTORS.get(ticker) == "finance"
        row_max = max((abs(fin[k]) for k in catalogue_fields._FIN_FIELDS if fin.get(k)), default=0.0)
        if 0 < row_max < catalogue_fields._MIN_PLAUSIBLE:
            for key in catalogue_fields._FIN_FIELDS:
                fin[key] = None
        # After junk-blanking so a curated figure survives it (UZNGP's junk
        # 2023 row carried code-values that both hid and then erased cash).
        for key, val in curated.get(ticker, {}).items():
            if fin.get(key) is None:
                fin[key] = val
        org = ticker_org.get(ticker)
        if not org:
            continue
        row_period = catalogue_ratios._row_period(fin)

        def _pick(field: str) -> tuple[str, float] | None:
            """The fact to use for ``field``: the row's own period if it exists,
            otherwise the newest one on file (which the caller must then treat as
            fill-only, because it describes a different reporting period)."""
            if row_period is not None:
                same = by_period.get((org, field, row_period))
                if same is not None:
                    return (row_period, same)
            return best.get((org, field))

        def _apply(target: str, hit: tuple[str, float] | None) -> None:
            """Write a fact onto the row under the period rule (see the docstring).

            Same period as the row -> authoritative, overwrite. Different period ->
            fill a null only, and record the period the figure actually describes so
            nothing is served under the wrong label.
            """
            if hit is None:
                return
            period, value = hit
            if period == row_period:
                fin[target] = value
                return
            if fin.get(target) is not None:
                # A real figure for this row's period already exists; a different
                # period's indicator does not get to replace it. Visible via
                # audit_financials_consistency rather than silently resolved.
                catalogue_settings.logger.debug(
                    "%s: keeping parsed %s for %s, not overwriting with the %s fact",
                    ticker, target, row_period, period,
                )
                return
            fin[target] = value
            fin.setdefault("field_periods", {})[target] = period

        rev = _pick("net_revenue")
        npf = _pick("net_profit")
        tl = _pick("total_liabilities")
        rev_v = rev[1] if rev and rev[1] not in (None, 0) else None
        npf_v = npf[1] if npf and npf[1] is not None else None
        tl_v = tl[1] if tl and tl[1] not in (None, 0) else None

        def _derive_margin_lines() -> None:
            # Gross/operating profit from the SAME-period published margin ×
            # revenue (verified against O'zbekneftgaz 2019, where the filed
            # figures reproduce the margins exactly). Fraction-valued margins
            # only — openinfo stores net_profit_margin in percent but gross/
            # ebit margins as fractions, and a mixed-unit hit would be junk.
            if rev is None or not rev[1]:
                return
            for fld, margin_key in (("gross_profit", "gross_profit_margin"),
                                    ("operating_income", "ebit_margin")):
                if fin.get(fld) is not None:
                    continue
                m = by_period.get((org, margin_key, rev[0]))
                if m is not None and 0 < m <= 1:
                    fin[fld] = round(rev[1] * m)
                    # The derived line inherits the revenue's period, which is not
                    # always the row's — carry that through, same rule as _apply.
                    if rev[0] != row_period:
                        fin.setdefault("field_periods", {})[fld] = rev[0]

        if ticker in ORG_OVERRIDES:
            # Org is human-verified, so openinfo's clean figures are authoritative
            # FOR THEIR OWN PERIOD. _apply still refuses to write a figure from one
            # period into a row labelled with another — a verified org says nothing
            # about which reporting period a number belongs to, and this branch is
            # where the UZMK "Q1 2026 carrying FY2024 revenue" overstatement came
            # from.
            _apply("net_income", npf if npf_v is not None else None)
            _apply("revenue", rev if rev_v is not None else None)
            _apply("total_liabilities", tl if tl_v is not None else None)
            _derive_margin_lines()
            continue

        # Finance issuers (banks and insurers): openinfo's net_revenue is the
        # authoritative top line. Banks have no NSBU revenue line at all; insurers
        # do (gross written premiums), but we show the net-of-reinsurance indicator
        # to stay consistent with how bank revenue is sourced. Non-finance keep the
        # NSBU figure and only fall back to the indicator when it is blank.
        if rev_v is not None and (is_bank or fin.get("revenue") is None):
            _apply("revenue", rev)
        if npf_v is not None:
            stored = fin.get("net_income")
            if is_bank and npf_v != 0:
                _apply("net_income", npf)
            elif stored is not None:
                year = fin.get("year")
                cmp_v = npf_by_year.get((org, year)) if year else None
                if cmp_v is None:
                    cmp_v = npf_v
                same_magnitude = abs(abs(stored) - abs(cmp_v)) / max(abs(cmp_v), 1.0) < 0.05
                if same_magnitude and (stored < 0) != (cmp_v < 0):
                    # A sign flip is a parser error on THIS row's own figure, not a
                    # different period's value — the magnitude test already proved
                    # they are the same number, so the label stays correct.
                    fin["net_income"] = cmp_v
        if fin.get("total_liabilities") is None and tl_v is not None:
            _apply("total_liabilities", tl)
        _derive_margin_lines()


def _inherit_financials_by_org(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Let every listed ticker inherit its issuer's financials (ТЗ data pipeline).

    Preferred shares (HMKBP) share the issuer org of the ordinary share (HMKB);
    bonds share the issuer that files the statements. Financials are computed per
    issuer (org_id) but stored under whatever ticker was synced, so a pref/bond
    ends up with an org resolved but no financials row. This maps every ticker in
    catalog_companies to its org's financials when it has none of its own — the
    values are identical because it is the same legal entity.
    """
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
    except Exception:
        return
    ticker_org: dict[str, str] = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    # One financials payload per org (any ticker of that org that already has one).
    org_fin: dict[str, dict[str, Any]] = {}
    for ticker, fin in out.items():
        org = ticker_org.get(ticker)
        if org and org not in org_fin:
            org_fin[org] = fin
    # Assign to sibling tickers that have an org but no financials of their own.
    for ticker, org in ticker_org.items():
        if ticker in out:
            continue
        source = org_fin.get(org)
        if source:
            # field_periods must be copied, not aliased: the enrichment pass that
            # runs after this one mutates it per ticker, and siblings can resolve to
            # different org records (UZMK/UZMKP), so a shared dict would leak one
            # ticker's provenance onto another's row.
            out[ticker] = {**source, "field_periods": dict(source.get("field_periods") or {}),
                           "annual": dict(source["annual"]) if source.get("annual") else None,
                           "inherited_from_org": org}

    # Preferred shares also inherit directly from their ordinary ticker, even when
    # openinfo indexes them under a different org record (duplicate org entries for
    # the same issuer, e.g. UZMK/UZMKP). Same legal entity → same financials.
    for ticker in list(ticker_org.keys()):
        if ticker in out or not ticker.endswith("P"):
            continue
        base = ticker[:-1]
        if base in out:
            out[ticker] = {**out[base], "field_periods": dict(out[base].get("field_periods") or {}),
                           "annual": dict(out[base]["annual"]) if out[base].get("annual") else None,
                           "inherited_from_ticker": base}


def _fin_row_fields(row: Any) -> dict[str, Any]:

    """One cached row's non-null fields, for the series readers.



    Rows written before the total_assets/total_equity columns existed can still

    carry the same figures inside the filed-balance block the reconcile pushes

    (balance_period's assets_end/equity_end) — those fill the gap, so the latest

    quarters show a balance before any backfill re-parses the history.

    """

    available = set(row.keys())

    fields = {k: row[k] for k in catalogue_fields._FIN_FIELDS + catalogue_fields._IFRS_BANK_FIELDS if k in available and row[k] is not None}

    if fields.get("total_assets") is None or fields.get("total_equity") is None:

        balance = catalogue_codecs._decode_balance_period(row["balance_period"]) or {}

        for field, key in (("total_assets", "assets_end"), ("total_equity", "equity_end")):

            if fields.get(field) is None and balance.get(key) is not None:

                fields[field] = balance[key]

    return fields


def get_financials_series(ticker: str, form: str = "NSBU") -> dict[str, dict[str, Any]]:

    """Every ANNUAL period this platform has parsed for one issuer, by year.



    Straight from the filings — catalog_financials for the sums and

    catalog_ratios for the ratios computed off the same two statements. This is

    the authority: the openinfo indicator feed it replaces had UZTL's 2023 and

    2024 revenue transposed and 2021 missing, while the filings agree with it

    everywhere it is right.



    Sums stay in the stored unit (thousands); the caller scales them, exactly as

    every other endpoint that serves absolute figures does.

    """

    t = str(ticker or "").strip().upper()

    if not t:

        return {}

    if form == "MSFO":

        from financial_ingestion.publication import series

        published = series(t)

        if published is not None:

            return published

    conn = catalogue_storage.get_catalog_conn()

    try:

        # By the ISSUER, not the ticker: a filing lands in the cache under

        # whichever share class it was catalogued under, and reading one class

        # alone left UZASP, UZTLP, UZIRP and the other preferred lines with no

        # filed years at all while their ordinary sibling showed a decade.

        siblings = catalogue_filings._org_siblings(conn, t) or [t]

        placeholders = ",".join("?" * len(siblings))

        fin = conn.execute(

            f"SELECT ticker, year, quarter, balance_period, {', '.join(catalogue_fields._FIN_FIELDS + catalogue_fields._IFRS_BANK_FIELDS)} FROM catalog_financials "

            f"WHERE ticker IN ({placeholders}) AND form=? "

            "AND (quarter=0 OR (quarter=4 AND form='NSBU' AND EXISTS ("

            "SELECT 1 FROM catalog_reports r WHERE r.ticker=catalog_financials.ticker "

            "AND r.report_form=catalog_financials.form AND r.year=catalog_financials.year "

            "AND r.quarter=4))) ORDER BY year",

            (*siblings, form)).fetchall()

        rat = conn.execute(

            "SELECT ticker, year, roa, roe, debt_ratio, debt_to_equity FROM catalog_ratios "

            f"WHERE ticker IN ({placeholders}) AND form=? AND quarter=0 ORDER BY year",

            (*siblings, form)).fetchall()

    finally:

        conn.close()

    out: dict[str, dict[str, Any]] = {}

    # Some banks really DO file a cumulative Q4 (e.g. DRBK 2019), even when

    # there is no separately labelled annual. It covers the same twelve months.

    # Keep the original row and document identity; never invent an annual filing

    # or merge an unaudited Q4 over a separately filed annual of that year.

    annual_years = {r["year"] for r in fin if not r["quarter"]}

    held_q4 = set()

    if any(r["quarter"] == 4 for r in fin):

        from data_quality import held_public_periods

        for sibling in siblings:

            held_q4.update(held_public_periods(sibling, form))

    fin = [r for r in fin if not r["quarter"] or (

        r["year"] not in annual_years and f"{r['year']}Q4" not in held_q4)]

    # Siblings first, the requested ticker last: where both classes carry the

    # same year (the same filing parsed twice) the requested one wins.

    for row in sorted(fin, key=lambda r: r["ticker"] == t):

        out.setdefault(str(row["year"]), {}).update(_fin_row_fields(row))

    for row in sorted(rat, key=lambda r: r["ticker"] == t):

        out.setdefault(str(row["year"]), {}).update(

            {k: row[k] for k in ("roa", "roe", "debt_ratio", "debt_to_equity")

             if row[k] is not None})

    # A reviewed "Добавить" can be the only known value in a year.  Seed those

    # years from the register before applying it; otherwise an absent database

    # row would make the correction itself unreachable.

    for period in (correction_periods_for(t) if form == "NSBU" else {}):

        if period.endswith("Q4"):

            out.setdefault(period[:4], {})

    for year, fields in out.items():

        _apply_registered_financial_corrections(t, f"{year}Q4", fields, form=form, quarter=0)

    return out


def get_financials_series_quarterly(ticker: str, form: str = "NSBU") -> dict[str, dict[str, Any]]:

    """Every QUARTERLY period parsed for one issuer, keyed "YYYYQn".



    The figures are as the filings state them: NSBU quarterly form 2 is

    CUMULATIVE from 1 January (a Q2 revenue is six months of revenue), and the

    balance lines are as of the quarter's end. Turning the running totals into

    three-month columns is the reader's job — the API derives them, so the raw

    period stays available to anything that needs the filing's own figure.



    Same issuer-wide read as :func:`get_financials_series`: a filing lands under

    whichever share class it was catalogued under, and the requested ticker's

    own rows win over a sibling's.

    """

    t = str(ticker or "").strip().upper()

    if not t:

        return {}

    if form == "MSFO":

        from financial_ingestion.publication import series

        published = series(t, quarterly=True)

        if published is not None:

            return published

    conn = catalogue_storage.get_catalog_conn()

    try:

        siblings = catalogue_filings._org_siblings(conn, t) or [t]

        placeholders = ",".join("?" * len(siblings))

        fin = conn.execute(

            f"SELECT ticker, year, quarter, balance_period, {', '.join(catalogue_fields._FIN_FIELDS)} "

            f"FROM catalog_financials "

            f"WHERE ticker IN ({placeholders}) AND form=? AND quarter!=0 "

            f"ORDER BY year, quarter",

            (*siblings, form)).fetchall()

    finally:

        conn.close()

    out: dict[str, dict[str, Any]] = {}

    for row in sorted(fin, key=lambda r: r["ticker"] == t):

        out.setdefault(f"{row['year']}Q{row['quarter']}", {}).update(_fin_row_fields(row))

    # As on the annual path, a correction-only quarter is still a real filed

    # quarter.  Q4 comes from the annual reader in derive_quarterly_series; add

    # Q1-Q3 here so a wholly absent cache row does not hide reviewed values.

    for period in (correction_periods_for(t) if form == "NSBU" else {}):

        if not period.endswith("Q4"):

            out.setdefault(period, {})

    for period, fields in out.items():

        _apply_registered_financial_corrections(t, period, fields, form=form, quarter=int(period[-1]))

    return out


def _remember_ifrs_sources(*, ticker: str, org_id: Any, records: list[dict]) -> int:
    """Retain every filing URL before the catalog projects filings into periods.

    A separate statement, group statement and revision can share the catalog's
    year key. The ingestion registry instead identifies documents by issuer and
    URL, so none of those originals should disappear in a catalog upsert.
    """
    from financial_ingestion import documents, extract, source_policy, store

    documents_to_register = []
    for record in records:
        if (str(record.get("organization")) != str(org_id)
                or record.get("report_type") not in {"MSFO", "Audition"}):
            continue
        document = catalogue_sources._build_report_document(record)
        url = document.get("pdf_url")
        if url and source_policy.allows(url):
            documents_to_register.append(document)
    if not documents_to_register:
        return 0
    processor = extract.processor_version()
    source_ids = set()
    with store.transaction() as c:
        for document in documents_to_register:
            source_ids.add(documents.register(
                c, org_id=org_id, ticker=ticker, url=document["pdf_url"],
                category=document["report_form"], metadata=document, processor=processor,
            ))
    return len(source_ids)


def _unified_statement_records(session: Any, org_id: Any, *,
                               period_type: str | None = None) -> list[dict[str, Any]]:
    """NSBU filings of the requested kind from the issuer's unified feed.

    Returns records carrying the accounting id the Excel export takes
    (``report_link``'s tail), the ``to_pdf`` id, the publication date and the
    export URL — everything except the period, which only the workbook knows.
    """
    out: list[dict[str, Any]] = []
    if not org_id:
        return out
    for page in range(1, 6):
        try:
            payload = catalogue_sources._json_get(session, "/reports/unified-financial-reports/",
                                {"format": "json", "page": page, "page_size": 200,
                                 "organization": org_id})
        except Exception as exc:
            raise RuntimeError(f"Statement filing discovery failed for issuer {org_id}, page {page}") from exc
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        for rec in results:
            props = rec.get("properties") or {}
            if str(rec.get("report_type") or "") != "NSBU":
                continue
            kind = str(props.get("report_type") or "").lower()
            if kind not in {"annual", "quarter"} or (period_type and kind != period_type):
                continue
            m = re.search(r"/reports/[a-z]+/[a-z]+/(\d+)/?$", str(rec.get("report_link") or ""))
            if not m or not rec.get("pub_date"):
                continue
            out.append({
                "accounting_id": m.group(1),
                "pdf_id": rec.get("id"),
                "pub_date": str(rec["pub_date"]),
                "org_type": props.get("org_type"),
                "title": props.get("report_title"),
                "period_type": kind,
                "excel_url": rec.get("excel_url") or catalogue_sources._nsbu_export_urls(
                    m.group(1), kind, props.get("org_type"))[1],
            })
        if len(results) < 200 or not (isinstance(payload, dict) and payload.get("next")):
            break
    # Newest first: a sweep that is cut short by a limit keeps the recent history
    # a reader is likelier to open.
    out.sort(key=lambda r: r["pub_date"], reverse=True)
    return out
