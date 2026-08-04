"""The board's change % must be the exchange's change %.

The exchange states a security's daily move against its own previous close, and
it CARRIES that close forward through sessions with no trades. UQEQ closed at
25 600 on 30.07 without a single execution — its last real trade was 29.07, and
before that 24.07 at 32 000 — so its +20.00% on 31.07 cannot be derived from the
execution feed, from openinfo's conclusions archive, or from the registry price
the board used to divide by. It exists only on the exchange's own security page.

These fixtures are that page, captured verbatim (header, session totals, session
OHLC and the daily closing history) for the three shapes that matter: a security
that traded, one whose previous close was carried forward, and one that did not
trade at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import uzse_quotes as uq

FIXTURES = Path(__file__).parent / "fixtures"


def _page(name: str) -> str:
    return (FIXTURES / f"uzse_{name}.html").read_text(encoding="utf-8")


@pytest.fixture()
def kfsk() -> dict:
    return uq.parse_quote(_page("kfsk_traded"), isin="UZ7001100005")


@pytest.fixture()
def uqeq() -> dict:
    return uq.parse_quote(_page("uqeq_carried_forward"), isin="UZ7042540003")


class TestTheExchangesOwnNumbers:
    """Each assertion is a cell of the exchange's 31.07.2026 bulletin."""

    def test_a_falling_security(self, kfsk) -> None:
        assert kfsk["ticker"] == "KFSK"
        # The issuer, not the security heading ("UZ7001100005 KFSK") — this row
        # may be the only name the board ever gets for the security.
        assert kfsk["name"].startswith("<Kafolat sug'urta kompaniyasi>")
        assert kfsk["trade_date"] == "20260731"
        assert kfsk["close_price"] == pytest.approx(82.0)
        assert kfsk["prev_close"] == pytest.approx(88.0)
        assert kfsk["prev_close_date"] == "20260730"
        assert kfsk["change_value"] == pytest.approx(-6.0)
        # The bulletin prints -6,82%.
        assert kfsk["change_percent"] == pytest.approx(-6.82, abs=0.005)

    def test_session_totals_and_ohlc(self, kfsk) -> None:
        assert kfsk["quantity"] == pytest.approx(60572)
        assert kfsk["turnover"] == pytest.approx(4_954_916.68)
        assert (kfsk["open_price"], kfsk["high_price"], kfsk["low_price"]) == (81.01, 82.0, 81.01)

    def test_a_previous_close_nobody_traded_at(self, uqeq) -> None:
        """The +20% that no feed of executions can produce."""
        assert uqeq["ticker"] == "UQEQ"
        assert uqeq["close_price"] == pytest.approx(30720.0)
        # 30.07 closed at 25 600 on zero volume — carried forward from 29.07.
        assert uqeq["prev_close"] == pytest.approx(25600.0)
        assert uqeq["prev_close_date"] == "20260730"
        assert uqeq["change_percent"] == pytest.approx(20.0)

    def test_the_registry_price_would_have_said_minus_four(self, uqeq) -> None:
        """openinfo's last conclusion for UQEQ is 32 000 (24.07): -4.00%, not +20%."""
        registry_percent = (uqeq["close_price"] - 32000.0) / 32000.0 * 100
        assert registry_percent == pytest.approx(-4.0)
        assert uqeq["change_percent"] != pytest.approx(registry_percent)


class TestASessionASecuritySatOut:
    """A page showing 0 / 0 / 0 dates no session, and must not overwrite one.

    Before a security's first trade of the day its page shows the current session
    as empty — the same shape it shows all day for a security that never trades.
    Attributing that to the latest session would replace a real close with a
    blank one every time the collector runs early.
    """

    def test_no_trade_means_no_dated_quote(self) -> None:
        quote = uq.parse_quote(_page("mxus_untraded"), isin="UZ7012480008")

        assert quote["traded"] is False
        assert quote["trade_date"] is None
        assert quote["quantity"] == 0
        # The close is still known — it is the carried-forward one.
        assert quote["close_price"] == pytest.approx(500.0)

    def test_the_collector_skips_it(self, monkeypatch) -> None:
        monkeypatch.setattr(uq, "fetch_quote",
                            lambda isin, market="STK", session=None:
                            uq.parse_quote(_page("mxus_untraded"), isin=isin))
        assert uq.fetch_session_quotes([("UZ7012480008", "STK")], pace=0) == []


class TestASecurityThatHasGoneQuiet:
    """UTGA last traded on 29.07 and the exchange has carried 116 000 forward ever
    since. Reading only the securities that traded left its board row — and eight
    others — showing an em-dash where uzse.uz publishes a price, because the page's
    *current* session is empty for a quiet security every day.

    The page answers anyway: its header dates the last trade, and its daily history
    prints that session's close, change, quantity and turnover. Captured verbatim on
    2026-08-04.
    """

    @pytest.fixture()
    def utga(self) -> dict:
        return uq.parse_quote(_page("utga_quiet"), isin="UZ7043380003")

    def test_the_current_session_is_empty(self, utga) -> None:
        assert utga["traded"] is False
        assert utga["trade_date"] is None
        # ...but the exchange still states when it last traded, and at what.
        assert utga["last_trade_date"] == "20260729"
        assert utga["last_price"] == pytest.approx(116000.0)

    def test_the_history_carries_the_close_forward_on_zero_volume(self, utga) -> None:
        carried = {h["date"]: h for h in utga["history"]}
        assert carried["20260803"]["quantity"] == 0
        assert carried["20260803"]["close"] == pytest.approx(116000.0)
        assert carried["20260729"]["quantity"] == pytest.approx(3.0)
        assert carried["20260729"]["turnover"] == pytest.approx(348000.0)

    def test_the_settled_row_is_the_session_it_last_traded_in(self, utga) -> None:
        settled = uq.settled_quote(utga)

        assert settled["trade_date"] == "20260729"
        assert settled["traded"] is True
        assert settled["close_price"] == pytest.approx(116000.0)
        assert settled["quantity"] == pytest.approx(3.0)
        assert settled["turnover"] == pytest.approx(348000.0)
        assert settled["change_percent"] == pytest.approx(0.0)
        # A finished session publishes no OHLC; saying nothing keeps whatever the
        # run that watched it live already stored (see bulk_upsert_quotes).
        assert (settled["open_price"], settled["high_price"], settled["low_price"]) == (None,) * 3

    def test_the_collector_takes_it_when_asked_to_settle(self, monkeypatch, utga) -> None:
        monkeypatch.setattr(uq, "fetch_quote",
                            lambda isin, market="STK", session=None: dict(utga))
        monkeypatch.setattr(uq, "fetch_issue_detail",
                            lambda isin, session=None: None)
        outcome: dict[str, int] = {}
        quotes = uq.fetch_session_quotes([("UZ7043380003", "STK")], pace=0,
                                         settle=True, outcome=outcome)

        assert [q["trade_date"] for q in quotes] == ["20260729"]
        assert outcome == {"targets": 1, "unreadable": 0, "idle": 0,
                           "settled": 1, "quoted": 1}

    def test_a_site_that_has_stopped_answering_ends_the_pass(self, monkeypatch) -> None:
        """Retrying keeps a bad minute from becoming a hole in the board; it also
        turns uzse.uz being down into a hundred pages x four attempts x a
        thirty-second timeout, and Railway skips a cron run whose predecessor is
        still going. Five unreadable in a row is the site being down."""
        asked: list[str] = []

        def _dead(isin, market="STK", session=None):
            asked.append(isin)
            return None

        monkeypatch.setattr(uq, "fetch_quote", _dead)
        outcome: dict[str, int] = {}
        quotes = uq.fetch_session_quotes([(f"UZ70000000{i:02d}", "STK") for i in range(40)],
                                         pace=0, outcome=outcome)

        assert quotes == []
        assert len(asked) == 5
        # ...and the securities never asked about are still reported unread, so
        # the caller sees a failed pass rather than a quiet one.
        assert outcome["unreadable"] == 40

    def test_a_security_that_never_traded_still_yields_nothing(self) -> None:
        """MXUS has no last-trade date at all — every history row is carried
        forward at 500 on zero volume. There is no session to publish."""
        assert uq.settled_quote(uq.parse_quote(_page("mxus_untraded"),
                                               isin="UZ7012480008")) is None


class TestTheParserRefusesWhatItCannotRead:
    def test_a_page_for_another_security_is_not_ours(self) -> None:
        """uzse.uz answers an unknown ISIN with its default security, not a 404."""
        assert uq.parse_quote(_page("kfsk_traded"), isin="UZ0000000000") is None

    @pytest.mark.parametrize("html", ["", "<html><body>Ошибка</body></html>",
                                      "<table><tr><td>nothing</td></tr></table>"])
    def test_a_page_without_the_tables_yields_nothing(self, html) -> None:
        assert uq.parse_quote(html, isin="UZ7001100005") is None


class TestNumbersAreReadInTheExchangesLocale:
    """"1,234.56" is 1234.56 here — a thousands comma read as a decimal point is
    a 1000x error, and these cells feed price, turnover and market cap."""

    @pytest.mark.parametrize(("cell", "expected"), [
        ("▼\n              6", -6.0),
        ("▲               5,120", 5120.0),
        ("▲                 897.98", 897.98),
        ("0", 0.0),
        ("", None),
    ])
    def test_the_arrow_carries_the_sign(self, cell, expected) -> None:
        assert uq._signed(cell) == (pytest.approx(expected) if expected is not None else None)

    def test_grouped_thousands(self) -> None:
        assert uq._num("4,954,916.68") == pytest.approx(4_954_916.68)
        assert uq._num("100,000,000") == pytest.approx(100_000_000)
