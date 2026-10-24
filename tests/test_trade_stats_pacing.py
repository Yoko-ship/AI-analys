"""The exchange feed must be walked slowly enough to finish a busy session."""
from __future__ import annotations

import trade_stats as ts


class _Response:
    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return {"results": self.rows}


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, _url, *, headers, params, timeout):
        assert headers["Accept"] == "application/json"
        assert timeout == 30
        self.calls.append(params["page"])
        if params["page"] == 1:
            return _Response([{
                "id": "first", "issue_code": "UZ7011340005", "trade_date": "20260911",
                "trade_price": "100", "trade_quantity": "5", "trading_value": "500",
            }])
        return _Response([])


def test_latest_day_walk_pauses_between_pages(monkeypatch):
    waits = []
    monkeypatch.setattr(ts.time, "sleep", waits.append)
    session = _Session()
    result = ts.fetch_trade_stats(session=session)

    assert result["complete"] is True
    assert result["count"] == 1
    assert session.calls == [1, 2]
    assert waits == [0.5]
