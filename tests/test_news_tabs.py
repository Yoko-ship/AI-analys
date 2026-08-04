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
