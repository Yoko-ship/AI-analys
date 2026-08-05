# coding: utf-8
"""Structured-JSON reconciliation of issuer financials against openinfo.uz.

Unlike the legacy Excel/PDF parser (openinfo_collector.py / reports_catalog.py),
this reads openinfo's clean structured report detail:

    list:   GET /api/v2/reports/main/?search={TICKER}&page_size=40
    detail: GET /api/v2/reports/{jsc|bank|insurance}/{quarter|annual}/{object_id}/

and applies the report-reading rules that the legacy path got wrong:

  * P&L (revenue, net profit): banks publish one signed ``value`` column; jsc and
    insurance publish an unsigned "прибыль" / "убыток" pair, so value1 is taken as
    positive and value2 as NEGATIVE. Never value1 - value2. Never index by array
    position.
  * Balance (liabilities, cash): value2 (end of period), fallback value1 / value.
  * All openinfo amounts are in thousands -> multiply by 1000 for the full sum.
  * Period = reporting_year (period-end date). quarter_no is a FORM code, not a
    quarter number, and is ignored. The chosen report is the one covering the
    latest reporting PERIOD, not the one published last — publication date only
    breaks ties between versions of the same period (a restated or audited
    refiling). Filing order and period order come apart every summer: an issuer
    files Q1 in late April and then the *previous* year's annual in July, and
    "newest published" hands last year's figures to a row labelled this year.
  * openinfo mis-stamps period-ends. A period cannot end after the report that
    carries it was filed, so pub_date bounds it: an interim stamped with its own
    filing day snaps back to the last quarter that had actually ended, and an
    annual stamped with a current/future year-end (2026-12-31 filed mid-2026) is
    clamped to the last fiscal year complete at filing. Both are logged.
  * Bind the issuer by organization id when openinfo's own ticker registry knows
    it (organizations.exchange_ticket_name), else by search + the report's
    organization_ticket_name (comma-separated), so ordinary / preferred siblings
    stay aligned.

Row map:
  bank      revenue = "Итого процентных доходов"; net = last "ЧИСТАЯ ПРИБЫЛЬ";
            liabilities = "Итого обязательств" (excl. "…и собственного капитала");
            cash = "Кассовая наличность…"; gross = None.
  jsc       revenue = tnum 010; net = "Чистая прибыль…отчетного периода" (tnum 270);
            gross = "Валовая прибыль" (030); operating = "…от основной деятельности".
  insurance revenue = tnum 010 ("Доходы от оказания страховых услуг"); net = tnum 320.
  jsc+ins   liabilities = the published obligations subtotal — "ИТОГО ПО II
            РАЗДЕЛУ (стр. 490+600)" on the jsc form, "Итого по разделу III
            (стр. 730+930)" on the insurance one — re-adding the two parts only
            when a filing omits it; cash = "Денежные средства на расчетном счете
            (5100)", not the "Денежные средства, всего" roll-up.
  microfin  same shape as bank (single-column P&L) except cash, which the
            microfinance form calls "Денежные средства в кассе…".

This module is a read/verify tool by default (compare against the reconciliation
registry) and can emit corrected rows for the existing push path.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re

import openinfo_http as _http
from numeric_parse import parse_decimal

log = logging.getLogger(__name__)

API_BASE = "https://new-api.openinfo.uz/api/v2"

# openinfo's own issuer registry — `exchange_ticket_name` is a comma-separated
# ticker list per organization, i.e. a ready ticker -> org id map for 273 of the
# symbols the exchange lists. Binding by org id removes the search step (and its
# ambiguity: "vagon" alone matches three different issuers).
ORGANIZATIONS_URL = f"{API_BASE}/organizations/organizations/"
UNIFIED_REPORTS_URL = f"{API_BASE}/reports/unified-financial-reports/"

# Report forms whose detail endpoint this module knows how to read.
ORG_TYPES = ("jsc", "bank", "insurance", "microfinance")

# Tickers whose own symbol is not openinfo's search key (bonds, some preferred /
# extra share classes) -> resolve the issuer by a parent ticker or issuer name.
# For these the strict organization_ticket_name check is relaxed (the symbol is
# not carried in the issuer's ticket list); the name/parent search is trusted.
SEARCH_OVERRIDE = {
    # bonds -> parent equity ticker
    "ALK201": "ALKB",
    "HMBK1": "HMKB",
    "KKB2": "BRBN",
    "MCB2": "MCBA",
    "IPTB2": "IPTB",
    "TNB101": "TNBN",
    "IPK3": "IPKY", "IPK4": "IPKY", "IPK5": "IPKY",
    "TRS2": "TRSB", "TRS201": "TRSB",
    "SQB2": "SQBN", "SQB3": "SQBN", "SQB301": "SQBN", "SQB4": "SQBN",
    "SQB6": "SQBN", "SQB7": "SQBN", "SQB8": "SQBN",
    "BFMT2B5": "Biznes Finans", "BFMT3B4": "Biznes Finans",
    "BFMT3V2": "Biznes Finans", "BFMT3V3": "Biznes Finans",
    "TNGB": "Tenge Bank",
    "UZUMS3B": "Uzum",
    # tickers openinfo's search does not index -> issuer name
    "KFSK": "Kafolat", "KFSKP": "Kafolat",
    "KPB2": "Kapitalbank", "KPB3": "Kapitalbank",
    "KPBA1": "Kapitalbank", "KPBA10": "Kapitalbank",
    "MXUS": "Maxsus trest",
    "PLSTP": "Portlatishsanoat",
    "TGBK": "Tenge Bank",
    "TGPG": "Tashgiprogor",
    "TKDM": "Toshkentdonmahsulotlari", "TKDMP": "Toshkentdonmahsulotlari",
    "UPOSP": "pochtasi",
    "UZMB2": "metallurgiya kombinati",
    "YRFS": "reftrans",
}
# Backwards-compatible alias.
BOND_PARENT = SEARCH_OVERRIDE

# Site ticker -> the symbol openinfo actually carries in organization_ticket_name,
# for issuers the exchange lists under a different code.
TICKER_ALIAS = {
    "KFSK": "KFLT", "KFSKP": "KFLTP",  # Kafolat sug'urta
    "NGQT": "NGSR",                     # NGQT AJ
}

# Relaxed tickers whose issuer report must additionally match this org-name hint
# (used to disambiguate a shared search prefix, e.g. "Uzum Bank" vs "Uzum Sarmoya").
ORG_HINT = {
    "UZUMS3B": "sarmoya",
}

# Tickers whose exact symbol/alias is not carried in organization_ticket_name and
# so bypass the strict ticket check (bonds + issuers openinfo lists without tickets).
RELAXED_MATCH = (set(SEARCH_OVERRIDE) - {"KFSK", "KFSKP"})

# Tickers openinfo's ticker registry does not carry and whose issuer cannot be
# reached by search either — bond symbols that share no prefix with the issuer.
# Pinned to the organization id, verified by INN against the issuer registry, so
# the reports are listed by organization instead of guessed by name.
ORG_ID_OVERRIDE = {
    "ACMT1B2": 1058, "ACMT1B3": 1058,          # "AGAT CREDIT" AJ MMT, INN 304463924
    "ACMT2B4": 1058, "ACMT2B5": 1058,
    "CTFB3": 1067, "CTFB3B2": 1067,            # "CONTACT FINANCE" MCHJ MMT, INN 311426602
    "UZUMS3B": 1100,                           # "UZUM SARMOYA" MCHJ XK, INN 310953289
    # Registered, but with a junk exchange_ticket_name ('0', empty) so the
    # registry cannot map them, and a name search that is ambiguous ("vagon"
    # matches three issuers). Pinned by INN.
    "UTHK": 80,                                # "O'z-Tong Hong Kompani" QK AJ, INN 201832779
    "UVGT": 731,                               # "O'zvagonta'mir" AJ, INN 203661294
    # Files 25 NSBU insurance forms, but its eight most recent disclosures are all
    # IFRS — which is why it was written off as IFRS-only and left unreconciled.
    # Do not substitute the lookalike "O'zbekinvest Hayot" (org 898): different issuer.
    "UZIN": 835, "UZINP": 835,                 # "O'zbekinvest", INN 201222058
}

# Tickers with no openinfo source at all — never auto-reconciled (раздел 8).
NO_SOURCE: set[str] = set()

# Pathological issuers whose recent openinfo NSBU filings are empty placeholders
# (holding companies reporting only in IFRS); auto-selection would walk back to
# stale years, so they are left for manual handling rather than "chased".
MANUAL_SKIP = {"UZNG", "UZNGP"}


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _getj(url, params=None):
    r = _http.get(url, params=params)
    r.raise_for_status()
    return r.json()


def _norm(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).lower().replace("ё", "е")).strip()


def _num(x):
    """One reconciler figure as a float, via the shared separator rules.

    A blanket comma->dot replacement here silently dropped every comma-grouped
    amount ("1,234,567" became the unparseable "1.234.567"), which on the
    authoritative reconcile path means a published figure just vanishes.
    """
    if x is None or (isinstance(x, str) and x.strip() in ("", "None")):
        return None
    return parse_decimal(x, group_sep=",", strip_non_numeric=False)


def _parse_date(s):
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# metric extraction (proven against the reconciliation oracle)
# --------------------------------------------------------------------------- #
def _signed_pair(row, profit_key, loss_key):
    """One доходы/расходы column pair as a signed number.

    A result line puts a PROFIT in the "доходы (прибыль)" column and a LOSS in
    "расходы (убытки)", as an unsigned magnitude — so "the first non-zero, keeping
    its stored sign" publishes every loss as a profit of the same size, and the
    board cannot tell a loss-maker from a top earner nor P/E from its negation.
    """
    profit, loss = _num(row.get(profit_key)), _num(row.get(loss_key))
    if profit:
        return profit
    if loss:
        return -loss
    return 0.0 if (profit is not None or loss is not None) else None


def pl_value(row):
    """P&L cell for the REPORTING period, in the sign convention its form uses.

    Two layouts exist:

      * bank / microfinance — one ``value`` column, already signed, no comparative.
      * jsc / insurance (NSBU form 2) — FOUR columns. **value3/value4 are
        "За отчетный период", value1/value2 the comparative "За соответствующий
        период прошлого года"** — that order, and not the intuitive one.

    This was read the wrong way round until 2026-08-04, so every non-bank
    issuer's revenue, gross profit, operating income and net income on the board
    was a year stale, and nothing caught it because each pair balances against
    itself (010 - 020 = 030 holds in both).

    Chronology settles it and needs no assumption: a filing's comparative is the
    same quarter one year earlier, so for the same quarter in consecutive years
    ``newer.value1 == older.value3``. O'zRTXB's 2025-06-30 filing carries
    237 634 918 in value3 and its 2026-06-30 filing carries the same number in
    value1 — a report published in July 2025 cannot hold H1 2026 figures, so
    237 634 918 is H1 2025 and value3 is the reporting period. Measured across
    thirty matched year-pairs and eight issuers: thirty for value3, none against.
    The balance sheet is NOT reversed — its value1 is "на начало года" (the same
    number repeats across Q1/Q2/Q3 of a year, as 1 January must) and value2 the
    period end, which is what ``bal_value`` already reads.
    """
    if row is None:
        return None
    if "value" in row:
        v = _num(row.get("value"))
        return v if v is not None else None
    return _signed_pair(row, "value3", "value4")


def prior_value(row):
    """The same P&L cell for the comparative period printed beside it.

    value1/value2 — "за соответствующий период прошлого года". See ``pl_value``
    for why that is the pair that looks like the reporting one. Only the jsc /
    insurance form has a comparative at all; the bank and microfinance forms
    publish a single ``value`` column.
    """
    if row is None or "value" in row:
        return None
    return _signed_pair(row, "value1", "value2")


def bal_value(row):
    """Balance cell: end of period = first NON-ZERO of value2, value1, value.

    value2 is normally the period-end column, but some quarter forms leave value2
    at 0 and carry the end figure in value1 (e.g. several banks' Q2 balance), so a
    zero value2 must fall back rather than being taken literally.

    Safe for a TOTAL, which is never legitimately zero. For a single account line
    it is not: see :func:`end_key` / :func:`end_value`, which decide the period-end
    column once for the whole statement so that a real zero stays a zero.
    """
    if row is None:
        return None
    for k in ("value2", "value1", "value"):
        if k in row:
            v = _num(row.get(k))
            if v is not None and v != 0:
                return v
    for k in ("value2", "value1", "value"):
        if k in row and _num(row.get(k)) is not None:
            return 0.0
    return None


def end_key(bal):
    """Which column carries the period end for THIS balance sheet.

    Normally value2 ("на конец отчетного периода"); a few filings leave the whole
    value2 column at zero and carry the period end in value1 instead, and the bank
    form publishes a single ``value``. Decided ONCE per statement, from whether the
    column has any data at all anywhere in it — never per row.

    Per row it cannot be decided, and deciding it per row is a live bug source: an
    account that legitimately went to zero (a long-term loan repaid, an emptied
    settlement account) looks exactly like an unfilled cell, and falling back to
    value1 there serves the OPENING balance as the closing one. BIOK's Q2 2026
    filing is the proof — стр.490 ends the period at 0 after repaying 9 000 000
    thousand, and reading the opening figure put a debt on the board the issuer no
    longer owes, 42% above its own published total.
    """
    for k in ("value2", "value1", "value"):
        if any(_num(r.get(k)) for r in bal):
            return k
    return "value2"


def end_value(row, key):
    """One balance cell from the statement's period-end column, zeros included."""
    if row is None:
        return None
    if key in row:
        return _num(row.get(key))
    return bal_value(row)


def _rows(detail, *keys):
    for k in keys:
        r = detail.get(k)
        if isinstance(r, list) and r:
            return r
    return []


def _by_tnum(rows, tnum):
    for r in rows:
        if str(r.get("tnum")) == tnum:
            return r
    return None


_FORMULA_RE = re.compile(r"стр\.?\s*([\d\s+]+)")


def _formula_tnums(title):
    """The line numbers a form's «(стр.330+340+350+360)» formula names."""
    m = _FORMULA_RE.search(_norm(title))
    return re.findall(r"\d+", m.group(1)) if m else []


def _breakdown_is_blank(rows, total_row, key):
    """True when a roll-up carries a figure but every line it sums reads nought.

    Then the issuer filed the total and skipped the breakdown, so there is no
    per-account figure in the filing to serve — as opposed to an account that
    really is empty, which shows up as a zero beside non-zero siblings. AGMK's
    2026 Q2 balance is the case that needs telling apart: «Денежные средства,
    всего» 688 238 787 with 5000, 5100, 5200 and 5500 all at nought.
    """
    if total_row is None:
        return False
    if not end_value(total_row, key):
        return False
    parts = _formula_tnums(total_row.get("title"))
    if not parts:
        return False
    return not any(end_value(_by_tnum(rows, t), key) for t in parts)


def _section_total(rows, part_rows, key):
    """The published «Итого по разделу …» line that sums exactly ``part_rows``.

    Found by its own printed formula rather than by its wording, because the two
    NSBU balance forms word it differently and neither wording is unique on the
    page: the jsc form prints «ИТОГО ПО II РАЗДЕЛУ (стр. 490+600)» while the
    insurance form prints «Итого по разделу III (стр. 730 + 930)», and the asset
    side of both prints «ИТОГО ПО РАЗДЕЛУ II (стр. 140+…)». The line numbers of
    the parts identify their total exactly, whatever the form calls it.
    """
    nums = [str(r.get("tnum") or "").strip() for r in part_rows if r is not None]
    if len(nums) != len(part_rows) or not all(nums):
        return None
    formula = "+".join(nums)
    for r in rows:
        squashed = re.sub(r"\s+", "", _norm(r.get("title")))
        if "итого" in squashed and formula in squashed:
            return end_value(r, key)
    return None


def _by_title(rows, needles, exclude=None, last=False):
    needles = [_norm(n) for n in needles]
    exclude = [_norm(e) for e in (exclude or [])]
    hits = [r for r in rows
            if all(n in _norm(r.get("title")) for n in needles)
            and not any(e in _norm(r.get("title")) for e in exclude)]
    if not hits:
        return None
    return hits[-1] if last else hits[0]


def extract_metrics(detail):
    """6 metrics in openinfo thousands (caller multiplies by 1000)."""
    org = detail.get("org_type")
    pl = _rows(detail, "quarter_financial_results_report", "financial_results_report")
    bal = _rows(detail, "quarter_balance_sheet_report", "balance_sheet_report")
    out = {
        "org_type": org,
        "reporting_year": detail.get("reporting_year"),
        "tickets": detail.get("organization_ticket_name"),
        "gross_profit": None,
        "operating_income": None,
        "prior": None,
    }
    if org in ("bank", "microfinance"):
        # The microfinance form is the bank form with different wording: its P&L
        # totals sit in a single `value` column ("Всего процентных доходов",
        # "Чистая прибыль (убыток)") and its liabilities line reads "Итого
        # обязательства", which the bank needle already matches as a prefix. Only
        # the cash line differs — no "кассовая наличность" row exists.
        out["revenue"] = pl_value(_by_title(pl, ["итого процентных доходов"])
                                  or _by_title(pl, ["всего процентных доходов"]))
        out["net_income"] = pl_value(_by_title(pl, ["чистая прибыль"], last=True))
        out["total_liabilities"] = bal_value(_by_title(bal, ["итого обязательств"], exclude=["капитал"]))
        out["cash"] = bal_value(_by_title(bal, ["кассовая наличность"])
                                or _by_title(bal, ["денежные средства в кассе"]))
    else:  # jsc / insurance
        rev_row = _by_tnum(pl, "010") or _by_title(pl, ["выручка"])
        net_row = _by_title(pl, ["чистая прибыль", "отчетного периода"])
        gross_row = _by_title(pl, ["валовая прибыль"])
        oper_row = _by_title(pl, ["прибыль", "от основной деятельности"])
        out["revenue"] = pl_value(rev_row)
        out["net_income"] = pl_value(net_row)
        out["gross_profit"] = pl_value(gross_row)
        out["operating_income"] = pl_value(oper_row)
        # ...and the comparative the same form prints beside each of them. Only
        # the P&L has one: the balance sheet's two columns are "на начало года"
        # and "на конец периода", which is a different statement, so cash and
        # liabilities have no prior-year figure here and must not be given one.
        prior = {"revenue": prior_value(rev_row),
                 "gross_profit": prior_value(gross_row),
                 "net_income": prior_value(net_row),
                 "operating_income": prior_value(oper_row)}
        out["prior"] = prior if any(v is not None for v in prior.values()) else None
        key = end_key(bal)
        # Obligations: the total the issuer itself published — «Итого по разделу
        # III (стр.730+930)» on the insurance form, «ИТОГО ПО II РАЗДЕЛУ
        # (стр.490+600)» on the jsc one. Re-adding the two parts is only the
        # fallback for a filing that omits the total: the parts are what carry an
        # unfilled or mis-keyed cell, and where the two disagree the published
        # total is the figure that satisfies the balance identity (BIOK 2026Q2:
        # parts 30 324 562, published 21 324 562, assets − equity = 21 324 562).
        lt_row = _by_title(bal, ["долгосрочные обязательства", "всего"])
        cur_row = _by_title(bal, ["текущие обязательства", "всего"])
        total = _section_total(bal, [lt_row, cur_row], key)
        if total is None:
            lt, cur = end_value(lt_row, key), end_value(cur_row, key)
            total = None if lt is None and cur is None else (lt or 0.0) + (cur or 0.0)
        out["total_liabilities"] = total
        # Cash: the settlement account, «Денежные средства на расчетном счете
        # (5100)» — the operating balance, not the «Денежные средства, всего»
        # roll-up that also carries the till (5000), the FX accounts (5200) and
        # the equivalents (5500/5600/5700). A settlement account that ends the
        # period empty reads 0: that is the issuer's own figure, not a gap. The
        # roll-up serves only where the filing has no such line, or none of the
        # accounts under it was filled in at all.
        cash_row = (_by_title(bal, ["денежные средства", "расчетном счете"])
                    or _by_title(bal, ["денежные средства", "(5100)"]))
        cash_total_row = _by_title(bal, ["денежные средства", "всего"])
        if cash_row is not None and not _breakdown_is_blank(bal, cash_total_row, key):
            out["cash"] = end_value(cash_row, key)
        else:
            out["cash"] = bal_value(cash_total_row)
    return out


# --------------------------------------------------------------------------- #
# report selection
# --------------------------------------------------------------------------- #
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,12}$")
_org_map_cache = None


def ticker_org_map(refresh=False):
    """ticker -> organization id, from openinfo's own issuer registry.

    `exchange_ticket_name` is a comma-separated ticker list ("HMKB, HMKBP"), but
    a few issuers filled it with junk — a literal '0', a '-', or their own company
    name — so only ticker-shaped entries are kept. Covers 273 symbols; issuers it
    misses fall back to ORG_ID_OVERRIDE or the name search.
    """
    global _org_map_cache
    if _org_map_cache is not None and not refresh:
        return _org_map_cache
    out = {}
    try:
        data = _getj(ORGANIZATIONS_URL, {"format": "json", "page_size": 800})
        for org in data.get("results", []):
            for raw in str(org.get("exchange_ticket_name") or "").split(","):
                t = raw.strip().upper()
                if _TICKER_RE.match(t) and org.get("id"):
                    out.setdefault(t, org["id"])
    except Exception:  # noqa: BLE001 — the search path still works without it
        log.exception("openinfo organization registry unavailable")
    _org_map_cache = out
    return out


def org_id_for(ticker):
    """The organization id to list reports under, or None to fall back to search."""
    t = str(ticker or "").strip().upper()
    if t in ORG_ID_OVERRIDE:
        return ORG_ID_OVERRIDE[t]
    registry = ticker_org_map()
    return registry.get(t) or registry.get(TICKER_ALIAS.get(t, "").upper())


def _candidate(pub_date, org_type, period_type, object_id, organization=None):
    return {
        "object_id": object_id,
        "org_type": org_type,
        "period_type": period_type,
        "pub_date": pub_date or "",
        "organization": organization,
    }


def list_candidates(search):
    """NSBU reports with an object_id and a quarter/annual form, newest pub first."""
    data = _getj(f"{API_BASE}/reports/main/", {"search": search, "page_size": 40})
    out = []
    for rec in data.get("results", []):
        props = rec.get("properties") or {}
        if (rec.get("report_type") == "NSBU"
                and rec.get("object_id")
                and props.get("report_type") in ("quarter", "annual")
                and props.get("org_type") in ORG_TYPES):
            out.append(_candidate(rec.get("pub_date"), props["org_type"],
                                  props["report_type"], rec["object_id"], rec.get("organization")))
    out.sort(key=lambda r: r["pub_date"], reverse=True)
    return out


def list_candidates_by_org(org_id):
    """Same list, bound to one issuer by id instead of by a name search.

    The unified feed carries no object_id of its own — the report's own id is the
    last segment of ``report_link`` (…/reports/jsc/annual/5985).
    """
    data = _getj(UNIFIED_REPORTS_URL, {"format": "json", "page_size": 40, "organization": org_id})
    out = []
    for rec in data.get("results", []):
        props = rec.get("properties") or {}
        if (rec.get("report_type") != "NSBU"
                or props.get("report_type") not in ("quarter", "annual")
                or props.get("org_type") not in ORG_TYPES):
            continue
        m = re.search(r"/reports/[a-z]+/[a-z]+/(\d+)/?$", str(rec.get("report_link") or ""))
        if not m:
            continue
        out.append(_candidate(rec.get("pub_date"), props["org_type"],
                              props["report_type"], int(m.group(1)), rec.get("organization_id")))
    out.sort(key=lambda r: r["pub_date"], reverse=True)
    return out


def fetch_detail(cand):
    return _getj(f"{API_BASE}/reports/{cand['org_type']}/{cand['period_type']}/{cand['object_id']}/")


def _ticket_match(detail, ticker):
    want = {ticker.upper()}
    alias = TICKER_ALIAS.get(ticker)
    if alias:
        want.add(alias.upper())
    tickets = {t.strip().upper() for t in (detail.get("organization_ticket_name") or "").split(",") if t.strip()}
    return bool(want & tickets)


def _has_data(metrics):
    """A report carries usable figures if any of the four headline metrics is set
    and non-zero (skips empty placeholder filings)."""
    return any(metrics.get(k) for k in ("revenue", "net_income", "total_liabilities", "cash"))


def _period_ceiling(cand, today):
    """The highest period rank a candidate published on this date could describe.

    Nothing about the report is known yet — only its filing date and its form —
    but a period cannot end after it was filed, so this bounds the candidate
    without spending a detail fetch. Candidates are walked newest-filed first, so
    the bound only falls as the walk goes on: once it drops to the best period
    already in hand, no older filing of that form can beat it and the rest are
    skipped unfetched.
    """
    bound = _bound_date(cand["pub_date"], today)
    if cand["period_type"] == "annual":
        return period_rank(_last_complete_fiscal_year(bound), 0)
    return period_rank(*_last_complete_quarter(bound))


def select_reports(ticker, today=None, max_fetch=8):
    """Pick this issuer's reports: the latest reporting PERIOD, and the last
    complete fiscal year.

    Returns ``(latest, annual)``, each ``{"metrics", "meta"}`` or None. `latest`
    is whichever filing covers the newest period — NOT the newest filing. The two
    orders come apart every summer: an issuer files Q1 in late April and the
    previous year's annual in July, and picking by publication served FY2025's
    revenue as the current quarter's. Publication date survives only as a
    tiebreaker: candidates are walked newest-filed first and a later filing of the
    SAME period (a restatement, an audited refiling) is therefore seen first and
    kept.

    `annual` is the companion 12-month figure. Once `latest` is a cumulative
    quarter, every ratio built on it (P/E above all) is on 3, 6 or 9 months of
    earnings; carrying the last complete year alongside is what keeps those
    comparable across issuers on different filing calendars.
    """
    today = today or _dt.date.today()
    relaxed = ticker in RELAXED_MATCH
    search = SEARCH_OVERRIDE.get(ticker, ticker)
    hint = ORG_HINT.get(ticker)

    # openinfo's own ticker registry binds the issuer exactly; the name search is
    # the fallback for the symbols it does not carry (bonds, alias tickers).
    org_id = org_id_for(ticker)
    cands, source = [], "search"
    if org_id:
        try:
            cands, source = list_candidates_by_org(org_id), f"org:{org_id}"
        except Exception:  # noqa: BLE001
            log.exception("openinfo org listing failed for %s (org %s)", ticker, org_id)
    if not cands:
        cands, source = list_candidates(search), "search"
    if not cands:
        return None, None, {"error": "no candidates", "search": search, "source": source}

    # An org-bound listing IS the issuer binding; the ticket string is only needed
    # to tell issuers apart when the candidates came from a name search.
    by_org = source.startswith("org:")
    best = best_annual = None
    fetched = 0
    for c in cands:
        annual = c["period_type"] == "annual"
        # An annual candidate is worth fetching while it can still improve the
        # companion, which is the weaker bar of the two (the companion never
        # outranks the latest period), so testing it alone covers both targets.
        floor = (best_annual if annual else best) or {}
        if _period_ceiling(c, today) <= floor.get("rank", -1):
            continue  # cannot improve either target — skip without fetching
        if fetched >= max_fetch:
            break
        try:
            d = fetch_detail(c)
        except Exception:  # noqa: BLE001
            continue
        fetched += 1
        if hint:
            names = _norm(d.get("organization_short_name")) + " " + _norm(d.get("organization_name"))
            if hint not in names:
                continue
        if not by_org and not relaxed and not _ticket_match(d, ticker):
            continue
        metrics = extract_metrics(d)
        if not _has_data(metrics):
            continue
        year, quarter = period_year_quarter(d.get("reporting_year"), c["period_type"],
                                            today=today, pub_date=c["pub_date"])
        if year is None:
            log.warning("%s: report %s has no readable period (%r) — skipped",
                        ticker, c["object_id"], d.get("reporting_year"))
            continue
        rank = period_rank(year, quarter)
        if rank > _period_ceiling(c, today):
            # Cannot happen once period_year_quarter has clamped, and is a data
            # error rather than a stale label if it ever does — never store it.
            log.warning("%s: report %s resolves to a future period %dQ%d — skipped",
                        ticker, c["object_id"], year, quarter)
            continue
        chosen = {
            "rank": rank,
            "metrics": metrics,
            "meta": {
                "object_id": c["object_id"],
                "org_type": c["org_type"],
                "period_type": c["period_type"],
                "reporting_year": d.get("reporting_year"),
                "pub_date": c["pub_date"],
                "tickets": d.get("organization_ticket_name"),
                "search": search,
                "source": source,
                "relaxed": relaxed and not by_org,
                "year": year,
                "quarter": quarter,
            },
        }
        if annual and rank > (best_annual or {}).get("rank", -1):
            best_annual = chosen
        if rank > (best or {}).get("rank", -1):
            best = chosen

    if best is None:
        return None, None, {"error": "no report with data", "search": search,
                            "source": source, "candidates": len(cands)}
    # Same report on both sides means the latest period IS the annual; one row.
    if best_annual is not None and best_annual["rank"] == best["rank"]:
        best_annual = None
    return best, best_annual, best["meta"]


def select_report(ticker, today=None, max_fetch=8):
    """(metrics, meta) for the latest reporting period — the single-row view of
    :func:`select_reports`, kept for callers that do not want the companion."""
    best, _annual, meta = select_reports(ticker, today=today, max_fetch=max_fetch)
    return (best["metrics"] if best else None), meta


METRIC_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",
               "net_income", "operating_income")

NSBU_THOUSANDS = 1000.0


_Q_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _quarter_of(d):
    return (d.month - 1) // 3 + 1


def _quarter_end(year, q):
    m, day = _Q_END[q]
    return _dt.date(year, m, day)


def _last_complete_quarter(asof):
    """The latest quarter whose end fell on or before `asof`."""
    y, q = asof.year, _quarter_of(asof)
    if _quarter_end(y, q) <= asof:
        return y, q
    q -= 1
    if q == 0:
        q, y = 4, y - 1
    return y, q


def _last_complete_fiscal_year(asof):
    """The latest fiscal year that had fully ended on `asof`.

    An annual report for FY Y covers 1 Jan - 31 Dec of Y and therefore cannot be
    filed before 31 Dec Y. That makes this the hard upper bound on the fiscal year
    any annual filed on `asof` can describe.
    """
    return asof.year if asof >= _dt.date(asof.year, 12, 31) else asof.year - 1


def _bound_date(pub_date, today):
    """The latest date a report's period may end on: its filing day, capped at today."""
    d = _parse_date(pub_date)
    return min(d, today) if d else today


def period_rank(year, quarter):
    """Ordering key over reporting periods — the site's ranking, in one place.

    ``year * 10 + (5 for an annual, else the quarter)``: the audited annual is the
    year's final word so it outranks that year's Q4, and any period of the next
    year outranks both. Identical to the SQL ranking in
    ``reports_catalog.get_all_financials``, so selection here and "latest period"
    there cannot disagree. Returns -1 for an underivable period.
    """
    if year is None:
        return -1
    return int(year) * 10 + (5 if not quarter else int(quarter))


def period_months(year, quarter):
    """How many months of activity a P&L figure for this period covers.

    NSBU quarterly forms are cumulative from 1 January — Q2 is six months, not
    three — so this is what makes one issuer's figure comparable to another's.
    Balance-sheet lines are point-in-time and need no such normalization.
    """
    if year is None:
        return None
    return 12 if not quarter else int(quarter) * 3


def period_end(year, quarter):
    """The date the period closes, or None when it is underivable."""
    if year is None:
        return None
    return _quarter_end(int(year), int(quarter) if quarter else 4)


def period_year_quarter(reporting_year, period_type, today=None, pub_date=None):
    """Map an openinfo reporting_year date + form type to the site's (year, quarter).

    Annual -> quarter 0. Quarterly -> the quarter whose end the period-end date
    falls in (Jan-Mar=1 ... Oct-Dec=4). Interim dates snap to the enclosing
    quarter. Returns (year, quarter) or (None, None).

    A period cannot end after the report carrying it was filed, and openinfo
    mis-stamps ``reporting_year`` in both directions of that rule:

      * interims stamped with their own filing day (reporting_year=2026-04-27 on a
        report filed 2026-05-13) — snapped back to the last quarter fully ended by
        the filing date, here Q1 2026;
      * annuals stamped with a current or future year-end (2026-12-31 on a report
        filed 2026-06-29) — clamped to the last fiscal year complete at filing,
        here FY2025. This is the "2026 Q4" that reached the site: the old code
        mapped such an annual to Q4 of the stamped year, which invented a period
        that has not happened and outranked every real filing forever.

    A stamp EARLIER than the bound is left alone — late filings are normal.
    """
    d = _parse_date(reporting_year)
    if d is None:
        return None, None
    today = today or _dt.date.today()
    bound = _bound_date(pub_date, today)
    if period_type == "annual":
        latest = _last_complete_fiscal_year(bound)
        year = min(d.year, latest)
        if year != d.year:
            log.info("openinfo annual mis-stamped %s (filed %s) — reading it as FY%d",
                     reporting_year, pub_date or "?", year)
        return (year, 0) if year >= 1990 else (None, None)
    year, q = d.year, _quarter_of(d)
    if _quarter_end(year, q) > bound:
        snapped = _last_complete_quarter(bound)
        log.info("openinfo interim mis-stamped %s (filed %s) — reading it as %dQ%d",
                 reporting_year, pub_date or "?", *snapped)
        return snapped
    return year, q


PRIOR_KEYS = ("revenue", "gross_profit", "net_income", "operating_income")


def _figures(ticker, metrics, meta):
    """One period's figures in both unit conventions, with its period label."""
    row = {"ticker": ticker, "year": meta["year"], "quarter": meta["quarter"],
           "period_months": period_months(meta["year"], meta["quarter"]),
           "is_ytd": bool(meta["quarter"])}
    for k in METRIC_KEYS:
        v = metrics.get(k)
        row[f"{k}_thousand"] = None if v is None else round(v, 2)
        row[f"{k}_full"] = None if v is None else round(v * NSBU_THOUSANDS, 2)
    # The comparative the SAME filing prints for the year before — the issuer's
    # own restated figure for that period, which is what a year-on-year change
    # should be struck against. It is labelled with its own period so nothing can
    # read it as belonging to this one.
    prior = metrics.get("prior")
    row["prior"] = None
    if prior:
        prior_year = meta["year"] - 1
        row["prior"] = {
            "year": prior_year, "quarter": meta["quarter"],
            "period_months": period_months(prior_year, meta["quarter"]),
            "is_ytd": bool(meta["quarter"]),
            **{f"{k}_thousand": (None if prior.get(k) is None else round(prior[k], 2))
               for k in PRIOR_KEYS},
            **{f"{k}_full": (None if prior.get(k) is None else round(prior[k] * NSBU_THOUSANDS, 2))
               for k in PRIOR_KEYS},
        }
    return row


def reconcile_ticker(ticker, today=None):
    """Return (row, meta) for a ticker.

    `row` carries both unit conventions so either sink can consume it directly:
      *_full     — full UZS (openinfo thousands x1000); matches the API read boundary
      *_thousand — openinfo thousands as stored in catalog_financials / admin push
    plus derived year/quarter for the period label, ``period_months`` (how many
    months of activity the P&L figures cover — NSBU quarters are cumulative) and
    ``annual``: the same shape for the last complete fiscal year, present only
    when the latest period is a part-year one. `row` is None on failure and
    `meta['error']` explains why (no source / manual skip / unresolved)."""
    if ticker in NO_SOURCE:
        return None, {"error": "no source (manual)"}
    if ticker in MANUAL_SKIP:
        return None, {"error": "manual skip (empty NSBU / IFRS-only)"}
    best, annual, meta = select_reports(ticker, today=today)
    if best is None:
        return None, meta
    row = _figures(ticker, best["metrics"], best["meta"])
    row["annual"] = _figures(ticker, annual["metrics"], annual["meta"]) if annual else None
    if annual:
        row["annual"]["_meta"] = {k: annual["meta"].get(k)
                                  for k in ("period_type", "reporting_year", "pub_date", "object_id")}
    return row, meta


def admin_push_row(row):
    """Shape a reconcile row for POST /api/admin/financials (stored in thousands)."""
    out = {"ticker": row["ticker"], "year": row["year"], "quarter": row["quarter"]}
    for k in METRIC_KEYS:
        out[k] = row.get(f"{k}_thousand")
    prior = row.get("prior")
    if prior:
        # Rides on the row it was filed with, labelled with its own period. It is
        # NOT pushed as a period of its own: the comparative column carries the
        # P&L only, and a half-empty period row would be picked up by anything
        # that ranks periods and divide a ratio by a balance sheet that is not
        # there.
        out["prior"] = {"year": prior["year"], "quarter": prior["quarter"],
                        **{k: prior.get(f"{k}_thousand") for k in PRIOR_KEYS}}
    return out


def admin_push_rows(row):
    """Every period this ticker should store: the latest, plus the last complete
    fiscal year when that is a different period.

    Both are pushed because the read path serves the latest period while ratios
    need a 12-month denominator — and because ``mode=replace`` clears the ticker
    first, so a period that is not in this list stops being served."""
    out = [admin_push_row(row)]
    if row.get("annual"):
        out.append(admin_push_row(row["annual"]))
    return out


def reconcile_all(tickers, today=None, progress=None):
    """Reconcile a list of tickers -> (rows, errors). `progress(i, n, ticker)` optional."""
    rows, errors = [], {}
    n = len(tickers)
    for i, t in enumerate(tickers):
        if progress:
            progress(i, n, t)
        try:
            row, meta = reconcile_ticker(t, today=today)
        except Exception as exc:  # noqa: BLE001
            errors[t] = f"exception: {exc}"
            continue
        if row is None:
            errors[t] = meta.get("error", "unresolved")
            continue
        row["_meta"] = {k: meta.get(k) for k in ("org_type", "period_type", "reporting_year", "pub_date", "object_id")}
        rows.append(row)
    return rows, errors


def _cli(argv):
    if not argv:
        print("usage: python openinfo_reconcile.py TICKER [TICKER...]   "
              "(prints reconciled figures; full UZS)")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for t in argv:
        t = t.strip().upper()
        row, meta = reconcile_ticker(t)
        if row is None:
            print(f"{t:<10} -> {meta.get('error')}")
            continue
        print(f"{t:<10} {meta.get('org_type'):<9} {meta.get('period_type'):<7} "
              f"reporting_year={meta.get('reporting_year')} (Y{row['year']}Q{row['quarter']}, "
              f"{row['period_months']}m) pub={str(meta.get('pub_date'))[:10]} via {meta.get('source')}")
        for k in ("revenue", "net_income", "total_liabilities", "cash"):
            v = row.get(f"{k}_full")
            print(f"    {k:<18} {v:,.0f}" if v is not None else f"    {k:<18} —")
        ann = row.get("annual")
        if ann:
            net = ann.get("net_income_full")
            print(f"    {'last full year':<18} FY{ann['year']} net={'—' if net is None else format(net, ',.0f')}")
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_cli(_sys.argv[1:]))
