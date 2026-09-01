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


class TestRegulatoryIsServedFromPrimarySources:
    """Regulatory cards come only from NAPP and OpenInfo, in every feed view."""

    def _sql(self, monkeypatch, news_type):
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

    def test_the_allowlist_is_exactly_napp_and_openinfo(self) -> None:
        assert ns.REGULATORY_SOURCE_IDS == {"napp", "openinfo_facts"}

    @pytest.mark.parametrize("news_type", ["regulatory", "economy", None])
    def test_regulatory_rows_are_restricted_in_every_view(self, monkeypatch, news_type) -> None:
        seen = self._sql(monkeypatch, news_type)

        assert "p.type <> ? OR COALESCE(n.source_id, '') IN (?,?)" in seen["sql"]
        assert "regulatory" in seen["params"]
        assert "napp" in seen["params"]
        assert "openinfo_facts" in seen["params"]

    def test_short_read_paths_drop_other_regulatory_sources(self, monkeypatch) -> None:
        monkeypatch.setattr(ns, "hidden_source_ids", lambda: set())
        items = [
            {"id": 1, "type": "regulatory", "source_id": "napp"},
            {"id": 2, "type": "regulatory", "source_id": "openinfo_facts"},
            {"id": 3, "type": "regulatory", "source_id": "cbu"},
            {"id": 4, "type": "market", "source_id": "cbu"},
        ]

        assert [item["id"] for item in ns.drop_hidden(items)] == [1, 2, 4]


class TestCorporateIsServedFromTheFilings:
    """«Корпоративные» carries the issuers' own disclosures (customer, 2026-08-11).

    A filing on openinfo is the primary record — dated, complete, naming its issuer in
    the field the instrument split reads. A paper's write-up of the same filing arrives
    later, names the company loosely, and puts a second card under one fact. So the
    corporate CLASSES are served from the disclosure sources; the other two, and the
    «Все» tab that asks for no class at all, keep every source.
    """
    def _sql(self, monkeypatch, news_type):
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

    def test_the_registry_names_openinfo_as_the_disclosure_source(self) -> None:
        assert "openinfo_facts" in ns.disclosure_source_ids()

    def test_a_corporate_request_is_narrowed_to_them(self, monkeypatch) -> None:
        seen = self._sql(monkeypatch, "corporate")

        assert "p.type NOT IN (?,?) OR COALESCE(n.source_id, '') IN (?)" in seen["sql"]
        assert "openinfo_facts" in seen["params"]

    def test_a_bare_corporate_class_is_narrowed_too(self, monkeypatch) -> None:
        """The tab is one caller; the rule belongs to the class, not to the tab."""
        seen = self._sql(monkeypatch, "financial_report")

        assert "COALESCE(n.source_id, '') IN (?)" in seen["sql"]
        # The clause is appended last, ahead of LIMIT's own parameter.
        assert seen["params"][-3:-1] == ["financial_report", "openinfo_facts"]

    def test_economy_does_not_apply_the_corporate_source_rule(self, monkeypatch) -> None:
        assert "p.type NOT IN" not in self._sql(monkeypatch, "economy")["sql"]

    def test_all_keeps_every_source(self, monkeypatch) -> None:
        """«Все» claims to be one mixed feed, so it must not quietly be two."""
        assert "p.type NOT IN" not in self._sql(monkeypatch, None)["sql"]

    def test_a_mixed_request_narrows_only_its_corporate_half(self, monkeypatch) -> None:
        """Written per type, so an economy item is not judged by a corporate rule."""
        seen = self._sql(monkeypatch, "economy,corporate_event")

        assert "p.type NOT IN (?) OR" in seen["sql"]
        # Both halves are asked for…
        assert seen["params"][:3] == ["market", "regulatory", "corporate_event"]
        # …but the narrowing names the corporate class alone, so economy passes it.
        assert seen["params"][-3:-1] == ["corporate_event", "openinfo_facts"]

    def test_an_unreadable_registry_leaves_the_tab_full(self, monkeypatch) -> None:
        """Fail-soft in the direction that shows too much, never too little."""
        monkeypatch.setattr(ns, "_disclosure_ids", None)
        monkeypatch.setattr(ns, "_ORIGINS_FILE", "no/such/news_sources.json")
        try:
            assert ns.disclosure_source_ids() == set()
            assert "p.type NOT IN" not in self._sql(monkeypatch, "corporate")["sql"]
        finally:
            ns._disclosure_ids = None


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


class TestNothingFallsBetweenTheTwoTabs:
    """The traded universe is not the listed one, and the split must survive it.

    `securities` is filled from the exchange feed, so it knows only what trades:
    the eleven dormant listings (AGMK, TGBK, UZNG…) are absent from it. Typing
    the split off that map alone dropped their filings out of «Акции» AND
    «Облигации» without a word — the exact silence ТЗ §4 exists to prevent.
    """
    def test_a_dormant_listing_is_still_a_share(self) -> None:
        """UZNG has not traded in months; its filings are still shareholders'."""
        types = {"UZNGP": "stock", "UZNG": "stock"}   # UZNG from the registry
        items = [{"id": 1, "tickers": ["UZNG"]}]

        assert [i["id"] for i in ns.filter_by_instrument(items, "stock", types)] == [1]

    def test_a_ticker_the_catalog_cannot_type_is_reported_not_swallowed(self) -> None:
        items = [{"id": 1, "tickers": ["HMKB"]}, {"id": 2, "tickers": ["TNGB"]}]
        types = {"HMKB": "stock"}

        assert ns.untyped_named_tickers(items, types) == ["TNGB"]

    def test_an_item_with_no_ticker_is_not_reported_as_untyped(self) -> None:
        """It names no instrument; that is not a gap in the catalog."""
        assert ns.untyped_named_tickers([{"id": 1, "tickers": []}], {"HMKB": "stock"}) == []

    def test_an_item_typed_as_the_other_kind_is_not_reported(self) -> None:
        """Excluded on purpose, not for want of an answer."""
        items = [{"id": 1, "tickers": ["BFMT2B5"]}]

        assert ns.untyped_named_tickers(items, {"BFMT2B5": "bond"}) == []

    def test_a_partly_typed_item_is_not_reported(self) -> None:
        """One known ticker is enough to place the filing."""
        items = [{"id": 1, "tickers": ["TNGB", "HMKB"]}]

        assert ns.untyped_named_tickers(items, {"HMKB": "stock"}) == []

    def test_the_feed_reports_what_it_could_not_place(self, monkeypatch) -> None:
        rows = [{"id": 1, "tickers": ["HMKB"]}, {"id": 2, "tickers": ["TNGB"]}]

        class _Conn:
            def execute(self, sql, params):
                return self

            def fetchall(self):
                return rows

            def close(self):
                return None

        monkeypatch.setattr(ns.rc, "get_catalog_conn", lambda: _Conn())
        monkeypatch.setattr(ns, "_row_to_item", lambda r: dict(r))
        notes: dict = {}
        got = ns.get_news_feed(instrument="stock", ticker_types={"HMKB": "stock"},
                               notes=notes, order="recent", days=0)

        assert [i["id"] for i in got] == [1]
        assert notes["untyped_tickers"] == ["TNGB"]

    def test_no_instrument_asked_for_reports_nothing(self, monkeypatch) -> None:
        """«Все бумаги» hides nothing, so it has nothing to explain."""
        class _Conn:
            def execute(self, sql, params):
                return self

            def fetchall(self):
                return [{"id": 2, "tickers": ["TNGB"]}]

            def close(self):
                return None

        monkeypatch.setattr(ns.rc, "get_catalog_conn", lambda: _Conn())
        monkeypatch.setattr(ns, "_row_to_item", lambda r: dict(r))
        notes: dict = {}
        got = ns.get_news_feed(ticker_types={}, notes=notes, order="recent", days=0)

        assert [i["id"] for i in got] == [2]
        assert "untyped_tickers" not in notes
