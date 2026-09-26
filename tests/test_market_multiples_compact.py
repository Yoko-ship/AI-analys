"""The board must not download a full issuer ledger for each visible cell."""
from __future__ import annotations

import server.market.valuations as subject_server_market_valuations

import api


def test_board_multiples_payload_keeps_screen_values_and_audit_context() -> None:
    payload = {
        "ok": True,
        "count": 1,
        "issuers": 1,
        "contract_version": "test",
        "input_snapshot": "snapshot",
        "by_issuer": {"issuer": {"large": "ledger"}},
        "items": [{
            "ticker": "TEST",
            "market_input": {"internal": "not for the board"},
            "market_cap_issuer": {"class_inputs": ["large"]},
            "pe": {"value": 7.2, "status": "ok", "base_period": "2026Q2",
                   "inputs": {"net_income": 1}, "calculation_snapshot": "private"},
            "pb": {"value": None, "status": "audit_blocked",
                   "reasons": ["source mismatch"], "note": "withheld"},
            "ps": {"value": 1.3, "status": "ok"},
            "roe": {"value": 11.0, "status": "ok"},
            "roa": {"value": 3.0, "status": "ok"},
            "net_margin": {"value": 5.0, "status": "ok"},
            "equity_assets": {"value": 41.0, "status": "ok"},
        }],
    }

    compact = subject_server_market_valuations._board_multiples_payload(payload)

    assert "by_issuer" not in compact
    assert compact["items"] == [{
        "ticker": "TEST",
        "pe": {"value": 7.2, "status": "ok", "base_period": "2026Q2"},
        "pb": {"value": None, "status": "audit_blocked",
               "reasons": ["source mismatch"], "note": "withheld"},
        "ps": {"value": 1.3, "status": "ok"},
        "roe": {"value": 11.0, "status": "ok"},
        "roa": {"value": 3.0, "status": "ok"},
        "net_margin": {"value": 5.0, "status": "ok"},
        "equity_assets": {"value": 41.0, "status": "ok"},
    }]
