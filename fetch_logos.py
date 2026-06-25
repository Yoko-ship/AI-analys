"""Fetch company logos from openinfo.uz and save to data/company_logos.json."""
from __future__ import annotations
import json, time, requests
from pathlib import Path
from company_catalog import COMPANY_CATALOG

OPENINFO_API = "https://new-api.openinfo.uz/api/v2"
OUT = Path("company_logos.json")

# Curated domain overrides. The openinfo.uz logos are wide horizontal
# wordmarks (icon + company name) that shrink to a fuzzy, unreadable strip
# in a small badge. Google's favicon service returns the crisp square
# brand icon-mark instead, which reads far better. Keyed by ticker; applied
# to the preferred-share (…P) sibling too.
DOMAIN_OVERRIDES = {
    "AGBA": "agrobank.uz", "AGMKP": "agmk.uz", "ALKB": "aloqabank.uz",
    "ALSM": "alskom.uz", "BRBN": "brb.uz", "DORI": "doridarmon.uz",
    "GRBK": "garantbank.uz", "HMKB": "hamkorbank.uz", "IPKY": "ipakyulibank.uz",
    "IPTB": "ipotekabank.uz", "KPBA": "kapitalbank.uz", "MCBA": "mikrokreditbank.uz",
    "SQBN": "sqb.uz", "TNBN": "turonbank.uz", "TNGB": "tengebank.uz",
    "TRSB": "trustbank.uz", "UNVB": "universalbank.uz", "UZNGP": "ung.uz",
    "UZTL": "uztelecom.uz",
}

def favicon_url(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

def override_for(ticker: str) -> str | None:
    base = ticker[:-1] if ticker.endswith("P") else ticker
    for cand in (ticker, base):
        if cand in DOMAIN_OVERRIDES:
            return favicon_url(DOMAIN_OVERRIDES[cand])
    return None

def autofill(session: requests.Session, name: str) -> list[dict]:
    try:
        r = session.get(f"{OPENINFO_API}/home/autofill/", params={"name": name}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else [data] if isinstance(data, dict) and data else []
    except Exception as exc:
        print(f"  ERROR autofill({name!r}): {exc}")
        return []

def best_logo(items: list[dict]) -> str | None:
    for item in items:
        logo = item.get("logo")
        if logo and isinstance(logo, str) and logo.startswith("http"):
            return logo
    return None

def main() -> None:
    session = requests.Session()
    session.headers["User-Agent"] = "UZStockAnalyzer/1.0"

    existing: dict[str, str] = {}
    if OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8"))

    logos: dict[str, str] = {}
    companies = list(COMPANY_CATALOG.items())
    print(f"Fetching logos for {len(companies)} companies...")

    for i, (name, ticker) in enumerate(companies, 1):
        override = override_for(ticker)
        if override:
            logos[ticker] = override
            print(f"  [{i}/{len(companies)}] {ticker} — override {override}")
            continue
        if ticker in existing:
            logos[ticker] = existing[ticker]
            print(f"  [{i}/{len(companies)}] {ticker} — cached")
            continue

        # Use the canonical company name without "(привилегированные)" suffix for lookup
        search_name = name.strip('"').split('"')[0].strip()
        search_name = search_name.replace("(привилегированные)", "").replace("(preferred)", "").strip()
        # Remove surrounding quotes
        search_name = search_name.strip("\"'")

        items = autofill(session, search_name)
        logo = best_logo(items)

        if logo:
            logos[ticker] = logo
            print(f"  [{i}/{len(companies)}] {ticker} — {logo}")
        else:
            logos[ticker] = ""
            print(f"  [{i}/{len(companies)}] {ticker} — NOT FOUND (searched: {search_name!r})")

        time.sleep(0.3)  # be polite

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(logos, ensure_ascii=False, indent=2), encoding="utf-8")
    found = sum(1 for v in logos.values() if v)
    print(f"\nDone. {found}/{len(logos)} logos found → {OUT}")

if __name__ == "__main__":
    main()
