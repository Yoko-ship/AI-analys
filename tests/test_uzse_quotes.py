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
