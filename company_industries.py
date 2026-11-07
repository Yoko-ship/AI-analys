"""Curated display hierarchy shared with the frontend; not a valuation classifier.

Only explicit ticker memberships join share classes. Source/profile assignments
remain distinguishable from checked codes and conflicting disclosures.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def registry():
    data = json.loads((Path(__file__).parent / "config/company_industries.json").read_text(encoding="utf-8"))
    seen = set()
    for group in data["groups"].values():
        assert group["sector"] in data["sections"], "Unknown industry section"
    for issuer in data["issuers"]:
        assert issuer["group"] in data["groups"], "Unknown industry subgroup"
        assert issuer["id"] in issuer["tickers"], "Missing issuer's primary ticker"
        assert issuer["status"] in {"documented", "inferred", "verified", "conflict"}
        for ticker in issuer["tickers"]:
            assert ticker and ticker == ticker.upper() and ticker not in seen, "Duplicate/invalid ticker"
            seen.add(ticker)
    for alias, ticker in data.get("aliases", {}).items():
        assert alias not in seen and ticker in seen, "Invalid issuer alias"
    return data


@lru_cache(maxsize=1)
def _index():
    data = registry()
    result = {}
    for issuer in data["issuers"]:
        sector = data["groups"][issuer["group"]]["sector"]
        classification = {**issuer, "issuer_id": issuer["id"], "sector": sector,
                          "section": data["sections"][sector]["code"],
                          "source": data["source"], "reviewed_on": data["reviewed_on"]}
        for ticker in issuer["tickers"]:
            result[ticker] = classification
    for alias, ticker in data.get("aliases", {}).items():
        result[alias] = result[ticker]
    return result


def classification_for(ticker):
    return deepcopy(_index().get(str(ticker or "").strip().upper()))


def display_sector(ticker, fallback=None):
    item = _index().get(str(ticker or "").strip().upper())
    return item["sector"] if item else fallback
