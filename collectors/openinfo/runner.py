"""Openinfo runner operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

import argparse
import collectors.openinfo.documents as collectors_openinfo_documents
import collectors.openinfo.issuers as collectors_openinfo_issuers
import collectors.openinfo.market as collectors_openinfo_market
import collectors.openinfo.pdf as collectors_openinfo_pdf
import collectors.openinfo.spreadsheets as collectors_openinfo_spreadsheets
import collectors.openinfo.transport as collectors_openinfo_transport
import json
import requests


def _probe_screener_availability(session: requests.Session) -> dict[str, Any]:
    """Check whether the OpenInfo stock screener has any data at all.

    Distinguishes "company is not listed" from "upstream screener is currently empty".
    """
    try:
        payload = collectors_openinfo_transport._json_get(session, "/iuzse/stock-screener/", {"mkt_id": "STK", "page_size": 1})
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
    session = collectors_openinfo_transport._make_session()
    company = collectors_openinfo_issuers.resolve_company(query, session=session)
    org_id = company.get("org_id")
    company_name = company.get("company_name") or query

    securities = collectors_openinfo_market.fetch_stock_screener(query, session=session)
    if not securities and company_name != query:
        securities = collectors_openinfo_market.fetch_stock_screener(company_name, session=session)

    security = collectors_openinfo_market._pick_security(query, securities, company_name=company_name)
    price_history: dict[str, Any] | None = None
    price_history_error: str | None = None
    if security and security.get("isin_code"):
        try:
            price_history = collectors_openinfo_market.fetch_price_history(security["isin_code"], session=session, months=history_months)
        except requests.RequestException as exc:
            price_history_error = str(exc)

    dividends = collectors_openinfo_market.fetch_dividends(query, session=session)
    if dividends["count"] == 0 and company_name != query:
        dividends = collectors_openinfo_market.fetch_dividends(company_name, session=session)

    reports = collectors_openinfo_documents.fetch_report_documents(
        query,
        org_id=org_id,
        session=session,
        validate_documents=validate_documents,
    )
    if reports["count"] == 0 and company_name != query:
        reports = collectors_openinfo_documents.fetch_report_documents(
            company_name,
            org_id=org_id,
            session=session,
            validate_documents=validate_documents,
        )

    if include_document_previews:
        for document in reports["items"][:8]:
            try:
                if document.get("excel_url") and document.get("period_type") == "annual":
                    document["excel_preview"] = collectors_openinfo_spreadsheets.preview_excel_url(session, document["excel_url"])
                    break
            except Exception as exc:
                document["excel_preview_error"] = str(exc)
        for document in reports["items"][:8]:
            try:
                if document.get("pdf_url") and document.get("report_form") in {"MSFO", "Audition"}:
                    document["pdf_preview"] = collectors_openinfo_pdf.preview_pdf_url(session, document["pdf_url"])
                    break
            except Exception as exc:
                document["pdf_preview_error"] = str(exc)

    accounting = collectors_openinfo_documents.fetch_accounting_bundle(
        org_id,
        session=session,
        include_raw=include_raw_reports,
    )
    excel_reports = (
        collectors_openinfo_spreadsheets.fetch_excel_report_snapshots(
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
            "summary": collectors_openinfo_market._market_summary(security, (price_history or {}).get("points") or []),
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
