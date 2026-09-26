"""OpenInfo catalogue transport and document retrieval adapter."""
from __future__ import annotations
from collectors.openinfo.settings import OPENINFO_API_BASE
from collectors.openinfo.settings import OPENINFO_WEB_BASE
from collectors.openinfo.settings import REQUEST_TIMEOUT
from collectors.openinfo.documents import _build_report_document
from collectors.openinfo.transport import _json_get
from collectors.openinfo.transport import _make_session
from collectors.openinfo.spreadsheets import parse_excel_report_document
from collectors.openinfo.issuers import resolve_company
import catalogue.history as catalogue_history
from typing import Any

from collectors.openinfo.settings import OPENINFO_API_BASE
from collectors.openinfo.settings import OPENINFO_WEB_BASE
from collectors.openinfo.settings import REQUEST_TIMEOUT
from collectors.openinfo.documents import _build_report_document
from collectors.openinfo.transport import _json_get
from collectors.openinfo.transport import _make_session
from collectors.openinfo.spreadsheets import parse_excel_report_document
from collectors.openinfo.issuers import resolve_company
from urllib.parse import urlencode
import catalogue.filings as catalogue_filings
import re


_LEGAL_FORM_TOKENS = {
    "atb", "aj", "ak", "ato", "mchj", "qmj", "xk", "uk", "ooo", "aytb",
    "ао", "оао", "зао", "акб", "хк", "ук", "чп", "ип", "atb.", "aj.",
}


def _org_search_terms(company_name: str) -> list[str]:
    """Best-first candidate queries for openinfo's /reports/main/ search.

    openinfo's search engine fails on the full legal name (quotes + legal-form
    suffix), so we also try the de-quoted name and the bare brand token(s).
    """
    name = (company_name or "").strip()
    terms: list[str] = []
    if name:
        terms.append(name)
    cleaned = re.sub(r"""["«»“”'`]""", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned not in terms:
        terms.append(cleaned)
    tokens = [t for t in cleaned.split(" ") if t]
    brand = [t for t in tokens if t.lower().strip(".") not in _LEGAL_FORM_TOKENS]
    phrase = " ".join(brand).strip()
    if phrase and phrase not in terms:
        terms.append(phrase)
    if brand and brand[0] not in terms:
        terms.append(brand[0])
    return terms


def _fetch_main_results(session: Any, company_name: str, org_id: Any) -> tuple[list[dict], str | None]:

    """Return (org-filtered /reports/main/ records, org_type) for a company.



    Tries progressively cleaner search terms until one returns records for this

    org_id — openinfo's search misses the full legal name for many issuers.

    """

    for query in _org_search_terms(company_name):

        try:

            payload = _json_get(session, "/reports/main/", {"page": 1, "page_size": 200, "search": query})

        except Exception:

            continue

        results = list(payload.get("results") or []) if isinstance(payload, dict) else []

        # The unified feed is paginated. Finding one recent issuer record does

        # not mean its older statements were included in the first 200 rows.

        seen = {str(r.get("id")) for r in results}

        for page in range(2, 21):

            batch = payload.get("results") or []

            if not batch or (not payload["next"] if "next" in payload else len(batch) < 200):

                break

            payload = _json_get(session, "/reports/main/", {"page": page, "page_size": 200, "search": query})

            fresh = [r for r in payload.get("results", []) if str(r.get("id")) not in seen]

            if payload.get("results") and not fresh:

                raise RuntimeError("OpenInfo repeated a report-listing page; discovery is incomplete")

            results.extend(fresh)

            seen.update(str(r.get("id")) for r in fresh)

        else:

            if payload.get("next") or ("next" not in payload and len(payload.get("results") or []) >= 200):

                raise RuntimeError("OpenInfo listing exceeded the bounded discovery window")

        filtered = [r for r in results if str(r.get("organization")) == str(org_id)]

        if filtered:

            org_type = next(

                ((r.get("properties") or {}).get("org_type") for r in filtered if (r.get("properties") or {}).get("org_type")),

                None,

            )

            return filtered, org_type

    return [], None


def _nsbu_export_urls(report_id: Any, period_type: str, org_type: str | None,
                      pdf_id: Any = None) -> tuple[str | None, str | None]:
    """Build (pdf_url, excel_url) for an NSBU accounting-report from its ids.

    NSBU records come from the ``/reports/accounting-report/`` endpoint, whose
    shape carries the financial line-items but no document URLs. The Excel export
    takes this record's own id (plus the period type and the issuer's
    ``org_type`` — without a correct org_type it returns HTTP 400, so excel_url
    is omitted when org_type is unknown).

    The PDF endpoint ``/ru/reports/to_pdf<id>/`` lives in a DIFFERENT id space:
    it takes the unified-feed record id, not this one. Passing the accounting id
    there serves whatever OTHER issuer's filing happens to sit at that feed id —
    measured 2026-08-09: UZML's annual 6021 rendered a cotton gin's quarterly.
    So the PDF link is built only from an explicitly supplied ``pdf_id`` (see
    ``_unified_pdf_id_map``); with none, no link is better than a wrong one.
    """
    if not report_id:
        return None, None
    pdf_url = f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{pdf_id}/" if pdf_id else None
    excel_url = None
    if org_type:
        excel_url = f"{OPENINFO_API_BASE}/reports/export-excel/?" + urlencode(
            {"report_type": period_type, "org_type": org_type, "report_id": report_id, "lang": "ru"}
        )
    return pdf_url, excel_url


def _unified_pdf_id_map(session: Any, org_id: Any) -> dict[str, dict[str, Any]]:
    """Accounting object id → {pdf_id, pub_date}, for one issuer.

    The unified feed is the only place the two id spaces meet: each record
    carries its own id (the ``to_pdf`` namespace) and a ``report_link`` whose
    tail is the accounting-report object id the structured sync works with.
    It is also the only source of a PUBLICATION date for an accounting record,
    which _effective_annual_year needs: the accounting-report endpoint itself
    carries nothing but the (often mis-stamped) reporting_year.
    """
    out: dict[str, dict[str, Any]] = {}
    if not org_id:
        return out
    for page in range(1, 6):
        try:
            payload = _json_get(session, "/reports/unified-financial-reports/",
                                {"format": "json", "page": page, "page_size": 200,
                                 "organization": org_id})
        except Exception:
            break
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        for rec in results:
            m = re.search(r"/reports/[a-z]+/[a-z]+/(\d+)/?$", str(rec.get("report_link") or ""))
            if m and rec.get("id"):
                out[m.group(1)] = {"pdf_id": rec["id"], "pub_date": rec.get("pub_date")}
        if len(results) < 200 or not (isinstance(payload, dict) and payload.get("next")):
            break
    return out


_ANNUAL_RECORD_EXCLUSIONS: set[tuple[str, str]] = {("11", "261")}


_ORG_TYPE_CANDIDATES = ("jsc", "bank", "insurance", "microfinance")


def _probe_org_type(session: Any, form2_records: list[dict], period_type: str) -> str | None:
    """Discover an issuer's org_type by probing the Excel export endpoint.

    openinfo's /reports/main/ search misses some issuers outright — names that
    tokenize to a single useless letter (e.g. "O'zqishloqelektrqurilish" → "O")
    return no org-matched records, so _fetch_main_results yields org_type=None and
    no NSBU Excel URL can be built (financials then stay empty). The export itself
    works once the right org_type label is supplied, so we try each candidate
    against a real report id and keep the first that returns a genuine .xlsx
    (HTTP 200 + spreadsheet content-type; a wrong org_type returns HTTP 400).
    """
    report_id = next(
        (doc.get("id") for rec in form2_records if (doc := _build_report_document(rec)).get("id")),
        None,
    )
    if not report_id:
        return None
    for org_type in _ORG_TYPE_CANDIDATES:
        url = _nsbu_export_urls(report_id, period_type, org_type)[1]
        try:
            resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            ctype = (resp.headers.get("content-type") or "").lower()
            resp.close()
        except Exception:  # noqa: BLE001 — any transport error just means "try next"
            continue
        if resp.status_code == 200 and ("spreadsheet" in ctype or "officedocument" in ctype):
            return org_type
    return None


def fetch_report_excel_data(ticker: str, form: str, year: int, quarter: int, *,

                            use_snapshot_cache: bool = True) -> dict[str, Any]:

    urls = catalogue_filings.get_report_urls(ticker, form, year, quarter)

    if not urls:

        return {"ok": False, "income": None, "balance": None, "error": "Report not found in catalog"}



    session = _make_session()

    income: dict | None = None

    balance: dict | None = None

    errors: list[str] = []



    if urls.get("excel_url"):

        doc = {"excel_url": urls["excel_url"], "id": None, "object_id": None,

               "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),

               "report_form": form, "title": urls.get("title")}

        try:

            parsed = (parse_excel_report_document(session, doc) if use_snapshot_cache

                      else catalogue_history._parse_workbook_uncached(session, doc["excel_url"]))

            if parsed.get("ok"):

                income = parsed

            else:

                errors.append(f"income/main: {parsed.get('error')}")

        except Exception as exc:

            errors.append(f"income/main: {exc}")



    if urls.get("excel_url_form1"):

        # OpenInfo commonly puts both NSBU forms in one workbook and publishes

        # the same URL for the income and balance links. Reuse the successful

        # parse: downloading it twice made a single transient second request

        # turn an otherwise valid filing into a partial workbook.

        if urls["excel_url_form1"] == urls.get("excel_url") and income is not None:

            balance = income

        else:

            doc1 = {"excel_url": urls["excel_url_form1"], "id": None, "object_id": None,

                    "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),

                    "report_form": form, "title": urls.get("title")}

            try:

                parsed1 = (parse_excel_report_document(session, doc1) if use_snapshot_cache

                           else catalogue_history._parse_workbook_uncached(session, doc1["excel_url"]))

                if parsed1.get("ok"):

                    balance = parsed1

                else:

                    errors.append(f"balance: {parsed1.get('error')}")

            except Exception as exc:

                errors.append(f"balance: {exc}")



    ok = income is not None or balance is not None

    if not urls.get("excel_url") and not urls.get("excel_url_form1"):

        errors.append("No Excel document is linked to this filing")

    return {

        "ok": ok,

        "income": income,

        "balance": balance,

        "error": "; ".join(errors) if errors and not ok else None,

        "warnings": errors if ok and errors else [],

    }
