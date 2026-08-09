"""
Audit and rebuild the company catalog based on openinfo.uz data availability.

Steps:
1. Fetch all UZSE-listed securities (stock screener).
2. For each security, resolve org_id via autofill API.
3. Check whether accounting reports exist (has data for analysis).
4. Cross-reference with current catalog.
5. Print what to ADD, REMOVE, and KEEP; write new catalog + logos JSON.
"""
from __future__ import annotations
import json, time, requests
from pathlib import Path
from typing import Any

from delisted import DELISTED_TICKERS

API = "https://new-api.openinfo.uz/api/v2"
TIMEOUT = 20

# Sector map: ticker -> sector key (fill in for new companies at the end)
KNOWN_SECTORS: dict[str, str] = {
    # Finance & Insurance
    "HMKB": "finance", "HMKBP": "finance",
    "IPKY": "finance",
    "IPTB": "finance", "IPTBP": "finance",
    "AGBA": "finance", "AGBAP": "finance",
    "SQBN": "finance", "SQBNP": "finance",
    "TRSB": "finance", "TRSBP": "finance",
    "TNBN": "finance", "TNBNP": "finance",
    "ALKB": "finance", "ALKBP": "finance",
    "GRBK": "finance",
    "MCBA": "finance", "MCBAP": "finance",
    "UNVB": "finance",
    "BRBN": "finance", "BRNBP": "finance", "BRBNP": "finance",
    "TNGB": "finance",
    "URTS": "finance",
    "UZINP": "finance",
    "ALSM": "finance", "ALSMP": "finance",
    "KASUP": "finance", "KASU": "finance",
    "TMYS": "finance",   # Temiryo'l-sug'urta (railway insurance)
    # Manufacturing
    "UZMK": "manufacturing", "UZMKP": "manufacturing",
    "KVTS": "manufacturing",
    "QZSM": "manufacturing",
    "BECM": "manufacturing", "BECMP": "manufacturing",
    "UZMT": "manufacturing",
    "DORI": "manufacturing",
    "ORGS": "manufacturing",
    "BIOK": "manufacturing",   # Biokimyo
    "UVGT": "manufacturing",   # O'zvagonta'mir (rail car repair)
    "UZHM": "manufacturing",   # O'zbekkimyomash zavodi
    # Mining
    "AGMKP": "mining",
    "BNGP": "mining", "BNGPP": "mining",
    "UZNGP": "mining",
    "UZGFP": "mining",
    "NGQS": "mining",
    "UZIR": "mining", "UZIRP": "mining",
    "PLST": "mining",   # Portlatishsanoat (explosives/blasting)
    "SANE": "mining",   # Sarbon-Neftegaz
    # Transport
    "UTGAP": "transport",
    "QATT": "transport",   # Qashqadaryo texnologik transport
    "UPOS": "transport", "UPOSP": "transport",  # O'zbekiston pochtasi
    # Telecom
    "UZTL": "telecom", "UZTLP": "telecom",
    # Professional
    "BTRL": "professional",
    # Trade
    "CBSK": "trade",
    # Other
    "JASM": "other",
    "TKDMP": "other", "TKDM": "other",
    "UZNF": "other",   # UzMIJ
}


def make_session() -> requests.Session:
    # Shared paced/retrying client — TLS verification on, polite pacing.
    from openinfo_http import make_session as _make_paced_session
    return _make_paced_session()


def get(session: requests.Session, path: str, params: dict | None = None) -> Any:
    url = path if path.startswith("http") else f"{API}{path}"
    r = session.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_screener(session: requests.Session) -> list[dict]:
    """Fetch all UZSE-listed securities."""
    results = []
    page = 1
    while True:
        data = get(session, "/iuzse/stock-screener/", {"mkt_id": "STK", "page_size": 100, "page": page})
        batch = data.get("results") or []
        results.extend(batch)
        if not data.get("next"):
            break
        page += 1
    return results


def autofill(session: requests.Session, name: str) -> list[dict]:
    try:
        data = get(session, "/home/autofill/", {"name": name})
        return data if isinstance(data, list) else ([data] if data else [])
    except Exception:
        return []


def resolve_org(session: requests.Session, ticker: str, issuer_name: str) -> tuple[str, str, str] | None:
    """Returns (org_id, canonical_name, logo_url) or None."""
    for query in [ticker, issuer_name]:
        items = autofill(session, query)
        if items:
            best = items[0]
            org_id = str(best.get("id", ""))
            name = best.get("full_name_text") or issuer_name
            logo = best.get("logo") or ""
            if org_id:
                return org_id, name, logo
    return None


def has_accounting_data(session: requests.Session, org_id: str) -> bool:
    """Quick check: does this org have any annual accounting reports?"""
    try:
        data = get(session, f"/reports/accounting-report/{org_id}/",
                   {"accounting_type": "form2", "report_type": "annual"})
        return bool(data)
    except Exception:
        return False


def has_report_documents(session: requests.Session, org_id: str, name: str) -> bool:
    """Fallback: check /reports/main/ for any published documents."""
    try:
        data = get(session, "/reports/main/", {"search": name, "page_size": 5})
        results = data.get("results") or []
        for item in results:
            if str(item.get("organization")) == org_id:
                return True
        return bool(results)  # if something came back it's likely the right org
    except Exception:
        return False


def main() -> None:
    import urllib3
    urllib3.disable_warnings()

    session = make_session()

    print("=== Fetching UZSE stock screener ===")
    screener = fetch_screener(session)
    print(f"Found {len(screener)} securities on UZSE.\n")

    # Load current catalog
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
    current_tickers: set[str] = set(COMPANY_CATALOG.values())

    # Load existing logos
    logos_path = Path("company_logos.json")
    existing_logos: dict[str, str] = json.loads(logos_path.read_text(encoding="utf-8")) if logos_path.exists() else {}

    results: list[dict] = []

    print("=== Checking each UZSE security for openinfo data ===")
    for i, sec in enumerate(screener, 1):
        ticker = sec.get("ticker") or ""
        issuer = sec.get("issuer_short_name") or sec.get("issuer_full_name") or ticker
        # Strip angle brackets openinfo adds
        issuer_clean = issuer.strip("<>")

        print(f"  [{i}/{len(screener)}] {ticker} — {issuer_clean} ...", end=" ", flush=True)

        resolved = resolve_org(session, ticker, issuer_clean)
        if not resolved:
            print("org_id NOT FOUND — skip")
            results.append({"ticker": ticker, "issuer": issuer_clean, "status": "no_org_id",
                             "in_catalog": ticker in current_tickers})
            time.sleep(0.3)
            continue

        org_id, canonical, logo = resolved
        has_data = has_accounting_data(session, org_id)
        if not has_data:
            # Fallback: check main reports
            has_data = has_report_documents(session, org_id, issuer_clean)

        status = "has_data" if has_data else "no_data"
        print(f"org={org_id} | data={'YES' if has_data else 'NO'} | logo={'yes' if logo else 'no'}")

        results.append({
            "ticker": ticker,
            "issuer": issuer_clean,
            "canonical_name": canonical,
            "org_id": org_id,
            "logo": logo,
            "has_data": has_data,
            "status": status,
            "in_catalog": ticker in current_tickers,
        })
        time.sleep(0.35)

    print("\n=== Also checking current catalog companies NOT in UZSE screener ===")
    uzse_tickers = {s.get("ticker") for s in screener}
    only_in_catalog = [(name, t) for name, t in COMPANY_CATALOG.items() if t not in uzse_tickers]
    print(f"  {len(only_in_catalog)} companies in catalog but not in UZSE screener:")

    for name, ticker in only_in_catalog:
        clean_name = name.strip('"').split('"')[0].strip()
        print(f"  [{ticker}] {clean_name} ...", end=" ", flush=True)
        resolved = resolve_org(session, ticker, clean_name)
        if not resolved:
            print("org_id NOT FOUND — no data")
            results.append({"ticker": ticker, "issuer": clean_name, "status": "no_org_id",
                             "in_catalog": True, "in_uzse": False})
            time.sleep(0.3)
            continue
        org_id, canonical, logo = resolved
        has_data = has_accounting_data(session, org_id)
        if not has_data:
            has_data = has_report_documents(session, org_id, clean_name)
        status = "has_data" if has_data else "no_data"
        print(f"org={org_id} | data={'YES' if has_data else 'NO'}")
        results.append({
            "ticker": ticker,
            "issuer": clean_name,
            "canonical_name": canonical,
            "org_id": org_id,
            "logo": logo or existing_logos.get(ticker, ""),
            "has_data": has_data,
            "status": status,
            "in_catalog": True,
            "in_uzse": False,
        })
        time.sleep(0.35)

    # ---- Summary ----
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    to_add    = [r for r in results if r.get("has_data") and not r.get("in_catalog")]
    to_remove = [r for r in results if r.get("in_catalog") and not r.get("has_data")]
    to_keep   = [r for r in results if r.get("has_data") and r.get("in_catalog")]

    print(f"\nKEEP  ({len(to_keep)}): {[r['ticker'] for r in to_keep]}")
    print(f"\nADD   ({len(to_add)}): {[r['ticker'] for r in to_add]}")
    print(f"\nREMOVE({len(to_remove)}): {[r['ticker'] for r in to_remove]}")

    # ---- Build new catalog ----
    new_catalog: dict[str, str] = {}
    new_sectors: dict[str, str] = {}
    new_logos: dict[str, str] = {}

    # Keep entries with data (from both current catalog and new UZSE companies)
    for r in results:
        if not r.get("has_data"):
            continue
        ticker = r["ticker"]
        if ticker in DELISTED_TICKERS:
            # Deleted from the site by decision, not by missing data — a rebuild
            # would otherwise silently put them back the moment openinfo answers.
            continue
        # Prefer canonical name from openinfo; fall back to current catalog name
        cname = r.get("canonical_name") or r["issuer"]
        new_catalog[cname] = ticker
        new_sectors[ticker] = KNOWN_SECTORS.get(ticker, COMPANY_SECTORS.get(ticker, "other"))
        logo = r.get("logo") or existing_logos.get(ticker, "")
        new_logos[ticker] = logo

    # Save results JSON for review
    Path("audit_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nNew catalog: {len(new_catalog)} companies")
    print("Saved audit_results.json for review.")
    print("\nNew catalog entries:")
    for name, ticker in sorted(new_catalog.items(), key=lambda x: x[1]):
        flag = "NEW" if ticker not in current_tickers else "   "
        print(f"  {flag} {ticker}: {name}")

    # Ask before overwriting
    ans = input("\nWrite new catalog and logos? [y/N] ").strip().lower()
    if ans != "y":
        print("Aborted — no files changed.")
        return

    # Write company_catalog.py
    catalog_lines = ["COMPANY_CATALOG = {\n"]
    for name, ticker in new_catalog.items():
        escaped = name.replace("'", "\\'")
        catalog_lines.append(f"    '{escaped}': '{ticker}',\n")
    catalog_lines.append("}\n\n")

    sectors_lines = ["COMPANY_SECTORS: dict[str, str] = {\n"]
    sector_groups: dict[str, list[str]] = {}
    for ticker, sector in new_sectors.items():
        sector_groups.setdefault(sector, []).append(ticker)
    for sector, tickers in sorted(sector_groups.items()):
        sectors_lines.append(f"    # {sector}\n")
        for ticker in sorted(tickers):
            sectors_lines.append(f"    '{ticker}': '{sector}',\n")
    sectors_lines.append("}\n")

    catalog_path = Path("company_catalog.py")
    catalog_path.write_text("".join(catalog_lines) + "".join(sectors_lines), encoding="utf-8")
    print(f"Written {catalog_path}")

    logos_path.write_text(json.dumps(new_logos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written {logos_path}")


if __name__ == "__main__":
    main()
