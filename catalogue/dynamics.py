"""Build comparable financial time series from stored statements."""
from __future__ import annotations
from typing import Any

import catalogue.parsing as catalogue_parsing
import catalogue.periods as catalogue_periods
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage


def build_dynamics_data(ticker: str, form: str = "NSBU") -> dict[str, Any]:
    conn = catalogue_storage.get_catalog_conn()
    annual_rows = conn.execute(
        """
        SELECT year, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'annual' AND year IS NOT NULL
          AND year <= ?
        ORDER BY year ASC
        """,
        (ticker, form, catalogue_periods._latest_complete_fiscal_year()),
    ).fetchall()
    conn.close()

    if not annual_rows:
        return {"ticker": ticker, "form": form, "years": [], "series": {}}

    session = catalogue_sources._make_session()
    years: list[int] = []
    series: dict[str, list[float | None]] = {
        "revenue": [],
        "net_income": [],
        "total_assets": [],
        "equity": [],
        "total_liabilities": [],
    }

    for row in annual_rows:
        yr = row["year"]
        years.append(yr)

        income_data: dict | None = None
        balance_data: dict | None = None

        if row["excel_url"]:
            doc = {"excel_url": row["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p = catalogue_sources.parse_excel_report_document(session, doc)
                if p.get("ok"):
                    income_data = p
            except Exception:
                pass

        if row["excel_url_form1"]:
            doc1 = {"excel_url": row["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p1 = catalogue_sources.parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    balance_data = p1
            except Exception:
                pass

        ratios = catalogue_parsing.compute_financial_ratios(income_data, balance_data)
        vals = ratios.get("source_values") or {}
        for key in series:
            series[key].append(vals.get(key))

    # --- Quarterly series (last 8 quarters) ----------------------------------
    conn2 = catalogue_storage.get_catalog_conn()
    quarter_rows = conn2.execute(
        """
        SELECT year, quarter, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'quarter'
          AND year IS NOT NULL AND quarter > 0
        ORDER BY year DESC, quarter DESC
        LIMIT 16
        """,
        (ticker, form),
    ).fetchall()
    conn2.close()

    quarterly: list[dict[str, Any]] = []
    metric_keys = ["revenue", "net_income", "total_assets", "equity", "total_liabilities"]
    for qrow in reversed(quarter_rows):
        yr, q = qrow["year"], qrow["quarter"]
        inc, bal = None, None
        if qrow["excel_url"]:
            doc = {"excel_url": qrow["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p = catalogue_sources.parse_excel_report_document(session, doc)
                if p.get("ok"):
                    inc = p
            except Exception:
                pass
        if qrow["excel_url_form1"]:
            doc1 = {"excel_url": qrow["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p1 = catalogue_sources.parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    bal = p1
            except Exception:
                pass
        vals_q = (catalogue_parsing.compute_financial_ratios(inc, bal).get("source_values") or {})
        entry: dict[str, Any] = {"label": f"Q{q} {yr}", "year": yr, "quarter": q}
        for k in metric_keys:
            entry[k] = vals_q.get(k)
        quarterly.append(entry)

    # --- De-cumulate flow metrics -------------------------------------------
    # NSBU quarterly form-2 figures are cumulative year-to-date (an H1 filing's
    # "revenue" is six months of revenue). Serving them per-quarter labeled
    # "Q2" overstated quarters and made seasonality structurally meaningless.
    # Derive true standalone quarters by differencing consecutive YTD values of
    # the same year; a quarter without its predecessor on file stays None (the
    # cumulative figure is still exposed as <metric>_ytd). Balance-sheet
    # metrics (assets/equity/liabilities) are point-in-time and stay as-is.
    flow_keys = ("revenue", "net_income")
    for e in quarterly:
        for k in flow_keys:
            e[f"{k}_ytd"] = e.get(k)
    ytd_by_period = {(e["year"], e["quarter"]): e for e in quarterly}
    for e in quarterly:
        for k in flow_keys:
            ytd = e.get(f"{k}_ytd")
            if not isinstance(ytd, (int, float)):
                e[k] = None
                continue
            if e["quarter"] <= 1:
                continue  # Q1 cumulative == standalone
            prev = ytd_by_period.get((e["year"], e["quarter"] - 1))
            prev_ytd = prev.get(f"{k}_ytd") if prev else None
            e[k] = round(ytd - prev_ytd, 2) if isinstance(prev_ytd, (int, float)) else None

    # --- Seasonality (ТЗ §3.5): average a headline metric by quarter across years.
    # Uses the de-cumulated standalone quarters computed above — averaging raw
    # YTD values would always rank Q3 "above" Q1 regardless of real seasonality.
    # Needs ≥3 years of history; otherwise flagged insufficient rather than shown.
    season_metric = "revenue"
    by_q: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    years_seen: set[int] = set()
    for e in quarterly:
        v = e.get(season_metric)
        q = e.get("quarter")
        if isinstance(v, (int, float)) and q in by_q:
            by_q[q].append(float(v))
            years_seen.add(e.get("year"))
    seasonality = {
        "metric": season_metric,
        "years_covered": len(years_seen),
        "insufficient": len(years_seen) < 3,
        "quarter_avg": {q: (round(sum(vals) / len(vals), 2) if vals else None) for q, vals in by_q.items()},
    }

    return {"ticker": ticker, "form": form, "years": years, "series": series,
            "quarterly": quarterly, "seasonality": seasonality}
