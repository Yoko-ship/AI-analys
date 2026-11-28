"""Openinfo documents operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from urllib.parse import urlencode
import collectors.openinfo.issuers as collectors_openinfo_issuers
import collectors.openinfo.settings as collectors_openinfo_settings
import collectors.openinfo.transport as collectors_openinfo_transport
import re
import requests
from nsbu_periods import OPENINFO_QUARTERS, stated_period, resolve_period


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
            pdf_url = f"{collectors_openinfo_settings.OPENINFO_WEB_BASE}/ru/reports/to_pdf{report_id}/"
        if object_id and report_period_type and org_type:
            excel_url = (
                f"{collectors_openinfo_settings.OPENINFO_API_BASE}/reports/export-excel/?"
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
        response = session.head(url, allow_redirects=True, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
        if response.status_code >= 400:
            response = session.get(url, stream=True, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
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
    """Report documents matching ``query``, restricted to ``org_id`` when given.

    ``/reports/main/?search=`` is a full-text search over filings, so it happily
    returns another issuer's documents for a name that merely shares words. When
    the caller knows the organization, an empty filtered result means "this issuer
    has no matching filing" — NOT "use whatever the search returned". The old
    ``if filtered:`` fallback silently handed back the unfiltered page in exactly
    that case, which is how another company's PDF ended up parsed into a ticker's
    financials.
    """
    client = session or collectors_openinfo_transport._make_session()
    params = {"page": 1, "page_size": page_size, "search": query}
    payload = collectors_openinfo_transport._json_get(client, "/reports/main/", params)
    results = list(payload.get("results") or []) if isinstance(payload, dict) else []
    if org_id:
        filtered = [item for item in results if str(item.get("organization")) == str(org_id)]
        if not filtered and results:
            collectors_openinfo_settings.logger.warning(
                "reports/main: %d hit(s) for %r, none belonging to org %s — returning none "
                "rather than another issuer's filings",
                len(results), query, org_id,
            )
        results = filtered

    documents = [_build_report_document(report) for report in results]
    if validate_documents:
        for document in documents:
            for field in ("pdf_url", "excel_url"):
                url = document.get(field)
                if url:
                    document[f"{field}_status"] = _probe_document(client, url)

    return {
        "source_url": f"{collectors_openinfo_settings.OPENINFO_API_BASE}/reports/main/?{urlencode(params)}",
        "count": len(documents),
        "items": documents,
    }


def fetch_accounting_bundle(
    org_id: str,
    session: requests.Session | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    client = session or collectors_openinfo_transport._make_session()
    base = f"/reports/accounting-report/{org_id}/"
    urls = {
        "income_annual": (base, {"accounting_type": "form2", "report_type": "annual"}),
        "balance_annual": (base, {"accounting_type": "form1", "report_type": "annual"}),
        "income_quarter": (base, {"accounting_type": "form2", "report_type": "quarter"}),
        "balance_quarter": (base, {"accounting_type": "form1", "report_type": "quarter"}),
        "financial_indicators": ("/reports/financial_indicators/", {"organization_id": org_id}),
    }
    bundle = {name: collectors_openinfo_transport._json_get(client, path, params) for name, (path, params) in urls.items()}
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


def fetch_statement_period(session, *, org_id, org_type, period_type, record_id, published_at=None):
    """Read period evidence from the original statement, bound to its issuer."""
    org_type = "jsc" if org_type == "llc" else org_type
    if org_type not in {"bank", "jsc", "insurance"} or not str(record_id).isdigit():
        raise ValueError("Statement identity is missing for period lookup")
    detail = collectors_openinfo_transport._json_get(session, f"/reports/{org_type}/{period_type}/{record_id}/")
    if not isinstance(detail, dict) or str(detail.get("id")) != str(record_id):
        raise ValueError("Statement identity does not match period lookup")
    issuer = detail.get("organization")
    issuer = issuer.get("id") if isinstance(issuer, dict) else issuer
    if str(issuer) != str(org_id):
        raise ValueError("Statement issuer does not match period lookup")
    period = resolve_period(detail.get("reporting_year"), period_type,
                          quarter=OPENINFO_QUARTERS.get(str(detail.get("quarter_no") or "")),
                          published_at=published_at or detail.get("pub_date"))
    if period is None:
        raise ValueError("Statement has no explicit completed reporting period")
    return period


def fetch_available_periods(
    org_id: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Return source-declared periods and diagnostics for unresolved filings."""
    client = session or collectors_openinfo_transport._make_session()
    base = f"/reports/accounting-report/{org_id}/"

    try:
        annual_records = collectors_openinfo_transport._json_get(client, base, {"accounting_type": "form2", "report_type": "annual"})
    except Exception:
        annual_records = []
    try:
        quarter_records = collectors_openinfo_transport._json_get(client, base, {"accounting_type": "form2", "report_type": "quarter"})
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

    # Parse quarterly periods from "period" string: "Q1 2026" → {year:2026, quarter:1}.
    # This endpoint deliberately exposes only its ten most recent records;
    # historical periods are supplemented from the unified filings feed below.
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

    # The structured response has only ten records. Recover older periods from
    # explicit unified metadata or the original statement, never upload timing.
    unresolved = []
    publication_fallbacks = []
    resolved_statements = {}
    for page in range(1, 6):
        try:
            payload = collectors_openinfo_transport._json_get(
                client,
                "/reports/unified-financial-reports/",
                {"format": "json", "page": page, "page_size": 200, "organization": org_id},
            )
        except Exception:  # The recent structured periods remain usable.
            break
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        for record in results:
            properties = record.get("properties") or {}
            if str(record.get("report_type") or "") != "NSBU":
                continue
            period_type = str(properties.get("report_type") or "").lower()
            if period_type not in {"annual", "quarter"}:
                continue
            title = str(properties.get("report_title") or "").strip()
            match = re.fullmatch(r"Q([1-4])\s+(\d{4})", title, re.IGNORECASE)
            year, quarter = stated_period(
                match[2] if match else properties.get("reporting_year"), period_type,
                quarter=int(match[1]) if match else None, published_at=record.get("pub_date"),
            )
            if year is None:
                key = (properties.get("org_type"), period_type, str(record.get("object_id")))
                if key not in resolved_statements:
                    try:
                        resolved_statements[key] = fetch_statement_period(
                            client, org_id=org_id, org_type=key[0], period_type=period_type,
                            record_id=record.get("object_id"), published_at=record.get("pub_date"),
                        )
                    except Exception as exc:
                        resolved_statements[key] = str(exc)
                result = resolved_statements[key]
                if isinstance(result, str):
                    unresolved.append({"id": record.get("id"), "reason": result})
                    continue
                year, quarter = result["year"], result["quarter"]
                if result["period_source"] == "publication_date":
                    publication_fallbacks.append({"id": record.get("id"), **result})
            if period_type == "annual":
                if year >= 2000 and year not in seen_annual:
                    seen_annual.add(year)
                    annual_years.append(year)
                continue
            if year < 2000 or (year, quarter) in seen_q:
                continue
            seen_q.add((year, quarter))
            quarterly.append({"year": year, "quarter": quarter})
        if len(results) < 200 or not (isinstance(payload, dict) and payload.get("next")):
            break
    quarterly.sort(key=lambda x: (x["year"], x["quarter"]), reverse=True)
    annual_years.sort(reverse=True)

    return {
        "publication_fallbacks": publication_fallbacks,
        "unresolved": unresolved,
        "annual_years": annual_years,
        "quarterly": quarterly,
        "latest_annual_year": annual_years[0] if annual_years else None,
        "latest_quarterly": quarterly[0] if quarterly else None,
    }


def get_company_periods(query: str) -> dict[str, Any]:
    """Resolve a company by name/ticker and return its available reporting periods."""
    session = collectors_openinfo_transport._make_session()
    company = collectors_openinfo_issuers.resolve_company(query, session=session)
    org_id = company.get("org_id")
    if not org_id:
        raise LookupError(f"No org_id found for {query!r}")
    periods = fetch_available_periods(org_id, session=session)
    return {"ok": True, "company": company, "periods": periods}
