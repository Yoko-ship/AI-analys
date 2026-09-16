"""What language a news item is actually in — code only, no model involved.

``news.lang`` used to be the source's *declared first* language from ``news_sources.json``:
a per-source constant, so every kun.uz item was stamped ``uz`` whether it was or not, and a
Latin headline slipping through a Russian feed was still stamped ``ru``. Nothing could be
built on it. This module reads the text itself instead.

Script settles almost every item on its own: the only Latin-script sources enabled are the
three English ones (Moody's, Fitch, The Diplomat), and Uzbek Cyrillic is marked by four
letters Russian does not have. Inside Latin, Uzbek and English are separated by function
words and by the two apostrophe letters (ʻ ʼ) Uzbek Latin uses and English never does.

Two deliberate asymmetries:

* The Cyrillic test is lopsided (a quarter of the letters is enough). Russian headlines
  routinely carry Latin brand names — "Uzbekistan Airways и China Southern запустили
  код-шеринговое соглашение" is half Latin by letter count — while a genuinely English
  headline carries no Cyrillic at all.
* An undecidable Latin headline is called English, not Uzbek. English is what the
  Latin-script sources publish, and the two mistakes do not cost the same: calling a
  Russian item foreign would swap a real headline out of the feed, while calling an Uzbek
  item English only mislabels a badge.
"""
from __future__ import annotations

import re

RU, UZ, EN = "ru", "uz", "en"

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
# Latin words, keeping the apostrophe attached so "bo'yicha" stays one token.
_LATIN_WORD_RE = re.compile(r"[A-Za-z']+")
# The five characters the outlets use interchangeably for the same Uzbek letter, folded to
# one so a word list does not need five spellings of "bo'yicha".
_APOSTROPHES = str.maketrans({"ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "`": "'"})

# Letters Uzbek Cyrillic has and Russian does not. One occurrence settles the alphabet.
_UZ_CYRILLIC = frozenset("ўқғҳЎҚҒҲ")
# Uzbek Latin writes oʻ / gʻ and the glottal stop with U+02BB / U+02BC, which nothing in
# English uses — an unconditional marker.
_UZ_LETTERS = ("ʻ", "ʼ")
# In practice the outlets type those two as quotation marks instead (kun.uz writes "koʻp" with
# U+2018), so the marks have to count as well — but only where English cannot put them:
#   * U+2018 is an OPENING quote in English, so it never follows a letter. Mid-word, it is Uzbek.
#   * a plain/right apostrophe after o or g is weaker evidence, because English possessives
#     look the same ("Chicago's"), so it scores half.
_UZ_MIDWORD_RE = re.compile(r"(?<=[A-Za-z])‘(?=[A-Za-z])")
_UZ_OG_RE = re.compile(r"(?<=[oOgG])['’](?=[a-z])")

# Function words, not topic words: these carry the grammar of the language and so appear in
# almost any headline of it, while a shared proper noun (Uzbekistan, Tashkent) appears in
# headlines of all three and would tell us nothing.
_UZ_WORDS = frozenset("""
va bilan uchun ham hamda haqida haqidagi lekin ammo yana emas ekan kerak mumkin
boyicha bo'yicha yildan yilda yili yil oyida kuni
bo'ldi boldi bo'lgan bolgan qildi qilindi qilish etdi etildi berdi berildi
chiqdi ketdi oshdi kamaydi topdi aytdi dedi
milliy davlat yangi katta bosh oraliq orasida o'rtasida ortasida
so'm som foiz mlrd mln uchta ikkita
""".split())
_EN_WORDS = frozenset("""
the of and in to for on at with from by as is are was were be been has have had will
its it this that these those after over amid into more than but not new says said
up down out about against during between under above per amid via
""".split())
# Uzbek agglutinative endings, as a fallback for headlines with no function word at all
# ("Neymar Braziliya milliy jamoasidan ketdi"). Kept to endings English does not produce:
# -ning is excluded on purpose, because "planning", "warning" and "earning" all end in it.
_UZ_SUFFIXES = ("moqda", "lari", "larida", "ganda", "digan", "gani", "ishi",
                "dagi", "idan", "asidan", "ining", "larni", "lardan")
# Below this share of Cyrillic letters the text is treated as Latin script. See the module
# docstring: the test is deliberately lopsided, not a majority vote.
_CYRILLIC_SHARE = 0.25


def _uzbek_latin_score(text: str) -> int:
    """How much Uzbek evidence a Latin string carries."""
    score = 2 * sum(text.count(ch) for ch in _UZ_LETTERS)
    score += 2 * len(_UZ_MIDWORD_RE.findall(text))
    score += len(_UZ_OG_RE.findall(text))
    words = _words(text)
    score += sum(1 for w in words if w in _UZ_WORDS)
    score += sum(1 for w in words if len(w) >= 6 and w.endswith(_UZ_SUFFIXES))
    return score


def _english_score(text: str) -> int:
    return sum(1 for w in _words(text) if w in _EN_WORDS)


def _words(text: str) -> list[str]:
    return _LATIN_WORD_RE.findall(text.translate(_APOSTROPHES).lower())


def detect_lang(*texts: str | None) -> str | None:
    """``"ru"`` / ``"uz"`` / ``"en"`` for the first argument that carries letters, else None.

    Pass the title first and the snippet second: the headline is what the card shows, and a
    title that is only a ticker and a number ("UZMK: сущфакт №21") has the snippet behind it.
    Returns None when nothing has letters at all, so the caller can keep whatever it had.
    """
    for text in texts:
        text = (text or "").strip()
        if not text:
            continue
        cyrillic = _CYRILLIC_RE.findall(text)
        latin = _LATIN_RE.findall(text)
        if not cyrillic and not latin:
            continue
        if cyrillic and len(cyrillic) >= _CYRILLIC_SHARE * (len(cyrillic) + len(latin)):
            return UZ if any(ch in _UZ_CYRILLIC for ch in cyrillic) else RU
        # Latin script: Uzbek only when it out-evidences English, per the docstring.
        return UZ if _uzbek_latin_score(text) > _english_score(text) else EN
    return None


def is_foreign(lang: str | None) -> bool:
    """True when an item would show a non-Russian headline on our Russian-first feed."""
    return bool(lang) and lang != RU
