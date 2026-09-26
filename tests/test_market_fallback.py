"""Production collection survives an exchange outage without publishing partial data."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from collectors.openinfo import market_fallback as archive
from collectors.financials import trading, market, delivery, retry
import trade_stats as ts
import uzse_quotes as uq

ISIN = "UZ7001100005"
DAY = "20260925"


def execution(**over):
    return {"isin_code": ISIN, "trade_datetime": "2026-09-25T10:00:01.123000",
            "market_id": "STK", "board_id": "G1", "trade_price": 10,
            "trade_quantity": 2, "trading_value": 20, **over}


def conclusion(**over):
    return {"date": "2026-09-25", "open": 10, "close": 10, "high": 10, "low": 10,
            "change": 1, "trading_volume": 4, "trading_value": 40, **over}


@pytest.fixture
def source(monkeypatch):
    # Two genuinely separate executions with identical visible fields, over
    # two pages. Neither deduplication nor half a download may turn four shares
    # into two. Production uses the server-reported page size in the same way.
    state = {"trades": [execution(), execution()], "conclusions": [conclusion()],
             "calls": [], "mutate": lambda payload, params: payload}

    def get(client, path, params):
        state["calls"].append((path, params))
        if path.endswith("conclusions/"):
            return {"ticker": "KFSK", "name": "Kafolat", "results": deepcopy(state["conclusions"])}
        if "start_date" not in params:
            return {"results": [state["trades"][0]]}
        page = params["page"]
        payload = {"count": 2, "total_pages": 2, "page_size": 1, "current_page": page,
                   "has_next": page < 2, "results": deepcopy(state["trades"][page - 1:page])}
        return state["mutate"](payload, params)

    monkeypatch.setattr(archive, "_json_get", get)
    return state


def test_complete_fallback_preserves_identical_executions_and_official_closes(source):
    data = archive.fetch_latest_trade_stats(session=object())
    assert data["complete"] and data["source"] == "openinfo"
    row = data["stats"][ISIN]
    assert (row["trade_count"], row["total_qty"], row["total_value"]) == (2, 4, 40)
    assert (row["open_price"], row["close_price"]) == (10, 10)
    assert data["quotes"][0]["history"][0]["quantity"] == 4
    assert data["intraday"] == []  # tied executions have no reliable hourly order


@pytest.mark.parametrize("problem", ["short", "wrong_count", "wrong_page", "broken_page",
                                    "wrong_day", "no_board", "nan", "lagging_quote", "short_quote"])
def test_incomplete_or_inconsistent_archive_never_exposes_publishable_rows(source, problem):
    def mutate(payload, params):
        if params["page"] == 2:
            if problem == "short":
                payload["results"] = []
            elif problem == "wrong_count":
                payload["count"] = 3
            elif problem == "wrong_page":
                payload["current_page"] = 1
            elif problem == "broken_page":
                raise ConnectionError("upstream unavailable")
        return payload

    source["mutate"] = mutate
    if problem == "wrong_day":
        source["trades"][1]["trade_datetime"] = "2026-09-24T10:00:00"
    elif problem == "no_board":
        source["trades"][1]["board_id"] = None
    elif problem == "nan":
        source["trades"][1]["trade_quantity"] = "NaN"
    elif problem == "lagging_quote":
        source["conclusions"][0]["date"] = "2026-09-24"
    elif problem == "short_quote":
        source["conclusions"][0]["trading_volume"] = 2
    result = archive.fetch_latest_trade_stats(session=object())
    assert not result["complete"]
    assert result["stats"] == {} and result["intraday"] == []


def test_archive_cannot_roll_back_a_newer_partial_exchange_session(source):
    assert not archive.fetch_latest_trade_stats(min_day="20260926", session=object())["complete"]


def test_archive_page_budget_is_enforced(source):
    assert not archive.fetch_latest_trade_stats(max_pages=1, session=object())["complete"]


def test_growing_archive_session_is_refused(source):
    first_reads = []

    def mutate(payload, params):
        if params["page"] == 1:
            first_reads.append(1)
            if len(first_reads) > 1:
                payload["count"] = 3
        return payload

    source["mutate"] = mutate
    assert not archive.fetch_latest_trade_stats(session=object())["complete"]


def test_negotiated_trade_does_not_change_auction_totals(source):
    source["trades"][1].update(board_id="T1", trade_price=5, trade_quantity=200, trading_value=1000)
    source["conclusions"][0].update(trading_volume=2, trading_value=20)
    row = archive.fetch_latest_trade_stats(session=object())["stats"][ISIN]
    assert (row["total_qty"], row["total_value"], row["block_qty"]) == (2, 20, 200)


def test_historical_zero_placeholder_does_not_hide_latest_valid_quote(source):
    source["conclusions"].append(conclusion(date="2026-04-21", close=0))
    quote = archive.fetch_quotes([(ISIN, "STK")], session=object())[0]
    assert quote["close_price"] == 10 and len(quote["history"]) == 1


def test_quiet_security_keeps_its_actual_trading_date(source):
    source["conclusions"] = [conclusion(trading_volume=0, trading_value=0),
                             conclusion(date="2026-09-24", close=9, change=2)]
    quote = archive.fetch_quotes([(ISIN, "STK")], session=object())[0]
    assert quote["trade_date"] == "20260924" and quote["prev_close"] == 7


@pytest.mark.parametrize("stamp,expected", [
    ("2026-09-25T10:15:00.100000", (DAY, 10)),
    ("2026-09-25T05:15:00+00:00", (DAY, 10)),
    ("2026-09-24T10:15:00", None), ("not-a-time", None),
])
def test_archive_timestamp_uses_exchange_local_day(stamp, expected):
    moment = ts.trade_moment({"trade_datetime": stamp, "trade_date": DAY})
    assert (moment[:2] if moment else None) == expected


@pytest.mark.parametrize("available", [True, False])
def test_scheduled_collector_publishes_only_a_complete_fallback(monkeypatch, source, available):
    data = archive.fetch_latest_trade_stats(session=object())
    monkeypatch.setattr(ts, "fetch_trade_stats", lambda: {"complete": False, "reachable": False})
    monkeypatch.setattr(archive, "fetch_latest_trade_stats", lambda **kw: data if available else {})
    monkeypatch.setattr(retry, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(market, "board_securities", lambda: [{"isin": ISIN, "_market": "STK"}])
    monkeypatch.setattr(market, "audit_board", lambda: 0)
    monkeypatch.setattr(market, "SKIP_QUOTES", False)
    def forbidden(*args, **kwargs):
        raise AssertionError("fallback must not crawl the unavailable exchange quote pages")
    monkeypatch.setattr(uq, "fetch_session_quotes", forbidden)
    monkeypatch.setattr(delivery, "_stamp_step", lambda *args: None)
    pushed = []
    monkeypatch.setattr(delivery, "_post", lambda path, body: pushed.append((path, body)) or 0)
    assert trading.push_trade_stats() == (0 if available else 1)
    if available:
        assert [p for p, _ in pushed] == ["/api/admin/trade-stats", "/api/admin/quotes"]
        assert pushed[1][1]["rows"][0]["close_price"] == 10
        assert pushed[1][1]["history"][0]["trade_date"] == DAY
    else:
        assert pushed == []


def test_failure_to_obtain_current_archive_quote_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(market, "board_securities", list)
    monkeypatch.setattr(archive, "fetch_quotes", lambda targets: [])
    monkeypatch.setattr(delivery, "_post", lambda *args: pytest.fail("must not publish stale quotes"))
    assert market.push_quotes({ISIN: {"trade_date": DAY, "trade_count": 1}}, source="openinfo") == 1


@pytest.mark.parametrize("payload", [{"error": "unavailable"}, {"results": {"error": "unavailable"}}])
def test_exchange_error_payload_is_not_an_empty_successful_session(monkeypatch, payload):
    monkeypatch.setattr(ts.time, "sleep", lambda seconds: None)
    session = SimpleNamespace(get=lambda *a, **kw: SimpleNamespace(json=lambda: payload))
    result = ts.fetch_trade_stats(session=session)
    assert not result["reachable"] and not result["complete"]


def test_archive_daily_range_must_agree_with_the_executions(source):
    source["conclusions"][0]["high"] = 50
    assert not archive.fetch_latest_trade_stats(session=object())["complete"]
