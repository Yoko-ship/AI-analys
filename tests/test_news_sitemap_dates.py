"""A sitemap-sourced item is dated by the publisher, not by the sitemap's build time.

``fetch_sitemap`` reads a publisher's XML sitemap as a feed for agencies with no usable
RSS. Moody's leaves ``<lastmod>`` off entirely, so its items arrive undated and are kept.
Fitch does the opposite and worse: it regenerates ``sitemap-research.xml`` daily and stamps
**every** entry with the generation timestamp, so a rating action published five days ago
would be served to readers as today's news, and the recency filter — which is the only thing
keeping the file's 2024–2025 stragglers out of the feed — would never fire.

The real date is in the slug (``…-uzbekistan-at-bb-outlook-stable-23-07-2026``), which is why
a source may declare ``slug_date``. These pin that, plus the ``url_filter`` gate that keeps
the ~99.8% of global research naming none of our issuers away from any model call.
"""
from __future__ import annotations

import pytest

import news_collector as nc
import collectors.news.sources as collectors_news_sources


FITCH = {
    "id": "fitch",
    "type": "sitemap",
    "url": "https://www.fitchratings.com/sitemap-research.xml",
    "lang": ["en"],
    "url_filter": "uzbek|hamkor|asaka|navoi",
    "title_from": "slug",
    "slug_strip": r"-\d{2}-\d{2}-\d{4}$",
    "slug_date": {"pattern": r"(\d{2}-\d{2}-\d{4})$", "format": "%d-%m-%Y"},
}

_URLS = [
    # Uzbek issuers and the sovereign — kept, each dated from its own slug.
    "https://www.fitchratings.com/research/sovereigns/fitch-affirms-uzbekistan-at-bb-outlook-stable-23-07-2026",
    "https://www.fitchratings.com/research/banks/fitch-upgrades-hamkorbank-to-bb-outlook-stable-05-05-2026",
    # Global research naming nobody of ours — must never reach the model.
    "https://www.fitchratings.com/research/insurance/fitch-affirms-pension-insurance-corp-a-ifs-28-07-2026",
    "https://www.fitchratings.com/research/banks/fitch-affirms-korea-development-bank-at-aa-10-02-2026",
    # 'panorama' contains 'anor', 'osaka' nearly contains 'asaka' — the filter is a plain
    # regex over the URL, so near-misses are the failure mode worth pinning.
    "https://www.fitchratings.com/research/structured-finance/fitch-upgrades-two-panorama-auto-trust-tranches-23-07-2026",
]


def _sitemap_xml(urls: list[str], lastmod: str | None = "2026-07-28") -> str:
    body = "".join(
        f"<url><loc>{u}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>"
        for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset>{body}</urlset>'


@pytest.fixture()
def served(monkeypatch):
    """Serve a sitemap body to fetch_sitemap without touching the network."""
    def _serve(xml: str):
        class _Resp:
            text = xml

            def raise_for_status(self):
                return None

        monkeypatch.setattr(nc.requests, "get", lambda *a, **k: _Resp())
    return _serve


def test_slug_date_wins_over_the_sitemap_build_time(served):
    served(_sitemap_xml(_URLS))
    items = collectors_news_sources.fetch_sitemap(FITCH, 40)

    dates = {i["title"]: i["published_at"] for i in items}
    assert dates["fitch affirms uzbekistan at bb outlook stable"] == "2026-07-23"
    assert dates["fitch upgrades hamkorbank to bb outlook stable"] == "2026-05-05"
    # Not the 2026-07-28 every entry claims via <lastmod>.
    assert "2026-07-28" not in set(dates.values())


def test_url_filter_drops_global_research_before_any_model_call(served):
    served(_sitemap_xml(_URLS))
    items = collectors_news_sources.fetch_sitemap(FITCH, 40)

    assert len(items) == 2, [i["title"] for i in items]
    joined = " ".join(i["title"] for i in items)
    assert "korea" not in joined and "panorama" not in joined and "pension" not in joined


def test_lastmod_is_the_fallback_when_a_slug_carries_no_date(served):
    served(_sitemap_xml(
        ["https://www.fitchratings.com/research/sovereigns/fitch-affirms-uzbekistan-at-bb"]))
    items = collectors_news_sources.fetch_sitemap(FITCH, 40)

    assert [i["published_at"] for i in items] == ["2026-07-28"]


def test_a_source_without_slug_date_is_unchanged(served):
    """Moody's path: no slug_date, no lastmod — undated, and _is_recent keeps it."""
    served(_sitemap_xml(["https://www.moodys.com/research/Moodys-affirms-Uzbekistan--PR_1"],
                        lastmod=None))
    moodys = {"id": "moodys", "type": "sitemap", "url": "x", "lang": ["en"],
              "url_filter": "uzbek", "title_from": "slug", "slug_strip": r"-{1,2}PR_\d+$"}
    items = collectors_news_sources.fetch_sitemap(moodys, 40)

    assert len(items) == 1
    assert items[0]["published_at"] is None
    assert items[0]["title"] == "Moodys affirms Uzbekistan"
    assert collectors_news_sources._is_recent(items[0]["published_at"], 30) is True
