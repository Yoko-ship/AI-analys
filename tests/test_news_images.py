"""Preview images: who gets fetched, and who gets the budget.

Two sources publish an og:image and the rest do not, so the interesting behaviour is
not the fetch — it is the arithmetic around it. A per-run cap applied to the wrong
list spends the whole budget on filings that can never have a picture, and does it
silently: the log still reads "0 of 0 fetched".
"""
from __future__ import annotations

import pytest

import news_collector as nc

FILING = "openinfo_facts"   # no image exists, ever — no page_image flag
OUTLET = "kun"              # publishes an og:image on the article page


@pytest.fixture()
def no_network(monkeypatch):
    """Record what would have been fetched; hand back an image for every page."""
    fetched: list[str] = []

    def fake_og(session, url, timeout=15):
        fetched.append(url)
        return f"{url}/preview.jpg"

    monkeypatch.setattr(nc, "_og_image", fake_og)
    monkeypatch.setattr(nc.time, "sleep", lambda *_: None)  # crawl delay, not tested here
    return fetched


def _candidates(filings: int, outlet: int) -> list[dict[str, object]]:
    """Filings first — the order prod's feed actually returns them in."""
    return ([{"url": f"https://openinfo.uz/ru/organizations/{i}?fact={i}",
              "source_id": FILING, "image_url": None} for i in range(filings)]
            + [{"url": f"https://kun.uz/ru/news/{i}", "source_id": OUTLET, "image_url": None}
               for i in range(outlet)])


class TestTheFetchBudget:
    def test_filings_never_consume_it(self, no_network):
        """28 imageless filings ahead of 8 outlet items, and a cap of 12.

        The cap belongs to the list of pages that CAN answer. Applied to the raw
        candidate list it stopped at the filings every time, and the eight items that
        do publish a picture were never reached.
        """
        items = _candidates(filings=28, outlet=8)
        found = nc.enrich_images(items, nc._source_registry(), max_fetch=12)
        assert found == 8
        assert no_network == [it["url"] for it in items if it["source_id"] == OUTLET]

    def test_the_cap_still_binds(self, no_network):
        items = _candidates(filings=0, outlet=30)
        assert nc.enrich_images(items, nc._source_registry(), max_fetch=12) == 12
        assert len(no_network) == 12

    def test_an_item_that_already_has_one_is_left_alone(self, no_network):
        items = _candidates(filings=0, outlet=2)
        items[0]["image_url"] = "https://kun.uz/existing.jpg"
        nc.enrich_images(items, nc._source_registry(), max_fetch=12)
        assert no_network == [items[1]["url"]]
        assert items[0]["image_url"] == "https://kun.uz/existing.jpg"


class TestTheBackfillPass:
    """The end-of-run retry: what a collector cycle actually calls."""

    def test_it_spends_its_budget_on_pages_that_can_answer(self, no_network, monkeypatch):
        pushed: dict[str, str] = {}
        monkeypatch.setattr(nc, "_prod_items_without_image",
                            lambda days: _candidates(filings=28, outlet=8))
        monkeypatch.setattr(nc.news_store, "rows_without_image", lambda **_: [])
        monkeypatch.setattr(nc.news_store, "image_urls_for", lambda urls: {})
        monkeypatch.setattr(nc.news_store, "set_image_urls", lambda images: len(images))
        monkeypatch.setattr(nc, "push_images", lambda images: pushed.update(images) or len(images))

        result = nc.backfill_images(limit=12, days=30, push=True)
        assert result["found"] == 8
        assert result["updated_prod"] == 8
        assert all("kun.uz" in url for url in pushed)

    def test_an_image_already_known_costs_no_request(self, no_network, monkeypatch):
        """A re-run after a failed push must push what it has, not re-fetch it."""
        known = {"https://kun.uz/ru/news/0": "https://storage.kun.uz/a.jpg"}
        monkeypatch.setattr(nc, "_prod_items_without_image",
                            lambda days: _candidates(filings=0, outlet=1))
        monkeypatch.setattr(nc.news_store, "rows_without_image", lambda **_: [])
        monkeypatch.setattr(nc.news_store, "image_urls_for", lambda urls: known)
        monkeypatch.setattr(nc.news_store, "set_image_urls", lambda images: len(images))
        monkeypatch.setattr(nc, "push_images", lambda images: len(images))

        result = nc.backfill_images(limit=12, days=30, push=True)
        assert no_network == []
        assert result["updated_prod"] == 1


class TestWhatCountsAsAnImage:
    def test_a_site_wide_share_card_is_not_one(self):
        """One social.jpg repeated down the whole feed is worse than no picture."""
        for path in ("/img/social.jpg", "/assets/default-image.png", "/static/logo.svg"):
            assert nc._GENERIC_IMAGE_RE.search(path), path

    def test_an_article_photo_is(self):
        for path in ("/source/1/nH2ag_n9qBhQpB3gTaiJJFD0oEo8-0mj.webp",
                     "/wp-content/uploads/2026/07/33a8c98f0cc1cd7fb6b9.jpg"):
            assert not nc._GENERIC_IMAGE_RE.search(path), path
