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
    bar, = data["intraday"]  # identical tied executions: one bar, both counted
    assert (bar["hour"], bar["open"], bar["close"], bar["quantity"]) == (10, 10, 10, 4)


@pytest.mark.parametrize("problem", ["short", "wrong_count", "wrong_page", "broken_page",
                                    "wrong_day", "no_board", "nan", "lagging_quote", "short_quote"])
def test_incomplete_or_inconsistent_archive_never_exposes_publishable_rows(source, problem, monkeypatch):
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
        # No conclusions yet for a session still trading: nothing to publish.
        source["conclusions"][0]["date"] = "2026-09-24"
        monkeypatch.setattr(archive, "_session_finished", lambda day: False)
    elif problem == "short_quote":
        source["conclusions"][0]["trading_volume"] = 2
    result = archive.fetch_latest_trade_stats(session=object())
    assert not result["complete"]
    assert result["stats"] == {} and result["intraday"] == []


def test_a_finished_session_without_conclusions_is_published_provisionally(source):
    """openinfo posts conclusions overnight; the executions are whole at 16:02."""
    source["trades"] = [execution(trade_datetime="2026-09-25T10:00:01.100000", trade_price=10),
                        execution(trade_datetime="2026-09-25T15:59:59.500000", trade_price=12)]
    source["conclusions"] = [conclusion(date="2026-09-24", close=9, change=-1,
                                        trading_volume=3, trading_value=27)]
    data = archive.fetch_latest_trade_stats(session=object())
    assert data["complete"] and data["provisional"]
    quote, = data["quotes"]
    assert (quote["trade_date"], quote["open_price"], quote["close_price"]) == (DAY, 10, 12)
    assert (quote["prev_close"], quote["change_value"], quote["quantity"], quote["turnover"]) == (9, 3, 4, 40)
    assert [h["date"] for h in quote["history"]] == ["20260924", DAY]


@pytest.mark.parametrize("before, tied, close", [
    (4176, [3889, 3903.02, 3906.67, 3905], 3889),   # YRFS 06.10: a sell sweep ends lowest
    (11500, [11070, 11080, 11100, 11110], 11070),   # UZIR 06.10
    (107800, [107800, 108027.65], 108027.65),       # ACMT2B5 06.10: a buy sweep ends highest
])
def test_a_sweep_closes_at_the_level_furthest_from_the_trade_before(source, before, tied, close):
    stamp = "2026-09-25T15:05:39.964000"
    source["trades"] = [execution(trade_datetime="2026-09-25T14:39:51.532000", trade_price=before)] + [
        execution(trade_datetime=stamp, trade_price=p) for p in tied]
    source["conclusions"] = [conclusion(date="2026-09-24")]
    source["mutate"] = lambda payload, params: dict(
        payload, count=len(source["trades"]), total_pages=1, page_size=1000, has_next=False,
        results=deepcopy(source["trades"]))
    quote, = archive.fetch_latest_trade_stats(session=object())["quotes"]
    assert quote["close_price"] == close


def test_a_sweep_opens_at_the_level_nearest_the_previous_close(source):
    stamp = "2026-09-25T10:00:18.808000"
    source["trades"] = [execution(trade_datetime=stamp, trade_price=102500),
                        execution(trade_datetime=stamp, trade_price=104505)]
    source["conclusions"] = [conclusion(date="2026-09-24", close=106999)]
    quote, = archive.fetch_latest_trade_stats(session=object())["quotes"]
    assert quote["open_price"] == 104505


def test_conclusions_for_some_securities_only_are_still_refused(monkeypatch):
    other = "UZ7002200006"
    trades = [execution(), execution(isin_code=other)]

    def get(client, path, params):
        if path.endswith("conclusions/"):
            day = "2026-09-25" if params["isu_cd"] == ISIN else "2026-09-24"
            return {"results": [conclusion(date=day, trading_volume=2, trading_value=20)]}
        if "start_date" not in params:
            return {"results": [trades[0]]}
        return {"count": 2, "total_pages": 1, "page_size": 1000, "current_page": 1,
                "has_next": False, "results": deepcopy(trades)}

    monkeypatch.setattr(archive, "_json_get", get)
    assert not archive.fetch_latest_trade_stats(session=object())["complete"]


def test_repo_deals_are_skipped_not_taken_for_a_corrupt_session(source):
    """Two REPO deals (market RPO) on 28.09 made the fallback refuse the whole
    session, so the board kept 25.09 and every change read 0 %."""
    source["trades"].append(execution(market_id="RPO", board_id="R1",
                                      isin_code="IQMK3B5XX030"))

    def mutate(payload, params):
        payload.update(count=3, total_pages=3)
        payload["has_next"] = params["page"] < 3
        return payload

    source["mutate"] = mutate
    data = archive.fetch_latest_trade_stats(session=object())
    assert data["complete"]
    assert set(data["stats"]) == {ISIN}
    assert data["stats"][ISIN]["total_qty"] == 4


def test_execution_with_no_market_is_still_refused(source):
    source["trades"][1]["market_id"] = None
    assert not archive.fetch_latest_trade_stats(session=object())["complete"]


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
        assert [p for p, _ in pushed] == ["/api/admin/trade-stats", "/api/admin/quotes",
                                          "/api/admin/quotes"]
        assert pushed[1][1]["intraday"][0]["quantity"] == 4  # the hourly bars
        assert pushed[2][1]["rows"][0]["close_price"] == 10
        assert pushed[2][1]["history"][0]["trade_date"] == DAY
    else:
        assert pushed == []


def test_failure_to_obtain_current_archive_quote_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(market, "board_securities", list)
    monkeypatch.setattr(archive, "fetch_quotes", lambda targets, **kw: [])
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


def test_a_pinned_older_session_is_read_even_after_a_newer_one_started(source):
    """28.09 for a test while 29.09 was still being written: the pin reads the
    finished session and quotes it as of its own day."""
    data = archive.fetch_latest_trade_stats(session=object(), session_day="2026-09-25")
    assert data["complete"] and data["trade_date"] == DAY
    trade_calls = [p for path, p in source["calls"] if "start_date" in p and not path.endswith("conclusions/")]
    assert trade_calls and all(p["start_date"] == "2026-09-25" for p in trade_calls)
    conclusion_calls = [p for path, p in source["calls"] if path.endswith("conclusions/")]
    assert conclusion_calls and all(p["end_date"] == "2026-09-26" for p in conclusion_calls)  # exclusive


def test_a_pinned_session_newer_than_the_archive_is_refused(source):
    assert not archive.fetch_latest_trade_stats(session=object(), session_day="2026-09-26")["complete"]


def test_quotes_ask_a_year_first_and_a_decade_only_for_a_quiet_security(source):
    archive.fetch_quotes([(ISIN, "STK")], session=object(), as_of="2026-09-25")
    spans = [p["start_date"] for path, p in source["calls"] if path.endswith("conclusions/")]
    assert spans == ["2025-08-21"]           # 400 days: it traded, no decade asked

    source["calls"].clear()
    source["conclusions"] = [conclusion(trading_volume=0)]
    archive.fetch_quotes([(ISIN, "STK")], session=object(), as_of="2026-09-25")
    spans = [p["start_date"] for path, p in source["calls"] if path.endswith("conclusions/")]
    assert spans == ["2025-08-21", "2016-09-27"]


def ex(stamp, price, isin=ISIN):
    return {**execution(trade_datetime=f"2026-09-25T{stamp}", trade_price=price,
                        trading_value=2 * price),
            "issue_code": isin, "trade_date": DAY}


def test_hourly_bars_resolve_tied_edges_to_real_neighbouring_prices():
    trades = [
        # 10h opens on a tie (12 / 9): the official day open (12) decides.
        ex("10:00:01.000000", 12), ex("10:00:01.000000", 9),
        # ...and closes on a tie (11 / 14): nearest 11h's first executions (14).
        ex("10:59:00.000000", 11), ex("10:59:00.000000", 14),
        # 11h opens on a tie (15 / 13.5): nearest 10h's close, 14 -> 13.5.
        ex("11:00:05.000000", 15), ex("11:00:05.000000", 13.5),
        # The last hour closes on a tie: the official day close (16) decides.
        ex("11:30:00.000000", 16), ex("11:30:00.000000", 17),
    ]
    ten, eleven = archive.session_bars(trades, {(ISIN, DAY): (12, 16)})
    assert (ten["open"], ten["close"], ten["high"], ten["low"]) == (12, 14, 14, 9)
    assert (eleven["open"], eleven["close"]) == (13.5, 16)
    assert ten["quantity"] == 8 and eleven["turnover"] == 2 * (15 + 13.5 + 16 + 17)


def test_session_bars_backfill_reads_conclusions_only_for_tied_day_edges(source):
    other = "UZ7011340005"
    source["trades"] = [execution(trade_price=10), execution(trade_price=11),
                        execution(isin_code=other, trade_datetime="2026-09-25T10:00:02.000000")]
    source["mutate"] = lambda payload, params: {
        **payload, "count": 3, "total_pages": 3, "has_next": params["page"] < 3}
    source["conclusions"] = [conclusion(open=11, close=10, high=11, low=10)]
    bars = archive.fetch_session_bars("2026-09-25", session=object())
    asked = [p["isu_cd"] for path, p in source["calls"] if path.endswith("conclusions/")]
    assert asked == [ISIN]  # the other security's day has no tie to resolve
    assert {b["isin"]: b["open"] for b in bars}[ISIN] == 11


def test_session_bars_backfill_takes_a_day_without_trades_as_empty(source):
    source["mutate"] = lambda payload, params: {**payload, "count": 0, "total_pages": 0,
                                                "has_next": False, "results": []}
    assert archive.fetch_session_bars("2026-09-27", session=object()) == []


def live(monkeypatch, payload):
    calls = []
    monkeypatch.setattr(archive, "_json_get", lambda client, path, params: calls.append(params) or deepcopy(payload))
    return calls


def test_live_bars_read_the_session_so_far_in_one_request(monkeypatch):
    today = archive.datetime.now(archive.TASHKENT).date().isoformat()
    trades = [execution(trade_datetime=f"{today}T10:00:01.000000", trade_price=12),
              execution(trade_datetime=f"{today}T10:00:01.000000", trade_price=9),
              execution(trade_datetime=f"{today}T11:15:00.000000", trade_price=10),
              execution(trade_datetime=f"{today}T11:20:00.000000", market_id="RPO")]
    calls = live(monkeypatch, {"count": 4, "has_next": False, "results": trades})
    ten, eleven = archive.fetch_live_bars(session=object())
    assert len(calls) == 1 and calls[0]["page_size"] == archive._LIVE_PAGE
    assert (ten["hour"], ten["open"], ten["low"], ten["quantity"]) == (10, 9, 9, 4)  # no conclusion yet
    assert (eleven["hour"], eleven["close"], eleven["quantity"]) == (11, 10, 2)      # REPO left out


@pytest.mark.parametrize("payload, expected", [
    ({"count": 0, "has_next": False, "results": []}, []),
    ({"count": 3, "has_next": False, "results": [execution()]}, None),   # short read
    ({"count": 1, "has_next": True, "results": [execution()]}, None),    # not one page
])
def test_live_bars_never_push_a_partial_read(monkeypatch, payload, expected):
    live(monkeypatch, payload)
    assert archive.fetch_live_bars(session=object()) == expected


def test_live_bars_step_pushes_bars_only(monkeypatch):
    bar = {"isin": ISIN, "date": DAY, "hour": 10, "open": 1, "high": 1, "low": 1,
           "close": 1, "quantity": 1, "turnover": 1}
    monkeypatch.setattr(archive, "fetch_live_bars", lambda: [bar])
    pushed = []
    monkeypatch.setattr(delivery, "_post", lambda path, body: pushed.append((path, body)) or 0)
    assert trading.push_live_bars() == 0
    assert pushed == [("/api/admin/quotes", {"rows": [], "history": [], "intraday": [bar]})]
    monkeypatch.setattr(archive, "fetch_live_bars", lambda: None)
    assert trading.push_live_bars() == 1


def coverage(monkeypatch, stats_day, quotes_day=None, official=None):
    import requests
    steps = {"trade_stats": {"last_day": stats_day},
             "quotes": {"last_day": stats_day if quotes_day is None else quotes_day}}
    if official:
        steps["official_quotes"] = {"last_day": official}
    answer = SimpleNamespace(json=lambda: {"collector": {"steps": steps}})
    monkeypatch.setattr(requests, "get", lambda url, **kw: answer)


@pytest.mark.parametrize("published, quotes_day, official, newest, posted, finished, outcome", [
    ("20260930", None, None, "20260930", True, True, "published"),        # nothing new
    ("20260930", None, None, "20261002", False, False, "not yet"),        # still trading
    ("20260930", None, None, "20261002", False, True, "go"),              # closed: provisional
    ("20261002", None, "20260930", "20261002", False, True, "published"), # provisional, no conclusions yet
    ("20261002", None, "20260930", "20261002", True, True, "go"),         # conclusions came: official
    ("20260930", None, None, "20261002", True, True, "go"),               # a new, complete session
    ("20260930", "20260929", None, "20260930", True, True, "go"),         # quotes never landed for it
    ("", None, None, "20260930", True, True, "go"),                       # no stamp at all
])
def test_a_run_with_nothing_to_publish_stops_after_one_or_two_requests(
        monkeypatch, published, quotes_day, official, newest, posted, finished, outcome):
    coverage(monkeypatch, published, quotes_day, official)
    monkeypatch.setattr(archive, "_session_finished", lambda day: finished)
    monkeypatch.setattr(trading.uzse_access, "enabled", lambda: False)
    monkeypatch.setattr(trading, "SESSION_DATE", None)
    monkeypatch.setattr(archive, "latest_session", lambda **kw: newest)
    monkeypatch.setattr(archive, "conclusions_posted", lambda day, **kw: posted)
    walked = []
    monkeypatch.setattr(archive, "fetch_latest_trade_stats", lambda **kw: walked.append(1) or {"reachable": False})
    monkeypatch.setattr(market, "audit_board", lambda: 0)
    status = trading.push_trade_stats()
    assert bool(walked) is (outcome == "go")
    assert status == (0 if outcome == "published" else 1)


def test_unknown_prod_state_or_a_pinned_session_always_runs_in_full(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError()))
    monkeypatch.setattr(trading.uzse_access, "enabled", lambda: False)
    monkeypatch.setattr(archive, "latest_session", lambda **kw: "20260930")
    monkeypatch.setattr(archive, "conclusions_posted", lambda day, **kw: True)
    assert trading._session_to_publish() == "go"
    coverage(monkeypatch, "20260930")
    monkeypatch.setattr(trading, "SESSION_DATE", "2026-09-30")
    walked = []
    monkeypatch.setattr(archive, "fetch_latest_trade_stats", lambda **kw: walked.append(kw) or {"reachable": False})
    trading.push_trade_stats()
    assert walked and walked[0]["session_day"] == "2026-09-30"


def test_conclusions_posted_reads_all_securities_in_one_request(monkeypatch):
    calls = []
    monkeypatch.setattr(archive, "_json_get", lambda c, path, params: calls.append(params) or
                        {"results": [{"date": "2026-10-02"}] if params["start_date"] == "2026-10-02" else []})
    assert archive.conclusions_posted("20261002", session=object()) is True
    assert archive.conclusions_posted("20261001", session=object()) is False
    assert calls[0] == {"isu_cd": "", "start_date": "2026-10-02", "end_date": "2026-10-03"}


@pytest.mark.parametrize("provisional", [False, True])
def test_only_a_session_from_the_conclusions_is_stamped_official(monkeypatch, source, provisional):
    if provisional:
        source["conclusions"] = [conclusion(date="2026-09-24")]
    data = archive.fetch_latest_trade_stats(session=object())
    assert bool(data.get("provisional")) is provisional
    monkeypatch.setattr(trading, "_session_to_publish", lambda: "go")
    monkeypatch.setattr(trading.uzse_access, "enabled", lambda: False)
    monkeypatch.setattr(trading, "SESSION_DATE", None)
    monkeypatch.setattr(archive, "fetch_latest_trade_stats", lambda **kw: data)
    monkeypatch.setattr(market, "board_securities", lambda: [{"isin": ISIN, "_market": "STK"}])
    monkeypatch.setattr(market, "SKIP_QUOTES", False)
    monkeypatch.setattr(market, "push_quotes", lambda *a, **kw: 0)
    monkeypatch.setattr(delivery, "_post", lambda path, body: 0)
    stamps = []
    monkeypatch.setattr(delivery, "_stamp_step", lambda step, day="": stamps.append((step, day)))
    assert trading.push_trade_stats() == 0
    assert ("trade_stats", DAY) in stamps
    assert (("official_quotes", DAY) in stamps) is not provisional
