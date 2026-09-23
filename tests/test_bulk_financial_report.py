"""Bulk manifests expose missing evidence without modifying published state."""
import json

import pytest

import reports_catalog as rc
from financial_ingestion import bulk_report, store


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("FINANCIAL_SOURCE_POLICY", "openinfo")
    monkeypatch.setattr(bulk_report.extract, "processor_version", lambda: "current")
    with store.transaction() as c:
        for ticker, org in (("BANK", "1"), ("BANKP", "1"), ("EMPTY", "2"), ("UNKNOWN", None)):
            c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)", (ticker, ticker, org))
        c.execute("INSERT INTO ingest_sources VALUES ('s','1','BANK','https://openinfo.uz/media/a.pdf','MSFO','{}','now','now',0,'v')")
        c.execute("INSERT INTO ingest_artifacts VALUES('sha','sha.pdf',1,'application/pdf','now')")
        c.execute("INSERT INTO ingest_versions VALUES('v','s','sha','{}','now')")
    return tmp_path


def candidate(identifier, year, *, scope="separate", processor="current", approved=False):
    payload = {"classification": {"standard": "MSFO", "scope": scope,
                "period_start": f"{year}-01-01", "period_end": f"{year}-12-31"},
               "figures": {"net_income": {"raw_value": "0"}, "interest_income": {"raw_value": "10"}}}
    with store.transaction() as c:
        c.execute("INSERT INTO ingest_candidates VALUES(?,?,?,?,?,?)", (
            identifier, "v", processor, json.dumps(payload),
            json.dumps({"valid": False, "errors": ["ISSUER_EVIDENCE_MISSING"]}), "now"))
        if approved:
            c.execute("INSERT INTO ingest_reviews VALUES(?,?,?,?,?,?)", (
                "review-" + identifier, identifier, "reviewer", "APPROVED", "test", "now"))


def test_sibling_selection_and_missing_evidence(catalog):
    candidate("draft", 2023)
    report = bulk_report.build_report(["bankp"])
    assert len(report["issuers"]) == 1
    issuer = report["issuers"][0]
    assert issuer["ticker"] == "BANK"
    assert issuer["tickers"] == ["BANK", "BANKP"]
    entry = issuer["sources"][0]["candidates"][0]
    assert "net_income" not in entry["missing_fields"]  # Reported zero is evidence.
    assert "total_assets" in entry["missing_fields"]
    assert "interest_expense" in entry["missing_fields"]
    assert entry["review_state"] == "UNREVIEWED"
    assert entry["validation_errors"] == ["ISSUER_EVIDENCE_MISSING"]
    assert report["publication_performed"] is False
    assert bulk_report.build_report([])["issuers"] == []
    assert bulk_report.build_report(["NOTREAL"])["unknown_tickers"] == ["NOTREAL"]


def test_current_parser_and_reviewed_proposals_remain_distinct(catalog):
    candidate("old", 2018, processor="old")
    candidate("new", 2021)
    candidate("reviewed", 2023, processor="reviewed-proposal-v1", approved=True)
    report = bulk_report.build_report(["BANK"])
    entries = report["issuers"][0]["sources"][0]["candidates"]
    assert {r["candidate_id"] for r in entries} == {"new", "reviewed"}
    reviewed = next(r for r in entries if r["candidate_id"] == "reviewed")
    assert reviewed["approved_unpublished"] is True
    assert reviewed["current_processor"] is False
    assert reviewed["reviewed_proposal"] is True
    ranges = report["issuers"][0]["candidate_annual_ranges"]
    assert ranges[0]["missing_years"] == [2022]
    assert report["summary"]["approved_unpublished"] == 1
    c = store.connect()
    try:
        assert c.execute("SELECT COUNT(*) FROM ingest_heads").fetchone()[0] == 0
    finally:
        c.close()


def test_gaps_never_mix_scopes_or_infer_before_first_observation(catalog):
    candidate("a", 2020)
    candidate("b", 2022)
    candidate("c", 2021, scope="consolidated")
    issuer = bulk_report.build_report(["BANK"])["issuers"][0]
    ranges = {r["scope"]: r for r in issuer["candidate_annual_ranges"]}
    assert ranges["separate"]["missing_years"] == [2021]
    assert ranges["consolidated"]["missing_years"] == []
    assert ranges["separate"]["observed_start"] == 2020
    assert issuer["published_annual_ranges"] == []


def test_missing_sources_candidates_and_failure_urls(catalog):
    with store.transaction() as c:
        store.enqueue(c, "s", "FETCH", "download")
        c.execute("UPDATE ingest_jobs SET state='FAILED',error='HTTP 503'")
        c.execute("INSERT INTO ingest_disclosures VALUES('d','1','BANK','/reports/bank/annual/1/',0,0,'[]','bad attachment')")
    report = bulk_report.build_report()
    issuers = {r["ticker"]: r for r in report["issuers"]}
    assert issuers["EMPTY"]["no_sources"] is True
    assert issuers["UNKNOWN"]["unresolved_issuer"] is True
    source = issuers["BANK"]["sources"][0]
    assert source["no_candidates"] is True
    assert source["no_current_candidates"] is True
    assert source["failures"][0]["url"] == source["url"]
    assert issuers["BANK"]["discovery_errors"][0]["url"].endswith("/reports/bank/annual/1/")
    assert report["summary"]["failed_jobs"] == 1
    assert report["summary"]["issuers"] == 3
