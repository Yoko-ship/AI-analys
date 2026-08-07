"""A rating action must not be lost at the cheapest gate, or arrive without its capitals.

The first live run with Fitch enabled (2026-07-29) fetched 0 items — correctly, its research
sitemap held no Uzbek issuer that morning — and the same run showed what would happen when
one arrived. Fitch publishes a rating action under a bare, lower-cased entity slug
(``…/jsc-uzbek-metallurgical-plant-29-07-2026``), and nothing else: no snippet, no lastmod
worth trusting, no article page that opens.

Two consequences, both pinned here.

Relevance for these sources is settled *before* any model sees them — the ``url_filter``
kept the URL precisely because it names one of our issuers, which is what makes the source
authoritative in ``news_store._AUTHORITATIVE_SOURCES``. Asking the triage gate "could this
plausibly matter?" about the string 'jsc uzbek metallurgical plant' can only lose, and a
triage rejection **is stored**, so one wrong verdict buries the action permanently. Hence
``skip_triage``.

And a headline read out of a lower-cased slug would sit in the feed among properly cased
ones looking broken. Hence ``title_case``, which is opt-in: Moody's slugs carry their own
capitals and rewriting them could only do damage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import news_collector as nc


REGISTRY = json.loads((Path(nc.__file__).resolve().parent / "news_sources.json")
                      .read_text(encoding="utf-8"))["sources"]


def _source(source_id: str) -> dict:
    return next(s for s in REGISTRY if s["id"] == source_id)


class TestSlugTitlesGetTheirCapitalsBack:
    @pytest.mark.parametrize("slug_title, expected", [
        # The one Fitch actually published on 2026-07-29 — 'jsc' is an acronym, not a word.
        ("jsc uzbek metallurgical plant", "JSC Uzbek Metallurgical Plant"),
        # Fitch's own house style: grade upper-cased, the joining words left alone.
        ("fitch affirms uzbekistan at bb outlook stable",
         "Fitch Affirms Uzbekistan at BB Outlook Stable"),
        ("fitch upgrades hamkorbank to bb+ outlook stable",
         "Fitch Upgrades Hamkorbank to BB+ Outlook Stable"),
        ("fitch rates ipoteka bank idr and esg", "Fitch Rates Ipoteka Bank IDR and ESG"),
    ])
    def test_a_lower_cased_slug_is_recased(self, slug_title, expected) -> None:
        assert nc._recase_title(slug_title, "title") == expected

    def test_a_bare_letter_is_a_rating_only_where_fitch_writes_one(self) -> None:
        # 'a' after 'to' is a grade; the article 'a' anywhere else is an ordinary word and
        # must survive as one, or every headline would grow a stray capital.
        assert nc._recase_title("fitch downgrades asaka bank to a", "title") == \
            "Fitch Downgrades Asaka Bank to A"
        assert nc._recase_title("uzbekistan opens a mining zone", "title") == \
            "Uzbekistan Opens a Mining Zone"

    def test_a_title_that_already_has_capitals_is_never_touched(self) -> None:
        moodys = "Moodys Ratings affirms Uzbekistan Ba3 rating outlook stable"
        assert nc._recase_title(moodys, "title") == moodys

    def test_a_source_that_does_not_ask_for_recasing_keeps_its_slug_verbatim(self) -> None:
        assert nc._recase_title("jsc uzbek metallurgical plant", None) == \
            "jsc uzbek metallurgical plant"

    def test_the_registry_entry_produces_a_cased_headline_end_to_end(self, monkeypatch) -> None:
        url = ("https://www.fitchratings.com/research/corporate-finance/"
               "jsc-uzbek-metallurgical-plant-29-07-2026")

        class _Resp:
            text = f"<urlset><url><loc>{url}</loc><lastmod>2026-07-29</lastmod></url></urlset>"

            def raise_for_status(self):
                return None

        monkeypatch.setattr(nc.requests, "get", lambda *a, **k: _Resp())
        items = nc.fetch_sitemap(_source("fitch"), 40)

        assert [i["title"] for i in items] == ["JSC Uzbek Metallurgical Plant"]
        assert items[0]["published_at"] == "2026-07-29"


class TestWhoSkipsTheTriageGate:
    def test_filings_and_url_filtered_agencies_bypass_it_separately(self) -> None:
        items = [
            {"id": 1, "always_relevant": True},                     # an issuer's own filing
            {"id": 2, "source_id": "fitch", "skip_triage": True},   # cleared the url_filter
            {"id": 3, "source_id": "spot", "skip_triage": False},   # a whole-site feed
            {"id": 4, "source_id": "kun"},                          # flag absent entirely
        ]
        filings, pre_gated, to_screen = nc._split_for_triage(items)

        assert [i["id"] for i in filings] == [1]
        assert [i["id"] for i in pre_gated] == [2]
        # Filings are classified by their own compact prompt, so they must NOT land in the
        # bucket that goes to the full classifier alongside the agencies.
        assert [i["id"] for i in to_screen] == [3, 4]

    def test_a_filing_never_lands_in_the_pre_gated_bucket(self) -> None:
        _, pre_gated, to_screen = nc._split_for_triage(
            [{"id": 1, "always_relevant": True, "skip_triage": True}])
        assert pre_gated == [] and to_screen == []

    @pytest.mark.parametrize("source_id", ["fitch", "moodys", "spglobal"])
    def test_the_agencies_declare_it_in_the_registry(self, source_id) -> None:
        assert _source(source_id).get("skip_triage") is True

    def test_only_a_filtered_source_may_declare_it(self) -> None:
        """The gate is skipped because a filter already named one of our issuers — over the
        URL for the two agencies with slugs, over the headline for S&P, whose <loc> is a bare
        numeric id. A source with neither filter has had nothing established, so skipping
        triage there would send a whole general-news feed to the full classifier at full
        price."""
        offenders = [s["id"] for s in REGISTRY
                     if s.get("skip_triage")
                     and not (s.get("url_filter") or s.get("title_filter"))]
        assert offenders == []


class TestWhenTheGateIsPerItem:
    """``skip_triage_filter`` — a source whose stream is mostly other countries' news."""

    def _diplomat(self, title, snippet="") -> bool:
        return nc._skip_triage(_source("thediplomat"),
                               {"title": title, "snippet": snippet, "url": ""})

    def test_the_uzbekistan_items_bypass_the_cheap_gate(self) -> None:
        # All three were fetched, judged by triage, and stored as irrelevant — measured on
        # the live window, 2026-08-07.
        assert self._diplomat("Uzbekistan's Nuclear Power Plant Project Advances")
        assert self._diplomat("Uzbekistan Launches Its First Tax-Free Crypto Mining Zone")
        assert self._diplomat("Progress on the China-Kyrgyzstan-Uzbekistan Railway, "
                              "Some Challenges Remain")

    def test_the_rest_of_central_asia_still_faces_it(self) -> None:
        assert not self._diplomat("Kazakh President Tokayev's 'Humble' Query for Peace")
        assert not self._diplomat("Mongolia's Fuel Crisis Is a Demand Problem")
        assert not self._diplomat("Far More Than Ruins: Life in Engilcheck, Kyrgyzstan")

    def test_a_source_level_flag_still_covers_every_item(self) -> None:
        assert nc._skip_triage(_source("fitch"), {"title": "jsc uzbek metallurgical plant"})
        assert nc._skip_triage({"skip_triage": True}, {"title": "anything at all"})

    def test_a_source_with_neither_knob_gates_everything(self) -> None:
        assert not nc._skip_triage(_source("spot"), {"title": "Uzbekistan launches something"})
