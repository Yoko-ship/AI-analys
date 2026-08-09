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

import json
from pathlib import Path

import pytest

import news_classifier
import news_collector as nc
import news_store


REGISTRY = json.loads((Path(nc.__file__).resolve().parent / "news_sources.json")
                      .read_text(encoding="utf-8"))["sources"]


def _source(source_id: str) -> dict:
    return next(s for s in REGISTRY if s["id"] == source_id)


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
            "fitch": {"id": "fitch", "content": "none", "article_body": False},
            "openinfo_facts": {"id": "openinfo_facts", "type": "openinfo"},
            "uza": {"id": "uza", "content": "snippet"},
        }
        items = [{"url": "https://fitchratings.com/a", "source_id": "fitch"},
                 {"url": "https://openinfo.uz/b?fact=1", "source_id": "openinfo_facts"},
                 {"url": "https://uza.uz/c", "source_id": "uza"}]

        nc.enrich_details(items, registry)

        assert called == ["https://uza.uz/c"]

    def test_a_listing_with_no_snippet_still_has_an_article_behind_it(self, monkeypatch):
        """`content` describes the LISTING, `article_body` the page — conflating them wrote
        off every napp.uz item, whose articles run to 1400 characters of prose."""
        called = []
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: called.append(a[1]) or "x" * 400)
        monkeypatch.setattr(nc, "write_detail", lambda *a, **k: {"ru": "p", "en": "p", "uz": "p"})

        nc.enrich_details([{"url": "https://napp.uz/ru/n/1", "source_id": "napp"}],
                          {"napp": {"id": "napp", "content": "none"}})

        assert called == ["https://napp.uz/ru/n/1"]

    def test_the_agencies_say_so_explicitly_in_the_registry(self):
        """Measured, not inferred — so the flag survives a change to `content`."""
        for sid in ("fitch", "moodys", "spglobal"):
            assert _source(sid).get("article_body") is False, sid
        assert _source("napp").get("article_body") is None

    def test_an_unreadable_page_is_never_sent_as_an_article(self, monkeypatch):
        """No body means no article call — the fallback below is a different prompt."""
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: "")
        monkeypatch.setattr(nc, "write_detail",
                            lambda *a, **k: pytest.fail("model called on an empty article"))
        monkeypatch.setattr(nc, "write_brief_detail", lambda *a, **k: {"ru": "", "en": "", "uz": ""})

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


class TestEveryItemCanHaveABody:
    """A third of the feed had no route to a long read at all.

    Measured on the live feed before this: 200 items, 18 with a body. 36 of them are openinfo
    filings, which have no article page anywhere — the portal 404s every per-fact URL — so no
    amount of crawling would ever have given them one. Those are written from the material we
    already hold, which for a filing is its own figures.
    """
    def test_a_filing_is_written_from_its_own_figures(self, monkeypatch):
        seen = []
        monkeypatch.setattr(nc, "_article_text",
                            lambda *a, **k: pytest.fail("an openinfo filing has no page"))
        monkeypatch.setattr(nc, "write_brief_detail",
                            lambda it, **k: seen.append(it["url"]) or {"ru": "p", "en": "p", "uz": "p"})
        items = [{"url": "https://openinfo.uz/b?fact=1", "source_id": "openinfo_facts",
                  "snippet": "Начислены доходы: 612,1253 сум на облигацию."}]

        out = nc.enrich_details(items, {"openinfo_facts": {"type": "openinfo"}})

        assert seen == ["https://openinfo.uz/b?fact=1"]
        assert out["https://openinfo.uz/b?fact=1"]["ru"] == "p"

    def test_a_page_that_would_not_read_falls_back_instead_of_giving_up(self, monkeypatch):
        """Otherwise the item is retried every run and stays bare every run."""
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: "")
        monkeypatch.setattr(nc, "write_brief_detail",
                            lambda it, **k: {"ru": "p", "en": "p", "uz": "p"})

        out = nc.enrich_details([{"url": "https://timesca.com/x", "source_id": "timesca",
                                  "summary_ru": "x" * 300}], {"timesca": {"id": "timesca"}})

        assert out["https://timesca.com/x"]["ru"] == "p"

    def test_nothing_to_lay_out_stays_empty(self):
        """A headline about nobody: no material, no issuer, nothing to state."""
        assert news_classifier.write_brief_detail({"title": "Fitch Affirms X at BB-"}) == {
            "ru": "", "en": "", "uz": ""}

    def test_a_headline_that_names_our_issuers_is_still_worth_two_paragraphs(self, monkeypatch):
        """/news/762: Fitch publishes a title and no body ANYWHERE — 1.1MB of shell that does
        not contain even its own headline — but the item names five listed insurers. What was
        published and whom it concerns are facts we hold; the research is not."""
        sent = {}

        class _Client:
            def complete_json(self, system, user, **kw):
                sent["system"], sent["user"] = system, user
                return {"detail_ru": "p", "detail_en": "p", "detail_uz": "p"}

        out = news_classifier.write_brief_detail(
            {"title": "Uzbek Insurers Benefit From Stronger Operating Environment",
             "summary_ru": "Fitch указывает на пользу для узбекских страховщиков.",
             "tickers": ["ALSM", "KASU", "UZINP"]},
            client=_Client())

        assert out["ru"] == "p"
        assert "ALSM" in sent["user"]

    def test_the_prompt_forbids_summarising_research_it_was_not_given(self):
        """The one way a headline-only page could become a lie."""
        assert "you do not know its reasoning" in news_classifier._BRIEF_SYSTEM
        assert "this reflects" in news_classifier._BRIEF_SYSTEM

    def test_the_material_is_deduplicated_before_the_model_sees_it(self):
        """snippet and summary are often the same sentence; twice is how two facts
        become four paragraphs."""
        same = "Эмитент заключил крупную сделку на 50 млрд сумов." * 4

        assert news_classifier.brief_material({"summary_ru": same, "snippet": same}) == same

    def test_the_brief_prompt_forbids_adding_facts(self):
        """The whole safety of a page written without a source behind it."""
        assert "ABSOLUTELY NO NEW FACTS" in news_classifier._BRIEF_SYSTEM
        assert "return empty strings" in news_classifier._BRIEF_SYSTEM


class TestTheBacklogDrains:
    """Newest-first with a cap under the day's inflow never converges.

    The pass took 12 a day while the feed took 16-36; the shortfall landed on the same items
    every run, so three weeks of stories were unreachable — 18 long reads on the live feed and
    every one of them from the last two days.
    """
    def test_the_cap_clears_a_normal_day(self):
        assert nc._DETAIL_CAP >= 30

    def test_part_of_every_run_is_reserved_for_the_oldest(self):
        assert 0 < nc._DETAIL_TAIL_SHARE < 1

    def test_the_work_list_can_be_read_from_the_old_end(self, monkeypatch):
        seen = {}

        class _Conn:
            def execute(self, sql, params):
                seen["sql"] = sql
                return self

            def fetchall(self):
                return []

            def close(self):
                return None

        monkeypatch.setattr(news_store.rc, "get_catalog_conn", lambda: _Conn())

        news_store.rows_without_detail(oldest_first=True)
        assert "ASC LIMIT" in seen["sql"]

        news_store.rows_without_detail()
        assert "DESC LIMIT" in seen["sql"]

    def test_one_budget_covers_both_routes(self, monkeypatch):
        """A cap of N must not mean N fetched articles PLUS N written filings."""
        calls = {"brief": 0, "article": 0}
        monkeypatch.setattr(nc, "_article_text", lambda *a, **k: "x" * 400)
        monkeypatch.setattr(nc, "write_brief_detail",
                            lambda it, **k: calls.__setitem__("brief", calls["brief"] + 1)
                            or {"ru": "p", "en": "p", "uz": "p"})
        monkeypatch.setattr(nc, "write_detail",
                            lambda it, text, **k: calls.__setitem__("article", calls["article"] + 1)
                            or {"ru": "p", "en": "p", "uz": "p"})
        items = ([{"url": f"https://openinfo.uz/{i}", "source_id": "openinfo_facts",
                   "snippet": "s" * 300} for i in range(10)]
                 + [{"url": f"https://uza.uz/{i}", "source_id": "uza"} for i in range(10)])

        nc.enrich_details(items, {"openinfo_facts": {"type": "openinfo"}, "uza": {"id": "uza"}},
                          max_fetch=6)

        assert calls["brief"] + calls["article"] == 6
        assert calls["brief"] and calls["article"]      # neither route starves the other

    def test_an_unused_half_is_left_to_the_other_route(self, monkeypatch):
        calls = {"brief": 0}
        monkeypatch.setattr(nc, "write_brief_detail",
                            lambda it, **k: calls.__setitem__("brief", calls["brief"] + 1)
                            or {"ru": "p", "en": "p", "uz": "p"})
        items = [{"url": f"https://openinfo.uz/{i}", "source_id": "openinfo_facts",
                  "snippet": "s" * 300} for i in range(10)]

        nc.enrich_details(items, {"openinfo_facts": {"type": "openinfo"}}, max_fetch=6)

        assert calls["brief"] == 6
