"""Storage + read helpers for the §3.11 news module.

Thin data layer over the same SQLite catalog the API already opens
(``reports_catalog.get_catalog_conn``); the ``news`` / ``news_nlp`` /
``news_entities`` tables live there and are created by ``_init_schema``. Kept in
its own module so the news code is cohesive and ``reports_catalog`` stays lean.

Legal invariant enforced here: we persist headline + our own ``summary_ru`` +
link + metadata only — never the source's article body.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

import news_lang
import reports_catalog as rc
from delisted import DELISTED_TICKERS

logger = logging.getLogger(__name__)

# Whitelisted so a pushed row can never smuggle arbitrary columns.
_NEWS_FIELDS = ("url", "source", "source_id", "lang", "title", "snippet", "summary_ru",
                "summary_en", "summary_uz", "image_url", "published_at", "coverage_weight")
# The UI languages a stored summary exists for. Russian is the pivot: it is what the
# classifier writes first and what every other language falls back to, so a missing
# translation costs a reader the wrong language, never a blank card.
SUMMARY_LANGS = ("ru", "en", "uz")
_NLP_FIELDS = ("relevant", "relevance_score", "type", "tone", "tone_score",
               "impact", "direction", "reason", "model")

# --------------------------------------------------------------------------- #
# feed ranking (TZ §3.11: the page promises news SORTED by likely price impact,
# so the read path ranks — it does not just order by date)
# --------------------------------------------------------------------------- #
_IMPACT_WEIGHT = {"high": 1.0, "medium": 0.65, "low": 0.35, "none": 0.1}
# An issuer-specific filing or corporate event outranks generic macro copy on a platform
# whose users hold these ~93 issuers; the model's own `impact` carries the rest.
_TYPE_WEIGHT = {"financial_report": 1.0, "corporate_event": 1.0, "regulatory": 0.8,
                "market": 0.6}
# Sources whose relevance is established before the model sees them, so the noise floor must
# not drop their items: openinfo filings are news because the issuer filed them, and a rating
# agency's item only reaches us if the collector's url_filter already matched an issuer of ours
# or the sovereign. Rating actions are rare and market-moving — losing one to a 0.29 score would
# hurt far more than admitting the occasional dull affirmation. Sources read whole (napp,
# thediplomat) are NOT here: nothing has vouched for their items before the model reads them.
_AUTHORITATIVE_SOURCES = {"openinfo_facts", "moodys", "fitch"}
# Sources whose headline is not the publisher's sentence but a URL slug we un-hyphenated
# (``title_from: "slug"`` in the registry, because these publishers ship no readable feed).
# A slug has lost the case, the punctuation and — critically — the rating notch, since '+'
# and '-' do not survive it. Machine translation cannot recover any of that and does not
# degrade gracefully on it: measured 2026-07-29, "fitch affirms uzbekistan at bb outlook
# stable" comes back as "fitch подтвердило ПРОГНОЗ по Узбекистану на уровне bb стабильный" —
# Fitch affirmed the RATING, and the outlook being stable is a separate fact. On the same
# engine, real prose ("Central Asia Weighs Its Options as Great Power Competition
# Intensifies") translates cleanly. So the rule is not "don't translate English", it is
# "don't translate a headline the publisher never wrote": these items keep ``summary_ru``
# and their original wording, and the read path marks them ``translatable: False`` so no
# client can decide otherwise.
_SLUG_TITLE_SOURCES = {"moodys", "fitch"}
# Half-life of the recency decay: a story is worth half as much after this many hours.
_RANK_HALF_LIFE_H = float(os.getenv("NEWS_RANK_HALF_LIFE_H", "36"))
# Items the model marked relevant but scored below this are dropped as noise. Measured
# 2026-07-25 on real rows: genuinely relevant items scored 0.60-0.85, rejected ones
# 0.00-0.10, so this sits in an empty band. Set to 0 to disable the floor.
_MIN_RELEVANCE = float(os.getenv("NEWS_MIN_RELEVANCE", "0.3"))
# Jaccard similarity over significant title words above which two items are treated as the
# same story from different outlets. 0 disables cross-source de-duplication.
_DEDUP_SIMILARITY = float(os.getenv("NEWS_DEDUP_SIMILARITY", "0.62"))
_DEDUP_WINDOW_H = float(os.getenv("NEWS_DEDUP_WINDOW_H", "48"))
# Short/function words carry no topical signal, so they must not inflate the overlap.
_STOPWORDS = {
    "в", "на", "и", "с", "по", "за", "из", "к", "у", "о", "об", "от", "до", "для", "не",
    "что", "как", "это", "при", "или", "но", "а", "же", "уже", "еще", "их", "его", "ее",
    "был", "была", "было", "были", "будет", "стал", "стала", "млн", "млрд", "тыс", "года",
    "год", "году", "the", "a", "an", "of", "in", "on", "to", "for", "and", "is", "was",
    "will", "has", "have", "by", "with", "at", "from", "va", "bilan", "uchun", "boldi",
}
_WORD_RE = re.compile(r"[\wЀ-ӿ]+", re.UNICODE)


def upsert_news(items: list[dict[str, Any]]) -> int:
    """Insert/refresh news items with their NLP output and ticker links.

    Each item carries the ``news`` columns plus the classifier output (``relevant``,
    ``type``, ``tone``, ``tone_score``, ``impact``, ``direction``, ``sectors``,
    ``reason``, ``model``) and a ``tickers`` list. Dedup is by ``url``.
    """
    if not items:
        return 0
    conn = rc.get_catalog_conn()
    written = 0
    with conn:
        for it in items:
            url = (it.get("url") or "").strip()
            if not url or not (it.get("title") or "").strip():
                continue
            cur = conn.execute(
                """
                INSERT INTO news (url, source, source_id, lang, title, snippet, summary_ru,
                                  summary_en, summary_uz,
                                  image_url, published_at, coverage_weight, collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(url) DO UPDATE SET
                    title           = excluded.title,
                    snippet         = excluded.snippet,
                    summary_ru      = excluded.summary_ru,
                    -- COALESCE, unlike summary_ru: a re-push that could not produce a
                    -- translation must not wipe one an earlier run (or the backfill)
                    -- already wrote.
                    summary_en      = COALESCE(NULLIF(excluded.summary_en, ''), news.summary_en),
                    summary_uz      = COALESCE(NULLIF(excluded.summary_uz, ''), news.summary_uz),
                    image_url       = COALESCE(excluded.image_url, news.image_url),
                    published_at    = COALESCE(excluded.published_at, news.published_at),
                    coverage_weight = excluded.coverage_weight
                """,
                (url, it.get("source", ""), it.get("source_id"), it.get("lang"),
                 it.get("title", "").strip(), it.get("snippet"), it.get("summary_ru"),
                 it.get("summary_en"), it.get("summary_uz"),
                 it.get("image_url"), it.get("published_at"), float(it.get("coverage_weight") or 0.5)),
            )
            row = conn.execute("SELECT id FROM news WHERE url = ?", (url,)).fetchone()
            if row is None:
                continue
            news_id = row["id"]
            conn.execute(
                """
                INSERT INTO news_nlp (news_id, relevant, relevance_score, type, tone,
                                      tone_score, impact, direction, sectors_json, reason, model,
                                      classified_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(news_id) DO UPDATE SET
                    relevant=excluded.relevant, relevance_score=excluded.relevance_score,
                    type=excluded.type, tone=excluded.tone, tone_score=excluded.tone_score,
                    impact=excluded.impact, direction=excluded.direction,
                    sectors_json=excluded.sectors_json, reason=excluded.reason,
                    model=excluded.model, classified_at=datetime('now')
                """,
                (news_id, 1 if it.get("relevant") else 0, it.get("relevance_score"),
                 it.get("type"), it.get("tone"), it.get("tone_score"), it.get("impact"),
                 it.get("direction"), json.dumps(it.get("sectors") or [], ensure_ascii=False),
                 it.get("reason"), it.get("model")),
            )
            conn.execute("DELETE FROM news_entities WHERE news_id = ?", (news_id,))
            for ticker in {str(t).strip().upper() for t in (it.get("tickers") or []) if str(t).strip()}:
                if ticker in DELISTED_TICKERS:
                    # The issuer has no page on the site any more, so the chip would
                    # link nowhere. The story itself is kept — only the tag is dropped.
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO news_entities (news_id, ticker) VALUES (?,?)",
                    (news_id, ticker),
                )
            written += 1
    conn.close()
    return written


def existing_urls(urls: list[str]) -> set[str]:
    """Return the subset of ``urls`` already stored — so the collector skips
    re-classifying (and re-paying for) items it has already processed."""
    urls = [u for u in urls if u]
    if not urls:
        return set()
    conn = rc.get_catalog_conn()
    found: set[str] = set()
    # Chunk to stay under SQLite's variable limit.
    for i in range(0, len(urls), 400):
        chunk = urls[i:i + 400]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT url FROM news WHERE url IN ({placeholders})", chunk
        ).fetchall()
        found.update(r["url"] for r in rows)
    conn.close()
    return found


def rows_without_image(*, limit: int = 40, days: int = 90) -> list[dict[str, Any]]:
    """Stored items that still have no preview image — backfill candidates.

    Feed-visible items first (``relevant``, then newest): the per-run fetch cap should
    be spent on the cards users actually see, not on items filtered out as off-topic.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.id, n.url, n.source_id FROM news n
        LEFT JOIN news_nlp p ON p.news_id = n.id
        WHERE (n.image_url IS NULL OR n.image_url = '')
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        ORDER BY COALESCE(p.relevant, 0) DESC, COALESCE(n.published_at, n.collected_at) DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", max(1, min(limit, 500))),
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "url": r["url"], "source_id": r["source_id"]} for r in rows]


def image_urls_for(urls: list[str]) -> dict[str, str]:
    """url → stored ``image_url`` for those we already have one for, so a backfill
    re-run pushes what is already known instead of re-fetching the page."""
    urls = [u for u in urls if u]
    if not urls:
        return {}
    conn = rc.get_catalog_conn()
    found: dict[str, str] = {}
    for i in range(0, len(urls), 400):
        chunk = urls[i:i + 400]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT url, image_url FROM news "
            f"WHERE url IN ({placeholders}) AND image_url IS NOT NULL AND image_url <> ''",
            chunk,
        ).fetchall()
        found.update({r["url"]: r["image_url"] for r in rows})
    conn.close()
    return found


def set_image_urls(images: dict[str, str]) -> int:
    """Fill in ``image_url`` for stored rows that have none; return rows changed.

    Image-only updates come through here, never ``upsert_news``: that path also writes
    ``news_nlp``, so an image-only record would reset the item's classification (and
    with ``relevant`` gone, drop it out of the feed). Never overwrites an existing image.
    """
    if not images:
        return 0
    conn = rc.get_catalog_conn()
    changed = 0
    with conn:
        for url, img in images.items():
            if not url or not img:
                continue
            cur = conn.execute(
                "UPDATE news SET image_url = ? "
                "WHERE url = ? AND (image_url IS NULL OR image_url = '')",
                (img, url),
            )
            changed += cur.rowcount
    conn.close()
    return changed


def rows_missing_translations(*, limit: int = 60, days: int = 90) -> list[dict[str, Any]]:
    """Stored items that have a Russian summary but not an English or Uzbek one.

    These are rows collected before the classifier wrote all three. Feed-visible items first
    (``relevant``, then newest), for the same reason the image backfill orders that way: the
    per-run budget should be spent on cards users actually see.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.url, n.title, n.summary_ru, n.summary_en, n.summary_uz
        FROM news n LEFT JOIN news_nlp p ON p.news_id = n.id
        WHERE COALESCE(n.summary_ru, '') <> ''
          AND (COALESCE(n.summary_en, '') = '' OR COALESCE(n.summary_uz, '') = '')
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        ORDER BY COALESCE(p.relevant, 0) DESC, COALESCE(n.published_at, n.collected_at) DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", max(1, min(limit, 500))),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_translations(translations: dict[str, dict[str, str]]) -> int:
    """Fill ``summary_en`` / ``summary_uz`` on stored rows; return rows changed.

    A partial update for the same reason as :func:`set_image_urls`: ``upsert_news`` also
    writes ``news_nlp``, so a translation-only record would reset the item's classification
    and drop it out of the feed. Only writes where the column is still empty, so a re-run is
    free and can never overwrite a translation the classifier itself produced.
    """
    if not translations:
        return 0
    conn = rc.get_catalog_conn()
    changed = 0
    with conn:
        for url, langs in translations.items():
            if not url or not isinstance(langs, dict):
                continue
            for code in ("en", "uz"):
                text = (langs.get(code) or "").strip()
                if not text:
                    continue
                cur = conn.execute(
                    f"UPDATE news SET summary_{code} = ? "
                    f"WHERE url = ? AND COALESCE(summary_{code}, '') = ''",
                    (text, url),
                )
                changed += cur.rowcount
    conn.close()
    return changed


def set_snippets(snippets: dict[str, str]) -> int:
    """Replace ``news.snippet`` on already-stored rows; return rows changed.

    The same reasoning as :func:`set_image_urls`, and the same reason it is not
    ``upsert_news``: that path also writes ``news_nlp``, so a snippet-only record would reset
    the item's classification and drop it out of the feed. Unlike images this DOES overwrite,
    because the whole point is to replace a bare "Существенный факт №21" with the filing's
    actual figures — but only ever with a longer text, so a re-run cannot shrink a row back.
    """
    if not snippets:
        return 0
    conn = rc.get_catalog_conn()
    changed = 0
    with conn:
        for url, text in snippets.items():
            if not url or not text:
                continue
            cur = conn.execute(
                "UPDATE news SET snippet = ? "
                "WHERE url = ? AND LENGTH(COALESCE(snippet, '')) < LENGTH(?)",
                (text, url, text),
            )
            changed += cur.rowcount
    conn.close()
    return changed


def delete_failed_classifications(*, limit: int = 1000) -> dict[str, Any]:
    """Drop items whose classification failed, so the collector can retry them.

    A failed classification (no API key, quota, outage) is stored as ``relevant = 0``:
    invisible in the feed, yet its URL makes ``existing_urls`` treat the item as done —
    permanently blocking a re-classification. Deleting the row is the retry: the source
    feed serves the item again on the next run. Only rows whose reason is exactly
    ``classification_failed`` are touched; a genuine "not market-relevant" verdict carries
    a real reason string and is left alone.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.id, n.source_id FROM news n JOIN news_nlp p ON p.news_id = n.id
        WHERE p.reason = 'classification_failed' LIMIT ?
        """,
        (max(1, min(limit, 5000)),),
    ).fetchall()
    ids = [r["id"] for r in rows]
    by_source: dict[str, int] = {}
    for r in rows:
        key = r["source_id"] or "?"
        by_source[key] = by_source.get(key, 0) + 1
    # ON DELETE CASCADE is declared and foreign_keys is ON, but the children are removed
    # explicitly so this stays correct on any connection.
    with conn:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM news_entities WHERE news_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM news_nlp WHERE news_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM news WHERE id IN ({placeholders})", chunk)
    conn.close()
    return {"deleted": len(ids), "by_source": by_source}


def summary_for(item: dict[str, Any], lang: str) -> str:
    """The stored summary in ``lang``, falling back to Russian, then to "".

    Russian is the pivot: it is what the classifier writes first, and a row collected before
    the other two columns existed has only that. Falling back keeps a card readable in the
    wrong language rather than empty, which is the better failure.
    """
    if lang in SUMMARY_LANGS:
        text = (item.get(f"summary_{lang}") or "").strip()
        if text:
            return text
    return (item.get("summary_ru") or "").strip()


def headline_for(item: dict[str, Any], lang: str) -> str | None:
    """A headline in ``lang`` for an item whose own headline is in another language — else None.

    Nothing is translated on this path. What we already have is the classifier's own
    one-or-two-sentence summary, written in all three UI languages in the same call that
    classified the item, which until now sat as small print underneath a headline the reader
    could not read. Promoting it to the headline costs no call and puts our own text on the
    card instead of the source's.

    An item counts as foreign when its own language is not the reader's — so on the English
    site a Russian headline needs this exactly as much as an English one does on the Russian
    site. Returns None when the item is already in the reader's language, or when we have no
    summary to promote (the caller then keeps the original rather than blanking the card).

    Deliberately NOT a phrase-table translation of the rating agencies' headlines, formulaic
    though those are ("fitch affirms uzbekistan at bb outlook stable" and a few dozen
    variants). Their headline reaches us through the URL slug, and a slug has already lost
    the notch — '+' and '-' do not survive it — so a template would print «BB» where the
    action actually said "BB-". A fabricated rating notch stated in confident Russian is a
    much worse failure than an English headline, so the original wording stays authoritative
    and the card shows it as attribution.
    """
    item_lang = item.get("lang")
    if not item_lang or item_lang == lang:
        return None
    return summary_for(item, lang) or None


def _row_to_item(r: Any) -> dict[str, Any]:
    keys = r.keys()
    item = {
        "id": r["id"], "url": r["url"], "source": r["source"], "source_id": r["source_id"],
        # Read from the text, not from the stored column: that column is only as good as the
        # source's declared language was on the day the row was written, so detecting here
        # also corrects rows collected before per-item detection existed.
        "lang": news_lang.detect_lang(r["title"], r["snippet"]) or r["lang"],
        "title": r["title"], "snippet": r["snippet"],
        "summary_ru": r["summary_ru"],
        # Absent on a row read back through an old SELECT list, and absent on rows collected
        # before the columns existed — both mean "no translation", not an error.
        "summary_en": r["summary_en"] if "summary_en" in keys else None,
        "summary_uz": r["summary_uz"] if "summary_uz" in keys else None,
        "image_url": r["image_url"], "published_at": r["published_at"],
        "type": r["type"], "tone": r["tone"], "tone_score": r["tone_score"],
        "impact": r["impact"], "direction": r["direction"],
        "sectors": json.loads(r["sectors_json"]) if r["sectors_json"] else [],
        "relevance_score": r["relevance_score"] if "relevance_score" in keys else None,
        "coverage_weight": r["coverage_weight"] if "coverage_weight" in keys else None,
        "tickers": ([t for t in (r["tickers_csv"] or "").split(",") if t]
                    if "tickers_csv" in keys else []),
    }
    # One field per UI language rather than a `?lang=` parameter on the endpoint: the feed is
    # served to all three from one cached response, and the client already knows which
    # language it is rendering. `title_ru` keeps its name — it is what the frontend reads.
    item["title_ru"] = headline_for(item, "ru")
    item["title_en"] = headline_for(item, "en")
    item["title_uz"] = headline_for(item, "uz")
    # Whether a client may put this headline through a machine translator (the browser's
    # own, on-device one). A property of the HEADLINE, not of any one reader's language:
    # which direction needs translating depends on who is looking, and the client knows that
    # from `lang`. What the server settles is whether the text is the publisher's own prose
    # at all — see _SLUG_TITLE_SOURCES for why the rating agencies are excluded here rather
    # than in the UI.
    item["translatable"] = bool(item["lang"]) and item["source_id"] not in _SLUG_TITLE_SOURCES
    return item


def _parse_dt(value: Any) -> datetime | None:
    """Stored timestamps come in both 'YYYY-MM-DDTHH:MM:SS' (feeds, filings) and
    'YYYY-MM-DD HH:MM:SS' (collected_at) shapes; dates alone also occur."""
    if not value:
        return None
    text = str(value).replace("T", " ").strip()
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    return None


def _title_words(title: str | None) -> set[str]:
    return {w for w in (m.group(0).lower() for m in _WORD_RE.finditer(title or ""))
            if len(w) > 3 and w not in _STOPWORDS}


def rank_score(item: dict[str, Any], now: datetime | None = None) -> float:
    """How prominently this item deserves to sit in the feed, in 0..1.

    Quality is the model's estimated price impact and its own relevance score, weighted by
    how authoritative the source is and whether the item names an issuer we cover; that is
    then decayed by age, because a stale high-impact story is still stale. Deterministic and
    pure, so the ordering is explainable and testable.
    """
    now = now or datetime.now()
    impact = _IMPACT_WEIGHT.get((item.get("impact") or "none"), 0.1)
    relevance = max(0.0, min(float(item.get("relevance_score") or 0.0), 1.0))
    source = max(0.0, min(float(item.get("coverage_weight") or 0.5), 1.0))
    type_w = _TYPE_WEIGHT.get((item.get("type") or "market"), 0.6)
    names_issuer = 1.0 if item.get("tickers") else 0.0
    quality = (0.38 * impact + 0.27 * relevance + 0.15 * source
               + 0.12 * type_w + 0.08 * names_issuer)
    published = _parse_dt(item.get("published_at"))
    age_h = max((now - published).total_seconds() / 3600.0, 0.0) if published else 24.0
    decay = 0.5 ** (age_h / _RANK_HALF_LIFE_H) if _RANK_HALF_LIFE_H > 0 else 1.0
    return round(quality * decay, 6)


def _drop_noise(items: list[dict[str, Any]], min_relevance: float) -> list[dict[str, Any]]:
    """Skip items the classifier passed as relevant but scored as barely so.

    Issuer filings are exempt: a disclosure is news because the issuer filed it, whatever
    score a model puts on 'change in the list of affiliated persons'.
    """
    if min_relevance <= 0:
        return items
    kept = []
    for it in items:
        if it.get("source_id") in _AUTHORITATIVE_SOURCES:
            kept.append(it)
            continue
        if float(it.get("relevance_score") or 0.0) >= min_relevance:
            kept.append(it)
    if len(kept) != len(items):
        logger.info("news feed: dropped %d low-relevance item(s) below %.2f",
                    len(items) - len(kept), min_relevance)
    return kept


def _dedupe_stories(items: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Collapse the same story reported by several outlets, keeping the best-ranked copy.

    Compares significant title words (Jaccard) only between items published within
    ``NEWS_DEDUP_WINDOW_H`` of each other — the same wording months apart is a different
    story (a daily FX report, say), not a duplicate. Items are expected pre-sorted best
    first, so the survivor is the one that already ranked highest.
    """
    if threshold <= 0 or len(items) < 2:
        return items
    kept: list[tuple[set[str], datetime | None, dict[str, Any]]] = []
    dropped = 0
    for it in items:
        words = _title_words(it.get("title"))
        when = _parse_dt(it.get("published_at"))
        duplicate = False
        if words:
            for prev_words, prev_when, _prev in kept:
                if not prev_words:
                    continue
                if when and prev_when:
                    gap_h = abs((when - prev_when).total_seconds()) / 3600.0
                    if gap_h > _DEDUP_WINDOW_H:
                        continue
                union = words | prev_words
                if union and len(words & prev_words) / len(union) >= threshold:
                    duplicate = True
                    break
        if duplicate:
            dropped += 1
        else:
            kept.append((words, when, it))
    if dropped:
        logger.info("news feed: merged %d duplicate cross-source story/stories", dropped)
    return [it for _w, _t, it in kept]


def get_news_feed(
    *, limit: int = 60, days: int = 30, only_relevant: bool = True,
    news_type: str | None = None, order: str = "rank",
    min_relevance: float | None = None,
) -> list[dict[str, Any]]:
    """Public editorial feed: relevant, classified items, **ranked by likely impact**.

    ``order="rank"`` (default) scores every candidate with :func:`rank_score`, drops
    low-relevance noise, merges the same story reported by several outlets, and returns the
    best first — which is what the page claims to show. ``order="recent"`` keeps the plain
    newest-first ordering (the sidebar's "latest" list).

    Ranking happens over a window wider than ``limit`` so a strong item just outside the
    newest N can still surface; each returned item carries its ``rank`` for transparency.
    """
    fetch = max(1, min(limit, 200))
    if order == "rank":
        # Rank over more rows than we return, or a high-impact filing from yesterday could
        # never outrank today's currency-rate note simply for being one row too far down.
        fetch = max(1, min(max(limit * 3, 60), 300))
    conn = rc.get_catalog_conn()
    q = [
        "SELECT n.*, p.type, p.tone, p.tone_score, p.impact, p.direction, p.sectors_json,",
        "       p.relevant, p.relevance_score,",
        "       (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e",
        "         WHERE e.news_id = n.id) AS tickers_csv",
        "FROM news n JOIN news_nlp p ON p.news_id = n.id",
        "WHERE 1=1",
    ]
    params: list[Any] = []
    if only_relevant:
        q.append("AND p.relevant = 1")
    if news_type:
        q.append("AND p.type = ?")
        params.append(news_type)
    if days:
        q.append("AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))")
        params.append(f"-{int(days)} days")
    q.append("ORDER BY COALESCE(n.published_at, n.collected_at) DESC LIMIT ?")
    params.append(fetch)
    rows = conn.execute(" ".join(q), params).fetchall()
    conn.close()
    items = [_row_to_item(r) for r in rows]
    if order != "rank":
        return items[:max(1, min(limit, 200))]

    now = datetime.now()
    items = _drop_noise(items, _MIN_RELEVANCE if min_relevance is None else min_relevance)
    for it in items:
        it["rank"] = rank_score(it, now)
    items.sort(key=lambda it: (-it["rank"], str(it.get("published_at") or "")))
    items = _dedupe_stories(items, _DEDUP_SIMILARITY)
    return items[:max(1, min(limit, 200))]


def get_news_item(news_id: int) -> dict[str, Any] | None:
    """One stored item with everything the article page shows — or ``None``.

    Read-only over what the collector already wrote: headline, our own ``summary_ru``,
    the classifier's tone / impact / direction, the issuers it names and the link out.
    Opening an article therefore costs nothing — no model is called on this path, and no
    source article body is served, because we never store one (see the module docstring).

    ``reason`` is deliberately not returned: the classifier prompt declares it an internal
    note, so it stays internal.
    """
    try:
        news_id = int(news_id)
    except (TypeError, ValueError):
        return None
    conn = rc.get_catalog_conn()
    row = conn.execute(
        """
        SELECT n.*, p.type, p.tone, p.tone_score, p.impact, p.direction, p.sectors_json,
               p.relevant, p.relevance_score, p.model, p.classified_at,
               (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e
                 WHERE e.news_id = n.id) AS tickers_csv
        FROM news n JOIN news_nlp p ON p.news_id = n.id
        WHERE n.id = ?
        """,
        (news_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    item = _row_to_item(row)
    item.update({
        "relevant": bool(row["relevant"]),
        "model": row["model"],
        "classified_at": row["classified_at"],
        "collected_at": row["collected_at"],
    })
    item["rank"] = rank_score(item)
    return item


def get_related_news(news_id: int, *, limit: int = 6, days: int = 180) -> list[dict[str, Any]]:
    """Neighbouring stories for the article page, best link first.

    Items sharing an issuer come first — on a platform organised by issuer that is the
    strongest connection — then the rest of the same news class fills the block. Plain SQL
    over stored rows: no similarity model, no extra classification.
    """
    try:
        news_id = int(news_id)
    except (TypeError, ValueError):
        return []
    cap = max(1, min(limit, 20))
    window = f"-{int(days)} days"
    conn = rc.get_catalog_conn()
    base = conn.execute(
        """
        SELECT p.type, (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e
                         WHERE e.news_id = n.id) AS tickers_csv
        FROM news n JOIN news_nlp p ON p.news_id = n.id WHERE n.id = ?
        """,
        (news_id,),
    ).fetchone()
    if base is None:
        conn.close()
        return []
    select = (
        "SELECT n.*, p.type, p.tone, p.tone_score, p.impact, p.direction, p.sectors_json,"
        "       p.relevance_score,"
        "       (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e"
        "         WHERE e.news_id = n.id) AS tickers_csv"
        " FROM news n JOIN news_nlp p ON p.news_id = n.id"
    )
    recent = ("AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))"
              " ORDER BY COALESCE(n.published_at, n.collected_at) DESC LIMIT ?")
    picked: dict[int, dict[str, Any]] = {}

    tickers = [t for t in (base["tickers_csv"] or "").split(",") if t]
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"{select} JOIN news_entities x ON x.news_id = n.id"
            f" WHERE x.ticker IN ({placeholders}) AND n.id <> ? AND p.relevant = 1"
            f" GROUP BY n.id {recent}",
            (*tickers, news_id, window, cap),
        ).fetchall()
        for r in rows:
            picked[r["id"]] = _row_to_item(r)

    if len(picked) < cap and base["type"]:
        rows = conn.execute(
            f"{select} WHERE p.type = ? AND n.id <> ? AND p.relevant = 1 {recent}",
            (base["type"], news_id, window, cap * 2),
        ).fetchall()
        for r in rows:
            if len(picked) >= cap:
                break
            picked.setdefault(r["id"], _row_to_item(r))
    conn.close()
    return list(picked.values())[:cap]


def get_news_for_ticker(ticker: str, *, limit: int = 30, days: int = 90) -> list[dict[str, Any]]:
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.*, p.type, p.tone, p.tone_score, p.impact, p.direction, p.sectors_json, p.relevant
        FROM news n
        JOIN news_entities e ON e.news_id = n.id
        JOIN news_nlp p       ON p.news_id = n.id
        WHERE e.ticker = ? AND p.relevant = 1
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        ORDER BY COALESCE(n.published_at, n.collected_at) DESC LIMIT ?
        """,
        (ticker.strip().upper(), f"-{int(days)} days", max(1, min(limit, 100))),
    ).fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


def get_news_sentiment(ticker: str, *, days: int = 30) -> dict[str, Any]:
    """Coverage-weighted background tone for an issuer — the §3.4 info-dimension входная точка.

    Returns a weighted mean tone_score plus counts. A statistical aggregate, not a verdict.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT p.tone, p.tone_score, n.coverage_weight
        FROM news n
        JOIN news_entities e ON e.news_id = n.id
        JOIN news_nlp p       ON p.news_id = n.id
        WHERE e.ticker = ? AND p.relevant = 1 AND p.tone_score IS NOT NULL
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        """,
        (ticker.strip().upper(), f"-{int(days)} days"),
    ).fetchall()
    conn.close()
    if not rows:
        return {"ticker": ticker.upper(), "count": 0, "weighted_tone": None,
                "positive": 0, "neutral": 0, "negative": 0}
    wsum = sum((r["coverage_weight"] or 0.5) for r in rows)
    weighted = sum((r["tone_score"] or 0.0) * (r["coverage_weight"] or 0.5) for r in rows) / (wsum or 1.0)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        counts[r["tone"]] = counts.get(r["tone"], 0) + 1
    return {"ticker": ticker.upper(), "count": len(rows), "weighted_tone": round(weighted, 3), **counts}
