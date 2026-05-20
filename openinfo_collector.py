from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from io import BytesIO
from typing import Any
from urllib.parse import urlencode

import requests

try:
    from urllib3.exceptions import InsecureRequestWarning
except Exception:  # pragma: no cover
    InsecureRequestWarning = None


OPENINFO_API_BASE = "https://new-api.openinfo.uz/api/v2"
OPENINFO_WEB_BASE = "https://openinfo.uz"
REQUEST_TIMEOUT = int(os.getenv("OPENINFO_TIMEOUT", "30"))
VERIFY_SSL = os.getenv("OPENINFO_VERIFY_SSL", "0").strip().lower() not in {"0", "false", "no"}

if not VERIFY_SSL and InsecureRequestWarning is not None:
    requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    })
    session.verify = VERIFY_SSL
    return session


def _normalize_key(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _fix_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _fix_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_fix_mojibake(item) for item in value]
    if isinstance(value, str) and ("Ð" in value or "Ñ" in value):
        try:
            return value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
    return value


def _json_get(
    session: requests.Session,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    url = path if path.startswith("http") else f"{OPENINFO_API_BASE}{path}"
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return _fix_mojibake(response.json())


def _safe_float(value: Any) -> float | None:
    if value is None or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_company(query: str, session: requests.Session | None = None) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ValueError("company query cannot be empty")

    client = session or _make_session()
    items = _json_get(client, "/home/autofill/", {"name": query})
    if not isinstance(items, list) or not items:
        raise LookupError(f"OpenInfo company was not found for {query!r}")

    normalized_query = _normalize_key(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        name = str(item.get("full_name_text") or "")
        score = 0
        if normalized_query:
            normalized_name = _normalize_key(name)
            if normalized_query == normalized_name:
                score += 100
            elif normalized_query and normalized_query in normalized_name:
                score += 20
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = scored[0][1]
    return {
        "input": query,
        "org_id": str(best.get("id")),
        "company_name": best.get("full_name_text") or "",
        "logo": best.get("logo"),
        "source_url": f"{OPENINFO_API_BASE}/home/autofill/?{urlencode({'name': query})}",
    }


def fetch_stock_screener(
    query: str,
    session: requests.Session | None = None,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    client = session or _make_session()
    payload = _json_get(
        client,
        "/iuzse/stock-screener/",
        {"mkt_id": "STK", "page_size": page_size, "search": query},
    )
    return list(payload.get("results") or []) if isinstance(payload, dict) else []


def _pick_security(
    query: str,
    securities: list[dict[str, Any]],
    company_name: str | None = None,
) -> dict[str, Any] | None:
    if not securities:
        return None

    query_key = _normalize_key(query)
    company_key = _normalize_key(company_name)
    for security in securities:
        ticker_key = _normalize_key(security.get("ticker"))
        isin_key = _normalize_key(security.get("isin_code"))
        if query_key and query_key in {ticker_key, isin_key}:
            return security

    if company_key:
        for security in securities:
            issuer_key = _normalize_key(security.get("issuer_short_name"))
            if company_key and (company_key in issuer_key or issuer_key in company_key):
                return security

    return securities[0]


def fetch_price_history(
    isin_code: str,
    session: requests.Session | None = None,
    months: int = 6,
) -> dict[str, Any]:
    client = session or _make_session()
    end_date = date.today()
    start_date = end_date - timedelta(days=max(1, months) * 30)
    params = {
        "isu_cd": isin_code,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    payload = _json_get(client, "/iuzse/conclusions/", params)
    return {
        "source_url": f"{OPENINFO_API_BASE}/iuzse/conclusions/?{urlencode(params)}",
        "name": payload.get("name"),
        "ticker": payload.get("ticker"),
        "points": payload.get("results") or [],
    }


def _market_summary(
    security: dict[str, Any] | None,
    history_points: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(
        history_points,
        key=lambda item: str(item.get("date") or ""),
    )
    closes = [_safe_float(point.get("close")) for point in ordered]
    closes = [value for value in closes if value is not None and value > 0]
    trading_values = [_safe_float(point.get("trading_value")) for point in ordered]
    trading_values = [value for value in trading_values if value is not None]
    trading_volumes = [_safe_float(point.get("trading_volume")) for point in ordered]
    trading_volumes = [value for value in trading_volumes if value is not None]

    period_change_percent = None
    if len(closes) >= 2 and closes[0]:
        period_change_percent = round((closes[-1] - closes[0]) / closes[0] * 100, 2)

    return {
        "latest_price": _safe_float((security or {}).get("trade_price")) or (closes[-1] if closes else None),
        "latest_trade_datetime": (security or {}).get("trade_datetime"),
        "day_change": _safe_float((security or {}).get("change")),
        "day_change_percent": _safe_float((security or {}).get("change_percent")),
        "history_points": len(history_points),
        "history_start": ordered[0].get("date") if ordered else None,
        "history_end": ordered[-1].get("date") if ordered else None,
        "period_change_percent": period_change_percent,
        "total_trading_value": round(sum(trading_values), 2) if trading_values else None,
        "avg_daily_trading_value": round(sum(trading_values) / len(trading_values), 2) if trading_values else None,
        "total_trading_volume": round(sum(trading_volumes), 2) if trading_volumes else None,
    }


def fetch_dividends(
    query: str,
    session: requests.Session | None = None,
    page_size: int = 20,
) -> dict[str, Any]:
    client = session or _make_session()
    params = {
        "stock_type": "simple",
        "page": 1,
        "page_size": page_size,
        "search": query,
        "ordering": "",
    }
    payload = _json_get(client, "/disclosure/dividend-calendar/", params)
    return {
        "source_url": f"{OPENINFO_API_BASE}/disclosure/dividend-calendar/?{urlencode(params)}",
        "count": payload.get("count", 0) if isinstance(payload, dict) else 0,
        "items": payload.get("results", []) if isinstance(payload, dict) else [],
    }


def _build_report_document(report: dict[str, Any]) -> dict[str, Any]:
    properties = report.get("properties") or {}
    report_form = report.get("report_type")
    report_period_type = properties.get("report_type")
    org_type = properties.get("org_type")
    object_id = report.get("object_id")
    report_id = report.get("id")

    pdf_url = report.get("pdf_url")
    excel_url = report.get("excel_url")

    if report_form == "NSBU":
        if report_id:
            pdf_url = f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{report_id}/"
        if object_id and report_period_type and org_type:
            excel_url = (
                f"{OPENINFO_API_BASE}/reports/export-excel/?"
                f"{urlencode({'report_type': report_period_type, 'org_type': org_type, 'report_id': object_id, 'lang': 'ru'})}"
            )

    return {
        "id": report_id,
        "object_id": object_id,
        "organization_id": report.get("organization"),
        "organization_name": report.get("organization_name"),
        "published_at": report.get("pub_date"),
        "status": report.get("status"),
        "views": report.get("watched"),
        "report_form": report_form,
        "period_type": report_period_type,
        "title": properties.get("report_title"),
        "pdf_url": pdf_url,
        "excel_url": excel_url,
    }


def _probe_document(session: requests.Session, url: str) -> dict[str, Any]:
    try:
        response = session.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        if response.status_code >= 400:
            response = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        content_length = response.headers.get("content-length")
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "content_length": int(content_length) if content_length and content_length.isdigit() else None,
        }
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


def fetch_report_documents(
    query: str,
    org_id: str | None = None,
    session: requests.Session | None = None,
    page_size: int = 100,
    validate_documents: bool = False,
) -> dict[str, Any]:
    client = session or _make_session()
    params = {"page": 1, "page_size": page_size, "search": query}
    payload = _json_get(client, "/reports/main/", params)
    results = list(payload.get("results") or []) if isinstance(payload, dict) else []
    if org_id:
        filtered = [item for item in results if str(item.get("organization")) == str(org_id)]
        if filtered:
            results = filtered

    documents = [_build_report_document(report) for report in results]
    if validate_documents:
        for document in documents:
            for field in ("pdf_url", "excel_url"):
                url = document.get(field)
                if url:
                    document[f"{field}_status"] = _probe_document(client, url)

    return {
        "source_url": f"{OPENINFO_API_BASE}/reports/main/?{urlencode(params)}",
        "count": len(documents),
        "items": documents,
    }


def fetch_accounting_bundle(
    org_id: str,
    session: requests.Session | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    client = session or _make_session()
    base = f"/reports/accounting-report/{org_id}/"
    urls = {
        "income_annual": (base, {"accounting_type": "form2", "report_type": "annual"}),
        "balance_annual": (base, {"accounting_type": "form1", "report_type": "annual"}),
        "income_quarter": (base, {"accounting_type": "form2", "report_type": "quarter"}),
        "balance_quarter": (base, {"accounting_type": "form1", "report_type": "quarter"}),
        "financial_indicators": ("/reports/financial_indicators/", {"organization_id": org_id}),
    }
    bundle = {name: _json_get(client, path, params) for name, (path, params) in urls.items()}
    financial_indicators = bundle.get("financial_indicators") or {}
    summary = {
        "income_annual_reports": len(bundle.get("income_annual") or []),
        "balance_annual_reports": len(bundle.get("balance_annual") or []),
        "income_quarter_reports": len(bundle.get("income_quarter") or []),
        "balance_quarter_reports": len(bundle.get("balance_quarter") or []),
        "financial_indicator_years": len(financial_indicators.get("results") or []) if isinstance(financial_indicators, dict) else 0,
    }
    result = {"summary": summary}
    if include_raw:
        result["raw"] = bundle
    return result


def preview_excel_url(session: requests.Session, url: str, max_rows: int = 5) -> dict[str, Any]:
    import pandas as pd

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    workbook = pd.ExcelFile(BytesIO(response.content))
    sheets = []
    for sheet_name in workbook.sheet_names[:5]:
        frame = workbook.parse(sheet_name, nrows=max_rows)
        sheets.append({
            "sheet": sheet_name,
            "columns": [str(column) for column in frame.columns],
            "rows": frame.fillna("").astype(str).to_dict("records"),
        })
    return {"content_type": response.headers.get("content-type"), "sheets": sheets}


def preview_pdf_url(session: requests.Session, url: str, max_pages: int = 2, max_chars: int = 3000) -> dict[str, Any]:
    import pdfplumber

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    chunks: list[str] = []
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        for page in pdf.pages[:max_pages]:
            chunks.append(page.extract_text() or "")
    return {
        "content_type": response.headers.get("content-type"),
        "pages_read": min(len(chunks), max_pages),
        "text": "\n".join(chunks).strip()[:max_chars],
    }


def collect_company_data(
    query: str,
    history_months: int = 6,
    include_raw_reports: bool = False,
    include_document_previews: bool = False,
    validate_documents: bool = False,
) -> dict[str, Any]:
    session = _make_session()
    company = resolve_company(query, session=session)
    org_id = company.get("org_id")
    company_name = company.get("company_name") or query

    securities = fetch_stock_screener(query, session=session)
    if not securities and company_name != query:
        securities = fetch_stock_screener(company_name, session=session)

    security = _pick_security(query, securities, company_name=company_name)
    price_history: dict[str, Any] | None = None
    if security and security.get("isin_code"):
        price_history = fetch_price_history(security["isin_code"], session=session, months=history_months)

    dividends = fetch_dividends(query, session=session)
    if dividends["count"] == 0 and company_name != query:
        dividends = fetch_dividends(company_name, session=session)

    reports = fetch_report_documents(
        query,
        org_id=org_id,
        session=session,
        validate_documents=validate_documents,
    )
    if reports["count"] == 0 and company_name != query:
        reports = fetch_report_documents(
            company_name,
            org_id=org_id,
            session=session,
            validate_documents=validate_documents,
        )

    if include_document_previews:
        for document in reports["items"][:8]:
            try:
                if document.get("excel_url") and document.get("period_type") == "annual":
                    document["excel_preview"] = preview_excel_url(session, document["excel_url"])
                    break
            except Exception as exc:
                document["excel_preview_error"] = str(exc)
        for document in reports["items"][:8]:
            try:
                if document.get("pdf_url") and document.get("report_form") in {"MSFO", "Audition"}:
                    document["pdf_preview"] = preview_pdf_url(session, document["pdf_url"])
                    break
            except Exception as exc:
                document["pdf_preview_error"] = str(exc)

    accounting = fetch_accounting_bundle(
        org_id,
        session=session,
        include_raw=include_raw_reports,
    )

    return {
        "ok": True,
        "company": company,
        "security": security,
        "available_securities": securities,
        "market": {
            "summary": _market_summary(security, (price_history or {}).get("points") or []),
            "price_history": price_history,
        },
        "dividends": dividends,
        "reports": reports,
        "accounting": accounting,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect OpenInfo market and report data for one issuer.")
    parser.add_argument("company", nargs="?", default="QATT")
    parser.add_argument("--history-months", type=int, default=6)
    parser.add_argument("--raw-reports", action="store_true")
    parser.add_argument("--validate-documents", action="store_true")
    parser.add_argument("--preview-documents", action="store_true")
    args = parser.parse_args()

    payload = collect_company_data(
        args.company,
        history_months=args.history_months,
        include_raw_reports=args.raw_reports,
        include_document_previews=args.preview_documents,
        validate_documents=args.validate_documents,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
