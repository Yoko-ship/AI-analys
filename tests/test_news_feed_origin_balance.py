"""The English-language wires get half the page, or as much of it as they can fill.

Measured 2026-08-07 on the live feed: 200 cards, 4 of them from an international source. That
is not a ranking accident to be tuned away — the local outlets publish ~40 market items a day
and the agencies publish a handful a week, and `rank_score` rewards naming a ticker, which an
international story rarely does. Ranking alone therefore hands the page to one side.

So the two streams are ranked separately and interleaved to a target share. What this must
never do: reorder within a side (each keeps its own ranking), hold a slot open when one side
has nothing to put in it, or shorten the page.
"""
from __future__ import annotations

import pytest

import news_store


def _item(i: int, source_id: str) -> dict:
    return {"id": i, "source_id": source_id, "title": f"item {i}", "rank": 1.0 / (i + 1)}


@pytest.fixture(autouse=True)
def _known_origins(monkeypatch):
    monkeypatch.setattr(news_store, "_international_ids", {"fitch", "trend", "thediplomat"})


def _origins(items):
    return "".join("I" if it["source_id"] in {"fitch", "trend", "thediplomat"} else "L"
                   for it in items)


def test_a_half_and_half_page_when_both_sides_have_enough(monkeypatch):
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.5)
    items = [_item(i, "trend") for i in range(10)] + [_item(i + 10, "spot") for i in range(10)]

    out = news_store._balance_origins(items, 10)

    assert _origins(out) == "ILILILILIL"


def test_each_side_keeps_its_own_ranking(monkeypatch):
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.5)
    intl = [_item(i, "fitch") for i in (0, 1, 2)]
    local = [_item(i, "kursiv") for i in (10, 11, 12)]

    out = news_store._balance_origins(intl + local, 6)

    assert [it["id"] for it in out if it["source_id"] == "fitch"] == [0, 1, 2]
    assert [it["id"] for it in out if it["source_id"] == "kursiv"] == [10, 11, 12]


def test_a_quiet_week_for_the_agencies_does_not_shorten_the_page(monkeypatch):
    """One rating action and nothing else — the other 19 slots stay full of local news."""
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.5)
    items = [_item(0, "fitch")] + [_item(i + 1, "uzdaily") for i in range(30)]

    out = news_store._balance_origins(items, 20)

    assert len(out) == 20
    assert _origins(out).count("I") == 1


def test_the_page_is_never_padded_with_local_items_it_does_not_have(monkeypatch):
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.5)
    items = [_item(i, "trend") for i in range(4)] + [_item(10, "spot")]

    out = news_store._balance_origins(items, 20)

    assert len(out) == 5
    assert _origins(out) == "ILIII"


def test_share_zero_restores_the_plain_ranked_order(monkeypatch):
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.0)
    items = [_item(0, "spot"), _item(1, "trend"), _item(2, "spot")]

    assert news_store._balance_origins(items, 3) == items


def test_a_one_sided_window_is_returned_untouched(monkeypatch):
    monkeypatch.setattr(news_store, "_INTERNATIONAL_SHARE", 0.5)
    items = [_item(i, "spot") for i in range(5)]

    assert news_store._balance_origins(items, 3) == items[:3]


class TestTheRegistryDrivesIt:
    def test_the_english_sources_are_the_international_ones(self, monkeypatch):
        monkeypatch.setattr(news_store, "_international_ids", None)
        ids = news_store.international_source_ids()

        # Every English-language source we read, and nothing that publishes in Russian.
        assert {"fitch", "moodys", "spglobal", "thediplomat", "trend", "timesca"} <= ids
        assert not ({"spot", "kursiv", "kun", "uzdaily", "cbu", "napp", "openinfo_facts"} & ids)

    def test_an_unreadable_registry_turns_the_balance_off_instead_of_failing(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(news_store, "_international_ids", None)
        monkeypatch.setattr(news_store, "_ORIGINS_FILE", str(tmp_path / "gone.json"))

        assert news_store.international_source_ids() == set()
        items = [_item(0, "trend"), _item(1, "spot")]
        assert news_store._balance_origins(items, 2) == items
