"""Statement validation and ISSUER-level multiples (ТЗ v1.2 §7/§8).

The defects pinned here, all reproduced against the live caches first:

  * P/E and P/B divided ONE share class's capitalisation by the WHOLE issuer's
    profit. 17 issuers in the catalog list two classes, so no pair of them could
    agree — KFSK showed 203.6 against KFSKP's 0.19 off one profit.
  * impossible statements were published as numbers: 12 of 68 cached rows fail
    an internal-consistency check (TGPG reports gross profit above revenue AND a
    net loss five times revenue; ALKB's stored profit implies a 3 038 % return
    against its own published 6.54 %).
  * ROE was printed at 10 715.33 % (UTGA/UTGAP, 2023) and 179.26 % (UZMT, 2019)
    and sorted beside real ones.
  * a loss-maker got a negative P/E that sorted as if it were cheap.
  * total market capitalisation summed bonds and dormant listings into one
    headline "market" figure.
"""
from __future__ import annotations

import pytest

import fundamentals


def stmt(**kw):
    base = {"year": 2025, "quarter": 0, "period_months": 12,
            "revenue": 1000.0, "gross_profit": 400.0, "net_income": 200.0,
            "total_liabilities": 500.0}
    base.update(kw)
    return base


def ratio(**kw):
    base = {"total_equity": 1000.0, "total_assets": 2000.0, "roe": 20.0,
            "roa": 10.0, "net_profit_margin": 20.0, "debt_to_equity": 0.5,
            "period": "2025"}
    base.update(kw)
    return base


def cls(ticker, cap=None, shares=None, preferred=False, name="Acme", price=None):
    # A coherent class by default: capitalisation IS price x shares, so the
    # share-count check passes and tests exercise what they mean to.
    if price is None and cap and shares:
        price = cap / shares
    return {"ticker": ticker, "name": name, "market_cap": cap, "last_price": price,
            "shares_outstanding": shares, "is_preferred": preferred, "type": "stock"}


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

class TestPeriods:
    def test_cumulative_quarter_is_not_three_months(self):
        assert fundamentals.period_months({"year": 2026, "quarter": 2}) == 6
        assert fundamentals.period_months({"year": 2026, "quarter": 0}) == 12

    def test_annualise_makes_a_sort_comparable(self):
        assert fundamentals.annualise(300.0, 3) == pytest.approx(1200.0)
        assert fundamentals.annualise(600.0, 6) == pytest.approx(1200.0)
        assert fundamentals.annualise(1200.0, 12) == pytest.approx(1200.0)
        assert fundamentals.annualise(None, 3) is None
        assert fundamentals.annualise(300.0, 0) is None

    def test_parse_period(self):
        assert fundamentals.parse_period("2025") == (2025, 12)
        assert fundamentals.parse_period("2025A") == (2025, 12)
        assert fundamentals.parse_period("2026Q2") == (2026, 6)
        assert fundamentals.parse_period("nonsense") is None

    def test_comparable_period_is_the_latest_everyone_has(self):
        fins = {
            "A": {"year": 2025, "quarter": 0, "period_months": 12},
            "B": {"year": 2026, "quarter": 1, "period_months": 3,
                  "annual": {"year": 2025, "quarter": 0, "net_income": 1}},
        }
        assert fundamentals.comparable_period(fins) == (2025, 12)

    def test_no_shared_period_is_reported_as_none(self):
        fins = {"A": {"year": 2025, "quarter": 0}, "B": {"year": 2019, "quarter": 0}}
        assert fundamentals.comparable_period(fins) is None


# ---------------------------------------------------------------------------
# Statement validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_a_sound_statement_passes(self):
        got = fundamentals.validate_statement(stmt(), ratio())
        assert got["valid"] is True and got["reasons"] == []

    def test_gross_profit_above_revenue_is_rejected(self):
        got = fundamentals.validate_statement(stmt(gross_profit=-1500.0), ratio())
        assert got["valid"] is False
        assert "gross_gt_revenue" in got["fields"]["gross_profit"]

    def test_net_income_far_above_revenue_is_rejected(self):
        got = fundamentals.validate_statement(stmt(net_income=-3250.0), ratio())
        assert "net_gt_revenue" in got["fields"]["net_income"]

    def test_negative_equity_is_rejected(self):
        got = fundamentals.validate_statement(stmt(), ratio(total_equity=-5.0))
        assert "equity_not_positive" in got["fields"]["total_equity"]

    def test_profit_inconsistent_with_equity_and_published_roe(self):
        """ALKB: a stored profit implying 3 038 % against a reported 6.54 %."""
        got = fundamentals.validate_statement(
            stmt(net_income=30_000.0), ratio(total_equity=1000.0, roe=6.54))
        assert got["valid"] is False
        assert "net_vs_equity_roe" in got["fields"]["net_income"]

    def test_that_check_does_not_fire_across_periods(self):
        """A Q1 profit against an annual ROE differs by four for a healthy issuer."""
        got = fundamentals.validate_statement(
            stmt(year=2026, quarter=1, period_months=3, net_income=50.0),
            ratio(period="2021", roe=25.48))
        assert "net_vs_equity_roe" not in got["fields"].get("net_income", [])

    def test_liabilities_vs_assets_only_within_one_period(self):
        same = fundamentals.validate_statement(
            stmt(total_liabilities=9_000.0), ratio(total_assets=2000.0, period="2025"))
        assert "liab_gt_assets" in same["fields"].get("total_liabilities", [])
        cross = fundamentals.validate_statement(
            stmt(total_liabilities=9_000.0), ratio(total_assets=2000.0, period="2019"))
        assert "total_liabilities" not in cross["fields"]

    def test_missing_statement_is_its_own_status(self):
        got = fundamentals.validate_statement(None, ratio())
        assert got["status"] == fundamentals.STATUS_NO_FINANCIALS


# ---------------------------------------------------------------------------
# Issuers
# ---------------------------------------------------------------------------

class TestIssuerGrouping:
    def test_share_classes_of_one_issuer_group_together(self):
        rows = [cls("AGBA", name="Agrobank"), cls("AGBAP", name="Agrobank", preferred=True)]
        groups = fundamentals.group_by_issuer(rows)
        assert len(groups) == 1
        assert sorted(c["ticker"] for c in next(iter(groups.values()))) == ["AGBA", "AGBAP"]

    def test_legal_form_and_apostrophes_do_not_split_an_issuer(self):
        a = fundamentals.issuer_key({"ticker": "UPOS", "name": "O‘zbekiston pochtasi AJ"})
        b = fundamentals.issuer_key({"ticker": "UPOSP", "name": "O'zbekiston Pochtasi"})
        assert a == b

    def test_bonds_never_enter_an_issuer_group(self):
        rows = [cls("X", name="Acme"), {**cls("XB1", name="Acme"), "type": "bond"}]
        groups = fundamentals.group_by_issuer(rows)
        assert [c["ticker"] for c in next(iter(groups.values()))] == ["X"]


class TestIssuerCapitalisation:
    def test_capitalisation_is_the_sum_over_classes(self):
        got = fundamentals.market_cap_issuer([cls("A", cap=100.0), cls("AP", cap=25.0)])
        assert got["value"] == pytest.approx(125.0) and got["status"] == "ok"

    def test_a_missing_class_makes_the_sum_null_not_partial(self):
        got = fundamentals.market_cap_issuer([cls("A", cap=100.0), cls("AP", cap=None)])
        assert got["value"] is None
        assert got["status"] == "incomplete" and got["missing_classes"] == ["AP"]


# ---------------------------------------------------------------------------
# Multiples — the invariant of §8
# ---------------------------------------------------------------------------

class TestMultiples:
    def _issuer(self, **kw):
        classes = [cls("A", cap=800.0, shares=100.0), cls("AP", cap=200.0, shares=25.0)]
        # roe=None by default: these tests vary net income on purpose, and the
        # profit-vs-published-ROE cross-check would reject the fixture instead of
        # letting the multiple under test be computed.
        rat = {"roe": None}
        rat.update(kw.pop("rat", {}))
        return fundamentals.issuer_multiples(classes, stmt(**kw.pop("fin", {})),
                                             ratio(**rat), kw.pop("earn", None))

    def test_pe_divides_the_issuer_capitalisation(self):
        got = self._issuer()
        # (800 + 200) / 200 = 5, not 800/200 and not 200/200.
        assert got["pe"]["value"] == pytest.approx(5.0)
        assert got["market_cap_issuer"]["value"] == pytest.approx(1000.0)

    def test_both_classes_receive_the_same_multiples(self):
        classes = [cls("A", cap=800.0, shares=100.0), cls("AP", cap=200.0, shares=25.0)]
        a = fundamentals.issuer_multiples(classes, stmt(), ratio())
        b = fundamentals.issuer_multiples(list(reversed(classes)), stmt(), ratio())
        for field in ("pe", "pb", "roe", "roa"):
            assert a[field]["value"] == b[field]["value"]

    def test_a_loss_says_loss_rather_than_a_negative_multiple(self):
        got = self._issuer(fin={"net_income": -50.0, "revenue": 1000.0})
        assert got["pe"]["value"] is None
        assert got["pe"]["status"] == fundamentals.STATUS_LOSS

    def test_pe_outside_the_range_is_withheld(self):
        got = self._issuer(fin={"net_income": 1.0})       # P/E = 1000
        assert got["pe"]["value"] is None
        assert got["pe"]["status"] == fundamentals.STATUS_OUT_OF_RANGE
        assert got["pe"]["computed"] == pytest.approx(1000.0)

    def test_roe_beyond_a_hundred_percent_is_withheld(self):
        """UTGA/UTGAP published 10 715.33 % (2023); UZMT 179.26 % (2019).

        No statement here, so nothing else can suppress the figure — the range
        check alone has to catch it.
        """
        classes = [cls("A", cap=800.0, shares=100.0)]
        got = fundamentals.issuer_multiples(classes, None, ratio(roe=10715.33))
        assert got["roe"]["value"] is None
        assert got["roe"]["status"] == fundamentals.STATUS_OUT_OF_RANGE
        assert got["roe"]["computed"] == pytest.approx(10715.33)

    def test_a_wildly_published_roe_also_invalidates_the_statement(self):
        """When both exist and disagree by 500x, the ROW is what is in doubt."""
        got = self._issuer(rat={"roe": 10715.33})
        assert got["roe"]["value"] is None
        assert got["roe"]["status"] == fundamentals.STATUS_UNVERIFIED

    def test_an_unverified_statement_produces_no_multiple_at_all(self):
        got = self._issuer(fin={"gross_profit": -5000.0})
        for field in ("pe", "pb", "roe", "roa"):
            assert got[field]["value"] is None
            assert got[field]["status"] == fundamentals.STATUS_UNVERIFIED

    def test_a_capitalisation_that_contradicts_the_price_suppresses_multiples(self):
        """The units error ТЗ §8 saw: a cap a thousand times price x shares."""
        classes = [cls("A", cap=800_000.0, shares=100.0, price=8.0),
                   cls("AP", cap=200.0, shares=25.0, price=8.0)]
        got = fundamentals.issuer_multiples(classes, stmt(), ratio(roe=None))
        assert got["shares_check"]["consistent"] is False
        assert got["shares_check"]["findings"][0]["looks_like_thousands"] is True
        assert got["pe"]["status"] == fundamentals.STATUS_INCONSISTENT
        assert got["pb"]["status"] == fundamentals.STATUS_INCONSISTENT

    def test_classes_of_different_size_are_not_an_error(self):
        """One class holding four times the shares of another is ordinary."""
        classes = [cls("A", cap=800.0, shares=100.0), cls("AP", cap=200.0, shares=25.0)]
        got = fundamentals.issuer_multiples(classes, stmt(), ratio(roe=None))
        assert got["shares_check"]["consistent"] is True
        assert got["pe"]["value"] is not None

    def test_book_value_per_share_uses_every_share_the_issuer_issued(self):
        classes = [cls("A", cap=800.0, shares=100.0), cls("AP", cap=200.0, shares=25.0)]
        got = fundamentals.bvps_issuer(classes, equity=1000.0)
        assert got["value"] == pytest.approx(1000.0 / 125.0)
        assert got["shares_outstanding"] == pytest.approx(125.0)

    def test_book_value_is_null_when_a_class_has_no_share_count(self):
        got = fundamentals.bvps_issuer([cls("A", cap=800.0, shares=None)], equity=1000.0)
        assert got["value"] is None and got["status"] == "no_share_count"

    def test_earnings_override_carries_its_period(self):
        got = self._issuer(earn={"net_income": 100.0, "period": "2025A", "months": 12})
        assert got["pe"]["value"] == pytest.approx(10.0)
        assert got["pe"]["base_period"] == "2025A"


# ---------------------------------------------------------------------------
# Market capitalisation
# ---------------------------------------------------------------------------

class TestMarketCapitalisation:
    def test_bonds_and_dormant_listings_are_excluded_and_reported(self):
        board = [
            {"ticker": "A", "market_cap": 100.0, "type": "stock"},
            {"ticker": "B", "market_cap": 50.0, "type": "bond"},
            {"ticker": "C", "market_cap": 30.0, "type": "stock", "inactive": True},
        ]
        got = fundamentals.market_capitalisation(board)
        assert got["value"] == pytest.approx(100.0)
        assert got["instruments"] == 1
        assert got["excluded"]["bonds"]["amount"] == pytest.approx(50.0)
        assert got["excluded"]["inactive_listings"]["amount"] == pytest.approx(30.0)

    def test_absent_capitalisation_is_not_counted_as_zero(self):
        board = [{"ticker": "A", "market_cap": None, "type": "stock"}]
        got = fundamentals.market_capitalisation(board)
        assert got["value"] == 0.0 and got["instruments"] == 0
