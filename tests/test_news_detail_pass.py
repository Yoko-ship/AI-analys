"""The story page's long read: our own account of the article, never the article.

A feed teaser is one sentence; the article behind it is five paragraphs. The detail pass
closes that gap by reading the source's page ONCE, in memory, and asking the model to retell
it — so what reaches the database is our text, which is the whole basis on which this module
is allowed to aggregate at all (NEWS_MODULE.md, legal invariant).

What has to hold: the extraction finds real paragraphs and not the navigation around them; a
page that is a paywall or a menu produces nothing rather than an invented article; sources
with no article page are never fetched; and the feed, which shows none of this, does not carry
three languages of prose for 200 items.
"""
from __future__ import annotations

import pytest

import news_classifier
import news_collector as nc
import news_store


_ARTICLE = """
<html><head><title>x</title></head><body>
  <nav><a href="/">Home</a><a href="/news">News</a></nav>
  <header><p>Subscribe to our newsletter for the latest updates from the region today</p></header>
  <article>
    <p>Short teaser.</p>
    <p>The Minister of Agriculture of the Republic of Uzbekistan met with the Ambassador
       Extraordinary and Plenipotentiary of the Islamic Republic of Iran to Uzbekistan.</p>
    <p>According to the Ministry of Agriculture, the talks focused on expanding bilateral
       cooperation and implementing new joint projects in the agricultural sector.</p>
    <p>Particular attention was paid to developing cooperation in agricultural mechanization,
       agricultural science and innovation, and modern machinery.</p>
    <figure><figcaption>Photo: UzA — the delegation meeting in Tashkent this morning</figcaption></figure>
  </article>
  <aside><p>Read also: another story about something entirely different from this one</p></aside>
  <footer><p>All rights reserved. Reproduction of materials without permission is prohibited.</p></footer>
</body></html>
"""


class _Resp:
    def __init__(self, body: str, status: int = 200):
        self.content = body.encode("utf-8")
        self.status_code = status
        self.encoding = "utf-8"


@pytest.fixture()
def served(monkeypatch):
    def _serve(body: str, status: int = 200):
        monkeypatch.setattr(nc.requests.Session, "get",
                            lambda self, url, **kw: _Resp(body, status))
    return _serve


class TestExtraction:
    def test_it_takes_the_article_and_leaves_the_furniture(self, served):
        served(_ARTICLE)
        text = nc._article_text(nc.requests.Session(), "https://uza.uz/en/posts/x")

        assert "Minister of Agriculture" in text
        assert "agricultural mechanization" in text
        # Nav, newsletter pitch, photo caption, "read also" rail and the footer notice are
        # not the article — and the caption is the trap, since it is a <p>-length sentence.
        for noise in ("Subscribe to our newsletter", "Read also", "All rights reserved",
                      "Photo: UzA"):
            assert noise not in text
        # Paragraphs survive as paragraphs — the field's whole shape depends on it.
        assert text.count("\n\n") == 2

    def test_a_short_stub_yields_nothing_rather_than_a_headline(self, served):
        served("<html><body><article><p>Sign in to continue.</p></article></body></html>")
        assert nc._article_text(nc.requests.Session(), "https://x.uz/a") == ""

    def test_a_non_200_is_not_an_article(self, served):
        served(_ARTICLE, status=403)
        assert nc._article_text(nc.requests.Session(), "https://x.uz/a") == ""


class TestWhatIsNeverAsked:
    def test_a_source_with_no_article_page_is_never_fetched(self, monkeypatch):
        """The rating agencies ship a headline and an SPA shell; openinfo has no page at all."""
        called = []
        monkeypatch.setattr(nc, "_article_text",
                            lambda *a, **k: called.append(a[1]) or "")
        registry = {
            "fitch": {"id": "fitch", "content": "none"},
            "openinfo_facts": {"id": "openinfo_facts", "type": "openinfo"},
            "uza": {"id": "uza", "content": "snippet"},
        }
        items = [{"url": "https://fitchratings.com/a", "source_id": "fitch"},
                 {"url": "https://openinfo.uz/b?fact=1", "source_id": "openinfo_facts"},
                 {"url": "https://uza.uz/c", "source_id": "uza"}]

        nc.enrich_details(items, registry)

        assert called == ["https://uza.uz/c"]

    def test_an_unreadable_page_costs_no_model_call(self, monkeypatch):
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: "")
        monkeypatch.setattr(nc, "write_detail",
                            lambda *a, **k: pytest.fail("model called on an empty article"))

        assert nc.enrich_details([{"url": "https://uza.uz/c", "source_id": "uza"}],
                                 {"uza": {"id": "uza"}}) == {}

    def test_the_per_run_cap_is_honoured(self, monkeypatch):
        seen = []
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: "x" * 400)
        monkeypatch.setattr(nc, "write_detail",
                            lambda it, text, **k: seen.append(it["url"]) or {"ru": "p", "en": "p", "uz": "p"})
        items = [{"url": f"https://uza.uz/{i}", "source_id": "uza"} for i in range(10)]

        out = nc.enrich_details(items, {"uza": {"id": "uza"}}, max_fetch=3)

        assert len(seen) == 3 and len(out) == 3


class TestTheModelContract:
    def test_a_page_with_no_body_is_not_sent_at_all(self):
        assert news_classifier.write_detail({"title": "x"}, "too short") == \
            {"ru": "", "en": "", "uz": ""}

    def test_all_three_languages_or_none(self):
        """Russian paragraphs under an English reader's headline is worse than no body."""

        class _Client:
            def complete_json(self, *a, **k):
                return {"detail_ru": "", "detail_en": "an English body", "detail_uz": ""}

        got = news_classifier.write_detail({"title": "x"}, "s" * 300, client=_Client())
        assert got == {"ru": "", "en": "", "uz": ""}

    def test_a_failed_call_leaves_the_page_as_it_was(self):
        class _Client:
            def complete_json(self, *a, **k):
                raise RuntimeError("provider down")

        assert news_classifier.write_detail({"title": "x"}, "s" * 300, client=_Client()) == \
            {"ru": "", "en": "", "uz": ""}


class TestTheFeedDoesNotCarryIt:
    def test_the_list_reports_only_whether_a_long_read_exists(self):
        row = {"id": 1, "url": "u", "source": "s", "source_id": "uza", "lang": "en",
               "title": "t", "snippet": "", "summary_ru": "s", "summary_en": "", "summary_uz": "",
               "detail_ru": "para one\n\npara two", "detail_en": "", "detail_uz": "",
               "image_url": None, "published_at": "2026-08-07", "type": "market",
               "tone": "neutral", "tone_score": 0.0, "impact": "low", "direction": "unclear",
               "sectors_json": None, "relevance_score": 0.6, "coverage_weight": 0.7,
               "tickers_csv": ""}

        item = news_store._row_to_item(_Row(row))

        assert item["has_detail"] is True
        # 200 items × three languages of prose is a megabyte the list never renders.
        assert "detail_ru" not in item and "detail_en" not in item


class _Row(dict):
    """A stand-in for a sqlite3.Row: keys() plus __getitem__."""

    def keys(self):  # noqa: D102
        return list(super().keys())
