from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests



from openinfo_http import (  # shared paced/retrying HTTP layer for all openinfo traffic
    OPENINFO_PROXY,
    VERIFY_SSL,
    make_session as _make_paced_session,
)

OPENINFO_API_BASE = "https://new-api.openinfo.uz/api/v2"
OPENINFO_WEB_BASE = "https://openinfo.uz"
REQUEST_TIMEOUT = int(os.getenv("OPENINFO_TIMEOUT", "30"))
EXCEL_PARSE_ENABLED = os.getenv("OPENINFO_EXCEL_PARSE_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
EXCEL_MAX_BYTES = int(os.getenv("OPENINFO_EXCEL_MAX_BYTES", "3000000"))
EXCEL_MAX_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_REPORTS", "3"))
EXCEL_MAX_ANNUAL_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_ANNUAL_REPORTS", "1"))
EXCEL_MAX_QUARTER_REPORTS = int(os.getenv("OPENINFO_EXCEL_MAX_QUARTER_REPORTS", "2"))
EXCEL_ABSOLUTE_MAX_REPORTS = int(os.getenv("OPENINFO_EXCEL_ABSOLUTE_MAX_REPORTS", "100"))
EXCEL_MAX_TABLE_ROWS_PER_SHEET = int(os.getenv("OPENINFO_EXCEL_MAX_TABLE_ROWS_PER_SHEET", "240"))
EXCEL_CACHE_TTL_SECONDS = int(os.getenv("OPENINFO_EXCEL_CACHE_TTL_DAYS", "30")) * 24 * 60 * 60
EXCEL_CACHE_PATH = Path(os.getenv("OPENINFO_EXCEL_CACHE_PATH", "data/openinfo_excel_cache.json")).expanduser()
EXCEL_PARSER_VERSION = "openinfo-excel-full-rows-v3"
_EXCEL_CACHE_LOCK = threading.Lock()

def _make_session() -> requests.Session:
    return _make_paced_session()


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


def _safe_report_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if abs(parsed) < 1e30 else None

    text = str(value).strip()
    if not text or text in {"-", "—", "–"}:
        return None
    text = text.replace("\xa0", " ").replace(" ", "")
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace("%", "").replace(",", ".")
    if text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if is_negative else parsed


def _compact_cell(value: Any) -> Any:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    parsed = _safe_report_number(value)
    if parsed is not None:
        return round(parsed, 4)
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)[:180]


def _excel_cache_file() -> Path:
    path = EXCEL_CACHE_PATH
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_excel_cache() -> dict[str, Any]:
    path = _excel_cache_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_excel_cache(cache: dict[str, Any]) -> None:
    path = _excel_cache_file()
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _get_excel_cache(url: str) -> dict[str, Any] | None:
    if not url or EXCEL_CACHE_TTL_SECONDS <= 0:
        return None
    with _EXCEL_CACHE_LOCK:
        cache = _load_excel_cache()
        item = cache.get(url)
    if not item:
        return None
    if time.time() - float(item.get("cached_at") or 0) > EXCEL_CACHE_TTL_SECONDS:
        return None
    payload = item.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["from_cache"] = True
        return payload
    return None


def _set_excel_cache(url: str, payload: dict[str, Any]) -> None:
    if not url or EXCEL_CACHE_TTL_SECONDS <= 0:
        return
    cached_payload = dict(payload)
    cached_payload["from_cache"] = False
    with _EXCEL_CACHE_LOCK:
        cache = _load_excel_cache()
        cache[url] = {"cached_at": time.time(), "payload": cached_payload}
        # Keep the cache small; parsed snapshots are enough for analysis.
        if len(cache) > 500:
            cache = dict(sorted(cache.items(), key=lambda pair: pair[1].get("cached_at", 0))[-500:])
        _save_excel_cache(cache)


def resolve_company(query: str, session: requests.Session | None = None) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ValueError("company query cannot be empty")

    client = session or _make_session()

    # Strategy 1: direct autofill (fast, returns logo).
    try:
        items = _json_get(client, "/home/autofill/", {"name": query})
    except requests.RequestException:
        items = []

    if isinstance(items, list) and items:
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

    # Strategy 2: shared fuzzy/transliteration/full-list lookup from main.py.
    # autofill misses Cyrillic queries, capitalization variants, missing dashes/apostrophes, etc.
    from main import _lookup_org_id_via_api

    fallback = _lookup_org_id_via_api(query)
    if fallback:
        org_id, company_name = fallback
        # Best-effort logo lookup using the canonical company name.
        logo = None
        try:
            logo_items = _json_get(client, "/home/autofill/", {"name": company_name})
            if isinstance(logo_items, list):
                for item in logo_items:
                    if str(item.get("id")) == str(org_id):
                        logo = item.get("logo")
                        break
        except requests.RequestException:
            pass
        return {
            "input": query,
            "org_id": str(org_id),
            "company_name": company_name,
            "logo": logo,
            "source_url": f"{OPENINFO_API_BASE}/home/autofill/?{urlencode({'name': query})}",
        }

    raise LookupError(f"OpenInfo company was not found for {query!r}")


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


def fetch_available_periods(
    org_id: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Return which annual years and quarterly periods actually exist for this org on openinfo.

    Each top-level record from the accounting-report endpoint has:
      - reporting_year: int  (e.g. 2026)
      - period: str          (e.g. "Q1 2026" for quarterly, or "2024" for annual)

    Q4 is never published as a quarterly report — year-end is the annual report only.
    IFRS/MSFO reports are annual-only PDF documents (no quarterly IFRS exists).
    """
    client = session or _make_session()
    base = f"/reports/accounting-report/{org_id}/"

    try:
        annual_records = _json_get(client, base, {"accounting_type": "form2", "report_type": "annual"})
    except Exception:
        annual_records = []
    try:
        quarter_records = _json_get(client, base, {"accounting_type": "form2", "report_type": "quarter"})
    except Exception:
        quarter_records = []

    if not isinstance(annual_records, list):
        annual_records = []
    if not isinstance(quarter_records, list):
        quarter_records = []

    # Extract annual years from reporting_year field
    annual_years: list[int] = []
    seen_annual: set[int] = set()
    for r in annual_records:
        yr = r.get("reporting_year")
        if isinstance(yr, int) and yr >= 2000 and yr not in seen_annual:
            seen_annual.add(yr)
            annual_years.append(yr)
    annual_years.sort(reverse=True)

    # Parse quarterly periods from "period" string: "Q1 2026" → {year:2026, quarter:1}
    quarterly: list[dict[str, int]] = []
    seen_q: set[tuple[int, int]] = set()
    for r in quarter_records:
        period_str = str(r.get("period") or "")
        parts = period_str.split()
        if len(parts) == 2 and parts[0].startswith("Q"):
            try:
                q = int(parts[0][1:])
                y = int(parts[1])
                if 1 <= q <= 3 and y >= 2000 and (y, q) not in seen_q:
                    seen_q.add((y, q))
                    quarterly.append({"year": y, "quarter": q})
            except ValueError:
                continue
    quarterly.sort(key=lambda x: (x["year"], x["quarter"]), reverse=True)

    return {
        "annual_years": annual_years,
        "quarterly": quarterly,
        "latest_annual_year": annual_years[0] if annual_years else None,
        "latest_quarterly": quarterly[0] if quarterly else None,
    }


def get_company_periods(query: str) -> dict[str, Any]:
    """Resolve a company by name/ticker and return its available reporting periods."""
    session = _make_session()
    company = resolve_company(query, session=session)
    org_id = company.get("org_id")
    if not org_id:
        raise LookupError(f"No org_id found for {query!r}")
    periods = fetch_available_periods(org_id, session=session)
    return {"ok": True, "company": company, "periods": periods}


EXCEL_FINANCIAL_KEYWORDS = (
    "выруч", "реализац", "себесто", "валов", "прибыл", "убыт", "доход", "расход",
    "актив", "капитал", "обязательств", "долг", "заем", "денеж", "дебитор", "кредитор",
    "запас", "налог", "процент", "амортиза", "дивиденд", "revenue", "sales", "profit",
    "loss", "income", "expense", "asset", "liabil", "equity", "cash", "debt", "tax",
    "daromad", "foyda", "xarajat", "aktiv", "kapital", "majburiyat", "qarz", "pul",
)


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


def _row_matches_financial_context(values: list[Any]) -> bool:
    text = " ".join(str(value).lower() for value in values if value not in (None, ""))
    if any(keyword in text for keyword in EXCEL_FINANCIAL_KEYWORDS):
        return True
    numeric_count = sum(1 for value in values if _safe_report_number(value) is not None)
    string_count = sum(1 for value in values if isinstance(value, str) and value.strip())
    return numeric_count >= 2 and string_count >= 1


def _excel_row_label(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values[:6]:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if _safe_report_number(text) is not None:
            continue
        parts.append(text)
    if parts:
        return " | ".join(parts)[:260]
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:260]
    return str(values[0])[:260] if values else ""


def _classify_excel_row(label: str, sheet_name: str) -> str:
    text = f"{sheet_name} {label}".lower()
    if any(token in text for token in ("финансов", "прибыл", "убыт", "доход", "расход", "income", "profit", "loss")):
        return "income_statement"
    if any(token in text for token in ("пассив", "обязатель", "капитал", "депозит", "устав", "equity", "liabil")):
        return "liabilities_equity"
    if any(token in text for token in ("актив", "касс", "цбру", "к получению", "инвести", "кредит", "лизинг", "asset")):
        return "assets"
    return "financial_row"


def _parse_excel_workbook(
    content: bytes,
    *,
    max_sheets: int = 12,
    max_rows_per_sheet: int = 360,
    max_matched_rows_per_sheet: int = 24,
) -> dict[str, Any]:
    import pandas as pd

    workbook = pd.ExcelFile(BytesIO(content))
    sheets: list[dict[str, Any]] = []
    facts_count = 0
    warnings: list[str] = []

    for sheet_name in workbook.sheet_names[:max_sheets]:
        try:
            frame = workbook.parse(sheet_name, header=None, nrows=max_rows_per_sheet)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{sheet_name}: {exc}")
            continue

        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        matched_rows: list[dict[str, Any]] = []
        table_rows: list[dict[str, Any]] = []
        max_table_rows = max(0, min(EXCEL_MAX_TABLE_ROWS_PER_SHEET, max_rows_per_sheet))

        for index, row in frame.iterrows():
            raw_values = [_compact_cell(value) for value in row.tolist()]
            values = [value for value in raw_values if value not in ("", None)]
            if not values:
                continue

            label = _excel_row_label(values)
            numeric_cells = []
            for col_index, value in enumerate(values[:18]):
                number = _safe_report_number(value)
                if number is not None:
                    numeric_cells.append({"index": col_index, "value": round(number, 4)})
            numeric_values = [cell["value"] for cell in numeric_cells][:14]

            if label and numeric_cells and len(table_rows) < max_table_rows:
                table_rows.append({
                    "row": int(index) + 1,
                    "label": label,
                    "values": values[:18],
                    "numeric_values": numeric_values,
                    "numeric_cells": numeric_cells[:14],
                    "kind": _classify_excel_row(label, str(sheet_name)),
                })

            if _row_matches_financial_context(values) and len(matched_rows) < max_matched_rows_per_sheet:
                matched_rows.append({
                    "row": int(index) + 1,
                    "label": label,
                    "values": values[:12],
                    "numeric_values": numeric_values,
                })
                facts_count += 1

        if matched_rows or table_rows:
            sheets.append({
                "sheet": str(sheet_name),
                "rows_scanned": int(len(frame)),
                "matched_rows": matched_rows,
                "table_rows": table_rows,
            })

    return {
        "parser_version": EXCEL_PARSER_VERSION,
        "sheet_count": len(workbook.sheet_names),
        "sheets_read": len(sheets),
        "facts_count": facts_count,
        "sheets": sheets,
        "warnings": warnings[:5],
    }


def parse_excel_report_document(
    session: requests.Session,
    document: dict[str, Any],
) -> dict[str, Any]:
    url = document.get("excel_url")
    if not url:
        return {"ok": False, "error": "excel_url is missing"}

    cached = _get_excel_cache(url)
    if cached and cached.get("parser_version") == EXCEL_PARSER_VERSION:
        return cached

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content_length = response.headers.get("content-length")
    size = int(content_length) if content_length and content_length.isdigit() else len(response.content)
    if size > EXCEL_MAX_BYTES:
        return {
            "ok": False,
            "error": f"Excel file is too large: {size} bytes",
            "content_length": size,
            "max_bytes": EXCEL_MAX_BYTES,
        }

    parsed = _parse_excel_workbook(response.content)
    payload = {
        "ok": True,
        "source": "openinfo_excel",
        "parser_version": EXCEL_PARSER_VERSION,
        "from_cache": False,
        "report_id": document.get("id"),
        "object_id": document.get("object_id"),
        "published_at": document.get("published_at"),
        "period_type": document.get("period_type"),
        "report_form": document.get("report_form"),
        "title": document.get("title"),
        "content_type": response.headers.get("content-type"),
        "content_length": size,
        **parsed,
    }
    _set_excel_cache(url, payload)
    return payload


def _bounded_report_limit(value: int | None, default: int) -> int:
    raw = default if value is None else value
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(EXCEL_ABSOLUTE_MAX_REPORTS, parsed))


def _select_excel_documents(
    documents: list[dict[str, Any]],
    *,
    include_all: bool = False,
    max_reports: int | None = None,
    max_annual_reports: int | None = None,
    max_quarter_reports: int | None = None,
) -> list[dict[str, Any]]:
    excel_documents = [document for document in documents if document.get("excel_url")]
    if include_all:
        return excel_documents[:_bounded_report_limit(max_reports, EXCEL_ABSOLUTE_MAX_REPORTS)]

    annual: list[dict[str, Any]] = []
    quarter: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for document in excel_documents:
        period_type = str(document.get("period_type") or "").lower()
        if period_type == "annual":
            annual.append(document)
        elif period_type == "quarter":
            quarter.append(document)
        else:
            other.append(document)

    report_limit = _bounded_report_limit(max_reports, EXCEL_MAX_REPORTS)
    if max_annual_reports is None and max_quarter_reports is None:
        return excel_documents[:report_limit]

    annual_limit = _bounded_report_limit(max_annual_reports, EXCEL_MAX_ANNUAL_REPORTS)
    quarter_limit = _bounded_report_limit(max_quarter_reports, EXCEL_MAX_QUARTER_REPORTS)
    selected = quarter[:quarter_limit]
    selected.extend(annual[:annual_limit])
    selected.extend(other)
    return selected[:report_limit]


def fetch_excel_report_snapshots(
    reports: dict[str, Any],
    session: requests.Session,
    *,
    include_all: bool = False,
    max_reports: int | None = None,
    max_annual_reports: int | None = None,
    max_quarter_reports: int | None = None,
) -> dict[str, Any]:
    if not EXCEL_PARSE_ENABLED:
        return {"enabled": False, "count": 0, "items": [], "errors": []}

    documents = list((reports or {}).get("items") or [])
    selected = _select_excel_documents(
        documents,
        include_all=include_all,
        max_reports=max_reports,
        max_annual_reports=max_annual_reports,
        max_quarter_reports=max_quarter_reports,
    )
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for document in selected:
        try:
            snapshot = parse_excel_report_document(session, document)
            if snapshot.get("ok"):
                items.append(snapshot)
            else:
                errors.append({
                    "report_id": document.get("id"),
                    "object_id": document.get("object_id"),
                    "error": snapshot.get("error"),
                })
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "report_id": document.get("id"),
                "object_id": document.get("object_id"),
                "error": str(exc),
            })

    return {
        "enabled": True,
        "count": len(items),
        "selected_count": len(selected),
        "items": items,
        "errors": errors[:10],
        "limits": {
            "include_all": include_all,
            "max_reports": _bounded_report_limit(
                max_reports,
                EXCEL_ABSOLUTE_MAX_REPORTS if include_all else EXCEL_MAX_REPORTS,
            ),
            "max_annual_reports": None if include_all else _bounded_report_limit(max_annual_reports, EXCEL_MAX_ANNUAL_REPORTS),
            "max_quarter_reports": None if include_all else _bounded_report_limit(max_quarter_reports, EXCEL_MAX_QUARTER_REPORTS),
            "absolute_max_reports": EXCEL_ABSOLUTE_MAX_REPORTS,
            "max_bytes": EXCEL_MAX_BYTES,
            "cache_ttl_days": round(EXCEL_CACHE_TTL_SECONDS / 86400, 2),
        },
    }


def parse_nsbu_pdf_financials(session: requests.Session, pdf_url: str) -> dict[str, Any]:
    """Extract headline financials from an NSBU report PDF.

    Fallback for issuers (microfinance MCHJ, some LLCs) whose Excel export is
    broken on openinfo but whose PDF carries the standard NSBU tables. Matches by
    the stable NSBU line codes first, then by Russian label, and rejects values
    below the plausibility floor (line codes like 180/280 misread as amounts).
    """
    import pdfplumber

    response = session.get(pdf_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [str(c).replace("\n", " ").strip() if c else "" for c in raw]
                    label = next((c for c in cells if re.search(r"[А-Яа-я]{4}", c)), "")
                    if not label:
                        continue
                    code = next((c for c in cells if re.fullmatch(r"\d{2,4}", c.strip())), None)
                    nums = [_safe_report_number(c) for c in cells]
                    nums = [n for n in nums if n is not None and abs(n) >= 10_000]
                    rows.append({"label": label.lower(), "code": code, "value": nums[-1] if nums else None})

    def by_code(code: str) -> float | None:
        for r in rows:
            if r["code"] == code and r["value"] is not None:
                return r["value"]
        return None

    def by_label(patterns: tuple[str, ...], exclude: tuple[str, ...] = ()) -> float | None:
        hit = None
        for r in rows:  # last match wins (final totals come after subtotals)
            if r["value"] is None:
                continue
            if any(p in r["label"] for p in patterns) and not any(e in r["label"] for e in exclude):
                hit = r["value"]
        return hit

    return {
        "net_income": by_code("1200") or by_label(("чистая прибыль (убыток)", "чистая прибыль(убыток)"))
        or by_label(("чистая прибыль", "чистый убыток"), exclude=("до ", "процент", "операц")),
        "total_liabilities": by_code("280") or by_label(("итого обязательства",), exclude=("капитал",)),
        "revenue": by_code("180") or by_label(("всего процентных доходов",))
        or by_label(("чистая выручка", "выручка от реализац")),
        "cash": by_code("010") or by_label(("денежные средства",)),
    }


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


def _probe_screener_availability(session: requests.Session) -> dict[str, Any]:
    """Check whether the OpenInfo stock screener has any data at all.

    Distinguishes "company is not listed" from "upstream screener is currently empty".
    """
    try:
        payload = _json_get(session, "/iuzse/stock-screener/", {"mkt_id": "STK", "page_size": 1})
        total = int(payload.get("count") or 0) if isinstance(payload, dict) else 0
        return {
            "ok": total > 0,
            "screener_total_securities": total,
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"screener probe failed: {exc}",
            "screener_total_securities": 0,
        }


def collect_company_data(
    query: str,
    history_months: int = 6,
    include_raw_reports: bool = False,
    include_document_previews: bool = False,
    include_excel_reports: bool = False,
    include_all_excel_reports: bool = False,
    excel_report_limit: int | None = None,
    excel_annual_report_limit: int | None = None,
    excel_quarter_report_limit: int | None = None,
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
    price_history_error: str | None = None
    if security and security.get("isin_code"):
        try:
            price_history = fetch_price_history(security["isin_code"], session=session, months=history_months)
        except requests.RequestException as exc:
            price_history_error = str(exc)

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
    excel_reports = (
        fetch_excel_report_snapshots(
            reports,
            session=session,
            include_all=include_all_excel_reports,
            max_reports=excel_report_limit,
            max_annual_reports=excel_annual_report_limit,
            max_quarter_reports=excel_quarter_report_limit,
        )
        if include_excel_reports
        else {"enabled": False, "count": 0, "items": [], "errors": []}
    )

    market_availability: dict[str, Any] = {
        "screener_match_count": len(securities),
        "selected_security_present": security is not None,
        "price_history_available": bool(price_history and (price_history.get("points") or [])),
    }
    if price_history_error:
        market_availability["price_history_error"] = price_history_error

    if not securities:
        probe = _probe_screener_availability(session)
        if probe.get("screener_total_securities", 0) == 0:
            market_availability.update({
                "available": False,
                "reason": "openinfo_stock_screener_empty",
                "note": (
                    "Источник https://new-api.openinfo.uz/api/v2/iuzse/stock-screener/ "
                    "сейчас возвращает 0 ценных бумаг для любых запросов "
                    "(подтверждено пробой без поиска). Биржевые данные временно недоступны на стороне openinfo.uz."
                ),
                "screener_total_securities": probe.get("screener_total_securities", 0),
            })
        else:
            market_availability.update({
                "available": False,
                "reason": "company_not_in_screener",
                "note": (
                    f"В скринере openinfo.uz найдено {probe.get('screener_total_securities')} бумаг, "
                    f"но ни одна не соответствует запросу. Скорее всего эмитент не торгуется на iUzse."
                ),
                "screener_total_securities": probe.get("screener_total_securities", 0),
            })
    else:
        market_availability["available"] = True
        if security and security.get("isin_code") and not market_availability["price_history_available"]:
            market_availability.setdefault(
                "note",
                "Эндпоинт /iuzse/conclusions/ не вернул историю котировок по ISIN. "
                "Цены и объёмы торгов в текущем наборе недоступны.",
            )

    return {
        "ok": True,
        "company": company,
        "security": security,
        "available_securities": securities,
        "market": {
            "summary": _market_summary(security, (price_history or {}).get("points") or []),
            "price_history": price_history,
            "availability": market_availability,
        },
        "dividends": dividends,
        "reports": reports,
        "excel_reports": excel_reports,
        "accounting": accounting,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect OpenInfo market and report data for one issuer.")
    parser.add_argument("company", nargs="?", default="QATT")
    parser.add_argument("--history-months", type=int, default=6)
    parser.add_argument("--raw-reports", action="store_true")
    parser.add_argument("--excel-reports", action="store_true")
    parser.add_argument("--all-excel-reports", action="store_true")
    parser.add_argument("--excel-report-limit", type=int, default=None)
    parser.add_argument("--validate-documents", action="store_true")
    parser.add_argument("--preview-documents", action="store_true")
    args = parser.parse_args()

    payload = collect_company_data(
        args.company,
        history_months=args.history_months,
        include_raw_reports=args.raw_reports,
        include_document_previews=args.preview_documents,
        include_excel_reports=args.excel_reports,
        include_all_excel_reports=args.all_excel_reports,
        excel_report_limit=args.excel_report_limit,
        validate_documents=args.validate_documents,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
