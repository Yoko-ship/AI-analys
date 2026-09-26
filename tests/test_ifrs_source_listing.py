"""Direct filing discovery preserves documents hidden by period collisions."""
import json

import pytest

import reports_catalog as rc
import catalogue.financial_store as catalogue_financial_store
import catalogue.snapshots as catalogue_snapshots
import catalogue.sources as catalogue_sources
import catalogue.sync as catalogue_sync
from financial_ingestion import extract, store


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("FINANCIAL_SOURCE_POLICY", "openinfo")
    monkeypatch.setattr(catalogue_financial_store, "_maybe_seed_financials", lambda *args: None)
    monkeypatch.setattr(extract, "processor_version", lambda: "listing-test")
    monkeypatch.setattr(catalogue_sources, "_make_session", lambda: object())
    monkeypatch.setattr(catalogue_sources, "_json_get", lambda *args, **kwargs: [])
    monkeypatch.setattr(catalogue_sources, "_unified_pdf_id_map", lambda *args: {})


def filing(identifier, *, org=23, form="MSFO", url=None):
    return {
        "id": identifier, "object_id": identifier, "organization": org,
        "report_type": form, "pub_date": "2025-05-01",
        "pdf_url": url or f"https://openinfo.uz/media/msfo/{identifier}.pdf",
        "properties": {"org_type": "bank", "report_type": "annual",
                       "reporting_year": 2024, "report_title": "Annual statements 2024"},
    }


def test_sync_preserves_same_period_distinct_pdfs_and_is_idempotent(catalog, monkeypatch):
    records = [filing("separate"), filing("group"), filing("revision")]
    monkeypatch.setattr(catalogue_sources, "_fetch_main_results", lambda *args: (records, "bank"))
    for _ in range(2):
        result = catalogue_sync.sync_company("TSTB", "Test bank", force=True, org_id="23")
        assert not result["errors"]
    c = store.connect()
    try:
        assert c.execute("SELECT COUNT(*) FROM catalog_reports").fetchone()[0] == 1
        sources = c.execute("SELECT * FROM ingest_sources").fetchall()
        assert {s["url"] for s in sources} == {r["pdf_url"] for r in records}
        assert {json.loads(s["metadata_json"])["id"] for s in sources} == {
            "separate", "group", "revision"}
        assert c.execute("SELECT COUNT(*) FROM ingest_jobs").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM ingest_heads").fetchone()[0] == 0
    finally:
        c.close()


def test_source_listing_filters_issuer_form_and_source_policy(catalog):
    records = [filing("audit", form="Audition"), filing("other", org=99),
               filing("national", form="NSBU"),
               filing("external", url="https://issuer.example/media/report.pdf")]
    assert catalogue_snapshots._remember_ifrs_sources(ticker="TSTB", org_id="23", records=records) == 1
    c = store.connect()
    try:
        sources = c.execute("SELECT * FROM ingest_sources").fetchall()
        assert len(sources) == 1
        assert sources[0]["url"] == records[0]["pdf_url"]
        assert sources[0]["category"] == "Audition"
    finally:
        c.close()
