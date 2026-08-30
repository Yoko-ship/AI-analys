"""The bond contour and the provenance layer (ТЗ Дополнение 1, части А and Б).

Eleven issues trade genuinely — 8 622 securities changed hands in ACMT2B5 on
31 July — and the interface does not contain them, while their issue value leaks
into equity arithmetic and two of them show minus a hundred percent on the map.
The addendum's point is that a half-closed contour is worse than either choice:
the data is there, the user cannot see it, and it affects the aggregates anyway.

The other half is provenance: no published figure names the report it came from,
so "where did this revenue come from?" has no answer. That gap is where the FIN
defect group grew.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import bonds
import provenance


def bond_row(ticker="ACMT2B5", price=105310.56, prev=106_000.0, trades=8622,
             turnover=908_000_000.0, cap=105_310_560_000.0, **kw):
    return {"ticker": ticker, "type": "bond", "last_price": price, "close_price": prev, "last_trade_date": date.today().isoformat(),
            "trade_count": trades, "volume": turnover, "market_cap": cap, **kw}


class TestClassAndExclusion:
    def test_a_bond_is_classified_as_a_bond_not_an_ordinary_share(self):
        """Its class currently says `ordinary`, which is how it reaches the
        equity branches of the code at all."""
        assert bonds.share_class(bond_row(), {"share_type": "ordinary"}) == "bond"
        assert bonds.share_class({"ticker": "A", "type": "stock"}, {}) == "ordinary"

    def test_equity_multiples_are_structurally_absent_not_null(self):
        row = bonds.bond_row(bond_row())
        assert row["multiples"]["available"] is False
        assert row["multiples"]["reason"]
        # Not "we could not compute it" — the question does not apply.
        assert "pe" not in row and "pb" not in row and "roe" not in row

    def test_issue_value_is_its_own_line(self):
        board = bonds.build_bond_board([bond_row(), bond_row("CTFB3", cap=692_000_000_000.0)])
        assert board["count"] == 2
        assert board["issue_value_total"] == pytest.approx(105_310_560_000.0 + 692_000_000_000.0)
        assert "капитализация" in board["issue_value_note"]

    def test_shares_are_not_picked_up_by_the_bond_board(self):
        board = bonds.build_bond_board([{"ticker": "UZHM", "type": "stock", "last_price": 100}])
        assert board["count"] == 0


class TestWithoutReference:
    def test_every_yield_metric_is_a_dash_with_a_reason(self):
        """No endpoint carries a nominal, coupon or maturity — so nothing that
        needs them may be computed, and an invented par is not a fallback."""
        row = bonds.bond_row(bond_row())
        for field in ("price_pct", "ytm", "duration", "accrued", "spread"):
            assert row[field]["value"] is None
            assert row[field]["status"] == bonds.STATUS_NO_REFERENCE
            assert row[field]["note"] == bonds.NO_REFERENCE_NOTE

    def test_the_reference_state_names_what_is_missing(self):
        state = bonds.reference_state({"nominal": 100_000})
        assert state["is_complete"] is False
        assert set(state["missing"]) == {"coupon_rate", "maturity_date"}

    def test_price_change_and_turnover_still_work(self):
        row = bonds.bond_row(bond_row(price=105.0, prev=100.0))
        assert row["change_pct"] == pytest.approx(5.0)
        assert row["status"] == "ok"

    def test_trades_without_a_price_are_a_status_not_minus_one_hundred(self):
        """ACMT1B2 traded 575 securities and showed −100 % on the map."""
        row = bonds.bond_row(bond_row("ACMT1B2", price=None, prev=100.0, trades=575))
        assert row["change_pct"] is None
        assert row["status"] == "no_price" and row["reason"]

    def test_the_day_count_basis_is_always_stated(self):
        """Two developers assuming different bases both get a number and both
        believe they are right."""
        assert bonds.bond_row(bond_row())["day_count_basis"] is None
        assert bonds.bond_row(bond_row(), reference={"day_count": "ACT/365"})["day_count_basis"] == "ACT/365"


class TestNominalOnly:
    """The exchange publishes the par value; nobody publishes the coupon.

    §А.3 said no endpoint carried a nominal, and the contour was built inert on
    that. The exchange's own card returns ``parval`` — 100 000 across the ACMT
    series — so the half that IS available must turn on without dragging the
    yields, which still have no coupon and no maturity to stand on.
    """

    NOMINAL_ONLY = {"nominal": 100_000.0, "issue_volume": 1_000_000.0,
                    "source_url": "https://uzse.uz/isu_infos/BND?isu_cd=UZ6058977AE0"}

    def test_price_reads_as_a_percentage_of_par_without_a_coupon(self):
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.NOMINAL_ONLY)
        assert row["reference"]["is_complete"] is False
        assert row["reference"]["has_nominal"] is True
        assert row["price_pct"]["value"] == pytest.approx(105.31056)

    def test_the_yields_do_not_turn_on_with_it(self):
        """A par cannot produce a yield. Only the coupon and the maturity can,
        and an invented coupon is the same error as an invented par."""
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.NOMINAL_ONLY)
        for field in ("ytm", "duration", "accrued", "spread", "simple_yield"):
            assert row[field]["value"] is None
            assert row[field]["status"] == bonds.STATUS_NO_REFERENCE
        assert set(row["price_pct"].keys()) >= {"value", "status"}

    def test_a_known_par_with_no_quote_blames_the_quote(self):
        """ACMT1B2 and CTFB3 have a par and no last price. Saying
        `no_bond_reference` there would blame the reference for the wrong gap."""
        row = bonds.bond_row(bond_row("ACMT1B2", price=None, trades=575),
                             reference=self.NOMINAL_ONLY)
        assert row["price_pct"]["value"] is None
        assert row["price_pct"]["status"] == "no_price"
        assert row["status"] == "no_price"

    def test_a_par_of_zero_is_not_a_par(self):
        row = bonds.bond_row(bond_row(price=105_310.56), reference={"nominal": 0})
        assert row["reference"]["has_nominal"] is False
        assert row["price_pct"]["status"] == bonds.STATUS_NO_REFERENCE

    def test_the_board_counts_both_stages_separately(self):
        board = bonds.build_bond_board(
            [bond_row(), bond_row("CTFB3", cap=1.0)],
            references={"ACMT2B5": self.NOMINAL_ONLY})
        assert board["with_nominal"] == 1     # the par arrived
        assert board["with_reference"] == 0   # the coupon and maturity did not


class TestCouponWithoutMaturity:
    """The middle stage: a coupon is filed for years before a redemption date.

    The issuer files each coupon payment as it happens (#32) but files a
    redemption window only when it starts redeeming (#31). Accrued interest and
    the running yield need the first and not the second, so gating them behind
    the maturity kept eleven of twelve issues showing a dash for a number their
    own filings state.
    """

    COUPON_ONLY = {"nominal": 100_000.0, "coupon_rate": 28.0, "coupon_freq": 12, "day_count": "ACT/365"}

    def _coupons(self, *offsets):
        return [{"coupon_no": i + 1, "amount": 2301.37,
                 "pay_date": (date.today() - timedelta(days=off)).isoformat()}
                for i, off in enumerate(offsets)]

    def test_accrued_and_running_yield_turn_on_without_a_maturity(self):
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.COUPON_ONLY,
                             coupons=self._coupons(40, 10))
        assert row["reference"]["has_coupon"] is True
        assert row["reference"]["is_complete"] is False
        assert row["accrued"]["value"] == pytest.approx(100_000 * 0.28 * 10 / 365)
        assert row["simple_yield"]["value"] == pytest.approx(28_000 / 105_310.56 * 100)
        assert row["dirty"]["value"] > row["clean"]["value"]

    def test_the_discounting_metrics_still_wait_for_the_redemption_date(self):
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.COUPON_ONLY,
                             coupons=self._coupons(10))
        for field in ("ytm", "duration", "modified_duration", "spread"):
            assert row[field]["value"] is None
            assert row[field]["status"] == bonds.STATUS_NO_REFERENCE

    def test_an_unfiled_coupon_does_not_inflate_the_accrual(self):
        """Filings arrive per payment, so the newest can be older than a period.
        Counting the whole gap would put accrued interest above a full coupon —
        which is what BND-09 exists to catch."""
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.COUPON_ONLY,
                             coupons=self._coupons(70))
        period_coupon = 100_000 * 0.28 / 12
        assert row["accrued"]["value"] < period_coupon

    def test_no_coupon_ever_paid_is_a_reason_not_a_zero(self):
        row = bonds.bond_row(bond_row(price=105_310.56), reference=self.COUPON_ONLY)
        assert row["accrued"]["value"] is None
        assert row["accrued"]["status"] == bonds.STATUS_NO_REFERENCE

    def test_a_redeemed_issue_says_so_instead_of_no_price(self):
        """ACMT1B2 stopped printing a price because it is being redeemed."""
        reference = {**self.COUPON_ONLY,
                     "maturity_date": (date.today() - timedelta(days=5)).isoformat()}
        row = bonds.bond_row(bond_row("ACMT1B2", price=None, trades=575), reference=reference)
        assert row["status"] == "matured"
        assert "погашается" in row["reason"]


class TestTheSessionEachRowIsFrom:
    """The quote feed and the day statistics are two feeds describing two days.

    The board screen has reconciled them since day one. This section never did,
    and on 2026-08-11 it printed IQMK5B8's **3 April** price and April turnover
    (101,92 млрд) beside issues that had traded that morning — while the day
    statistics held its trade of that very day, 124,53 млрд at 1 037 753,42.
    The trade count was empty for 15 of the 17 for the same reason: the quote
    feed carries none for a bond, and the statistics carry one for every issue.
    """
    ISIN = "UZ6056887AH6"

    def _row(self, **kw):
        return bond_row("IQMK5B8", price=1_019_168.31, prev=1_000_000.01, trades=None,
                        turnover=101_916_831_000.0, isin=self.ISIN,
                        last_trade_date="2026-04-03", **kw)

    def _stats(self, day="20260811", **kw):
        return {"trade_date": day, "total_value": 124_530_410_400.0, "total_qty": 120_000.0,
                "trade_count": 1, "close_price": 1_037_753.42, "vwap": 1_037_753.42, **kw}

    def test_a_newer_session_in_the_statistics_wins_the_row(self):
        row = bonds.bond_row(self._row(), stats=self._stats())

        assert row["price"] == pytest.approx(1_037_753.42)
        assert row["turnover"] == pytest.approx(124_530_410_400.0)
        assert row["last_trade_date"] == "2026-08-11"

    def test_the_stale_price_becomes_the_previous_close(self):
        """Close-to-close, matching the daily bulletin — not April against today."""
        row = bonds.bond_row(self._row(), stats=self._stats())

        assert row["change_pct"] == pytest.approx((1_037_753.42 / 1_019_168.31 - 1) * 100)

    def test_statistics_older_than_the_row_are_ignored(self):
        """ACMT1B2: the feed has 17.07, the statistics 14.07. A turnover from
        another week belongs to no quote on this page."""
        row = bonds.bond_row(
            bond_row("ACMT1B2", price=100_000.01, prev=100_500.0, trades=7,
                     turnover=4_300_000.36, isin="X", last_trade_date="2026-07-17"),
            stats={"trade_date": "20260714", "total_value": 22_093_140.0, "trade_count": 16})

        assert row["turnover"] == pytest.approx(4_300_000.36)
        assert row["trades"] == 7
        assert row["last_trade_date"] == "2026-07-17"

    def test_the_trade_count_comes_from_the_statistics_when_the_feed_has_none(self):
        row = bonds.bond_row(
            bond_row("BFMT3V2", trades=None, turnover=3_956_244.42, isin="Y",
                     last_trade_date="2026-08-11"),
            stats={"trade_date": "20260811", "total_value": 3_956_244.42, "trade_count": 14})

        assert row["trades"] == 14

    def test_the_statistics_day_is_read_in_its_own_spelling(self):
        """`YYYYMMDD` is how the statistics store spells a day. Read as ISO it
        parses as nothing, and every row silently takes the "no session" branch."""
        assert bonds._as_date("20260811") == date(2026, 8, 11)
        assert bonds._as_date("11.08.2026") == date(2026, 8, 11)
        assert bonds._as_date("2026-08-11") == date(2026, 8, 11)

    def test_the_board_names_its_session_and_counts_what_is_not_from_it(self):
        board = bonds.build_bond_board(
            [bond_row("A", isin="A", last_trade_date="2026-08-11"),
             bond_row("B", isin="B", last_trade_date="2026-08-04")])

        assert board["board_day"] == "2026-08-11"
        assert board["traded_today"] == 1 and board["stale"] == 1
        by_ticker = {r["ticker"]: r for r in board["items"]}
        assert by_ticker["A"]["is_current"] is True
        assert by_ticker["B"]["is_current"] is False


class TestARedeemedIssueSaysSo:
    """ACMT1B2 was redeemed on 23.07 and kept earning a coupon on this page —
    19 days of accrual on a principal already paid back — while its YTM blamed
    «нет справочных данных по выпуску», about the one issue on the board whose
    reference IS complete."""
    def _reference(self, days_ago=19):
        return {"nominal": 100_000.0, "coupon_rate": 28.0, "coupon_freq": 12,
                "maturity_date": (date.today() - timedelta(days=days_ago)).isoformat()}

    def _row(self):
        return bonds.bond_row(bond_row("ACMT1B2", price=100_000.01, prev=100_500.0),
                              reference=self._reference(),
                              coupons=[{"pay_date": (date.today() - timedelta(days=40)).isoformat()}])

    def test_the_accrual_stops_at_redemption(self):
        assert self._row()["accrued"]["value"] is None

    def test_the_discounting_metrics_blame_the_redemption_not_the_data(self):
        row = self._row()
        for field in ("ytm", "duration", "modified_duration", "spread"):
            assert row[field]["value"] is None
            assert row[field]["status"] == bonds.STATUS_MATURED
            assert "погашен" in row[field]["note"]

    def test_a_redeemed_issue_is_flagged_even_while_a_price_is_still_carried(self):
        """The exchange carries the last close forward; that is not a live issue."""
        assert self._row()["status"] == "matured"

    def test_a_live_issue_is_untouched_by_any_of_this(self):
        reference = {"nominal": 100_000.0, "coupon_rate": 28.0, "coupon_freq": 12,
                     "day_count": "ACT/365",
                     "maturity_date": (date.today() + timedelta(days=200)).isoformat()}
        row = bonds.bond_row(bond_row("ACMT1B3", price=104_999.99), reference=reference,
                             coupons=[{"pay_date": (date.today() - timedelta(days=10)).isoformat()}])

        assert row["status"] == "ok"
        assert row["accrued"]["value"] is not None
        assert row["ytm"]["status"] != bonds.STATUS_MATURED


class TestHistoryQuality:
    """The tier column shipped with no input behind it for a week."""

    def test_the_board_carries_the_tier_it_is_given(self):
        board = bonds.build_bond_board(
            [bond_row()], quality={"ACMT2B5": {"data_tier": "full", "points": 226}})
        assert board["items"][0]["quality"]["data_tier"] == "full"

    def test_the_endpoint_asks_for_history_of_bonds_only(self, monkeypatch):
        """A share on the same board must not cost an openinfo fetch, and one
        unreadable history must not take the board down with it."""
        import asyncio

        import api

        asked = []

        async def fake_history(isin, months=60):
            asked.append(isin)
            if isin == "UZ6BAD":
                raise RuntimeError("openinfo is down")
            return {"points": [{"date": "2026-07-31", "close": 100}]}

        monkeypatch.setattr(api, "_full_history", fake_history)
        inputs = {"board": [{"ticker": "ACMT2B5", "type": "bond", "isin": "UZ6OK"},
                            {"ticker": "CTFB3", "type": "bond", "isin": "UZ6BAD"},
                            {"ticker": "UZHM", "type": "stock", "isin": "UZ7EQ"}],
                  "securities": {}}
        got = asyncio.run(api._bond_history_quality(inputs))
        assert sorted(asked) == ["UZ6BAD", "UZ6OK"]
        assert "ACMT2B5" in got and "CTFB3" not in got


class TestTermsFromFilings:
    """The rate is inverted from the filed payments, never parsed from prose."""

    def _accruals(self, amount, count=4, step=30):
        return [{"amount": amount, "pay_date": date(2026, 1, 1) + timedelta(days=step * i)}
                for i in range(count)]

    def test_the_rate_comes_back_whole_from_the_filed_amount(self):
        import bond_terms

        rate, period, kind = bond_terms._coupon_rate(100_000.0, self._accruals(2301.37))
        assert (rate, period, kind) == (28.0, 30, "fixed")

    def test_a_longer_month_is_the_same_coupon(self):
        """2 378.08 over 31 days and 2 301.37 over 30 are both 28 %."""
        import bond_terms

        mixed = self._accruals(2301.37, 3) + [{"amount": 2378.08, "pay_date": date(2026, 4, 1)}]
        rate, _period, kind = bond_terms._coupon_rate(100_000.0, mixed)
        assert (rate, kind) == (28.0, "fixed")

    def test_amounts_that_do_not_share_a_rate_get_no_rate(self):
        import bond_terms

        moving = self._accruals(2301.37, 2) + [{"amount": 3500.0, "pay_date": date(2026, 3, 2)}]
        rate, _period, kind = bond_terms._coupon_rate(100_000.0, moving)
        assert rate is None and kind == "floating"

    def test_a_quarterly_issue_is_read_as_quarterly(self):
        import bond_terms

        rate, period, _kind = bond_terms._coupon_rate(100_000_000.0,
                                                      self._accruals(5_917_808.22, 3, step=91))
        assert (rate, period) == (24.0, 90)

    def test_the_series_is_matched_on_par_and_quantity_then_sequence(self):
        """AGAT's four series share a par and three share a quantity — neither
        field alone is a key, and a coupon on the wrong series is worse than
        none."""
        import bond_terms

        issues = [{"nominal": 100_000.0, "quantity": 400_000.0, "sequence": 3, "id": "third"},
                  {"nominal": 100_000.0, "quantity": 400_000.0, "sequence": 4, "id": "fourth"},
                  {"nominal": 100_000.0, "quantity": 300_000.0, "sequence": 2, "id": "second"}]
        assert bond_terms.match_issue(
            {"ticker": "ACMT2B4", "nominal": 100_000, "issue_volume": 400_000}, issues)["id"] == "fourth"
        assert bond_terms.match_issue(
            {"ticker": "ACMT1B2", "nominal": 100_000, "issue_volume": 300_000}, issues)["id"] == "second"
        # Nothing distinguishes a ticker whose digit matches neither candidate.
        assert bond_terms.match_issue(
            {"ticker": "ACMT9B9", "nominal": 100_000, "issue_volume": 400_000}, issues) is None

    def test_the_issue_sequence_is_read_from_the_registration_number(self):
        import bond_terms

        assert bond_terms._issue_sequence("RU303P1079T0") == 3
        assert bond_terms._issue_sequence("Q0845-2") == 2
        assert bond_terms._issue_sequence("1079-5") == 5
        assert bond_terms._issue_sequence("Q0845") == 1


class TestReferenceCollector:
    """What the loader is allowed to write, and what it must leave empty."""

    DETAIL = [{"company_name": "AGAT CREDIT", "shares": [
        {"type": "Простая акция", "isu_cd": "UZ7058970011", "isu_srt_cd": "OACM",
         "list_shrs": 0, "parval": 0.0},
        {"type": "Облигация", "isu_cd": "UZ6058977AB6", "isu_srt_cd": "ACMT1B2",
         "list_shrs": 300000, "parval": 100000.0},
        {"type": "Облигация", "isu_cd": "UZ6058977AE0", "isu_srt_cd": "ACMT2B5",
         "list_shrs": 1000000, "parval": 100000.0},
    ]}]

    def _collect(self, monkeypatch, listing_rows):
        import listings_collector as lc

        calls = []

        class _Resp:
            def json(self_inner): return TestReferenceCollector.DETAIL

        class _Session:
            def get(self_inner, url, **kw):
                calls.append(url)
                return _Resp()

        monkeypatch.setattr(lc, "_make_session", lambda: _Session())
        monkeypatch.setattr(lc, "_BOND_SERIES_CACHE", {})
        monkeypatch.setattr(lc, "_uzse_bond_nominal", lambda *a, **k: None)
        return lc.collect_bond_reference_rows(listing_rows), calls

    def test_the_par_and_the_issue_size_are_read_from_the_exchange(self, monkeypatch):
        rows, _ = self._collect(monkeypatch, [
            {"ticker": "ACMT2B5", "isin": "UZ6058977AE0"}])
        assert rows[0]["nominal"] == 100_000.0
        assert rows[0]["issue_volume"] == 1_000_000.0
        assert rows[0]["source_url"].endswith("UZ6058977AE0")

    def test_the_coupon_and_the_maturity_are_never_invented(self, monkeypatch):
        """The whole point of §А.3: a plausible coupon is not a coupon."""
        rows, _ = self._collect(monkeypatch, [
            {"ticker": "ACMT2B5", "isin": "UZ6058977AE0"}])
        for field in ("coupon_rate", "coupon_freq", "maturity_date", "issue_date"):
            assert field not in rows[0]
        assert bonds.reference_state(rows[0])["is_complete"] is False

    def test_one_request_fills_every_series_of_the_issuer(self, monkeypatch):
        """The card answers with the whole issuer, so asking per series would
        be four identical requests for one answer."""
        rows, calls = self._collect(monkeypatch, [
            {"ticker": "ACMT2B5", "isin": "UZ6058977AE0"},
            {"ticker": "ACMT1B2", "isin": "UZ6058977AB6"}])
        assert len(rows) == 2 and len(calls) == 1

    def test_equities_are_not_given_a_bond_reference(self, monkeypatch):
        rows, calls = self._collect(monkeypatch, [{"ticker": "UZHM", "isin": "UZ7011340005"}])
        assert rows == [] and calls == []


class TestWithReference:
    def _reference(self, **kw):
        base = {"nominal": 100_000.0, "coupon_rate": 12.0, "coupon_freq": 1,
                "day_count": "ACT/365",
                "maturity_date": (date.today() + timedelta(days=365 * 3)).isoformat(),
                "days_from_coupon": 0}
        base.update(kw)
        return base

    def _coupons(self, years=3, amount=12_000.0):
        return [{"coupon_no": i + 1, "pay_date": (date.today() + timedelta(days=365 * (i + 1))
                                                  ).isoformat(), "amount": amount}
                for i in range(years)]

    def test_metrics_turn_on_the_moment_the_reference_is_complete(self):
        row = bonds.bond_row(bond_row(price=100_000.0), reference=self._reference(),
                             coupons=self._coupons())
        assert row["reference"]["is_complete"] is True
        assert row["price_pct"]["value"] == pytest.approx(100.0)
        assert row["ytm"]["value"] is not None

    def test_price_is_shown_as_a_percentage_of_par(self):
        """100 301 in one issue and 10 062 465 in another are different pars;
        comparing them in absolute sums is meaningless."""
        got = bonds.price_pct(105_310.56, 100_000.0)
        assert got["value"] == pytest.approx(105.31056)

    def test_yield_to_maturity_solves_the_par_case(self):
        flows = [(1.0, 12_000.0), (2.0, 12_000.0), (3.0, 112_000.0)]
        got = bonds.yield_to_maturity(flows, 100_000.0)
        assert got["status"] == "ok"
        assert got["value"] == pytest.approx(12.0, abs=1e-6)

    def test_non_convergence_is_reported_not_approximated(self):
        got = bonds.yield_to_maturity([(1.0, 1.0)], 1e12)
        assert got["value"] is None and got["status"] == "not_converged"

    def test_yield_is_computed_on_the_dirty_price(self):
        """Swapping clean for dirty makes the error the size of the coupon."""
        accrued = bonds.accrued_interest(100_000.0, 12.0, 182)
        assert accrued["value"] == pytest.approx(100_000 * 0.12 * 182 / 365)
        assert accrued["day_count_basis"] == "ACT/365"
        assert bonds.dirty_price(99_000.0, accrued["value"]) > 99_000.0

    def test_duration_is_positive_and_below_maturity(self):
        flows = [(1.0, 12_000.0), (2.0, 12_000.0), (3.0, 112_000.0)]
        ytm = bonds.yield_to_maturity(flows, 100_000.0)["value"]
        duration = bonds.macaulay_duration(flows, 100_000.0, ytm)
        assert 0 < duration["value"] < 3.0
        modified = bonds.modified_duration(duration["value"], ytm, 1)
        assert modified["value"] < duration["value"]

    def test_cashflows_drop_coupons_already_paid(self):
        reference = self._reference()
        coupons = [{"coupon_no": 0, "pay_date": (date.today() - timedelta(days=30)).isoformat(),
                    "amount": 12_000.0}] + self._coupons()
        flows = bonds.coupon_cashflows(reference, coupons)
        assert all(t > 0 for t, _ in flows)
        assert len(flows) == 4                       # three future coupons + redemption


class TestProvenance:
    @pytest.fixture(autouse=True)
    def _clean(self):
        provenance.init()
        conn = provenance._conn()
        try:
            conn.execute("DELETE FROM report_figures WHERE report_id IN "
                         "(SELECT id FROM source_reports WHERE org_id LIKE 'TEST%')")
            conn.execute("DELETE FROM source_reports WHERE org_id LIKE 'TEST%'")
            conn.execute("DELETE FROM issuers WHERE org_id LIKE 'TEST%'")
            conn.commit()
        finally:
            conn.close()
        yield
        conn = provenance._conn()
        try:
            conn.execute("DELETE FROM report_figures WHERE report_id IN "
                         "(SELECT id FROM source_reports WHERE org_id LIKE 'TEST%')")
            conn.execute("DELETE FROM source_reports WHERE org_id LIKE 'TEST%'")
            conn.execute("DELETE FROM issuers WHERE org_id LIKE 'TEST%'")
            conn.commit()
        finally:
            conn.close()

    def test_a_report_is_registered_once_per_period(self):
        a = provenance.upsert_report("TEST1", "NSBU", "quarter", 2026, 1, pdf_url="u")
        b = provenance.upsert_report("TEST1", "NSBU", "quarter", 2026, 1, pdf_url="u")
        assert a == b

    def test_a_replaced_file_sends_the_report_back_to_be_parsed_again(self):
        """The source is entitled to re-upload; that has to be caught, not ignored."""
        rid = provenance.upsert_report("TEST1", "NSBU", "year", 2025,
                                       hash_value=provenance.file_hash("v1"))
        provenance.set_state(rid, "published")
        provenance.upsert_report("TEST1", "NSBU", "year", 2025,
                                 hash_value=provenance.file_hash("v2"))
        assert provenance.report(rid)["state"] == "discovered"

    def test_figures_carry_the_page_and_the_label_they_came_from(self):
        rid = provenance.upsert_report("TEST2", "NSBU", "quarter", 2026, 1)
        provenance.record_figures(rid, [{"field": "revenue", "value": 31_379_733_363_530.0,
                                         "unit_scale": 1, "page": 4,
                                         "raw_label": "Выручка от реализации"}])
        figures = provenance.report(rid)["figures"]
        assert figures[0]["page"] == 4
        assert figures[0]["raw_label"] == "Выручка от реализации"

    def test_a_rejected_report_stays_with_its_reason(self):
        """'We have the report and could not parse it' is information."""
        rid = provenance.upsert_report("TEST3", "NSBU", "quarter", 2026, 1)
        provenance.set_state(rid, "rejected", "FIN-03: выручка 6 мес превышает годовую в 131 раз")
        row = provenance.report(rid)
        assert row["state"] == "rejected" and "FIN-03" in row["state_reason"]
        assert row["used_by"]["financials"] is False

    def test_counters_and_the_list_come_from_one_query(self):
        """85 against 73 was two queries nobody compared."""
        conn = provenance._conn()
        try:
            conn.execute("INSERT INTO issuers (org_id, name, synced_at) VALUES "
                         "('TEST9','Acme','2026-08-01T00:00:00+00:00')")
            conn.commit()
        finally:
            conn.close()
        provenance.upsert_report("TEST9", "NSBU", "year", 2025)
        summary = provenance.summary()
        assert summary["issuers"] == len(summary["items"])
        assert summary["reports_total"] == sum(i["reports"] for i in summary["items"])

    def test_staleness_is_a_stated_fact(self):
        """ТЗ Б.6: the catalog was ten days behind the market and the screen
        showed only a date. Age is measured from the MOST RECENT sync, so the
        clock is moved rather than a stale row planted — a fresher real row
        would otherwise dominate the maximum and make the assertion meaningless.
        """
        from datetime import datetime, timedelta, timezone

        conn = provenance._conn()
        try:
            conn.execute("INSERT INTO issuers (org_id, name, synced_at) VALUES "
                         "('TEST8','Old','2026-07-21T15:26:17+00:00')")
            conn.commit()
        finally:
            conn.close()
        fresh = provenance.summary()
        assert fresh["last_sync"] is not None
        anchor = datetime.fromisoformat(fresh["last_sync"])
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        summary = provenance.summary(now=anchor + timedelta(days=10))
        assert summary["staleness_hours"] == pytest.approx(240.0, abs=1.0)
        assert summary["is_stale"] is True
        # ...and inside the window it is not stale.
        assert provenance.summary(now=anchor + timedelta(hours=2))["is_stale"] is False

    def test_the_queue_holds_what_has_not_been_parsed(self):
        rid = provenance.upsert_report("TEST4", "NSBU", "quarter", 2026, 2)
        provenance.set_state(rid, "parse_failed", "таблица не распознана")
        assert any(r["id"] == rid for r in provenance.queue())

    def test_an_unknown_state_is_refused(self):
        rid = provenance.upsert_report("TEST5", "NSBU", "year", 2024)
        with pytest.raises(ValueError):
            provenance.set_state(rid, "probably-fine")

    def test_bond_reference_round_trips(self):
        provenance.upsert_bond_reference([{"ticker": "ZZB1", "nominal": 100_000.0,
                                           "coupon_rate": 12.0, "coupon_freq": 2,
                                           "maturity_date": "2029-01-01"}])
        try:
            stored = provenance.bond_references()["ZZB1"]
            assert stored["nominal"] == pytest.approx(100_000.0)
            assert bonds.reference_state(stored)["is_complete"] is True
        finally:
            conn = provenance._conn()
            conn.execute("DELETE FROM bond_reference WHERE ticker='ZZB1'")
            conn.commit()
            conn.close()


# ---------------------------------------------------------------------------
# Parallel-run rollout (ТЗ §11.6)
# ---------------------------------------------------------------------------

class TestRollout:
    def test_identical_implementations_are_ready(self):
        import rollout

        report = rollout.compare(["A", "B"], lambda s: {"pe": 8.0}, lambda s: {"pe": 8.0})
        assert report["identical"] == 2 and report["ready_to_enable"] is True

    def test_float_noise_is_not_a_difference(self):
        import rollout

        report = rollout.compare(["A"], lambda s: {"v": 1.0000000001}, lambda s: {"v": 1.0})
        assert report["identical"] == 1

    def test_an_unexplained_difference_blocks_the_flag(self):
        """ТЗ §11.6: every change must have a cause named in the specification."""
        import rollout

        report = rollout.compare(["KFSK"], lambda s: {"pe": 203.56}, lambda s: {"pe": 8.4})
        assert report["ready_to_enable"] is False
        assert report["unexplained"][0]["subject"] == "KFSK"

    def test_an_explained_difference_does_not(self):
        import rollout

        report = rollout.compare(
            ["KFSK"], lambda s: {"pe": 203.56}, lambda s: {"pe": 8.4},
            explain=lambda s, a, b: "ТЗ §8: P/E теперь считается от прибыли эмитента")
        assert report["ready_to_enable"] is True
        assert report["differences"][0]["explained"] is True

    def test_a_failing_subject_is_recorded_not_raised(self):
        import rollout

        def boom(_s):
            raise RuntimeError("history unavailable")

        report = rollout.compare(["X"], boom, lambda s: {})
        assert report["failures"][0]["subject"] == "X"
        assert report["ready_to_enable"] is False


# ---------------------------------------------------------------------------
# The registry is FED, not merely built (ТЗ Дополнение 1 §Б.2)
# ---------------------------------------------------------------------------

class TestProvenanceWiring:
    """A provenance layer nothing writes to is a well-tested empty room.

    These pin the connection: the catalog seeds the registry, a parse moves the
    report through its states, and the published figure names the report.
    """

    @pytest.fixture(autouse=True)
    def seeded_catalog(self, monkeypatch, tmp_path):
        """Exercise the real registry with owned data, not a developer's cache."""
        import reports_catalog as rc
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.sqlite3"))
        monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *args, **kwargs: None)
        conn = rc.get_catalog_conn()
        try:
            conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)",
                         ("ZZSEED", "Provenance test issuer", "TESTSEED"))
            conn.execute("INSERT INTO catalog_reports (ticker, report_form, period_type, year, quarter, excel_url) "
                         "VALUES (?,?,?,?,?,?)", ("ZZSEED", "NSBU", "annual", 2025, 0, "https://example.org/filing.xlsx"))
            conn.commit()
        finally:
            conn.close()
        rc.upsert_financials_cache("ZZSEED", "NSBU", 2025, 0, {"revenue": 1000, "net_income": 100})

    def test_the_catalog_seeds_the_registry(self):
        result = provenance.sync_from_catalog()
        summary = provenance.summary()
        assert result["issuers"] > 0
        # ТЗ Б.1: the list is ISSUERS, not tickers — 73 rows are 66 organisations.
        assert summary["issuers"] == len(summary["items"])
        assert summary["reports_total"] == sum(i["reports"] for i in summary["items"])

    def test_registering_twice_does_not_reset_a_parsed_report(self):
        provenance.sync_from_catalog()
        rows = provenance.queue(1)
        if not rows:
            pytest.skip("no catalogued reports in this environment")
        report_id = rows[0]["id"]
        provenance.set_state(report_id, "validated")
        provenance.sync_from_catalog()
        assert provenance.report(report_id)["state"] == "validated"

    def _own_report(self, quarter=None):
        """A report this test owns.

        Picking one off the shared queue made these tests order-dependent: an
        earlier test moves a report out of `discovered` and the next one asserts
        against a different row. Each creates its own instead.
        """
        import reports_catalog as rc

        org = "TESTWIRE"
        conn = provenance._conn()
        try:
            conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) "
                         "VALUES (?,?,?) ON CONFLICT(ticker) DO UPDATE SET org_id=excluded.org_id",
                         ("ZZWIRE", "Wire Test", org))
            conn.commit()
        finally:
            conn.close()
        year = 2001 if quarter is None else 2002
        report_id = provenance.upsert_report(org, "NSBU",
                                             "annual" if quarter is None else "quarter",
                                             year, quarter)
        return rc, "ZZWIRE", report_id, year, quarter

    def test_a_parse_records_its_figures_and_returns_the_link(self):
        rc, ticker, report_id, year, quarter = self._own_report()
        got = rc._register_parse(ticker, "NSBU", year, quarter, {"ok": True},
                                 {"revenue": 1000.0, "net_income": 100.0})
        assert got == report_id
        stored = provenance.report(report_id)
        assert stored["state"] == "validated"
        assert {f["field"] for f in stored["figures"]} == {"revenue", "net_income"}
        assert stored["used_by"]["financials"] is True

    def test_a_report_that_yields_nothing_keeps_its_reason(self):
        rc, ticker, report_id, year, quarter = self._own_report(quarter=3)
        rc._register_parse(ticker, "NSBU", year, quarter, {"ok": True}, {})
        stored = provenance.report(report_id)
        assert stored["state"] == "parse_failed" and stored["state_reason"]

    def test_a_download_failure_is_a_state_not_a_silence(self):
        rc, ticker, report_id, year, quarter = self._own_report(quarter=4)
        rc._register_parse(ticker, "NSBU", year, quarter, {"ok": False, "error": "404"}, {})
        assert provenance.report(report_id)["state"] == "download_failed"

    def test_an_unregistered_report_publishes_without_a_link(self):
        """A missing link is a finding (SRC-03), not something to paper over."""
        import reports_catalog as rc

        assert rc._register_parse("NOSUCHTICKER", "NSBU", 1999, None,
                                  {"ok": True}, {"revenue": 1.0}) is None

    def test_published_figures_expose_their_source(self):
        import reports_catalog as rc

        rows = rc.get_all_financials()
        assert rows, "no financials in this environment"
        assert all("report_id" in row for row in rows.values())

    def test_the_backfill_links_figures_cached_before_provenance_existed(self):
        """Every cached row came from the filing for its own period — that
        mapping is deterministic, so the link is recovered without re-downloading.
        """
        import reports_catalog as rc

        result = rc.backfill_report_links()
        assert set(result) == {"linked", "unresolved"}
        rows = rc.get_all_financials()
        if not rows:
            pytest.skip("no financials in this environment")
        linked = sum(1 for v in rows.values() if v.get("report_id"))
        # Not "all": a row whose report is absent from the catalog stays unlinked
        # on purpose, and SRC-03 reports it rather than a guess being recorded.
        assert linked > 0
        for row in rows.values():
            if row.get("report_id"):
                stored = provenance.report(row["report_id"])
                assert stored is not None
                assert stored["state"] in provenance.PUBLISHABLE

    def test_the_backfill_is_idempotent(self):
        import reports_catalog as rc

        rc.backfill_report_links()
        second = rc.backfill_report_links()
        assert second["linked"] == 0


class TestRegisterCost:
    """/api/admin/catalog/register has to fit in the collector's HTTP timeout.

    It walked the catalog a row at a time — a SELECT and a write per filing, and
    the whole walk twice because the backfill re-seeded the registry the caller
    had just seeded. That is free against a local SQLite file and 7 670 network
    round trips against PostgreSQL: the collector's 120s read timeout expired
    mid-request and the daily run went red on 2026-08-03. What must not come
    back is the SCALING, so that is what these measure.
    """

    def _count_statements(self, monkeypatch) -> dict[str, int]:
        import dbx

        counter = {"n": 0}
        raw_execute, raw_many = dbx.Cursor.execute, dbx.Cursor.executemany

        def execute(self, sql, params=None):
            counter["n"] += 1
            return raw_execute(self, sql, params)

        def executemany(self, sql, seq):
            counter["n"] += 1          # one batch is one round trip
            return raw_many(self, sql, seq)

        monkeypatch.setattr(dbx.Cursor, "execute", execute)
        monkeypatch.setattr(dbx.Cursor, "executemany", executemany)
        return counter

    def test_registering_does_not_scale_with_the_catalog(self, monkeypatch):
        import reports_catalog as rc

        conn = rc.get_catalog_conn()
        try:
            catalogued = conn.execute(
                "SELECT COUNT(*) AS n FROM catalog_reports WHERE year IS NOT NULL"
            ).fetchone()["n"]
        finally:
            conn.close()
        if catalogued < 50:
            pytest.skip("catalog too small for the cost to say anything")

        # Warm the pool first: schema DDL is applied once per physical
        # connection, and the steady state is what a running server pays.
        provenance.sync_from_catalog()
        rc.backfill_report_links(seed=False)

        counter = self._count_statements(monkeypatch)
        provenance.sync_from_catalog()
        rc.backfill_report_links(seed=False)
        # A constant, not one per filing. The bound is loose on purpose — the
        # order of magnitude is the assertion, not the exact count.
        assert counter["n"] < 50, f"{counter['n']} statements for {catalogued} filings"

    def test_two_tickers_of_one_issuer_collapse_to_one_report(self):
        """A batch cannot deduplicate by re-reading its own writes.

        ALKB and ALKBP are Aloqabank: the catalog holds one filing under both
        tickers and the registry's UNIQUE key holds it once. The row-at-a-time
        loop collapsed them by accident — the batch has to mean it, or the whole
        insert is rejected.
        """
        org, tickers = "TESTDUP", ("ZZDUPA", "ZZDUPB")
        self._purge(org, tickers)
        conn = provenance._conn()
        try:
            for ticker in tickers:
                conn.execute(
                    "INSERT INTO catalog_companies (ticker, company_name, org_id) "
                    "VALUES (?,?,?) ON CONFLICT(ticker) DO UPDATE SET org_id=excluded.org_id",
                    (ticker, "Dup Test", org))
                conn.execute(
                    "INSERT INTO catalog_reports (ticker, report_form, period_type, "
                    "year, quarter, pdf_url) VALUES (?,?,?,?,?,?)",
                    (ticker, "NSBU", "annual", 2003, 0,
                     "http://example/b.pdf" if ticker == "ZZDUPB" else None))
            conn.commit()
        finally:
            conn.close()

        try:
            provenance.sync_from_catalog()
            conn = provenance._conn()
            try:
                rows = conn.execute(
                    "SELECT id, pdf_url FROM source_reports WHERE org_id=?", (org,)).fetchall()
            finally:
                conn.close()
            assert len(rows) == 1
            # COALESCE precedence survives the merge: the non-null url wins,
            # whichever order the two rows arrive in.
            assert rows[0]["pdf_url"] == "http://example/b.pdf"
        finally:
            self._purge(org, tickers)

    @staticmethod
    def _purge(org, tickers):
        marks = ",".join("?" * len(tickers))
        conn = provenance._conn()
        try:
            conn.execute("DELETE FROM report_figures WHERE report_id IN "
                         "(SELECT id FROM source_reports WHERE org_id = ?)", (org,))
            conn.execute("DELETE FROM source_reports WHERE org_id = ?", (org,))
            conn.execute(f"DELETE FROM catalog_reports WHERE ticker IN ({marks})", tickers)
            conn.execute(f"DELETE FROM catalog_companies WHERE ticker IN ({marks})", tickers)
            conn.commit()
        finally:
            conn.close()


@pytest.fixture(autouse=True, scope="module")
def _clean_wire_fixtures():
    """Remove the rows TestProvenanceWiring creates for itself."""
    yield
    conn = provenance._conn()
    try:
        conn.execute("DELETE FROM report_figures WHERE report_id IN "
                     "(SELECT id FROM source_reports WHERE org_id = 'TESTWIRE')")
        conn.execute("DELETE FROM source_reports WHERE org_id = 'TESTWIRE'")
        conn.execute("DELETE FROM catalog_companies WHERE ticker = 'ZZWIRE'")
        conn.commit()
    finally:
        conn.close()
