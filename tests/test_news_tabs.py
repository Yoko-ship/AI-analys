"""The news section reads in two modes, over the classes we already assign.

§3.11 classifies every item into one of four types. "Экономика" and
"Корпоративные" are those four grouped in two — market + regulatory is the
market as a whole, corporate_event + financial_report is one issuer — so the
tabs are a filter on data we hold, not a second pipeline and not a second model
call. The grouping has to PARTITION the four: a class in neither group is a
story reachable from no tab, and a class in both puts the same story under two
headings.
"""
from __future__ import annotations

import typing

import pytest

import news_classifier as nc
import news_store as ns


class TestTheGroupsCoverEveryClass:
    def test_together_they_are_exactly_the_four_classes(self) -> None:
        grouped = [t for group in ns.NEWS_GROUPS.values() for t in group]

        assert set(grouped) == set(typing.get_args(nc.NewsType))
        assert len(grouped) == len(set(grouped))  # no class under two headings

    @pytest.mark.parametrize(("group", "types"), [
        ("economy", ["market", "regulatory"]),
        ("corporate", ["corporate_event", "financial_report"]),
    ])
    def test_each_group_resolves_to_its_classes(self, group, types) -> None:
        assert ns.resolve_news_types(group) == types


class TestWhatAFeedRequestMayAskFor:
    def test_a_bare_class_still_works(self) -> None:
        """The API took a single type before the tabs existed and still does."""
        assert ns.resolve_news_types("regulatory") == ["regulatory"]

    def test_a_comma_separated_list(self) -> None:
        assert ns.resolve_news_types("economy,corporate_event") == [
            "market", "regulatory", "corporate_event"]

    def test_a_list_is_deduplicated(self) -> None:
        assert ns.resolve_news_types(["market", "market", "economy"]) == ["market", "regulatory"]

    @pytest.mark.parametrize("empty", [None, "", "  ", [], ","])
    def test_nothing_asked_for_means_no_filter(self, empty) -> None:
        assert ns.resolve_news_types(empty) == []

    def test_an_unknown_name_is_passed_through_not_expanded(self) -> None:
        """A future class the tabs do not know must still be filterable."""
        assert ns.resolve_news_types("something_new") == ["something_new"]


class TestTheQueryItBuilds:
    def _rows(self, monkeypatch, news_type):
        seen = {}

        class _Conn:
            def execute(self, sql, params):
                seen["sql"], seen["params"] = sql, list(params)
                return self

            def fetchall(self):
                return []

            def close(self):
                return None

        monkeypatch.setattr(ns.rc, "get_catalog_conn", lambda: _Conn())
        ns.get_news_feed(news_type=news_type, order="recent", days=0)
        return seen

    def test_a_group_becomes_an_IN_clause(self, monkeypatch) -> None:
        seen = self._rows(monkeypatch, "economy")

        assert "p.type IN (?,?)" in seen["sql"]
        assert seen["params"][:2] == ["market", "regulatory"]

    def test_no_type_adds_no_clause(self, monkeypatch) -> None:
        seen = self._rows(monkeypatch, None)

        assert "p.type IN" not in seen["sql"]


class TestTheInstrumentSplit:
    """«Корпоративные» splits again by the instrument a filing is ABOUT.

    The classifier cannot make this split — a coupon payment and a dividend are
    both `corporate_event` — so it comes from the securities each item NAMES,
    typed by the catalog. Two properties matter: a filing that names both
    classes of one issuer reaches both readers, and an item that names nothing
    reaches neither, because "news about bonds" is a claim the silence does not
    support.
    """
    TYPES = {"HMKB": "stock", "HMKBP": "stock", "BFMT2B5": "bond", "ACMT1B2": "bond"}

    def _items(self):
        return [
            {"id": 1, "tickers": ["HMKB"]},
            {"id": 2, "tickers": ["BFMT2B5"]},
            {"id": 3, "tickers": ["HMKB", "BFMT2B5"]},
            {"id": 4, "tickers": []},
        ]

    def test_shares_keep_the_share_filings(self) -> None:
        kept = ns.filter_by_instrument(self._items(), "stock", self.TYPES)

        assert [i["id"] for i in kept] == [1, 3]

    def test_bonds_keep_the_bond_filings(self) -> None:
        kept = ns.filter_by_instrument(self._items(), "bond", self.TYPES)

        assert [i["id"] for i in kept] == [2, 3]

    def test_a_filing_naming_both_reaches_both_readers(self) -> None:
        """Not a duplicate — the same fact is relevant to two holders."""
        shares = ns.filter_by_instrument(self._items(), "stock", self.TYPES)
        bonds = ns.filter_by_instrument(self._items(), "bond", self.TYPES)

        assert 3 in [i["id"] for i in shares]
        assert 3 in [i["id"] for i in bonds]

    def test_an_item_naming_no_issuer_is_in_neither(self) -> None:
        for kind in ("stock", "bond"):
            assert 4 not in [i["id"] for i in ns.filter_by_instrument(self._items(), kind, self.TYPES)]

    @pytest.mark.parametrize("nothing", [None, "", "  ", "all", "равно_что_угодно"])
    def test_no_instrument_asked_for_filters_nothing(self, nothing) -> None:
        assert ns.filter_by_instrument(self._items(), nothing, self.TYPES) == self._items()

    def test_an_unknown_ticker_is_not_guessed_from_its_shape(self) -> None:
        """BFMT3V2 LOOKS like a bond; without the catalog we do not say so."""
        items = [{"id": 9, "tickers": ["BFMT3V2"]}]

        assert ns.filter_by_instrument(items, "bond", self.TYPES) == []

    def test_the_filter_runs_before_ranking(self, monkeypatch) -> None:
        """Filtering after the rank window would spend it on hidden stories."""
        rows = [{"id": 1, "tickers": ["HMKB"]}, {"id": 2, "tickers": ["BFMT2B5"]}]

        class _Conn:
            def execute(self, sql, params):
                return self

            def fetchall(self):
                return rows

            def close(self):
                return None

        monkeypatch.setattr(ns.rc, "get_catalog_conn", lambda: _Conn())
        monkeypatch.setattr(ns, "_row_to_item", lambda r: dict(r))
        seen = {}
        monkeypatch.setattr(ns, "_drop_noise", lambda items, _m: seen.setdefault("ranked", items) or items)
        monkeypatch.setattr(ns, "rank_score", lambda _i, _n: 1.0)
        monkeypatch.setattr(ns, "_dedupe_stories", lambda items, _s: items)
        monkeypatch.setattr(ns, "_balance_origins", lambda items, _l: items)

        ns.get_news_feed(instrument="bond", ticker_types=self.TYPES, days=0)

        assert [i["id"] for i in seen["ranked"]] == [2]
