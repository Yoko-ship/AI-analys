# coding: utf-8
"""Structured-JSON reconciliation of issuer financials against openinfo.uz.

Unlike the legacy Excel/PDF parser (openinfo_collector.py / reports_catalog.py),
this reads openinfo's clean structured report detail:

    list:   GET /api/v2/reports/main/?search={TICKER}&page_size=40
    detail: GET /api/v2/reports/{jsc|bank|insurance}/{quarter|annual}/{object_id}/

and applies the report-reading rules that the legacy path got wrong:

  * P&L (revenue, net profit): first NON-ZERO of (value, value1, value2), keep its
    stored sign. Never value1 - value2. Never index by array position.
  * Balance (liabilities, cash): value2 (end of period), fallback value1 / value.
  * All openinfo amounts are in thousands -> multiply by 1000 for the full sum.
  * Period = reporting_year (period-end date). quarter_no is a FORM code, not a
    quarter number, and is ignored. The chosen report is the newest *published*
    one (across quarter + annual) that carries real data; empty placeholders are
    skipped. Note: openinfo mis-stamps some genuine annuals with a current- or
    future-year period-end (e.g. 2026-12-31, or a today-dated interim), and those
    ARE the freshest real figures — so selection keys on publication + non-empty
    data, not on the calendar validity of reporting_year.
  * Bind the issuer via organization_ticket_name (comma-separated), not the search
    name, so ordinary / preferred siblings stay aligned.

Row map:
  bank      revenue = "Итого процентных доходов"; net = last "ЧИСТАЯ ПРИБЫЛЬ";
            liabilities = "Итого обязательств" (excl. "…и собственного капитала");
            cash = "Кассовая наличность…"; gross = None.
  jsc       revenue = tnum 010; net = "Чистая прибыль…отчетного периода" (tnum 270);
            gross = "Валовая прибыль" (030); operating = "…от основной деятельности".
  insurance revenue = tnum 010 ("Доходы от оказания страховых услуг"); net = tnum 320.
  jsc+ins   liabilities = "Долгосрочные обязательства, всего" + "Текущие
            обязательства, всего" (value2); cash = "Денежные средства, всего".

This module is a read/verify tool by default (compare against the reconciliation
registry) and can emit corrected rows for the existing push path.
"""
from __future__ import annotations

import datetime as _dt
import re

import openinfo_http as _http

API_BASE = "https://new-api.openinfo.uz/api/v2"

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

# Tickers with no openinfo source at all — never auto-reconciled (раздел 8).
NO_SOURCE = {
    "UTHK", "UVGT", "UZIN", "UZINP",
    "ACMT1B2", "ACMT1B3", "ACMT2B4", "ACMT2B5", "CTFB3", "CTFB3B2",
}

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
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "None"):
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


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
def pl_value(row):
    """P&L cell: first NON-ZERO of value/value1/value2, keeping the stored sign."""
    if row is None:
        return None
    for k in ("value", "value1", "value2"):
        if k in row:
            v = _num(row.get(k))
            if v is not None and v != 0:
                return v
    for k in ("value", "value1", "value2"):
        if k in row and _num(row.get(k)) is not None:
            return 0.0
    return None


def bal_value(row):
    """Balance cell: end of period = first NON-ZERO of value2, value1, value.

    value2 is normally the period-end column, but some quarter forms leave value2
    at 0 and carry the end figure in value1 (e.g. several banks' Q2 balance), so a
    zero value2 must fall back rather than being taken literally.
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
    }
    if org == "bank":
        out["revenue"] = pl_value(_by_title(pl, ["итого процентных доходов"]))
        out["net_income"] = pl_value(_by_title(pl, ["чистая прибыль"], last=True))
        out["total_liabilities"] = bal_value(_by_title(bal, ["итого обязательств"], exclude=["капитал"]))
        out["cash"] = bal_value(_by_title(bal, ["кассовая наличность"]))
    else:  # jsc / insurance
        rev_row = _by_tnum(pl, "010") or _by_title(pl, ["выручка"])
        out["revenue"] = pl_value(rev_row)
        out["net_income"] = pl_value(_by_title(pl, ["чистая прибыль", "отчетного периода"]))
        out["gross_profit"] = pl_value(_by_title(pl, ["валовая прибыль"]))
        out["operating_income"] = pl_value(_by_title(pl, ["прибыль", "от основной деятельности"]))
        lt = bal_value(_by_title(bal, ["долгосрочные обязательства", "всего"]))
        cur = bal_value(_by_title(bal, ["текущие обязательства", "всего"]))
        out["total_liabilities"] = None if lt is None and cur is None else (lt or 0.0) + (cur or 0.0)
        out["cash"] = bal_value(_by_title(bal, ["денежные средства", "всего"]))
    return out


# --------------------------------------------------------------------------- #
# report selection
# --------------------------------------------------------------------------- #
def list_candidates(search):
    """NSBU reports with an object_id and a quarter/annual form, newest pub first."""
    data = _getj(f"{API_BASE}/reports/main/", {"search": search, "page_size": 40})
    out = []
    for rec in data.get("results", []):
        props = rec.get("properties") or {}
        if (rec.get("report_type") == "NSBU"
                and rec.get("object_id")
                and props.get("report_type") in ("quarter", "annual")
                and props.get("org_type") in ("jsc", "bank", "insurance")):
            out.append({
                "object_id": rec["object_id"],
                "org_type": props["org_type"],
                "period_type": props["report_type"],
                "pub_date": rec.get("pub_date") or "",
                "organization": rec.get("organization"),
            })
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


def select_report(ticker, today=None, max_fetch=8):
    """Return (metrics, meta) for the newest *published* report bound to `ticker`
    that carries real data.

    Candidates are walked newest-published first (across quarter + annual). The
    first one that (a) resolves to this issuer and (b) is not an empty placeholder
    is chosen. Calendar validity of reporting_year is intentionally NOT a filter:
    openinfo publishes freshly-filed annuals stamped 2026-12-31 / interim quarters
    dated with the filing day, and those are the current figures the site should
    show. `today` is accepted for API stability but no longer gates selection.
    """
    relaxed = ticker in RELAXED_MATCH
    search = SEARCH_OVERRIDE.get(ticker, ticker)
    hint = ORG_HINT.get(ticker)

    cands = list_candidates(search)
    if not cands:
        return None, {"error": "no candidates", "search": search}

    fetched = 0
    for c in cands:
        if fetched >= max_fetch:
            break
        try:
            d = fetch_detail(c)
        except Exception:
            continue
        fetched += 1
        if hint:
            names = _norm(d.get("organization_short_name")) + " " + _norm(d.get("organization_name"))
            if hint not in names:
                continue
        if not relaxed and not _ticket_match(d, ticker):
            continue
        metrics = extract_metrics(d)
        if not _has_data(metrics):
            continue
        meta = {
            "object_id": c["object_id"],
            "org_type": c["org_type"],
            "period_type": c["period_type"],
            "reporting_year": d.get("reporting_year"),
            "pub_date": c["pub_date"],
            "tickets": d.get("organization_ticket_name"),
            "search": search,
            "relaxed": relaxed,
        }
        return metrics, meta

    return None, {"error": "no report with data", "search": search, "candidates": len(cands)}


METRIC_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",
               "net_income", "operating_income")

NSBU_THOUSANDS = 1000.0


def period_year_quarter(reporting_year, period_type):
    """Map an openinfo reporting_year date + form type to the site's (year, quarter).

    Annual -> quarter 0. Quarterly -> the quarter whose end the period-end date
    falls in (Jan-Mar=1 ... Oct-Dec=4). Interim dates snap to the enclosing
    quarter. Returns (year, quarter) or (None, None)."""
    d = _parse_date(reporting_year)
    if d is None:
        return None, None
    if period_type == "annual":
        return d.year, 0
    return d.year, (d.month - 1) // 3 + 1


def reconcile_ticker(ticker, today=None):
    """Return (row, meta) for a ticker.

    `row` carries both unit conventions so either sink can consume it directly:
      *_full     — full UZS (openinfo thousands x1000); matches the API read boundary
      *_thousand — openinfo thousands as stored in catalog_financials / admin push
    plus derived year/quarter for the period label. `row` is None on failure and
    `meta['error']` explains why (no source / manual skip / unresolved)."""
    if ticker in NO_SOURCE:
        return None, {"error": "no source (manual)"}
    if ticker in MANUAL_SKIP:
        return None, {"error": "manual skip (empty NSBU / IFRS-only)"}
    metrics, meta = select_report(ticker, today=today)
    if metrics is None:
        return None, meta
    year, quarter = period_year_quarter(meta.get("reporting_year"), meta.get("period_type"))
    row = {"ticker": ticker, "year": year, "quarter": quarter}
    for k in METRIC_KEYS:
        v = metrics.get(k)
        row[f"{k}_thousand"] = None if v is None else round(v, 2)
        row[f"{k}_full"] = None if v is None else round(v * NSBU_THOUSANDS, 2)
    return row, meta


def admin_push_row(row):
    """Shape a reconcile row for POST /api/admin/financials (stored in thousands)."""
    out = {"ticker": row["ticker"], "year": row["year"], "quarter": row["quarter"]}
    for k in METRIC_KEYS:
        out[k] = row.get(f"{k}_thousand")
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
    import json as _json
    if not argv:
        print("usage: python openinfo_reconcile.py TICKER [TICKER...]   "
              "(prints reconciled figures; full UZS)")
        return 1
    for t in argv:
        t = t.strip().upper()
        row, meta = reconcile_ticker(t)
        if row is None:
            print(f"{t:<10} -> {meta.get('error')}")
            continue
        print(f"{t:<10} {meta.get('org_type'):<9} {meta.get('period_type'):<7} "
              f"reporting_year={meta.get('reporting_year')} (Y{row['year']}Q{row['quarter']}) "
              f"pub={str(meta.get('pub_date'))[:10]}")
        for k in ("revenue", "net_income", "total_liabilities", "cash"):
            v = row.get(f"{k}_full")
            print(f"    {k:<18} {v:,.0f}" if v is not None else f"    {k:<18} —")
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_cli(_sys.argv[1:]))
