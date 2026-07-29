"""The code-only language detector behind the Russian-first news feed (news_lang.py).

Every string below is a real headline (or a real headline's shape) from an enabled source:
kun.uz for Uzbek Latin, Moody's / Fitch / The Diplomat for English, kursiv / spot / uzdaily /
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


def test_ru_headline_promotes_the_stored_summary_only_for_foreign_items():
    import news_store

    foreign = {"lang": "en", "title": "fitch affirms uzbekistan at bb outlook stable",
               "summary_ru": "Fitch подтвердило суверенный рейтинг Узбекистана."}
    assert news_store.ru_headline(foreign) == "Fitch подтвердило суверенный рейтинг Узбекистана."
    # A Russian item keeps its own headline — the summary stays the dek.
    assert news_store.ru_headline({**foreign, "lang": "ru"}) is None
    # No summary to promote: the caller falls back to the original headline rather than
    # showing an empty card.
    assert news_store.ru_headline({**foreign, "summary_ru": ""}) is None
