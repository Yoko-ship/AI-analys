"""On-demand Soliq company registry enrichment.

The browser identifies an issuer by exchange ticker. OpenInfo is the identity
bridge (ticker -> organization -> INN), while Soliq is the source of the legal,
tax, address, and management record. Keeping both hops on the server prevents
the Soliq API key from ever reaching client-side JavaScript.
"""
from __future__ import annotations

import os
import re
import math
from typing import Any

import requests

from entity_resolver import ORG_OVERRIDES, get_org_index


_TICKER_RE = re.compile(r"^[A-Z0-9.-]{2,40}$")
# These fields are present in Soliq's full record but have been determined
# unreliable for UZStock.  Remove them before the record reaches any API
# consumer; hiding them only in the browser would still expose bad data.
_UNRELIABLE_COMPANY_FIELDS = frozenset({
    "soato",
    "kfs",
    "taxpayerType",
    "taxMode",
    "vatNumber",
    "businessFund",
})


class SoliqConfigurationError(RuntimeError):
    """The server is not configured to call Soliq."""


class CompanyIdentityNotFound(RuntimeError):
    """OpenInfo could not resolve this exchange ticker to an INN."""


class SoliqUpstreamError(RuntimeError):
    """Soliq rejected or failed the upstream request."""


def _normalise_ticker(ticker: str) -> str:
    value = str(ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(value):
        raise CompanyIdentityNotFound("company ticker is invalid")
    return value


def _org_id_from_catalog(ticker: str) -> str | None:
    """Use the operational catalog for issuers absent from today's screener."""
    if ticker in ORG_OVERRIDES:
        return str(ORG_OVERRIDES[ticker])
    try:
        from reports_catalog import get_company_index

        value = get_company_index(ticker).get("org_id")
        return str(value).strip() if value else None
    except Exception:
        return None


def _tin_from_index(index: dict[str, Any], ticker: str) -> tuple[str | None, str | None]:
    by_ticker = index.get("by_ticker") or {}
    hit = by_ticker.get(ticker)
    if not hit and ticker.endswith("P"):
        hit = by_ticker.get(ticker[:-1])

    org_id = str((hit or {}).get("org_id") or _org_id_from_catalog(ticker) or "").strip()
    if not org_id:
        return None, None

    for tin, entry in (index.get("by_inn") or {}).items():
        if str((entry or {}).get("org_id") or "").strip() == org_id:
            candidate = str(tin or "").strip()
            if candidate.isdigit() and len(candidate) == 9:
                return candidate, org_id
    return None, org_id


def resolve_company_tin(ticker: str) -> dict[str, str]:
    """Resolve one ticker to its legal entity's nine-digit INN via OpenInfo.

    The cached index is the normal path. A live refresh happens only on a miss,
    so opening an already-known company page does not re-download the issuer
    universe.
    """
    normalised = _normalise_ticker(ticker)
    index = get_org_index()
    tin, org_id = _tin_from_index(index, normalised)
    if not tin:
        refreshed = get_org_index(force=True)
        tin, org_id = _tin_from_index(refreshed, normalised)
    if not tin:
        raise CompanyIdentityNotFound(f"INN is unavailable for {normalised}")
    return {"ticker": normalised, "tin": tin, "org_id": str(org_id or "")}


def _registry_location(payload: dict[str, Any]) -> dict[str, float] | None:
    """Return only coordinates supplied by the authoritative registry.

    A postal address is not a coordinate.  In particular, do not silently turn
    it into a Google Maps search: an ambiguous search renders unrelated pins.
    The aliases below cover common coordinate spellings should Soliq add them
    to either its address or location object.
    """
    candidates: list[Any] = [
        payload.get("location"),
        payload.get("geoLocation"),
        payload.get("coordinates"),
        payload.get("companyBillingAddress"),
        payload.get("company"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        latitude = next((candidate.get(key) for key in ("latitude", "lat") if candidate.get(key) not in (None, "")), None)
        longitude = next((candidate.get(key) for key in ("longitude", "lon", "lng") if candidate.get(key) not in (None, "")), None)
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            continue
        # A legal entity returned by Soliq should be located in Uzbekistan.
        # Reject swapped, placeholder, and unrelated coordinates instead of
        # displaying a confident-looking but incorrect marker.
        if 37.0 <= latitude <= 46.0 and 55.0 <= longitude <= 74.0:
            return {"latitude": latitude, "longitude": longitude}
    return None


def _public_registry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy the upstream record and exclude fields we do not publish."""
    result = dict(payload)
    company = payload.get("company")
    if isinstance(company, dict):
        result["company"] = {
            key: value for key, value in company.items()
            if key not in _UNRELIABLE_COMPANY_FIELDS
        }
    return result


def fetch_company_registry(ticker: str) -> dict[str, Any]:
    """Fetch the full Soliq record for exactly one company page request."""
    api_key = os.getenv("SOLIQ_API_KEY", "").strip()
    if not api_key:
        raise SoliqConfigurationError("SOLIQ_API_KEY is not configured")

    identity = resolve_company_tin(ticker)
    base_url = os.getenv(
        "SOLIQ_API_BASE_URL",
        "https://my.soliq.uz/api/remote-access-api",
    ).strip().rstrip("/")
    try:
        timeout = min(30.0, max(1.0, float(os.getenv("SOLIQ_API_TIMEOUT", "12"))))
    except ValueError:
        timeout = 12.0

    try:
        response = requests.get(
            f"{base_url}/company/info/{identity['tin']}",
            params={"type": "full"},
            headers={"Accept": "application/json", "X-API-KEY": api_key},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SoliqUpstreamError("Soliq is temporarily unavailable") from exc

    if response.status_code in {401, 403}:
        raise SoliqConfigurationError("Soliq rejected the configured API key")
    if response.status_code in {400, 404}:
        raise CompanyIdentityNotFound(f"Soliq has no company record for {identity['tin']}")
    if not response.ok:
        raise SoliqUpstreamError(f"Soliq returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SoliqUpstreamError("Soliq returned an invalid JSON response") from exc
    company = payload.get("company") if isinstance(payload, dict) else None
    if not isinstance(company, dict):
        raise SoliqUpstreamError("Soliq response is missing company data")
    returned_tin = str(company.get("tin") or "").strip()
    if returned_tin and returned_tin != identity["tin"]:
        raise SoliqUpstreamError("Soliq returned a different company identity")

    return {
        **identity,
        "type": "full",
        "registry": _public_registry_payload(payload),
        "location": _registry_location(payload),
    }
