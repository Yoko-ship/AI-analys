"""A successful HTTP response may contain only a partial collection publication."""
from types import SimpleNamespace
import pytest
import requests
from fastapi.testclient import TestClient
import api
import collectors.financials.delivery as delivery
import collectors.news.delivery as news_delivery
import server.ingestion.routes as ingestion
from collection_ops.model import parse_receipts

@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("ADMIN_API_SECRET", "private-collection-secret")

def response(body, status=200):
    return SimpleNamespace(status_code=status, json=lambda: body, text="private-collection-secret")

def test_publication_receipt_preserves_server_counts_without_exposing_payload(secret, monkeypatch, capsys):
    monkeypatch.setattr(delivery.requests, "post", lambda *a, **kw: response({"ok": True, "upserted": 5, "history": 22}))
    assert delivery._post("/api/admin/quotes", {"rows": [{"private": "do not log"}]}) == 0
    output = capsys.readouterr().out
    receipt = parse_receipts(output.splitlines())[0]
    assert receipt["counts"] == {"upserted": 5, "history": 22}
    assert receipt["ok"]
    assert "do not log" not in output

@pytest.mark.parametrize("transport", ["financials", "news"])
def test_http_and_connection_failures_record_the_stage(secret, monkeypatch, capsys, transport):
    module = delivery if transport == "financials" else news_delivery
    call = (lambda: delivery._post("/api/admin/quotes", {"rows": []})) if transport == "financials" else (lambda: news_delivery.push_news([]))
    monkeypatch.setattr(module.requests, "post", lambda *a, **kw: response({}, 503))
    assert call() == 1
    receipt = parse_receipts(capsys.readouterr().out.splitlines())[-1]
    assert receipt["ok"] is False and "HTTP 503" in receipt["reason"]
    def fail(*args, **kwargs):
        raise requests.Timeout("timed out private-collection-secret")
    monkeypatch.setattr(module.requests, "post", fail)
    with pytest.raises(requests.Timeout):
        call()
    output = capsys.readouterr().out
    assert "private-collection-secret" not in output
    assert "Timeout" in parse_receipts(output.splitlines())[-1]["reason"]

def test_partial_server_response_marks_run_failed_but_keeps_acknowledged_writes(secret, monkeypatch, capsys):
    monkeypatch.setattr(delivery.requests, "post", lambda *a, **kw: response({
        "ok": True, "upserted": 10, "history": 0,
        "errors": [{"stage": "quote_history", "reason": "RuntimeError: history store unavailable"}]}))
    assert delivery._post("/api/admin/quotes", {"rows": [], "history": [{}]}) == 1
    events = parse_receipts(capsys.readouterr().out.splitlines())
    assert any(event["ok"] and event["counts"]["upserted"] == 10 for event in events)
    assert events[-1]["stage"] == "quote_history" and not events[-1]["ok"]

def test_quote_history_failure_is_returned_to_the_collector(secret, monkeypatch):
    monkeypatch.setattr(ingestion.catalogue_market_store, "bulk_upsert_quotes", lambda rows: 1)
    monkeypatch.setattr(ingestion.catalogue_market_store, "bulk_upsert_intraday_history", lambda rows: 1)
    monkeypatch.setattr(ingestion.audit_jobs, "_schedule_audit", lambda *a: None)
    def fail(rows):
        raise RuntimeError("history store unavailable")
    monkeypatch.setattr(ingestion.catalogue_market_store, "bulk_upsert_quote_history", fail)
    result = TestClient(api.app).post("/api/admin/quotes",
        headers={"X-Admin-Secret": "private-collection-secret"}, json={
            "rows": [{"ticker": "MIQE", "isin": "UZ7007440009", "close_price": 2401, "trade_date": "20260911"}],
            "history": [{"isin": "UZ7007440009", "trade_date": "20260911", "close_price": 2401}]})
    assert result.status_code == 200  # The board write is retained.
    assert result.json()["upserted"] == 1
    assert result.json()["errors"] == [{"stage": "quote_history", "reason": "RuntimeError: history store unavailable"}]

def test_ratio_failure_also_reports_partial_publication(secret, monkeypatch):
    monkeypatch.setattr(ingestion.catalogue_financial_store, "bulk_upsert_financials", lambda *a: 1)
    monkeypatch.setattr(ingestion.audit_jobs, "_schedule_audit", lambda *a: None)
    def fail(*args):
        raise RuntimeError("ratio store unavailable")
    monkeypatch.setattr(ingestion.catalogue_financial_store, "upsert_ratio_cache", fail)
    result = TestClient(api.app).post("/api/admin/financials",
        headers={"X-Admin-Secret": "private-collection-secret"}, json={"rows": [],
            "ratios": [{"ticker": "CBSK", "year": 2026, "quarter": 2, "debt_to_equity": 0.21}]})
    assert result.status_code == 200
    assert result.json()["errors"] == [{"stage": "financial_ratios", "reason": "RuntimeError: ratio store unavailable"}]
