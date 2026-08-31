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
3.25 bn; KSCM and UZNGP report gross 30 and net 270 on revenue 10). Those figures
are shown as «данные проверяются», never as a number — but line by line, not row
by row: the failure withholds the multiples built FROM the broken line and leaves
the rest standing, because a liability that contradicts assets says nothing about
P/E and blanking the row for it published thirteen empty cells that had answers.

Everything is a pure function of its arguments — no database, no HTTP — so the
market screen, the company card and the export share one implementation.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date
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
STATUS_NEGATIVE_EQUITY = "negative_equity"   # «отрицательный капитал»
STATUS_NOT_APPLICABLE = "not_applicable"     # P/S у банка, ROE у облигации


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
# TTM — the twelve-month base (ТЗ мультипликаторов 2026-08-10, листы 01/02/10)
# ---------------------------------------------------------------------------

# P&L flows the TTM assembly covers. Balance lines are point-in-time and have
# no TTM; they come from balance_snapshot below.
TTM_KEYS = ("net_income", "revenue", "gross_profit", "operating_income",
            "noninterest_income")

_BANK_FORMS = ("bank", "microfinance")


def _interim_label(year: Any, quarter: Any) -> str:
    """«6М2026» — the way the ТЗ names a cumulative interim period."""
    return f"{int(quarter) * 3}М{int(year)}"


def twelve_month_flows(fin: dict[str, Any] | None,
                       keys: Sequence[str] = TTM_KEYS) -> dict[str, Any]:
    """Twelve months of each P&L flow, assembled the way the ТЗ orders it.

    ``TTM = годовая величина + YTD текущего года − YTD того же периода прошлого
    года`` (правило V1). All three components come from the same NSBU filings:
    the annual companion the read path attaches, the row's own figures, and the
    comparative the SAME filing prints beside them (value1/value2) — so a
    restated prior period is netted against the issuer's own restatement, never
    against a separately-filed report.

    Per key the preference order is:
      ``ttm``         annual(Y−1) + YTD(Y) − YTD(Y−1), all three present;
      ``annual``      the last complete fiscal year alone (the pre-ТЗ behaviour,
                      kept when the filing carries no comparative — the bank
                      form prints a single column);
      ``annualized``  the cumulative interim scaled ×12/months — ONLY when no
                      annual exists at all, and always flagged ``estimate``
                      («оценка»), as the ТЗ demands (6 мес × 2, 9 мес × 4/3).

    A Q4 quarterly (or the row being an annual) is already twelve months —
    NSBU interims accumulate from 1 January — and is served as ``annual``.

    Returns ``{"values": {key: float|None}, "methods": {key: str|None},
    "period": str|None, "months": 12|None, "estimate": bool, "status": str}``.
    ``period`` is the base-period label the interface shows next to the number
    («2025A + 6М2026 − 6М2025»), keyed to how net profit was assembled.
    """
    if not fin or not fin.get("year"):
        return {"values": {k: None for k in keys}, "methods": {k: None for k in keys},
                "period": None, "months": None, "estimate": False,
                "status": STATUS_NO_FINANCIALS}
    year = int(fin["year"])
    quarter = int(_num(fin.get("quarter")) or 0)
    months = period_months(fin) or 12

    values: dict[str, Any] = {}
    methods: dict[str, Any] = {}

    if months >= 12:
        # The row itself is twelve months of activity — an annual, or a Q4
        # cumulative filing standing in for one.
        for k in keys:
            values[k] = _num(fin.get(k))
            methods[k] = "annual" if values[k] is not None else None
        label = f"{year}A" if not quarter else f"{year}Q4"
        return {"values": values, "methods": methods, "period": label,
                "months": 12, "estimate": False, "status": STATUS_OK}

    annual = fin.get("annual") or None
    prior = fin.get("prior") or None
    # V1 binds the three components to consecutive periods of one issuer: the
    # 12-month base must be the year the interim continues, the comparative
    # must be the same interim one year earlier. Anything else is not a TTM.
    annual_ok = bool(annual and _num(annual.get("year")) == year - 1
                     and (period_months(annual) or 12) == 12)
    prior_ok = bool(prior and _num(prior.get("year")) == year - 1
                    and int(_num(prior.get("quarter")) or 0) == quarter)

    estimate = False
    for k in keys:
        current = _num(fin.get(k))
        annual_v = _num(annual.get(k)) if annual_ok else None
        prior_v = _num(prior.get(k)) if prior_ok else None
        if annual_v is not None and current is not None and prior_v is not None:
            values[k] = annual_v + current - prior_v
            methods[k] = "ttm"
        elif annual_v is not None:
            values[k] = annual_v
            methods[k] = "annual"
        elif current is not None and not annual_ok:
            values[k] = annualise(current, months)
            methods[k] = "annualized"
            estimate = True
        else:
            values[k] = None
            methods[k] = None

    lead = methods.get("net_income") or methods.get("revenue")
    if lead == "ttm":
        # The label IS the arithmetic. «2025A + 6М2026» read as eighteen months
        # of profit — the subtracted comparative was assembled but never named,
        # and a reader took the sum at face value. Spelled in full it can only
        # be read as the sliding twelve months it is.
        label = (f"{year - 1}A + {_interim_label(year, quarter)}"
                 f" − {_interim_label(year - 1, quarter)}")
    elif lead == "annual":
        label = f"{annual['year']}A" if annual else None
    elif lead == "annualized":
        label = _interim_label(year, quarter)
    else:
        label = period_label(fin)
    return {"values": values, "methods": methods, "period": label,
            "months": 12, "estimate": estimate, "status": STATUS_OK}


def report_age_days(fin: dict[str, Any] | None, today: date | None = None) -> int | None:
    """Days since the reporting period the row describes ENDED."""
    if not fin or not fin.get("year"):
        return None
    year = int(fin["year"])
    quarter = int(_num(fin.get("quarter")) or 0)
    month_end = {0: (12, 31), 1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    month, day = month_end.get(quarter, (12, 31))
    try:
        end = date(year, month, day)
    except ValueError:
        return None
    return ((today or date.today()) - end).days


def base_report_age(fin: dict[str, Any] | None,
                    today: date | None = None) -> tuple[str | None, int | None]:
    """The OLDEST period the earnings base rests on, and its age in days.

    Judging the latest filing alone is what let UZMT carry a P/E: its annualised
    9М2025 was 323 days old and passed, while the newest audited twelve months
    behind it — FY2019, 2423 days — was never looked at. UTGA the same, on a
    FY2023 annual. The complete twelve-month period is the thing a multiple is
    anchored to, so it is judged alongside the row: an issuer that has stopped
    filing annuals is out of date however punctually it files its quarters.

    The annual companion is the newest complete twelve months the issuer has
    (a filed annual, or the Q4 cumulative that stands in for one), attached by
    the read path whether or not the arithmetic ends up using it. Where none is
    attached the issuer has never filed one and the row answers for itself.

    Returns ``(period_label, age_days)`` for whichever period is older.
    """
    candidates = []
    for row in (fin, (fin or {}).get("annual")):
        if not row:
            continue
        age = report_age_days(row, today)
        if age is not None:
            candidates.append((age, period_label(row)))
    if not candidates:
        return (period_label(fin), None)
    age, label = max(candidates)
    return (label, age)


def _opening(value: Any, closing: float | None) -> float | None:
    """The period-opening balance, or None when the form left the column empty.

    An unfilled «на начало отчетного периода» cell comes back as a literal 0,
    not as null — the bank form and the young-issuer filings both do it. Averaged
    against a real closing figure that zero halves the denominator, and ROE/ROA
    come out at exactly twice the truth (UZNF 9,40% for 4,70%, TRSB 43,5% for
    23,6%, IPKY 37,9% for 19,0% — the multiplier was 2,00 in every case). A
    balance sheet that ends the period with assets or capital did not start it at
    nothing, so a zero opening beside a non-zero closing is a gap in the form and
    the average degrades to the closing value alone.

    A negative opening IS filed data — an issuer can carry a capital deficit into
    the period — and still averages.
    """
    start = _num(value)
    if start is None:
        return None
    if start == 0 and closing not in (None, 0):
        return None
    return start


def balance_snapshot(fin: dict[str, Any] | None,
                     ratio: dict[str, Any] | None,
                     today: date | None = None) -> dict[str, Any]:
    """The equity and assets every balance-side figure divides by.

    Preference is the FILED balance riding on the latest statement row
    (``fin["balance"]``: start and end of the period, straight from the form —
    jsc стр.480/400, bank «30»/«31», insurance стр.570/490). That is what the
    ТЗ orders for P/B («капитал на конец последнего квартального отчёта») and
    for ROE/ROA («средний за период»). The openinfo indicator feed remains the
    fallback for rows collected before the balance block existed — end values
    only, no average, and it is the feed whose insurance «капитал» carried the
    reserves, which is why it never wins over a filing.
    """
    fcfg = thresholds()["financials"]
    max_age = int(fcfg.get("report_max_age_days", 730))
    bal = (fin or {}).get("balance") or {}
    eq_end = _num(bal.get("equity_end"))
    as_end = _num(bal.get("assets_end"))
    if eq_end is not None or as_end is not None:
        eq_start = _opening(bal.get("equity_start"), eq_end)
        as_start = _opening(bal.get("assets_start"), as_end)
        age = report_age_days(fin, today)
        return {
            "equity": eq_end,
            "assets": as_end,
            # The mean of start and end where the filing states both; the end
            # value alone where it does not — never a number averaged with
            # itself dressed up as a period mean.
            "equity_avg": ((eq_start + eq_end) / 2.0
                           if eq_start is not None and eq_end is not None else eq_end),
            "assets_avg": ((as_start + as_end) / 2.0
                           if as_start is not None and as_end is not None else as_end),
            "period": period_label(fin),
            "source": "filing",
            "stale": age is not None and age > max_age,
        }
    ratio = ratio or {}
    equity = _num(ratio.get("total_equity"))
    assets = _num(ratio.get("total_assets"))
    period = ratio.get("period")
    parsed = parse_period(period)
    stale = False
    if parsed:
        age = report_age_days({"year": parsed[0], "quarter": parsed[1] // 3
                               if parsed[1] < 12 else 0}, today)
        stale = age is not None and age > max_age
    return {"equity": equity, "assets": assets,
            "equity_avg": equity, "assets_avg": assets,
            "period": str(period) if period else None,
            "source": "indicators", "stale": stale}


# ---------------------------------------------------------------------------
# Statement validation (ТЗ §7)
# ---------------------------------------------------------------------------

def validate_statement(fin: dict[str, Any] | None,
                       ratio: dict[str, Any] | None = None) -> dict[str, Any]:
    """Is this statement internally consistent enough to publish?

    Returns ``{"valid": bool, "status": str, "reasons": [...], "fields": {...},
    "findings": [...]}`` where ``fields`` names the individual lines that failed
    and ``findings`` pairs each line with the sentence explaining it, so the
    table can suppress one cell rather than the whole row where that is enough.
    """
    cfg = thresholds()["financials"]
    reasons: list[str] = []
    fields: dict[str, list[str]] = {}
    findings: list[dict[str, str]] = []

    def fail(field: str, code: str, reason: str) -> None:
        reasons.append(reason)
        fields.setdefault(field, []).append(code)
        findings.append({"field": field, "code": code, "reason": reason})

    if not fin:
        return {"valid": False, "status": STATUS_NO_FINANCIALS, "reasons": [],
                "fields": {}, "findings": []}

    revenue = _num(fin.get("revenue"))
    gross = _num(fin.get("gross_profit"))
    net = _num(fin.get("net_income"))
    liabilities = _num(fin.get("total_liabilities"))
    assets = _num((ratio or {}).get("total_assets"))
    equity = _num((ratio or {}).get("total_equity"))
    months = period_months(fin)

    if revenue is not None and revenue < 0:
        fail("revenue", "negative_revenue", "выручка отрицательна")

    if revenue is not None and gross is not None and revenue > 0:
        if abs(gross) > abs(revenue) * float(cfg["gross_profit_vs_revenue_max"]):
            fail("gross_profit", "gross_gt_revenue", "валовая прибыль больше выручки")

    if revenue is not None and net is not None and revenue > 0:
        if abs(net) > abs(revenue) * float(cfg["net_income_vs_revenue_max"]):
            fail("net_income", "net_gt_revenue", "чистая прибыль больше выручки в 1,5 раза")

    # Liabilities and assets come from two different filings — the NSBU statement
    # and openinfo's financial_indicators — and the second is often a different
    # year. Comparing across periods flags healthy issuers (ALKB's 2025 statement
    # against 2025 indicators is fine; its 2019 ones are not), so the check only
    # runs when both describe the SAME year.
    ratio_period = parse_period((ratio or {}).get("period"))
    same_period = bool(ratio_period and fin.get("year") and ratio_period[0] == int(fin["year"]))
    if same_period and assets is not None and liabilities is not None and assets > 0:
        if liabilities > assets * float(cfg["liabilities_vs_assets_max"]):
            fail("total_liabilities", "liab_gt_assets", "обязательства превышают активы")

    if equity is not None and equity <= 0:
        fail("total_equity", "equity_not_positive", "собственный капитал не положителен")

    # V2 (ТЗ мультипликаторов, лист 11): the filed balance must close — capital
    # plus obligations equals assets within 0,1 %. All three figures come from
    # the SAME filing here, so a miss is a broken parse or a broken filing, and
    # every balance-side figure built on it is withheld as «проверяется».
    bal = (fin or {}).get("balance") or {}
    bal_equity = _num(bal.get("equity_end"))
    bal_assets = _num(bal.get("assets_end"))
    # v2.2: quarantine a cross-form scale anomaly even if the income
    # statement is internally consistent and no prior annual exists.
    if bal_assets is not None and bal_assets > 0 and net is not None and abs(net) / bal_assets > 100:
        for field in ("revenue", "gross_profit", "net_income", "total_equity", "total_assets"):
            fail(field, "blocked_unit_mismatch", "масштабы Форм №1 и №2 требуют подтверждения источником")
    if (bal_equity is not None and liabilities is not None
            and bal_assets is not None and bal_assets > 0):
        tolerance = float(cfg.get("balance_identity_tolerance", 0.001))
        if abs(bal_equity + liabilities - bal_assets) > tolerance * abs(bal_assets):
            fail("total_equity", "balance_identity",
                 "баланс не сходится: капитал + обязательства ≠ активы")

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
            fail("net_income", "net_vs_equity_roe",
                 "прибыль не согласуется с капиталом и опубликованной ROE")

    # A cumulative period scaled to a year must land near the issuer's own annual
    # — but only where that comparison means anything. This rule hunts a units
    # error, and two gates keep it from calling ordinary business a defect:
    #
    #   * the annual must be the year that just ended. KSCM's newest annual is
    #     2020; measuring its 2026 half-year against it compares two different
    #     companies and fired on six issuers whose numbers were never in doubt.
    #   * both sides must earn a material share of revenue. Off a near-breakeven
    #     base the run-rate multiple explodes on arithmetic alone — GRBK made
    #     0.7 kopeks of profit per soum of 2025 revenue, so its recovery reads as
    #     11x with every figure correct. Where the profit IS material the rule
    #     still bites: UQEQ's half-year revenue is 400x its annual (3613x on
    #     profit), and that is the parsing error the rule exists to catch.
    #
    # A units error inside a hairline margin therefore passes here; it is left to
    # the net-income-vs-revenue and ROE cross-checks above, which do not depend
    # on a second filing to notice it.
    annual = fin.get("annual")
    if annual and months and months < 12:
        annual_net = _num(annual.get("net_income"))
        scaled = annualise(net, months)
        # Opposite signs are exempt: a loss year followed by a profitable half
        # (PLST: −3 829 млн annual against +4 504 млн in six months) multiplies
        # past any constant threshold on arithmetic alone, and a sign change is
        # exactly what a units error cannot produce.
        if annual_net and scaled and annual_net != 0 \
                and (annual_net > 0) == (scaled > 0) \
                and _periods_are_adjacent(fin, annual, cfg) \
                and _both_margins_material(fin, annual, cfg):
            ratio_ = abs(scaled / annual_net)
            limit = float(cfg["half_year_vs_annual_max"])
            if ratio_ > limit or ratio_ < 1.0 / limit:
                fail("net_income", "period_vs_annual",
                     "период не согласуется с годовым отчётом")

    valid = not reasons
    return {
        "valid": valid,
        "status": STATUS_OK if valid else STATUS_UNVERIFIED,
        "reasons": reasons,
        "fields": fields,
        "findings": findings,
        "period": period_label(fin),
        "months": months,
    }


def _periods_are_adjacent(fin: dict[str, Any], annual: dict[str, Any],
                          cfg: dict[str, Any]) -> bool:
    """Is the annual recent enough to be this interim's benchmark?"""
    year, annual_year = _num(fin.get("year")), _num(annual.get("year"))
    if year is None or annual_year is None:
        return False
    return abs(int(year) - int(annual_year)) <= int(cfg["period_vs_annual_max_year_gap"])


def _both_margins_material(fin: dict[str, Any], annual: dict[str, Any],
                           cfg: dict[str, Any]) -> bool:
    """Do both filings earn enough per soum of revenue for their ratio to mean
    anything? Unknown margins count as material: where we cannot measure
    thinness we keep the guard rather than drop it."""
    floor = float(cfg["period_vs_annual_min_margin"])
    for source in (fin, annual):
        revenue, net = _num(source.get("revenue")), _num(source.get("net_income"))
        if not revenue or net is None:
            continue
        if abs(net) / abs(revenue) < floor:
            return False
    return True


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
    _rejoin_preferred_classes(out)
    return out


def _rejoin_preferred_classes(groups: dict[str, list[dict[str, Any]]]) -> None:
    """Put a preferred class back with its ordinary when the NAMES disagree.

    The join key is the legal name because it is the only field both classes
    share — but the registry files the two classes of one issuer under names
    that normalise apart often enough to matter: 17 of 32 pairs (UZTL/UZTLP,
    HMKB/HMKBP, TRSB/TRSBP, ALKB/ALKBP…) landed in separate groups while 15
    joined. A stranded preferred class is not a cosmetic grouping error: ТЗ §8
    divides the WHOLE issuer's profit by the summed capitalisation of its
    classes, so alone it divided the whole company's earnings into the
    preferred float and printed P/E 0,12× for UZTLP, 0,005× for TRSBP.

    The ticker convention (ordinary + «P») settles it, and only where the source
    already calls the security preferred — BNGP ends in «P» and is ORDINARY, its
    preferred is BNGPP, so the flag decides and never the shape of the ticker.
    """
    where = {}
    for key, members in groups.items():
        for sec in members:
            where[str(sec.get("ticker") or "").upper()] = key
    for key in list(groups):
        for sec in list(groups.get(key, ())):
            ticker = str(sec.get("ticker") or "").upper()
            if not sec.get("is_preferred") or not ticker.endswith("P"):
                continue
            target = where.get(ticker[:-1])
            if target is None or target == key:
                continue
            groups[target].append(sec)
            groups[key].remove(sec)
            where[ticker] = target
        if not groups[key]:
            del groups[key]


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
# Multiples (ТЗ §8 + ТЗ мультипликаторов 2026-08-10)
# ---------------------------------------------------------------------------

def _flag_range(value: float | None, low: float, high: float, **extra: Any) -> dict[str, Any]:
    """V15: outside its plausibility range a multiple is PUBLISHED with a
    «проверить» flag — never silently hidden. Hiding is how KFSK's real P/B of
    73,86 and UZIR's P/E of 2 803,8 became unexplained dashes; a reader shown
    the number and the flag can judge, a reader shown a dash cannot."""
    if value is None:
        return _metric(None, STATUS_NO_FINANCIALS)
    if not (low <= value <= high):
        return _metric(value, STATUS_OUT_OF_RANGE, allowed=[low, high],
                       check=True, **extra)
    return _metric(value, STATUS_OK, **extra)


def _regression_checks(pe: dict[str, Any], pb: dict[str, Any], ps: dict[str, Any],
                       roe: dict[str, Any], roa: dict[str, Any],
                       net_margin: dict[str, Any],
                       equity_assets: dict[str, Any],
                       snap: dict[str, Any] | None = None) -> dict[str, Any]:
    """V11–V14 — the identities that bind the published figures to each other.

    P/E × ROE / 100 = P/B; P/S = P/E × маржа / 100; ROE / ROA = Активы /
    Капитал; ROE × К/А / 100 = ROA. A miss flags the row for review — it never
    hides a cell, because each identity mixes a price-side and a statement-side
    figure and cannot say which of the two is the wrong one.

    Three of the four bind a balance-side figure, and the ТЗ deliberately builds
    the two sides on DIFFERENT denominators: P/B and Капитал/Активы on capital
    at the period END (лист 09), ROE and ROA on the period AVERAGE. Compared
    literally the identities then fail for every issuer whose balance moved more
    than the tolerance during the period — which is nearly every issuer that
    grows: 45 of 95 rows carried a flag that meant nothing, and all 111 of those
    flags cleared the moment the same denominator was used on both sides. That
    artefact IS the external audit's «97% арифметики / 72% точь-в-точь».

    So the identities are evaluated against the AVERAGED base while the
    published cells keep their end-of-period denominators. Where the filing
    states no opening balance the average IS the closing figure and this changes
    nothing. The check measures the arithmetic, not the ТЗ's choice of base.

    None = the identity could not be evaluated (an input is absent), which is
    not a failure.
    """
    cfg = thresholds()["multiples"]
    tight = float(cfg.get("identity_tolerance", 0.01))
    loose = float(cfg.get("leverage_tolerance", 0.02))

    def val(metric: dict[str, Any] | None) -> float | None:
        return (metric or {}).get("value")

    def close(a: float | None, b: float | None, tol: float) -> bool | None:
        if a is None or b is None:
            return None
        scale = max(abs(a), abs(b))
        if scale == 0:
            return True
        return abs(a - b) <= tol * scale

    pe_v, pb_v, ps_v = val(pe), val(pb), val(ps)
    roe_v, roa_v, nm_v, ea_v = val(roe), val(roa), val(net_margin), val(equity_assets)

    # Restate the two balance-side cells on the base ROE and ROA divide by.
    snap = snap or {}
    eq_end, eq_avg = _num(snap.get("equity")), _num(snap.get("equity_avg"))
    as_avg = _num(snap.get("assets_avg"))
    if pb_v is not None and eq_end and eq_avg:
        pb_v = pb_v * eq_end / eq_avg
    if eq_avg is not None and as_avg:
        ea_v = eq_avg / as_avg * 100.0

    results = {
        "v11_pe_roe_pb": (close(pe_v * roe_v / 100.0, pb_v, tight)
                          if None not in (pe_v, roe_v, pb_v) else None),
        "v12_ps_pe_margin": (close(ps_v, pe_v * nm_v / 100.0, tight)
                             if None not in (ps_v, pe_v, nm_v) else None),
        "v13_leverage": (close(roe_v / roa_v, 100.0 / ea_v, loose)
                         if None not in (roe_v, roa_v, ea_v)
                         and roa_v != 0 and ea_v > 0 else None),
        "v14_roe_ea_roa": (close(roe_v * ea_v / 100.0, roa_v, loose)
                           if None not in (roe_v, ea_v, roa_v) else None),
    }
    return {"results": results,
            "flags": sorted(k for k, ok in results.items() if ok is False)}


def issuer_multiples(classes: Sequence[dict[str, Any]],
                     fin: dict[str, Any] | None,
                     ratio: dict[str, Any] | None,
                     earnings: dict[str, Any] | None = None,
                     today: date | None = None) -> dict[str, Any]:
    """Every multiple for one issuer — identical for all of its share classes.

    The twelve-month base is assembled by :func:`twelve_month_flows` (TTM where
    the filings allow it, the last complete year otherwise, an annualised
    estimate only when no year exists); the balance side comes from
    :func:`balance_snapshot` (the filed balance first, the indicator feed as
    legacy fallback). ``earnings`` is accepted for backward compatibility and
    ignored — the selection the ТЗ orders is not a caller's choice anymore.
    """
    cfg = thresholds()["multiples"]
    fcfg = thresholds()["financials"]
    ratio = ratio or {}
    validation = validate_statement(fin, ratio)

    cap = market_cap_issuer(classes)
    flows = twelve_month_flows(fin)
    snap = balance_snapshot(fin, ratio, today)
    shares_check = share_count_consistency(classes)

    org_type = str((fin or {}).get("org_type") or "").lower() or None
    if org_type is None and any(c.get("ticker") == "DRBK" for c in classes):
        org_type = "bank"  # Davr-bank; legacy cache omitted its form type.
    sector = next((str(c.get("sector") or "").lower()
                   for c in classes if c.get("sector")), None)
    is_bank = org_type in _BANK_FORMS
    # P/S has no meaning where «выручка» is not a form line: banks and insurers
    # (лист 07). Until the form type has been collected, the finance sector is
    # the conservative stand-in — a P/S briefly missing is a smaller lie than a
    # bank shown with one.
    is_financial = (is_bank or org_type == "insurance"
                    or (org_type is None and sector == "finance"))

    ni = flows["values"].get("net_income")
    revenue = flows["values"].get("revenue")
    base_period = flows["period"] or period_label(fin)
    base_months = flows["months"] or period_months(fin)
    estimate = True if flows["estimate"] else None

    # V4: a base older than two years is not current data. «нет данных», not a
    # number computed off a 2019 annual (the UZMT case) — and the age is the age
    # of the OLDEST period the base rests on, the last complete twelve months
    # included, not of the most recent filing alone.
    stale_period, age = base_report_age(fin, today)
    max_age = int(fcfg.get("report_max_age_days", 730))
    if fin and age is not None and age > max_age:
        note = ("последний годовой отчёт старше 2 лет"
                if stale_period != period_label(fin) else "последний отчёт старше 2 лет")
        stale = _metric(None, STATUS_STALE, base_period=stale_period, age_days=age,
                        note=note)
        return {
            "market_cap_issuer": cap, "base_period": stale_period,
            "base_months": period_months(fin), "balance_period": period_label(fin),
            "org_type": org_type,
            "pe": dict(stale), "pb": dict(stale), "ps": dict(stale),
            "roe": dict(stale), "roa": dict(stale), "net_margin": dict(stale),
            "equity_assets": dict(stale), "bvps": _metric(None, STATUS_STALE),
            "shares_check": shares_check, "validation": validation,
            "checks": {"results": {}, "flags": []},
        }

    cap_value = cap["value"]
    equity, assets = snap.get("equity"), snap.get("assets")
    equity_avg, assets_avg = snap.get("equity_avg"), snap.get("assets_avg")
    bal_period, bal_stale = snap.get("period"), bool(snap.get("stale"))
    bal_source = snap.get("source")

    pe_lo, pe_hi = (float(x) for x in cfg["pe_range"])
    pb_lo, pb_hi = (float(x) for x in cfg["pb_range"])
    ps_lo, ps_hi = (float(x) for x in cfg.get("ps_range", [0.01, 50]))
    roe_max = float(cfg["roe_abs_max"])
    margin_max = float(cfg.get("margin_abs_max", 100))

    # --- P/E: cap over twelve months of profit ------------------------------
    if cap_value is None:
        pe = _metric(None, "no_market_cap")
    elif ni is None:
        pe = _metric(None, STATUS_NO_FINANCIALS)
    elif ni <= 0:
        # ТЗ: at a loss the cell says «убыток» — a number is not printed and
        # the row does not sort beside profitable issuers as if it were cheap.
        pe = _metric(None, STATUS_LOSS, base_period=base_period)
    else:
        pe = _flag_range(cap_value / ni, pe_lo, pe_hi,
                         base_period=base_period, base_months=base_months,
                         estimate=estimate)

    # --- P/B: cap over the LAST FILED balance's equity -----------------------
    if bal_stale:
        pb = _metric(None, STATUS_STALE, base_period=bal_period,
                     note="баланс старше 2 лет")
    elif cap_value is None:
        pb = _metric(None, "no_market_cap")
    elif equity is None:
        pb = _metric(None, STATUS_NO_FINANCIALS)
    elif equity <= 0:
        pb = _metric(None, STATUS_NEGATIVE_EQUITY, base_period=bal_period)
    else:
        pb = _flag_range(cap_value / equity, pb_lo, pb_hi,
                         base_period=bal_period, balance_source=bal_source)

    # --- P/S: the multiple that works at a loss; not for the financial forms -
    if is_financial:
        ps = _metric(None, STATUS_NOT_APPLICABLE,
                     note="для банков и страховых вместо P/S — Капитал/Активы")
    elif cap_value is None:
        ps = _metric(None, "no_market_cap")
    elif revenue is None or revenue <= 0:
        ps = _metric(None, STATUS_NO_FINANCIALS,
                     note=None if revenue is None else "выручка TTM не положительна")
    else:
        ps = _flag_range(cap_value / revenue, ps_lo, ps_hi,
                         base_period=base_period, estimate=estimate)

    # --- ROE / ROA: TTM profit over the period-average base ------------------
    def _return_on(average: float | None) -> dict[str, Any]:
        if bal_stale:
            return _metric(None, STATUS_STALE, base_period=bal_period)
        if ni is not None and average is not None:
            if average <= 0:
                return _metric(None, STATUS_NEGATIVE_EQUITY, base_period=bal_period)
            return _flag_range(ni / average * 100.0, -roe_max, roe_max,
                               base_period=base_period,
                               denominator_period=bal_period, estimate=estimate)
        return _metric(None, STATUS_NO_FINANCIALS)

    roe = _return_on(equity_avg)
    if roe.get("status") == STATUS_NO_FINANCIALS and ratio.get("roe") is not None:
        # Legacy passthrough for rows the filings cannot yet answer for.
        roe = _flag_range(_num(ratio.get("roe")), -roe_max, roe_max,
                          base_period=ratio.get("period"), source="indicators")
    roa = _return_on(assets_avg)
    if roa.get("status") == STATUS_NO_FINANCIALS and ratio.get("roa") is not None:
        roa = _flag_range(_num(ratio.get("roa")), -roe_max, roe_max,
                          base_period=ratio.get("period"), source="indicators")

    # --- Net margin: one period, one unit (percent) --------------------------
    if is_bank:
        nonint = flows["values"].get("noninterest_income")
        margin_ni, margin_revenue = ni, revenue
        margin_period, margin_estimate = base_period, estimate
        methods = {flows["methods"].get(k) for k in ("net_income", "revenue", "noninterest_income")}
        if len(methods) != 1 or None in methods:
            # Never add annual non-interest income to TTM interest income.
            # A complete annual remains usable, with its own explicit period.
            annual = (fin or {}).get("annual") or {}
            margin_ni = _num(annual.get("net_income"))
            margin_revenue = _num(annual.get("revenue"))
            nonint = _num(annual.get("noninterest_income"))
            margin_period = period_label(annual)
            margin_estimate = None
        total_income = (margin_revenue + nonint
                        if margin_revenue is not None and nonint is not None else None)
        if margin_ni is not None and total_income is not None and total_income > 0:
            net_margin = _flag_range(margin_ni / total_income * 100.0, -margin_max, margin_max,
                                     base_period=margin_period, estimate=margin_estimate,
                                     numerator=margin_ni, denominator_value=total_income,
                                     denominator="total_income",
                                     note="для банков — от совокупного дохода")
        else:
            net_margin = _metric(None, STATUS_NO_FINANCIALS,
                                 note="совокупный доход банка недоступен")
    elif ni is not None and revenue is not None and revenue > 0:
        net_margin = _flag_range(ni / revenue * 100.0, -margin_max, margin_max,
                                 base_period=base_period, estimate=estimate)
    elif ratio.get("net_profit_margin") is not None:
        net_margin = _metric(_num(ratio.get("net_profit_margin")), STATUS_OK,
                             source="indicators", base_period=ratio.get("period"))
    else:
        net_margin = _metric(None, STATUS_NO_FINANCIALS)

    # --- Капитал/Активы: the Долг/Капитал replacement (лист 08) --------------
    if bal_stale:
        equity_assets = _metric(None, STATUS_STALE, base_period=bal_period)
    elif equity is not None and assets is not None and assets > 0:
        ea_value = equity / assets * 100.0
        if ea_value > 100.0:
            # Bounded above by construction: capital exceeding the balance it
            # is part of is an extraction error, not a figure (лист 08 п.9).
            equity_assets = _metric(None, STATUS_OUT_OF_RANGE, computed=ea_value,
                                    allowed=[0, 100],
                                    note="капитал больше активов — ошибка извлечения")
        elif ea_value < 0:
            equity_assets = _metric(ea_value, STATUS_NEGATIVE_EQUITY,
                                    base_period=bal_period)
        else:
            equity_assets = _metric(ea_value, STATUS_OK, base_period=bal_period,
                                    balance_source=bal_source)
    else:
        equity_assets = _metric(None, STATUS_NO_FINANCIALS)

    bvps = bvps_issuer(classes, equity)

    # A capitalisation that disagrees with price × shares poisons every
    # cap-based figure and no other (ТЗ §8).
    if not shares_check["consistent"]:
        worst = max(shares_check["findings"], key=lambda f: abs(math.log10(f["ratio"])))
        note = (f"капитализация {worst['ticker']} расходится с ценой на акцию "
                f"в {worst['ratio']:.0f} раз")
        blocked = _metric(None, STATUS_INCONSISTENT, note=note)
        pe, pb, ps = dict(blocked), dict(blocked), dict(blocked)

    result = {
        "market_cap_issuer": cap,
        "base_period": base_period,
        "base_months": base_months,
        "balance_period": bal_period,
        "org_type": org_type,
        "pe": pe, "pb": pb, "ps": ps,
        "roe": roe, "roa": roa,
        "net_margin": net_margin,
        "equity_assets": equity_assets,
        "bvps": bvps,
        "shares_check": shares_check,
        "validation": validation,
    }
    result = _suppress_unverified(result, validation)
    # The identities run over what will actually be published — after the
    # suppressions, not before — or they would flag cells the reader never saw.
    result["checks"] = _regression_checks(result["pe"], result["pb"], result["ps"],
                                          result["roe"], result["roa"],
                                          result["net_margin"], result["equity_assets"],
                                          snap)
    return result


# Which statement lines each multiple is actually built from. A failure withholds
# the multiples that read the broken line and no others: obligations that exceed
# assets say nothing about P/E, and before this one bad line took the whole row
# dark. Revenue and gross profit count as inputs to every profit-based multiple —
# when the top of the P&L cannot be true, the net income read out of the same
# column is not evidence either. Долг/Капитал is gone from the storefront by the
# audit's decision (лист 06) — 47 of its 99 values reproduced under no formula.
MULTIPLE_INPUTS: dict[str, tuple[str, ...]] = {
    "pe": ("revenue", "gross_profit", "net_income"),
    "pb": ("total_equity",),
    "ps": ("revenue", "gross_profit"),
    "roe": ("revenue", "gross_profit", "net_income", "total_equity"),
    "roa": ("revenue", "gross_profit", "net_income", "total_assets"),
    "net_margin": ("revenue", "gross_profit", "net_income"),
    "equity_assets": ("total_equity", "total_assets"),
}


def _suppress_unverified(result: dict[str, Any],
                         validation: dict[str, Any]) -> dict[str, Any]:
    """Withhold the multiples a failed statement line feeds, carrying that line's
    own reason — the cell says «проверяется» about the number it describes."""
    findings = validation.get("findings") or []
    if validation.get("valid", True) or not findings:
        return result
    if any(f.get("code") == "blocked_unit_mismatch" for f in findings):
        for metric in (*MULTIPLE_INPUTS, "bvps"):
            result[metric] = _metric(None, "blocked_unit_mismatch", note="межформенный масштаб не подтверждён")
        return result
    for metric, inputs in MULTIPLE_INPUTS.items():
        reasons = list(dict.fromkeys(f["reason"] for f in findings if f["field"] in inputs))
        if not reasons:
            continue
        current = result.get(metric) or {}
        result[metric] = _metric(None, STATUS_UNVERIFIED, reasons=reasons,
                                 base_period=current.get("base_period"))
    return result


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
