"""Openinfo issuers operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from urllib.parse import urlencode
import collectors.openinfo.settings as collectors_openinfo_settings
import collectors.openinfo.transport as collectors_openinfo_transport
import re
import requests


def _normalize_key(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _catalog_name_for_ticker(value: str) -> str | None:
    """Return the OpenInfo-searchable issuer name for a known exchange ticker.

    Company pages and the analysis picker hand the API a ticker (``YGSY``),
    whereas OpenInfo's autofill indexes the legal issuer name
    (``"Yuggazstroy" AJ``).  Resolve that translation before attempting a
    fuzzy upstream lookup; otherwise opening analysis from a company page
    reliably fails even though the issuer is in our own catalog.
    """
    ticker = str(value or "").strip().upper()
    if not ticker:
        return None
    try:
        from company_catalog import COMPANY_CATALOG
        return next(
            (name for name, listed_ticker in COMPANY_CATALOG.items()
             if str(listed_ticker).strip().upper() == ticker),
            None,
        )
    except Exception:  # The direct user-supplied name path remains available.
        return None


def resolve_company(query: str, session: requests.Session | None = None) -> dict[str, Any]:
    input_query = (query or "").strip()
    if not input_query:
        raise ValueError("company query cannot be empty")
    catalog_name = _catalog_name_for_ticker(input_query)
    query = catalog_name or input_query

    client = session or collectors_openinfo_transport._make_session()

    # Strategy 1: direct autofill (fast, returns logo).
    try:
        items = collectors_openinfo_transport._json_get(client, "/home/autofill/", {"name": query})
    except requests.RequestException:
        items = []

    if isinstance(items, list) and items:
        # /home/autofill/ IGNORES its search parameter and returns the full org
        # list (~790 items), so taking the top row without a score floor selects
        # an arbitrary organization — this is how tickers used to end up serving
        # another company's data. Accept only an exact or substring match on the
        # normalized name; anything weaker falls through to the fuzzy chain
        # below, which has its own confidence floor.
        normalized_queries = {_normalize_key(query)}
        if catalog_name:
            # The catalog uses the short legal suffix (AJ/ATB), while OpenInfo
            # expands it ("aksiyadorlik jamiyati").  The issuer's distinctive
            # name is still an identity floor; the legal-form word is not.
            brand = re.sub(
                r"\s+(?:aj|atb|atib|chakb|xk|uk|mchj|ooo)(?:\s*\([^)]*\))?\s*$",
                "",
                catalog_name,
                flags=re.IGNORECASE,
            )
            normalized_brand = _normalize_key(brand)
            if normalized_brand:
                normalized_queries.add(normalized_brand)
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            name = str(item.get("full_name_text") or "")
            score = 0
            normalized_name = _normalize_key(name)
            if any(candidate and candidate == normalized_name for candidate in normalized_queries):
                score += 100
            elif any(candidate and candidate in normalized_name for candidate in normalized_queries):
                score += 20
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored and scored[0][0] >= 20:
            best = scored[0][1]
            return {
                "input": input_query,
                "org_id": str(best.get("id")),
                "company_name": best.get("full_name_text") or "",
                "logo": best.get("logo"),
                "source_url": f"{collectors_openinfo_settings.OPENINFO_API_BASE}/home/autofill/?{urlencode({'name': query})}",
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
            logo_items = collectors_openinfo_transport._json_get(client, "/home/autofill/", {"name": company_name})
            if isinstance(logo_items, list):
                for item in logo_items:
                    if str(item.get("id")) == str(org_id):
                        logo = item.get("logo")
                        break
        except requests.RequestException:
            pass
        return {
            "input": input_query,
            "org_id": str(org_id),
            "company_name": company_name,
            "logo": logo,
            "source_url": f"{collectors_openinfo_settings.OPENINFO_API_BASE}/home/autofill/?{urlencode({'name': query})}",
        }

    raise LookupError(f"OpenInfo company was not found for {input_query!r}")
