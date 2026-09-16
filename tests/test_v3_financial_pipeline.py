"""Acceptance tests for the immutable UZStock V3 financial ledger."""
from __future__ import annotations

import sqlite3

import pytest

import v3_financial_pipeline as v3


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))


def _document(issuer: str, token: str, start: str, end: str):
    return v3.add_document(
        issuer_id=issuer, source_url=f"https://openinfo.test/{token}", original=token.encode(),
        standard="NSBU", period_start=start, period_end=end, period_resolution="EXPLICIT_FILE",
        parser_version="nsbu-v3-test",
    )


def _facts(document, start: str, end: str, revenue: str, income: str, assets: str, equity: str):
    return v3.record_facts(document["id"], [
        {"statement": "form2", "line_code": "010", "normalized_key": "revenue", "value": revenue, "period_start": start, "period_end": end, "page": 2, "cell": "D10"},
        {"statement": "form2", "line_code": "270", "normalized_key": "net_income", "value": income, "period_start": start, "period_end": end, "page": 2, "cell": "D27"},
        {"statement": "form1", "line_code": "400", "normalized_key": "total_assets", "value": assets, "period_start": start, "period_end": end, "page": 1, "cell": "D40"},
        {"statement": "form1", "line_code": "500", "normalized_key": "equity", "value": equity, "period_start": start, "period_end": end, "page": 1, "cell": "D50"},
    ])


def test_reconciliation_groups_conflicting_uqeq_rows_into_one_evidenced_incident():
    v3.upsert_issuer(issuer_id="uqeq", name="UQEQ")
    first = _document("uqeq", "uqeq-q2-a", "2026-01-01", "2026-06-30")
    second = _document("uqeq", "uqeq-q2-b", "2026-01-01", "2026-06-30")
    _facts(first, "2026-01-01", "2026-06-30", "100", "10", "300", "200")
    _facts(second, "2026-01-01", "2026-06-30", "120", "10", "300", "200")

    checked = v3.reconcile_document(second["id"])

    assert checked["quality"] == "CONFLICT"
    conflict = next(v3.incident(item) for item in checked["incidents"] if v3.incident(item)["code"] == "VALUE_CONFLICT")
    assert conflict["evidence"]["line_code"] == "010"
    assert len(conflict["facts"]) == 2
    assert {item["page"] for item in conflict["facts"]} == {2}


def test_calculation_uses_decimal_ltm_average_balance_and_idempotent_publication():
    v3.upsert_issuer(issuer_id="issuer", name="Issuer")
    annual = _document("issuer", "annual", "2025-01-01", "2025-12-31")
    prior = _document("issuer", "prior", "2025-01-01", "2025-06-30")
    current = _document("issuer", "current", "2026-01-01", "2026-06-30")
    _facts(annual, "2025-01-01", "2025-12-31", "1000", "100", "900", "600")
    _facts(prior, "2025-01-01", "2025-06-30", "400", "40", "800", "550")
    _facts(current, "2026-01-01", "2026-06-30", "600", "60", "1000", "700")
    v3.set_security_class(issuer_id="issuer", class_id="ordinary", ticker="TEST", isin="UZ000", share_type="ordinary", price="10", shares_outstanding="50")

    rows = {row["metric"]: row for row in v3.calculate_issuer("issuer", "2026-06-30")}

    assert rows["market_cap"]["value"] == "500"
    assert rows["pe"]["value"] == "4.166666666666666666666666667"  # 500 / (100 + 60 - 40)
    assert rows["roe"]["value"] == "0.1846153846153846153846153846"  # 120 / average(600, 700)
    snapshot = v3.issuer_snapshot("issuer")
    assert snapshot["publication"]["status"] == "PUBLISHED"
    assert all(isinstance(row["value"], (str, type(None))) for row in rows.values())

    # Retrying an identical job cannot advance the public pointer.
    v3.calculate_issuer("issuer", "2026-06-30")
    assert v3.issuer_snapshot("issuer")["publication"]["id"] == snapshot["publication"]["id"]


def test_source_and_fact_records_cannot_be_rewritten():
    v3.upsert_issuer(issuer_id="immutable", name="Immutable")
    doc = _document("immutable", "immutable", "2026-01-01", "2026-06-30")
    facts = _facts(doc, "2026-01-01", "2026-06-30", "10", "1", "20", "15")
    conn = v3._connection()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE v3_documents SET title='changed' WHERE id=?", (doc["id"],))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM v3_facts WHERE id=?", (facts[0]["id"],))
    finally:
        conn.close()


def test_period_is_resolved_from_filing_content_before_publication_metadata():
    assert v3.resolve_period(
        explicit=("2026-01-01", "2026-06-30"),
        form_header=("2026-01-01", "2026-03-31"),
        publication_metadata=("2026-01-01", "2026-09-30"),
    ) == {"period_start": "2026-01-01", "period_end": "2026-06-30", "period_resolution": "EXPLICIT_FILE"}
    assert v3.resolve_period() == {"period_start": None, "period_end": None, "period_resolution": "NEEDS_REVIEW"}
