"""Connectivity probe for openinfo.uz.

Answers, from whatever host it runs on, exactly which openinfo endpoint classes
are reachable — the same ones the collector uses (autofill, org list,
accounting-report lists, financial indicators, dividend calendar, Excel export,
web host). Run it on the API deployment to see what its egress IP can reach,
or locally to compare.

Usable three ways:
- CLI:   python openinfo_probe.py [--search NAME] [--org-id ID]
- API:   GET /api/admin/openinfo-probe  (X-Admin-Secret; runs on the API host)
- code:  run_probe() -> dict
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from typing import Any, Callable

import requests

from collectors.openinfo.settings import OPENINFO_API_BASE, OPENINFO_WEB_BASE
from openinfo_collector import OPENINFO_PROXY, VERIFY_SSL
from collectors.openinfo.transport import _make_session

# Any large, long-listed issuer works; only used when autofill itself is down
# so the org-scoped endpoints can still be probed.
_FALLBACK_ORG_ID = os.getenv("OPENINFO_PROBE_ORG_ID", "8")  # Hamkorbank
_PROBE_TIMEOUT = int(os.getenv("OPENINFO_PROBE_TIMEOUT", "15"))
_STEP_DELAY_SECONDS = 0.3


def _run_step(name: str, url: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {"name": name, "url": url, "ok": False}
    try:
        outcome = fn() or {}
        result.update(outcome)
        result["ok"] = bool(result.get("status_code", 0) and result["status_code"] < 400)
    except requests.exceptions.SSLError as exc:
        result["error"] = f"ssl: {exc}"
    except requests.exceptions.ProxyError as exc:
        result["error"] = f"proxy: {exc}"
    except requests.exceptions.ConnectTimeout:
        result["error"] = "connect timeout (network-level block or unreachable)"
    except requests.exceptions.ReadTimeout:
        result["error"] = "read timeout"
    except requests.exceptions.ConnectionError as exc:
        result["error"] = f"connection error (likely IP block or DNS): {exc}"
    except Exception as exc:  # noqa: BLE001 - probe must report, never raise
        result["error"] = str(exc)
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


def _get_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=_PROBE_TIMEOUT)
    out: dict[str, Any] = {"status_code": response.status_code}
    try:
        payload = response.json()
        if isinstance(payload, dict):
            out["note"] = f"json dict, keys={list(payload.keys())[:6]}"
            out["payload"] = payload
        elif isinstance(payload, list):
            out["note"] = f"json list, {len(payload)} items"
            out["payload"] = payload
    except ValueError:
        out["note"] = f"non-JSON body ({len(response.content)} bytes) — possible WAF/challenge page"
    return out


def _get_head(session: requests.Session, url: str) -> dict[str, Any]:
    """GET but read only the first KB — enough to prove reachability."""
    with session.get(url, timeout=_PROBE_TIMEOUT, stream=True) as response:
        chunk = next(response.iter_content(chunk_size=1024), b"")
        return {"status_code": response.status_code, "note": f"first {len(chunk)} bytes read"}


def run_probe(search: str = "Hamkorbank", org_id: str | None = None) -> dict[str, Any]:
    session = _make_session()
    results: list[dict[str, Any]] = []

    def step(name: str, url: str, fn: Callable[[], Any]) -> dict[str, Any]:
        res = _run_step(name, url, fn)
        res.pop("payload", None)
        results.append(res)
        time.sleep(_STEP_DELAY_SECONDS)
        return res

    # Which IP openinfo sees (through the proxy if one is configured). Non-fatal.
    step("egress_ip", "https://api.ipify.org", lambda: {
        "status_code": 200,
        "note": session.get("https://api.ipify.org", timeout=_PROBE_TIMEOUT).text.strip(),
    })

    autofill_url = f"{OPENINFO_API_BASE}/home/autofill/"
    autofill_res = _run_step("api_autofill", autofill_url,
                             lambda: _get_json(session, autofill_url, {"search": search}))
    autofill_payload = autofill_res.pop("payload", None)
    results.append(autofill_res)
    time.sleep(_STEP_DELAY_SECONDS)

    # Reuse the org autofill just found so org-scoped probes hit a real issuer.
    probe_org = org_id or _FALLBACK_ORG_ID
    if not org_id and isinstance(autofill_payload, list) and autofill_payload:
        found = autofill_payload[0].get("id")
        if found:
            probe_org = str(found)

    org_list_url = f"{OPENINFO_API_BASE}/home/organizations/"
    step("api_organizations", org_list_url,
         lambda: {k: v for k, v in _get_json(session, org_list_url, {"page": 1}).items() if k != "payload"})

    accounting_url = f"{OPENINFO_API_BASE}/reports/accounting-report/{probe_org}/"
    step("api_accounting_reports", accounting_url,
         lambda: {k: v for k, v in _get_json(
             session, accounting_url,
             {"accounting_type": "form2", "report_type": "quarter"}).items() if k != "payload"})

    reports_main_url = f"{OPENINFO_API_BASE}/reports/main/"
    reports_res = _run_step(
        "api_reports_main", reports_main_url,
        lambda: _get_json(session, reports_main_url,
                          {"organization_id": probe_org, "page": 1, "page_size": 10}))
    reports_payload = reports_res.pop("payload", None)
    results.append(reports_res)
    time.sleep(_STEP_DELAY_SECONDS)

    indicators_url = f"{OPENINFO_API_BASE}/reports/financial_indicators/"
    step("api_financial_indicators", indicators_url,
         lambda: {k: v for k, v in _get_json(session, indicators_url, {"organization_id": probe_org}).items()
                  if k != "payload"})

    dividends_url = f"{OPENINFO_API_BASE}/disclosure/dividend-calendar/"
    step("api_dividend_calendar", dividends_url,
         lambda: {k: v for k, v in _get_json(
             session, dividends_url,
             {"stock_type": "simple", "page": 1, "page_size": 1, "search": search}).items() if k != "payload"})

    # Excel export needs a real report id — take an NSBU record from reports/main.
    excel_url = None
    main_records = (reports_payload or {}).get("results") if isinstance(reports_payload, dict) else None
    if isinstance(main_records, list):
        for report in main_records:
            properties = report.get("properties") or {}
            if (report.get("report_type") == "NSBU" and report.get("object_id")
                    and properties.get("report_type") and properties.get("org_type")):
                from urllib.parse import urlencode
                excel_url = (f"{OPENINFO_API_BASE}/reports/export-excel/?"
                             + urlencode({"report_type": properties["report_type"],
                                          "org_type": properties["org_type"],
                                          "report_id": report["object_id"],
                                          "lang": "ru"}))
                break
    if excel_url:
        step("api_excel_export", excel_url, lambda: _get_head(session, excel_url))
    else:
        results.append({"name": "api_excel_export", "url": None, "ok": False,
                        "error": "skipped — no report with export properties found upstream"})

    step("web_home", OPENINFO_WEB_BASE, lambda: _get_head(session, f"{OPENINFO_WEB_BASE}/"))

    checked = [r for r in results if r["name"] != "egress_ip"]
    reachable = [r for r in checked if r["ok"]]
    failed = [r for r in checked if not r["ok"]]
    if not failed:
        verdict = "openinfo fully reachable from this host"
    elif not reachable:
        verdict = "openinfo unreachable from this host — IP/network-level block likely"
    else:
        verdict = "partially reachable — see failed steps"

    return {
        "ok": True,
        "host": socket.gethostname(),
        "proxy_configured": bool(OPENINFO_PROXY),
        "verify_ssl": VERIFY_SSL,
        "probe_org_id": probe_org,
        "verdict": verdict,
        "reachable": len(reachable),
        "failed": len(failed),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe openinfo.uz reachability from this host")
    parser.add_argument("--search", default="Hamkorbank", help="issuer name for search-based probes")
    parser.add_argument("--org-id", default=None, help="openinfo org id for org-scoped probes")
    args = parser.parse_args()
    print(json.dumps(run_probe(args.search, args.org_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
