"""Openinfo spreadsheets operations with explicit dependencies."""
from __future__ import annotations
from typing import Any
import requests
import hashlib

from io import BytesIO
import collectors.openinfo.cache as collectors_openinfo_cache
import collectors.openinfo.settings as collectors_openinfo_settings
import collectors.openinfo.workbooks as collectors_openinfo_workbooks


def preview_excel_url(session: requests.Session, url: str, max_rows: int = 5) -> dict[str, Any]:
    import pandas as pd

    response = session.get(url, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
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


def parse_excel_report_document(
    session: requests.Session,
    document: dict[str, Any],
    *, revalidate_cached: bool = False,
) -> dict[str, Any]:
    url = document.get("excel_url")
    if not url:
        return {"ok": False, "error": "excel_url is missing"}

    cached = collectors_openinfo_cache._get_excel_cache(url)
    compatible = cached and cached.get("parser_version") == collectors_openinfo_settings.EXCEL_PARSER_VERSION
    revision = document.get('financial_revision')
    changed = compatible and revision is not None and cached.get('financial_revision') != revision
    if compatible:
        if not changed and not revalidate_cached:
            return cached
        if not collectors_openinfo_cache.claim_excel_refresh(url, revision):
            if changed:
                cached['refresh_failed'] = True
            return cached

    try:
        return _download_excel_report(session, document)
    except Exception:
        if not compatible:
            raise
        collectors_openinfo_settings.logger.warning('OpenInfo workbook refresh failed; retaining cached source', exc_info=True)
        collectors_openinfo_cache.failed_excel_refresh(url)
        cached['refresh_failed'] = True
        return cached


def _download_excel_report(session, document):
    url = document['excel_url']

    response = session.get(url, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
    response.raise_for_status()
    content_length = response.headers.get("content-length")
    size = int(content_length) if content_length and content_length.isdigit() else len(response.content)
    if size > collectors_openinfo_settings.EXCEL_MAX_BYTES:
        raise ValueError(f"Excel file is too large: {size} bytes")

    parsed = collectors_openinfo_workbooks._parse_excel_workbook(response.content)
    if not parsed.get('sheets') or parsed.get('warnings'):
        raise ValueError('Workbook could not be parsed completely')
    payload = {
        "ok": True,
        "source": "openinfo_excel",
        "parser_version": collectors_openinfo_settings.EXCEL_PARSER_VERSION,
        "from_cache": False,
        "report_id": document.get("id"),
        "object_id": document.get("object_id"),
        "published_at": document.get("published_at"),
        "period_type": document.get("period_type"),
        "report_form": document.get("report_form"),
        "title": document.get("title"),
        "content_type": response.headers.get("content-type"),
        "content_length": size,
        "content_sha256": hashlib.sha256(response.content).hexdigest(),
        "financial_revision": document.get('financial_revision'),
        **parsed,
    }
    collectors_openinfo_cache._set_excel_cache(url, payload)
    return payload


def _bounded_report_limit(value: int | None, default: int) -> int:
    raw = default if value is None else value
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(collectors_openinfo_settings.EXCEL_ABSOLUTE_MAX_REPORTS, parsed))


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
        return excel_documents[:_bounded_report_limit(max_reports, collectors_openinfo_settings.EXCEL_ABSOLUTE_MAX_REPORTS)]

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

    report_limit = _bounded_report_limit(max_reports, collectors_openinfo_settings.EXCEL_MAX_REPORTS)
    if max_annual_reports is None and max_quarter_reports is None:
        return excel_documents[:report_limit]

    annual_limit = _bounded_report_limit(max_annual_reports, collectors_openinfo_settings.EXCEL_MAX_ANNUAL_REPORTS)
    quarter_limit = _bounded_report_limit(max_quarter_reports, collectors_openinfo_settings.EXCEL_MAX_QUARTER_REPORTS)
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
    if not collectors_openinfo_settings.EXCEL_PARSE_ENABLED:
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
                collectors_openinfo_settings.EXCEL_ABSOLUTE_MAX_REPORTS if include_all else collectors_openinfo_settings.EXCEL_MAX_REPORTS,
            ),
            "max_annual_reports": None if include_all else _bounded_report_limit(max_annual_reports, collectors_openinfo_settings.EXCEL_MAX_ANNUAL_REPORTS),
            "max_quarter_reports": None if include_all else _bounded_report_limit(max_quarter_reports, collectors_openinfo_settings.EXCEL_MAX_QUARTER_REPORTS),
            "absolute_max_reports": collectors_openinfo_settings.EXCEL_ABSOLUTE_MAX_REPORTS,
            "max_bytes": collectors_openinfo_settings.EXCEL_MAX_BYTES,
            "cache_ttl_days": round(collectors_openinfo_settings.EXCEL_CACHE_TTL_SECONDS / 86400, 2),
        },
    }
