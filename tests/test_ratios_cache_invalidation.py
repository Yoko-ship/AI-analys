"""The market-wide ratios memo must never outlive a write to its sources.

/api/market/multiples reads ratios through a short memo; a corrected ratio has
to reach the next request, not the one a minute later.
"""
from __future__ import annotations

import reports_catalog as rc
import catalogue.financial_store as catalogue_financial_store
import catalogue.ratios as catalogue_ratios
import catalogue.storage as catalogue_storage


def test_a_ratio_write_drops_the_memo(tmp_path, monkeypatch):
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    calls = []
    monkeypatch.setattr(catalogue_ratios, "get_all_ratios", lambda: calls.append(1) or {"ACME": {"roe": len(calls)}})
    catalogue_ratios.invalidate_ratios_cache()

    assert catalogue_ratios.get_all_ratios_cached()["ACME"]["roe"] == 1
    assert catalogue_ratios.get_all_ratios_cached()["ACME"]["roe"] == 1   # served from the memo
    assert len(calls) == 1

    catalogue_financial_store.upsert_ratio_cache("ACME", "NSBU", 2025, 0, {"ROE": 12.0})

    assert catalogue_ratios.get_all_ratios_cached()["ACME"]["roe"] == 2   # re-read after the write
    catalogue_ratios.invalidate_ratios_cache()
