"""Commercial-bank exchange rates from bankxizmatlari.uz — the Central Bank's
own retail-services portal.

The page hands every bank's rate matrix (USD/EUR/RUB x buy/sell x three
channels) as `data-*` attributes on one server-rendered page, plus a stable
per-bank code and the bank's own stated update time. Two things it does NOT
hand us: a "correct" rate to validate against, and a guarantee the bank typed
its own numbers right (Халк банки published a RUB обменный-пункт spread of
180% against a market of 20-90% on 2026-08-18). The tests pin the parse, the
peer-relative flag that catches that kind of anomaly without ever discarding a
real number, and that storage upserts on the bank's own timestamp so a quiet
poll does not grow history.
"""
from __future__ import annotations

import pytest

import bank_fx_collector as bf
import provenance


def _item(bank_code, name, updated="11:00, 18.08.2026", href="/ru/banks/1/", **cells):
    attrs = " ".join(f'data-{k}="{v}"' for k, v in cells.items())
    return (
        f'<div class="item js-element-item" data-bank="{bank_code}" {attrs}>'
        f'  <a href="{href}" class="item__media--bank"></a>'
        f'  <div class="item__header--name">{name}</div>'
        f'  <div class="item__update--text">Время обновления: {updated}</div>'
        f'</div>'
    )


def _page(*items):
    return f'<div class="items-list">{"".join(items)}</div>'


class TestParser:
    def test_reads_bank_code_name_and_the_full_currency_matrix(self):
        html = _page(_item(
            "006", "Халк банки",
            **{"usd-buy-bank": "11800.00", "usd-sale-bank": "11900.00"}))
        rows = bf.parse_bank_rates(html)
        assert len(rows) == 1
        row = rows[0]
        assert row["bank_code"] == "006"
        assert row["bank_name"] == "Халк банки"
        assert row["ccy"] == "USD"
        assert row["channel"] == "BANK"
        assert row["buy"] == pytest.approx(11800.0)
        assert row["sell"] == pytest.approx(11900.0)
        assert row["source_url"] == "https://bankxizmatlari.uz/ru/banks/1/"

    def test_a_blank_or_zero_channel_is_absent_not_a_zero_rate(self):
        html = _page(_item(
            "006", "Bank",
            **{"usd-buy-bank": "11800.00", "usd-sale-bank": "11900.00",
               "usd-buy-app": "0", "usd-sale-app": "",
               "usd-buy-atm": "0.00", "usd-sale-atm": "0"}))
        rows = bf.parse_bank_rates(html)
        channels = {r["channel"] for r in rows if r["ccy"] == "USD"}
        assert channels == {"BANK"}

    def test_the_banks_own_update_time_is_read_as_tashkent_local(self):
        """rfind(":") used to match the ':' inside "Время обновления:" — it
        never once found "11:00", so bank_updated_at was NULL for every row
        the collector ever parsed. Regression pin."""
        html = _page(_item("006", "Bank", updated="11:00, 18.08.2026",
                           **{"usd-buy-bank": "11800.00", "usd-sale-bank": "11900.00"}))
        row = bf.parse_bank_rates(html)[0]
        assert row["bank_updated_at"] == "2026-08-18T11:00:00+05:00"

    def test_an_unparseable_update_time_is_none_not_a_crash(self):
        html = _page(_item("006", "Bank", updated="только что",
                           **{"usd-buy-bank": "11800.00", "usd-sale-bank": "11900.00"}))
        row = bf.parse_bank_rates(html)[0]
        assert row["bank_updated_at"] is None


class TestPlausibilityFlag:
    def _peer_page(self, spreads, outlier_ccy="RUB", outlier=("50.00", "140.00")):
        items = []
        for i, (buy, sell) in enumerate(spreads):
            items.append(_item(f"{i:03d}", f"Bank {i}",
                               **{f"{outlier_ccy.lower()}-buy-bank": buy,
                                  f"{outlier_ccy.lower()}-sale-bank": sell}))
        items.append(_item("out", "Outlier",
                           **{f"{outlier_ccy.lower()}-buy-bank": outlier[0],
                              f"{outlier_ccy.lower()}-sale-bank": outlier[1]}))
        return _page(*items)

    def test_a_spread_far_above_its_peers_is_flagged_not_dropped(self):
        # Five peers around a 40-45% RUB spread (a real, wide-but-normal market —
        # see the module docstring), one outlier at 180%.
        peers = [("100.00", "142.00"), ("100.00", "145.00"), ("90.00", "130.00"),
                 ("95.00", "138.00"), ("100.00", "140.00")]
        html = self._peer_page(peers)
        rows = bf.parse_bank_rates(html)
        outlier = next(r for r in rows if r["bank_code"] == "out")
        assert outlier["flag"] == "wide_spread"
        assert outlier["buy"] == pytest.approx(50.0)
        assert outlier["sell"] == pytest.approx(140.0)  # still published, never dropped

    def test_ordinary_variation_among_peers_is_not_flagged(self):
        peers = [("100.00", "142.00"), ("100.00", "145.00"), ("90.00", "130.00"),
                 ("95.00", "138.00")]
        html = self._peer_page(peers, outlier=("95.00", "137.00"))
        rows = bf.parse_bank_rates(html)
        assert all(r["flag"] is None for r in rows)

    def test_too_few_peers_to_judge_means_no_flag(self):
        html = self._peer_page([("100.00", "142.00")])
        rows = bf.parse_bank_rates(html)
        assert all(r["flag"] is None for r in rows)

    def test_sell_below_buy_is_always_flagged_inverted(self):
        html = _page(_item("006", "Bank",
                           **{"usd-buy-bank": "11900.00", "usd-sale-bank": "11800.00"}))
        row = bf.parse_bank_rates(html)[0]
        assert row["flag"] == "inverted"


class TestStorage:
    def _cleanup(self, bank_code):
        conn = provenance._conn()
        try:
            conn.execute("DELETE FROM bank_fx_rates WHERE bank_code=?", (bank_code,))
            conn.commit()
        finally:
            conn.close()

    def test_the_same_timestamp_upserts_in_place(self):
        row = {"bank_code": "TST", "bank_name": "Test Bank", "ccy": "USD",
              "channel": "BANK", "buy": 100.0, "sell": 101.0, "flag": None,
              "bank_updated_at": "2026-08-18T11:00:00+05:00", "source_url": "https://x"}
        try:
            provenance.upsert_bank_fx_rates([row])
            provenance.upsert_bank_fx_rates([{**row, "sell": 102.0}])
            conn = provenance._conn()
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM bank_fx_rates WHERE bank_code='TST'").fetchone()[0]
            finally:
                conn.close()
            assert count == 1  # same key -> no new history row
            latest = [r for r in provenance.bank_fx_rates_latest() if r["bank_code"] == "TST"]
            assert latest[0]["sell"] == pytest.approx(102.0)  # but the value did update
        finally:
            self._cleanup("TST")

    def test_a_new_timestamp_adds_history_and_latest_wins(self):
        base = {"bank_code": "TST", "bank_name": "Test Bank", "ccy": "USD",
               "channel": "BANK", "buy": 100.0, "sell": 101.0, "flag": None,
               "source_url": "https://x"}
        try:
            provenance.upsert_bank_fx_rates([
                {**base, "bank_updated_at": "2026-08-18T09:00:00+05:00", "sell": 101.0},
                {**base, "bank_updated_at": "2026-08-18T11:00:00+05:00", "sell": 103.0},
            ])
            conn = provenance._conn()
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM bank_fx_rates WHERE bank_code='TST'").fetchone()[0]
            finally:
                conn.close()
            assert count == 2
            latest = [r for r in provenance.bank_fx_rates_latest() if r["bank_code"] == "TST"]
            assert len(latest) == 1
            assert latest[0]["sell"] == pytest.approx(103.0)
            assert latest[0]["bank_updated_at"] == "2026-08-18T11:00:00+05:00"
        finally:
            self._cleanup("TST")

    def test_a_row_with_no_readable_timestamp_still_gets_a_non_null_key(self):
        """PostgreSQL rejects NULL in a primary-key column — the fallback to
        the collector's own fetch time must actually land, not just be tried."""
        row = {"bank_code": "TST", "bank_name": "Test Bank", "ccy": "EUR",
              "channel": "BANK", "buy": 100.0, "sell": 101.0, "flag": None,
              "bank_updated_at": None, "source_url": "https://x"}
        try:
            written = provenance.upsert_bank_fx_rates([row])
            assert written == 1
            latest = [r for r in provenance.bank_fx_rates_latest() if r["bank_code"] == "TST"]
            assert latest[0]["bank_updated_at"]  # non-empty, not NULL
        finally:
            self._cleanup("TST")
