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


def test_board_multiples_payload_names_the_class_that_blocks_the_issuer_cap() -> None:
    # AGMKP trades; the ordinary AGMK never has. The board must carry enough of
    # the issuer-cap gap for the cell to read «нет торгов AGMK», not a bare
    # «нет капитализации» beside AGMKP's own visible market cap.
    agmk = {"ticker": "AGMK", "price": 3914.0, "price_as_of": None, "price_age_days": None,
            "max_price_age_days": 90, "limitation_reason": "verified class price is unavailable",
            "usable_for_issuer_cap": False, "market_cap": None, "shares_outstanding": 708620381.0}
    agmkp = {"ticker": "AGMKP", "price": 31850.0, "price_as_of": "2026-10-08", "price_age_days": 0,
             "max_price_age_days": 90, "limitation_reason": None,
             "usable_for_issuer_cap": True, "market_cap": 284344131200.0}
    payload = {"items": [{
        "ticker": "AGMKP",
        "market_cap_issuer": {"value": None, "status": "incomplete", "missing_classes": ["AGMK"],
                              "class_inputs": [agmk, agmkp], "calculation_snapshot": "private"},
        "pe": {"value": None, "status": "no_market_cap"},
    }]}

    row = subject_server_market_valuations._board_multiples_payload(payload)["items"][0]

    assert row["market_cap_issuer"] == {
        "status": "incomplete",
        "missing_classes": ["AGMK"],
        "class_inputs": [
            {k: agmk[k] for k in ("ticker", "price_as_of", "price_age_days", "max_price_age_days",
                                  "limitation_reason", "usable_for_issuer_cap", "market_cap")},
            {k: agmkp[k] for k in ("ticker", "price_as_of", "price_age_days", "max_price_age_days",
                                   "limitation_reason", "usable_for_issuer_cap", "market_cap")},
        ],
    }
