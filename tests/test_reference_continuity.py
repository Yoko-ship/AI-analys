"""«Изменение больше лимита биржи» (audit of 12.10.2026): real print or broken history?

The register listed ORFI's session −54,08 % (573,95 on 27.07.2021 against 1 250)
as a move beyond the exchange's ±20 % corridor. It is a real print — two G1
fills totalling 92 344 746 shares — and the exchange's own change for that
session (−676,05) says it was measured from that very 1 250, the close of
07.10.2016. The SIZE of a move does not tell a real print from a broken history;
the exchange's REFERENCE does. A session whose reference is not the close stored
before it is either a share-count event nobody registered (UZTL 21.04.2026,
TRSB 25.08.2026) or a stored close that disagrees with the exchange's.
"""
from __future__ import annotations

from types import SimpleNamespace

import market_audit


def _row(day: str, close: float, change: float | None, turnover: float = 1.0) -> dict:
    return {"trade_date": day, "close_price": close, "change_value": change, "turnover": turnover}


def _breaks(rows, ticker="TEST", actions=()):
    return market_audit.reference_breaks({"UZ7000000001": rows}, {"UZ7000000001": ticker},
                                         actions_for=lambda t: actions)


class TestARealMoveIsNotABreak:
    def test_orfi_minus_54_percent_after_five_years_is_the_exchanges_own_move(self) -> None:
        rows = [_row("20161007", 1250.0, 0.0), _row("20210727", 573.95, -676.05)]
        assert _breaks(rows, "ORFI") == []

    def test_limit_moves_and_carried_closes_follow_their_reference(self) -> None:
        """UQEQ: 25 600 carried forward without a trade, then +20 % to 30 720."""
        rows = [_row("20260729", 32000.0, 0.0), _row("20260730", 25600.0, -6400.0, 0.0),
                _row("20260731", 30720.0, 5120.0)]
        assert _breaks(rows, "UQEQ") == []

    def test_a_one_tick_line_doubling_is_not_a_break(self) -> None:
        """KASU at 0,01 ↔ 0,02: the corridor cannot hold at one tick, the reference does."""
        rows = [_row("20250620", 0.02, 0.0), _row("20250623", 0.01, -0.01), _row("20250624", 0.02, 0.01)]
        assert _breaks(rows, "KASU") == []

    def test_a_registered_event_explains_its_own_break(self) -> None:
        """ALSM: split 2:1 from 19.05.2025 — the reference halves on the ex-date."""
        split = SimpleNamespace(ex_date="2025-05-19", ratio=2.0)
        rows = [_row("20250402", 3000.0, 0.0), _row("20250519", 1550.0, 50.0)]
        assert _breaks(rows, "ALSM", (split,)) == []

    def test_a_session_rebuilt_from_executions_states_no_reference(self) -> None:
        rows = [_row("20260420", 5760.0, -1440.0), _row("20260421", 2880.0, None)]
        assert _breaks(rows) == []


class TestABrokenHistoryIsNamed:
    def test_uztl_reference_reset_on_21_april_is_a_suspected_share_event(self) -> None:
        rows = [_row("20260224", 7200.0, 199.0), _row("20260420", 5760.0, -1440.0),
                _row("20260421", 2880.0, 480.0), _row("20260422", 3456.0, 576.0)]

        [brk] = _breaks(rows, "UZTL")

        assert (brk["date"], brk["previous_close"], brk["reference"]) == ("20260421", 5760.0, 2400.0)
        assert brk["ratio"] == 2.4
        assert brk["kind"] == "share_event_suspected"

    def test_trsb_two_for_one_on_25_august(self) -> None:
        rows = [_row("20260813", 16500.0, 0.0), _row("20260824", 16500.0, 0.0, 0.0),
                _row("20260825", 9789.0, 1539.0)]

        [brk] = _breaks(rows, "TRSB")

        assert (brk["ratio"], brk["kind"]) == (2.0, "share_event_suspected")

    def test_a_stored_close_the_exchange_did_not_print(self) -> None:
        """AGMKP 13.10.2025: stored 8 800, the exchange measured 14.10 from 8 701,01."""
        rows = [_row("20251013", 8800.0, None), _row("20251014", 9216.0, 514.99)]

        [brk] = _breaks(rows, "AGMKP")

        assert brk["kind"] == "close_disagrees_with_reference"
        assert brk["reference"] == 8701.01

    def test_the_check_reports_without_failing_the_run(self) -> None:
        history = {"UZ7004510002": [_row("20260420", 5760.0, -1440.0), _row("20260421", 2880.0, 480.0)]}
        check = market_audit.history_check(history, {"UZ7004510002": "UZTL"}, actions_for=lambda t: ())

        assert check["ok"] is False and check["blocking"] is False
        assert check["offenders"] == ["UZTL 20260421 ×2.4"]
        line = market_audit.format_verdict({"ok": True, "checks": [check]})
        assert "[WARN] history_follows_the_exchange_reference" in line
