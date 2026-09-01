"""The code-only language detector behind the Russian-first news feed (news_lang.py).

Every string below is a real headline (or a real headline's shape) from an enabled source:
kun.uz for Uzbek Latin, Moody's / Fitch / The Diplomat for English, spot / uzdaily /
openinfo for Russian. The point of the module is that a Russian feed stays Russian, so the
Russian cases are the ones that must never regress.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from news_lang import detect_lang, is_foreign  # noqa: E402


RUSSIAN = [
    "ЦБ сохранил ставку на уровне 13,5%",
    "Узбекистан разместил облигации на 3,6 млрд сумов",
    # Half the letters are Latin (two brand names) and it is still a Russian headline —
    # this is why the Cyrillic test is a low share, not a majority vote.
    "Uzbekistan Airways и China Southern запустили код-шеринговое соглашение",
    "Sonect расширяет портфель BPO-услуг в Ташкенте",
    "Взаимодействие с Citi расширяется в финансировании торговых операций",
    "AGMK: существенный факт №21",
    "Хамкорбанк: рекомендация НС по распределению чистой прибыли (3)",
]

UZBEK = [
    "Neymar Braziliya milliy jamoasidan ketdi",
    # kun.uz types oʻ/gʻ as U+2018, a LEFT quote, which English never puts after a letter.
    "Toshkentda 6 oyda 151 ta ko‘p qavatli uy qurib bitkazildi.",
    "Xivada «Qovun sayli» festivali bo‘lib o‘tadi.",
    "Buxoro tarixiy qismida zamonaviy xavfsizlik tizimi o‘rnatiladi.",
    # The typographically correct spelling, U+02BB, which nothing in English uses.
    "Shavkat Mirziyoyev «Kelajak oʻyinlari»ning ochilish marosimida ishtirok etdi",
    "OAV: Zelenskiy Tramp va senatni urushda gʻalaba qozona olishiga ishontirdi",
    # No function word and no apostrophe: the agglutinative endings have to carry it.
    "Samarqandda yangi zavod ishga tushirilmoqda",
    # Uzbek Cyrillic, told from Russian by letters Russian does not have.
    "Ўзбекистонда янги қонун қабул қилинди",
]

ENGLISH = [
    # Moody's and Fitch reach us as URL slugs, so lowercase and stripped of punctuation.
    "fitch affirms uzbekistan at bb outlook stable",
    "fitch downgrades garland tx idr to aa rates 75mm gos aa outlook stable",
    "Moodys Ratings affirms Zeda Limiteds Ba3 rating outlook stable",
    "jsc uzbek metallurgical plant",
    "us life insurance governance risks rise with investment complexity",
    "Central Asia Weighs Its Options as Great Power Competition Intensifies",
    # Curly quotes around a rating, i.e. U+2018 where it IS an opening quote.
    "Fitch Affirms Uzbekistan at ‘BB-’; Outlook Stable",
    # Apostrophes after o and g, which is the Uzbek digraph shape in English words.
    "Moody's Ratings changes Chicago's outlook to negative",
]


@pytest.mark.parametrize("text", RUSSIAN)
def test_russian_headlines_stay_russian(text):
    assert detect_lang(text) == "ru"
    assert not is_foreign(detect_lang(text))


@pytest.mark.parametrize("text", UZBEK)
def test_uzbek_headlines(text):
    assert detect_lang(text) == "uz"


@pytest.mark.parametrize("text", ENGLISH)
def test_english_headlines(text):
    assert detect_lang(text) == "en"


def test_falls_through_to_the_snippet_when_the_title_has_no_letters():
    assert detect_lang("№21 — 2026", "Общество сообщает о выплате дивидендов") == "ru"


def test_returns_none_when_nothing_can_be_judged():
    assert detect_lang("", None, "2026-07-29 · 13,5%") is None


def test_headline_promotes_the_stored_summary_only_for_foreign_items():
    import news_store

    foreign = {"lang": "en", "title": "fitch affirms uzbekistan at bb outlook stable",
               "summary_ru": "Fitch подтвердило суверенный рейтинг Узбекистана."}
    assert news_store.headline_for(foreign, "ru") == "Fitch подтвердило суверенный рейтинг Узбекистана."
    # An item already in the reader's language keeps its own headline — the summary stays the dek.
    assert news_store.headline_for({**foreign, "lang": "ru"}, "ru") is None
    assert news_store.headline_for(foreign, "en") is None
    # No summary to promote: the caller falls back to the original headline rather than
    # showing an empty card.
    assert news_store.headline_for({**foreign, "summary_ru": ""}, "ru") is None


def test_a_russian_item_is_foreign_to_an_english_reader():
    """The whole point of the three-language feed: 'foreign' is relative to the reader.

    A Russian headline needs replacing on the English site exactly as an English one does on
    the Russian site, and before this the English and Uzbek versions served a Russian feed.
    """
    import news_store

    item = {"lang": "ru", "title": "ЦБ сохранил ставку на уровне 13,5%",
            "summary_ru": "Центробанк сохранил ставку.",
            "summary_en": "The central bank held its rate.",
            "summary_uz": "Markaziy bank stavkani saqlab qoldi."}
    assert news_store.headline_for(item, "ru") is None
    assert news_store.headline_for(item, "en") == "The central bank held its rate."
    assert news_store.headline_for(item, "uz") == "Markaziy bank stavkani saqlab qoldi."


def test_a_missing_translation_falls_back_to_russian_never_to_blank():
    import news_store

    item = {"lang": "ru", "title": "ЦБ сохранил ставку", "summary_ru": "Центробанк сохранил ставку."}
    # Rows collected before the columns existed have only Russian. A reader gets the wrong
    # language, which is recoverable; a blank card is not.
    assert news_store.summary_for(item, "en") == "Центробанк сохранил ставку."
    assert news_store.summary_for(item, "uz") == "Центробанк сохранил ставку."
    assert news_store.summary_for({}, "en") == ""


class _Row(dict):
    """Just enough of a sqlite3.Row for _row_to_item."""

    def keys(self):  # noqa: D102
        return list(super().keys())


def _row(**over):
    base = dict(id=1, url="u", source="s", source_id="thediplomat", lang="en",
                title="Uzbekistan Signs Railway Deal With China and Kyrgyzstan",
                snippet="", summary_ru="Узбекистан подписал соглашение.",
                summary_en="Uzbekistan signed a railway deal.",
                summary_uz="Oʻzbekiston temir yoʻl bitimini imzoladi.", image_url=None,
                published_at=None, type="market", tone="neutral", tone_score=0.0,
                impact="low", direction="unclear", sectors_json=None,
                relevance_score=0.5, coverage_weight=0.5, tickers_csv="")
    base.update(over)
    return _Row(base)


def test_prose_sources_may_be_machine_translated():
    import news_store

    item = news_store._row_to_item(_row())
    assert item["lang"] == "en"
    assert item["translatable"] is True


@pytest.mark.parametrize("source_id", ["moodys", "fitch"])
def test_slug_titled_sources_are_never_machine_translated(source_id):
    """The safety rule from the module comment, pinned.

    Their headline is a URL slug, so the rating notch is already gone ('+'/'-' do not survive
    one) and machine translation reads "affirms X at BB, outlook stable" as an affirmation of
    the OUTLOOK. The server must say no once, for every client.
    """
    import news_store

    item = news_store._row_to_item(
        _row(source_id=source_id, title="fitch affirms uzbekistan at bb outlook stable"))
    assert item["lang"] == "en"
    assert item["translatable"] is False
    # The Russian summary still carries the card — excluded from translation is not the
    # same as left in English.
    assert item["title_ru"] == "Узбекистан подписал соглашение."


def test_a_row_carries_a_headline_for_every_ui_language():
    import news_store

    item = news_store._row_to_item(
        _row(source_id="spot", lang="ru", title="ЦБ сохранил ставку на уровне 13,5%"))
    assert item["lang"] == "ru"
    # Russian reader: the item is already Russian, so its own headline stands.
    assert item["title_ru"] is None
    # English and Uzbek readers get our summary promoted instead of a Russian headline.
    assert item["title_en"] == "Uzbekistan signed a railway deal."
    assert item["title_uz"] == "Oʻzbekiston temir yoʻl bitimini imzoladi."
    # `translatable` is a property of the headline, not of any one reader: a Russian headline
    # is publisher prose and Chrome can do ru->en, so the client is allowed to try.
    assert item["translatable"] is True


def test_a_classification_without_translations_still_validates():
    """A model that omits summary_en/summary_uz must not fail the whole item.

    The two columns are nullable and the reader falls back to Russian, so a provider that
    ignores the new fields costs a language, never a card — and never a batch: a
    ValidationError here would send the item to classification_failed.
    """
    from news_classifier import NewsClassification

    c = NewsClassification.model_validate({"relevant": True, "summary_ru": "Только по-русски."})
    assert c.summary_en == "" and c.summary_uz == ""

    full = NewsClassification.model_validate({
        "relevant": True, "summary_ru": "Центробанк сохранил ставку.",
        "summary_en": "The central bank held its rate.",
        "summary_uz": "Markaziy bank stavkani saqlab qoldi."})
    assert full.summary_en == "The central bank held its rate."
    assert full.summary_uz == "Markaziy bank stavkani saqlab qoldi."


def test_a_translation_only_update_cannot_overwrite_or_reclassify(tmp_path, monkeypatch):
    """`set_translations` is the backfill's only write path, and it is deliberately narrow.

    It must fill an empty column and stop there: overwriting what the classifier itself wrote
    would let a cheap translation pass degrade a good summary, and touching news_nlp would
    drop the item out of the feed (the reason images and snippets have their own routes too).
    """
    import reports_catalog as rc
    import news_store

    # Patch the path function, not an env var: _catalog_db_path builds it from APP_DATA_DIR
    # and reads no environment, so anything else writes to the developer's real catalog.
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))

    news_store.upsert_news([{
        "url": "https://example.test/x", "source": "S", "source_id": "napp", "lang": "ru",
        "title": "ЦБ сохранил ставку", "snippet": "", "summary_ru": "Центробанк сохранил ставку.",
        "summary_en": "Written by the classifier.", "summary_uz": "",
        "relevant": True, "relevance_score": 0.8, "type": "regulatory", "tone": "neutral",
        "tone_score": 0.0, "impact": "high", "direction": "unclear", "sectors": [],
        "reason": "r", "model": "test", "tickers": [],
    }])
    news_store.set_translations({"https://example.test/x": {
        "en": "A backfill trying to overwrite.", "uz": "Backfill matni."}})

    item = next(i for i in news_store.get_news_feed(limit=50, days=3650)
                if i["url"] == "https://example.test/x")
    assert item["summary_en"] == "Written by the classifier."   # not overwritten
    assert item["summary_uz"] == "Backfill matni."              # the empty one was filled
    assert item["impact"] == "high"                             # classification untouched
