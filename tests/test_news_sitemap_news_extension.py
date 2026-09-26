"""A news sitemap is read by the publisher's own headline and date, and gated on that headline.

S&P Global publishes what Moody's and Fitch do not: a Google-news sitemap, where every entry
carries ``<news:title>`` and ``<news:publication_date>``. Two consequences the adapter has to
get right, and this pins both.

The ``<loc>`` is ``…/article/-/view/sourceId/101700054`` — a number. A ``url_filter`` over
that would match nothing, ever, and the source would sit there looking merely quiet (which is
exactly how Moody's and Fitch look on a day with no Uzbek action, so the failure would be
invisible). Hence ``title_filter``, over the only field that names anybody.

And the date is stated per item, so ``slug_date`` — which exists to overrule Fitch's
sitemap-wide build timestamp — must not fire and re-date it from a number in the URL.
"""
from __future__ import annotations

import pytest

import news_collector as nc
import collectors.news.sources as collectors_news_sources


SPGLOBAL = {
    "id": "spglobal",
    "type": "sitemap",
    "url": "https://www.spglobal.com/ratings/sitemaps/news-sitemap.xml",
    "lang": ["en"],
    "title_filter": "uzbek|hamkor|asaka|navoi|uzpromstroy",
    "skip_triage": True,
}

_ENTRIES = [
    ("https://www.spglobal.com/ratings/en/regulatory/article/-/view/sourceId/101700054",
     "Uzbekistan-Based JSC Uzpromstroybank Upgraded To 'BB-' On Improving Capitalization",
     "2026-08-05"),
    ("https://www.spglobal.com/ratings/en/regulatory/article/-/view/sourceId/101700844",
     "Republic of Uzbekistan 'BB-/B' Ratings Affirmed; Outlook Stable", "2026-08-07"),
    ("https://www.spglobal.com/ratings/en/regulatory/article/-/view/sourceId/101700843",
     "Middle Township, NJ Series 2026 Bond Anticipation Notes Rated 'SP-1+'", "2026-08-07"),
    ("https://www.spglobal.com/ratings/en/regulatory/article/-/view/sourceId/101700841",
     "Santander Mortgage Asset Receivable Trust 2026-NQM6 Notes Assigned Ratings", "2026-08-07"),
]


def _news_sitemap(entries) -> str:
    body = "".join(
        f"<url><loc>{u}</loc><lastmod>2026-08-07T21:00:00Z</lastmod>"
        f"<news:news><news:title><![CDATA[{t}]]></news:title>"
        f"<news:publication_date>{d}</news:publication_date></news:news></url>"
        for u, t, d in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?><urlset '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + body + "</urlset>")


@pytest.fixture()
def served(monkeypatch):
    def _serve(xml: str):
        class _Resp:
            text = xml

            def raise_for_status(self):
                return None

        monkeypatch.setattr(nc.requests, "get", lambda *a, **k: _Resp())
    return _serve


def test_title_filter_gates_a_sitemap_whose_urls_are_numbers(served):
    served(_news_sitemap(_ENTRIES))
    items = collectors_news_sources.fetch_sitemap(SPGLOBAL, 40)

    titles = [i["title"] for i in items]
    assert len(items) == 2, titles
    assert titles[0].startswith("Uzbekistan-Based JSC Uzpromstroybank")
    assert not any("Santander" in t or "Middle Township" in t for t in titles)


def test_the_publishers_own_headline_and_date_are_used(served):
    served(_news_sitemap(_ENTRIES))
    items = collectors_news_sources.fetch_sitemap(SPGLOBAL, 40)

    dated = {i["title"]: i["published_at"] for i in items}
    # Its own publication_date, not the sitemap-wide <lastmod> of 2026-08-07T21:00Z.
    assert dated["Uzbekistan-Based JSC Uzpromstroybank Upgraded To 'BB-' On Improving "
                 "Capitalization"] == "2026-08-05"
    assert dated["Republic of Uzbekistan 'BB-/B' Ratings Affirmed; Outlook Stable"] == "2026-08-07"


def test_a_publisher_dated_item_is_never_redated_from_its_url(served):
    """slug_date overrules a build timestamp, not a date the publisher stated per item."""
    source = {**SPGLOBAL,
              "slug_date": {"pattern": r"(\d{2}-\d{2}-\d{4})$", "format": "%d-%m-%Y"}}
    served(_news_sitemap([_ENTRIES[0]]))
    items = collectors_news_sources.fetch_sitemap(source, 40)

    assert items[0]["published_at"] == "2026-08-05"


def test_a_sitemap_with_neither_filter_is_refused(served):
    served(_news_sitemap(_ENTRIES))
    naked = {k: v for k, v in SPGLOBAL.items() if k != "title_filter"}

    assert collectors_news_sources.fetch_sitemap(naked, 40) == []


def test_slug_sources_are_unaffected_by_the_news_extension(served):
    """Fitch's path: no <news:> anywhere, headline still read out of the slug."""
    fitch = {"id": "fitch", "type": "sitemap", "url": "x", "lang": ["en"],
             "url_filter": "uzbek", "title_from": "slug",
             "slug_strip": r"-\d{2}-\d{2}-\d{4}$",
             "slug_date": {"pattern": r"(\d{2}-\d{2}-\d{4})$", "format": "%d-%m-%Y"},
             "title_case": "title"}
    xml = ('<?xml version="1.0"?><urlset><url><loc>https://www.fitchratings.com/research/'
           'sovereigns/fitch-affirms-uzbekistan-at-bb-outlook-stable-23-07-2026</loc>'
           "<lastmod>2026-08-07</lastmod></url></urlset>")
    served(xml)
    items = collectors_news_sources.fetch_sitemap(fitch, 40)

    assert items[0]["published_at"] == "2026-07-23"
    assert items[0]["title"] == "Fitch Affirms Uzbekistan at BB Outlook Stable"


def test_headers_from_the_registry_reach_the_request(monkeypatch):
    """S&P's edge answers 403 to a lone User-Agent; the declared headers must be sent."""
    seen: dict = {}

    class _Resp:
        text = '<?xml version="1.0"?><urlset></urlset>'

        def raise_for_status(self):
            return None

    def _get(url, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return _Resp()

    monkeypatch.setattr(nc.requests, "get", _get)
    collectors_news_sources.fetch_sitemap({**SPGLOBAL, "user_agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/139",
                      "headers": {"Sec-Fetch-Mode": "navigate", "Accept-Language": "en-US"}}, 5)

    assert seen["User-Agent"].startswith("Mozilla/5.0 (Windows NT 10.0)")
    assert seen["Sec-Fetch-Mode"] == "navigate"
    assert seen["Accept-Language"] == "en-US"
