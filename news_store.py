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


def record_news_usage(record: dict[str, Any]) -> int:
    """Persist one collector usage record, idempotently by ``run_id``."""
    run_id = str(record.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("news usage record requires run_id")
    fields = (
        "run_id", "mode", "started_at", "finished_at", "model", "calls",
        "prompt_tokens", "completion_tokens", "cached_input_tokens", "total_tokens",
        "subscription_tokens", "codex_before_pct", "codex_after_pct", "codex_delta_pct",
        "codex_resets_at", "fetched", "classified", "relevant", "pushed", "status",
    )
    values = [record.get(field) for field in fields]
    conn = rc.get_catalog_conn()
    try:
        with conn:
            conn.execute(
                f"""
                INSERT INTO news_usage_runs ({', '.join(fields)})
                VALUES ({', '.join('?' for _ in fields)})
                ON CONFLICT(run_id) DO UPDATE SET
                    mode=excluded.mode,
                    finished_at=excluded.finished_at,
                    model=excluded.model,
                    calls=excluded.calls,
                    prompt_tokens=excluded.prompt_tokens,
                    completion_tokens=excluded.completion_tokens,
                    cached_input_tokens=excluded.cached_input_tokens,
                    total_tokens=excluded.total_tokens,
                    subscription_tokens=excluded.subscription_tokens,
                    codex_before_pct=excluded.codex_before_pct,
                    codex_after_pct=excluded.codex_after_pct,
                    codex_delta_pct=excluded.codex_delta_pct,
                    codex_resets_at=excluded.codex_resets_at,
                    fetched=excluded.fetched,
                    classified=excluded.classified,
                    relevant=excluded.relevant,
                    pushed=excluded.pushed,
                    status=excluded.status
                """,
                values,
            )
        return 1
    finally:
        conn.close()

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
_AUTHORITATIVE_SOURCES = {"openinfo_facts", "moodys", "fitch", "spglobal"}
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
# Jaccard similarity above which two items are treated as the same story from different
# outlets. Measured against the title AND our own summary_ru (see _dedupe_stories for why
# the summary is the stronger signal). 0 disables cross-source de-duplication.
# 0.55, from the 2026-08-11 audit of 200 served cards: every observed false pair (two
# «Узбекистан и X обсудили проекты» meetings, a deposit-tax vs a carbon-tax proposal) sat
# at ≤ 0.42, and the closest pair that is genuinely two stories — the ЦБ and the Институт
# фискального анализа each commenting on the same tax idea — scored 0.53. True duplicates
# run 0.55–1.0. The band 0.42–0.55 still holds real duplicates (a retold headline shares
# fewer words than a copied one); they are the price of never merging two real stories.
_DEDUP_SIMILARITY = float(os.getenv("NEWS_DEDUP_SIMILARITY", "0.55"))
# The band below the threshold where a retelling can still hide (headline rewritten, only
# the gist shared). Overlap alone cannot split this band — see _DEDUP_BAND's corroboration
# rule in _dedupe_stories. 0 disables the band.
_DEDUP_BAND = float(os.getenv("NEWS_DEDUP_BAND", "0.40"))
# 72h, not 48: the same CBU reserves release was carded by two outlets 66h apart (weekend
# in between), while genuinely recurring same-title items (spot's weekly «какие банки
# работают в выходные») sit ≥ 160h apart — the window has room on both sides.
_DEDUP_WINDOW_H = float(os.getenv("NEWS_DEDUP_WINDOW_H", "72"))
# Summary similarity is only trusted when both summaries carry at least this many
# significant words: two four-word summaries can collide on phrasing alone.
_DEDUP_MIN_SUMMARY_WORDS = 5
# The integer part of every figure an item states, title + summary: «64,34 млрд» and
# «$64,3 млрд» both say 64. Fragments after the decimal separator are NOT tokens — \d+
# alone would read «64,34» as a 64 and a 34, and the 34 could match anything.
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
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
                    "INSERT INTO news_entities (news_id, ticker) VALUES (?,?) "
                    "ON CONFLICT DO NOTHING",
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


def set_image_urls(images: dict[str, str], *, replace: bool = False) -> int:
    """Fill in ``image_url`` for stored rows that have none; return rows changed.

    Image-only updates come through here, never ``upsert_news``: that path also writes
    ``news_nlp``, so an image-only record would reset the item's classification (and
    with ``relevant`` gone, drop it out of the feed).

    ``replace=True`` is the one case where an existing image is overwritten: the collector's
    upgrade pass, which swaps a feed's thumbnail for the full-size original behind it (uza.uz
    ships 320px in RSS and keeps 1024px one filename away). The caller has already verified
    the replacement exists and is an image, and the update is still a no-op when the row
    already holds it.
    """
    if not images:
        return 0
    conn = rc.get_catalog_conn()
    changed = 0
    where = "" if replace else " AND (image_url IS NULL OR image_url = '')"
    with conn:
        for url, img in images.items():
            if not url or not img:
                continue
            cur = conn.execute(
                f"UPDATE news SET image_url = ? WHERE url = ?{where} "
                "AND COALESCE(image_url, '') <> ?",
                (img, url, img),
            )
            changed += cur.rowcount
    conn.close()
    return changed


def rows_with_upgradable_image(*, days: int = 90, limit: int = 500) -> list[dict[str, Any]]:
    """Stored rows that have an image — candidates for the thumbnail-to-original swap.

    Which of them can actually be upgraded is the collector's business (the rules live in the
    source registry); this only supplies the rows and their current image.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.url, n.source_id, n.image_url FROM news n
        WHERE COALESCE(n.image_url, '') <> ''
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        ORDER BY COALESCE(n.published_at, n.collected_at) DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", max(1, min(limit, 2000))),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def rows_without_detail(*, limit: int = 20, days: int = 30,
                        source_ids: list[str] | None = None,
                        oldest_first: bool = False) -> list[dict[str, Any]]:
    """Feed-visible items with no long read yet — the detail pass's work list.

    Relevant rows only. ``source_ids`` narrows it to the sources that HAVE an article page
    (the caller reads that from the registry — the rating agencies serve a shell and openinfo
    has no page at all).

    ``oldest_first`` exists because newest-first ALONE starves the backlog. The pass has a
    per-run cap; while the cap is below the day's inflow, a newest-first work list picks
    today's items every run and yesterday's are pushed down for good. Measured on the live
    feed: 148 items eligible for a long read, 18 written, and all eighteen from the last two
    days — three weeks of stories that would never have been reached. The caller spends part
    of each run from this end so the tail drains.
    """
    conn = rc.get_catalog_conn()
    q = ["SELECT n.url, n.title, n.source_id, n.snippet, n.summary_ru",
         "FROM news n JOIN news_nlp p ON p.news_id = n.id",
         "WHERE p.relevant = 1 AND COALESCE(n.detail_ru, '') = ''",
         "AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))"]
    params: list[Any] = [f"-{int(days)} days"]
    if source_ids:
        q.append(f"AND n.source_id IN ({','.join('?' * len(source_ids))})")
        params.extend(source_ids)
    q.append("ORDER BY COALESCE(n.published_at, n.collected_at) "
             + ("ASC" if oldest_first else "DESC") + " LIMIT ?")
    params.append(max(1, min(limit, 200)))
    rows = conn.execute(" ".join(q), params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_details(details: dict[str, dict[str, str]]) -> int:
    """Write the long read on stored rows; return rows changed.

    Partial, like :func:`set_translations` and for the same reason: ``upsert_news`` rewrites
    ``news_nlp`` too, so a detail-only record would reset the classification and drop the item
    out of the feed. Only fills an empty column, so a re-run is free and cannot overwrite a
    better text with a worse one.
    """
    if not details:
        return 0
    conn = rc.get_catalog_conn()
    changed = 0
    with conn:
        for url, langs in details.items():
            if not url or not isinstance(langs, dict):
                continue
            for code in SUMMARY_LANGS:
                text = (langs.get(code) or "").strip()
                if not text:
                    continue
                cur = conn.execute(
                    f"UPDATE news SET detail_{code} = ? "
                    f"WHERE url = ? AND COALESCE(detail_{code}, '') = ''",
                    (text, url),
                )
                changed += cur.rowcount
    conn.close()
    return changed


def detail_for(item: dict[str, Any], lang: str) -> str:
    """The stored long read in ``lang``, falling back to Russian, then to "".

    Same pivot rule as :func:`summary_for`: Russian is what always exists, so a reader in
    another language gets the wrong language rather than an empty page.
    """
    if lang in SUMMARY_LANGS:
        text = (item.get(f"detail_{lang}") or "").strip()
        if text:
            return text
    return (item.get("detail_ru") or "").strip()


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


def delete_rejected_from_source(source_id: str, *, days: int = 60,
                                limit: int = 1000) -> dict[str, Any]:
    """Drop one source's REJECTED rows so the next run fetches and judges them again.

    A verdict is stored so we never pay to classify the same item twice, which also means a
    gate that was wrong stays wrong for as long as the row lives. When the gate itself
    changes — a source gains ``skip_triage_filter``, an authoritative source stops being
    overridable by the model — the items it already buried are exactly the ones the change
    was for, and nothing re-reads them on its own.

    Only ``relevant = 0`` rows are touched: a published card is never withdrawn by this, and
    an item that stays uninteresting simply gets the same verdict again next run (one
    classification, once). Bounded by ``days`` so it cannot walk the whole archive.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT n.id FROM news n JOIN news_nlp p ON p.news_id = n.id
        WHERE n.source_id = ? AND COALESCE(p.relevant, 0) = 0
          AND COALESCE(n.published_at, n.collected_at) >= datetime('now', ?)
        LIMIT ?
        """,
        (source_id, f"-{int(days)} days", max(1, min(limit, 5000))),
    ).fetchall()
    ids = [r["id"] for r in rows]
    with conn:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM news_entities WHERE news_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM news_nlp WHERE news_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM news WHERE id IN ({placeholders})", chunk)
    conn.close()
    return {"source_id": source_id, "deleted": len(ids)}


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
        # Whether this item HAS a long read, not the text of it: three languages of
        # multi-paragraph prose is ~5KB per item, and the feed returns up to 200. The text
        # itself is added by get_news_item, which serves exactly one story.
        "has_detail": bool("detail_ru" in keys and (r["detail_ru"] or "").strip()),
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


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _number_tokens(it: dict[str, Any]) -> set[str]:
    """The integer parts of the figures an item states, title + summary."""
    text = f"{it.get('title') or ''} {it.get('summary_ru') or ''}"
    return {m.group(0).split(",")[0].split(".")[0] for m in _NUMBER_RE.finditer(text)}


def _dedupe_stories(items: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Collapse the same story reported by several outlets, keeping the best-ranked copy.

    Two texts speak, and the higher similarity decides. Title similarity catches the copied
    headline. ``summary_ru`` similarity catches what a title can never show: the same story
    RETOLD — another outlet's own headline shares 40% of the words, and a story arriving in
    English or Uzbek shares none. Our summaries are all written in Russian by the same
    classifier, so two summaries of one fact converge on the same words whatever language
    the sources wrote in (measured 2026-08-11: uza's English geology headline vs uzdaily's
    Russian one — title overlap 0.0, summary overlap 1.0). The summary signal is only
    trusted when both summaries are long enough to be distinctive
    (``_DEDUP_MIN_SUMMARY_WORDS``).

    Below the clean threshold sits a band (``_DEDUP_BAND``..threshold) where overlap alone
    cannot decide: a rewritten headline of the SAME story and two stories cut from the same
    template («Узбекистан и <кто-то> обсудили проекты») overlap identically there —
    measured, both kinds sit at 0.40-0.53. What separates them in every audited pair is the
    FIGURE: two tellings of one fact quote the same number (резервы «$64,3 млрд» / «64,34
    млрд долларов», ставка «14%» twice, «27 скважин» twice), while two same-shaped stories
    never do — different meetings, different sums. So in the band a shared number token is
    required, and without one both items stay.

    Compared only between items published within ``NEWS_DEDUP_WINDOW_H`` of each other —
    the same wording months apart is a different story (a weekly banks-open-Sunday note,
    say), not a duplicate.

    Issuer disclosures are exempt on BOTH sides: a filing is the statutory record, and the
    same issuer files «Сделка с аффилированным лицом» week after week — identical titles,
    identical summaries, DISTINCT facts. Similarity between filings means nothing, so
    merging them would silently drop a real disclosure. Items are expected pre-sorted best
    first, so the survivor is the one that already ranked highest.
    """
    if threshold <= 0 or len(items) < 2:
        return items
    disclosures = disclosure_source_ids()
    kept: list[tuple[set[str], set[str], set[str], datetime | None]] = []
    out: list[dict[str, Any]] = []
    dropped = 0
    for it in items:
        if str(it.get("source_id") or "") in disclosures:
            out.append(it)
            continue
        t_words = _title_words(it.get("title"))
        s_words = _title_words(it.get("summary_ru"))
        if len(s_words) < _DEDUP_MIN_SUMMARY_WORDS:
            s_words = set()
        numbers = _number_tokens(it)
        when = _parse_dt(it.get("published_at"))
        duplicate = False
        for prev_t, prev_s, prev_nums, prev_when in kept:
            if when and prev_when:
                gap_h = abs((when - prev_when).total_seconds()) / 3600.0
                if gap_h > _DEDUP_WINDOW_H:
                    continue
            score = _jaccard(t_words, prev_t) if t_words and prev_t else 0.0
            if s_words and prev_s:
                score = max(score, _jaccard(s_words, prev_s))
            if score >= threshold or (
                    0 < _DEDUP_BAND <= score and numbers & prev_nums):
                duplicate = True
                break
        if duplicate:
            dropped += 1
        else:
            kept.append((t_words, s_words, numbers, when))
            out.append(it)
    if dropped:
        logger.info("news feed: merged %d duplicate cross-source story/stories", dropped)
    return out


# --------------------------------------------------------------------------- #
# international / local balance
# --------------------------------------------------------------------------- #
# The English-language wires (the rating agencies, The Diplomat, Trend, TCA, UzA English)
# publish a handful of market items a day between them; the local outlets publish forty.
# Rank alone therefore hands the whole page to the local side — and worse for exactly the
# items this exists for, since an international story rarely names a ticker and the score
# rewards that. So the two streams are ranked separately and interleaved to a target share.
# 0 turns the balance off entirely and restores the plain ranked order.
_INTERNATIONAL_SHARE = max(0.0, min(float(os.getenv("NEWS_INTERNATIONAL_SHARE", "0.5")), 1.0))
_ORIGINS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_sources.json")
_international_ids: set[str] | None = None
_hidden_ids: set[str] | None = None
_disclosure_ids: set[str] | None = None

# A story classified as regulation is publishable only when it comes from the
# regulator itself or from the statutory OpenInfo disclosure feed.  Other
# outlets still remain valid sources for market and corporate stories; this is
# a per-class editorial rule, not a source-wide block.
REGULATORY_SOURCE_IDS = frozenset({"napp", "openinfo_facts"})


def hidden_source_ids() -> set[str]:
    """Source ids the registry takes off the site (cached, fail-soft).

    Two flags, one effect. ``paywall: true`` — a source whose article page asks the reader for
    money gives us a headline, a sentence and a link that leads to a payment demand. It can
    never carry a long read either, so the card is permanently the thinnest kind we publish
    and the one action it offers is one the reader cannot take (2026-08-09, trend.az: «Get
    access to all paid news on Trend — just $1»). ``hidden: true`` — the customer dropped the
    outlet for editorial reasons, with nothing wrong with its pages (2026-08-11, kursiv).

    Read time, not collection time: the rows stay, so flipping the flag back brings the
    source's history with it instead of leaving a month-shaped hole.
    """
    global _hidden_ids
    if _hidden_ids is None:
        try:
            with open(_ORIGINS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            _hidden_ids = {s["id"] for s in data.get("sources", [])
                           if s.get("id") and (s.get("paywall") is True
                                               or s.get("hidden") is True)}
        except (OSError, ValueError, KeyError):
            logger.warning("could not read hidden sources from %s — nothing suppressed",
                           _ORIGINS_FILE)
            _hidden_ids = set()
    return _hidden_ids


def international_source_ids() -> set[str]:
    """Source ids the registry marks ``origin: "international"`` (cached, fail-soft)."""
    global _international_ids
    if _international_ids is None:
        try:
            with open(_ORIGINS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            _international_ids = {s["id"] for s in data.get("sources", [])
                                  if s.get("id") and s.get("origin") == "international"}
        except (OSError, ValueError, KeyError):
            logger.warning("could not read source origins from %s — feed balance is off",
                           _ORIGINS_FILE)
            _international_ids = set()
    return _international_ids


def drop_hidden(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Take editorially disallowed sources out of a list of items.

    Used on the short read paths — related stories, an issuer's news, the sentiment inputs —
    where the row count is small and a Python filter is clearer than threading positional
    parameters through four differently-shaped queries. The feed filters in SQL instead,
    because there a dropped row costs a slot in the rank window.
    """
    hidden = hidden_source_ids()
    return [
        it for it in items
        if str(it.get("source_id") or "") not in hidden
        and (
            str(it.get("type") or "") != "regulatory"
            or str(it.get("source_id") or "") in REGULATORY_SOURCE_IDS
        )
    ]


def _balance_origins(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Interleave the international and local streams to ``_INTERNATIONAL_SHARE``.

    Each side keeps its own ranking, so this decides *how many* of each get shown, never
    which ones. Whichever side runs out is filled from the other — a quiet week for the
    agencies must not shorten the page, and it must not hold a slot open with a stale card.
    """
    if _INTERNATIONAL_SHARE <= 0 or not items:
        return items[:limit]
    intl_ids = international_source_ids()
    if not intl_ids:
        return items[:limit]
    intl = [it for it in items if it.get("source_id") in intl_ids]
    local = [it for it in items if it.get("source_id") not in intl_ids]
    if not intl or not local:
        return items[:limit]

    out: list[dict[str, Any]] = []
    i = j = 0
    while len(out) < limit and (i < len(intl) or j < len(local)):
        # Take from the side that would still be under its share after this slot is filled.
        want_intl = i < _INTERNATIONAL_SHARE * (i + j + 1)
        if want_intl and i < len(intl):
            out.append(intl[i]); i += 1
        elif j < len(local):
            out.append(local[j]); j += 1
        elif i < len(intl):
            out.append(intl[i]); i += 1
    return out


# The two reading modes the news section offers, over the four classes the
# classifier already assigns (news_classifier.NewsType). Between them they cover
# all four, so no item is reachable from neither tab:
#
#   экономика     — the market as a whole: rates, macro, regulation
#   корпоративные — one issuer: its events and its reporting
NEWS_GROUPS: dict[str, tuple[str, ...]] = {
    "economy": ("market", "regulatory"),
    "corporate": ("corporate_event", "financial_report"),
}


def disclosure_source_ids() -> set[str]:
    """Source ids that are an issuer's own disclosure, not a paper's write-up.

    ``type: "openinfo"`` in the registry — the statutory filing feed. «Корпоративные» is
    served from these alone (customer, 2026-08-11): a filing is the primary record, dated
    and complete, and it names its issuer in the field the instrument split reads, while a
    press retelling of the same filing arrives later, names the company loosely and puts a
    second card under the same fact.

    Fail-soft to the empty set, which the caller reads as *no restriction*: a registry we
    cannot parse must leave the tab full, never empty it.
    """
    global _disclosure_ids
    if _disclosure_ids is None:
        try:
            with open(_ORIGINS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            _disclosure_ids = {s["id"] for s in data.get("sources", [])
                               if s.get("id") and s.get("type") == "openinfo"}
        except (OSError, ValueError, KeyError):
            logger.warning("could not read disclosure sources from %s — «корпоративные» "
                           "keeps every source", _ORIGINS_FILE)
            _disclosure_ids = set()
    return _disclosure_ids


def resolve_news_types(news_type: Any) -> list[str]:
    """The classifier types a feed request means.

    Accepts a group name ("economy"), a single class ("regulatory"), a
    comma-separated list, or a list — so the tab bar can ask for a group and the
    API keeps taking a bare type as it always did.
    """
    if not news_type:
        return []
    raw = news_type if isinstance(news_type, (list, tuple, set)) else str(news_type).split(",")
    out: list[str] = []
    for name in raw:
        key = str(name).strip().lower()
        if not key:
            continue
        for value in NEWS_GROUPS.get(key, (key,)):
            if value not in out:
                out.append(value)
    return out


def untyped_named_tickers(items: list[dict[str, Any]],
                          ticker_types: dict[str, str] | None) -> list[str]:
    """Tickers an item NAMES that the catalog cannot type.

    These are the only items an instrument filter loses without meaning to: an
    item that names nothing is not about an instrument, and one typed as the
    other kind was excluded on purpose. A ticker the catalog does not know is a
    third case — the filter has no answer, and a filter with no answer must not
    answer «no» in silence. Reported so the page can say where the item went.
    """
    types = ticker_types or {}
    out: list[str] = []
    for it in items:
        named = [str(t).upper() for t in (it.get("tickers") or []) if str(t).strip()]
        if named and not any(types.get(t) in ("stock", "bond") for t in named):
            for t in named:
                if t not in out:
                    out.append(t)
    return sorted(out)


def filter_by_instrument(items: list[dict[str, Any]], instrument: str | None,
                         ticker_types: dict[str, str] | None) -> list[dict[str, Any]]:
    """Keep the items that name at least one security of `instrument`'s kind.

    Corporate news splits cleanly along the instrument a reader holds: a coupon
    payment, a new tranche or a redemption concerns bondholders and nobody else,
    while a dividend or a board change concerns shareholders. The classifier has
    no opinion about this — both are «corporate_event» — so the split comes from
    the securities the filing NAMES, which the catalog already types.
    A filing that names both classes of one issuer belongs to both readers and
    is returned to both; that is not a duplicate, it is the same fact being
    relevant twice.

    An item with no issuer at all (macro copy that slipped into the group) is
    dropped by any instrument filter: "news about bonds" is a claim about the
    item, and silence is not that claim.
    """
    kind = str(instrument or "").strip().lower()
    if kind not in ("stock", "bond"):
        return items
    types = ticker_types or {}
    out = []
    for it in items:
        for tk in it.get("tickers") or []:
            if types.get(str(tk).upper()) == kind:
                out.append(it)
                break
    return out


def get_news_feed(
    *, limit: int = 60, days: int = 30, only_relevant: bool = True,
    news_type: Any = None, order: str = "rank",
    min_relevance: float | None = None,
    instrument: str | None = None, ticker_types: dict[str, str] | None = None,
    notes: dict[str, Any] | None = None,
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
    wanted = resolve_news_types(news_type)
    if wanted:
        q.append(f"AND p.type IN ({','.join('?' * len(wanted))})")
        params.extend(wanted)
    if days:
        q.append("AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))")
        params.append(f"-{int(days)} days")
    # In SQL rather than after the fetch: a hidden source would otherwise eat rows out of
    # the rank window and shorten the page by however many it contributed. Appended last on
    # purpose — the clauses above own the leading positional parameters, and a test reads
    # them by position.
    hidden = sorted(hidden_source_ids())
    if hidden:
        q.append(f"AND COALESCE(n.source_id, '') NOT IN ({','.join('?' * len(hidden))})")
        params.extend(hidden)
    # Regulatory news is primary-source only (customer, 2026-09-01). Apply the
    # rule even when no type is requested, so «Все» cannot reintroduce a press
    # retelling that the dedicated «Регулятор» tab correctly omits. Market and
    # corporate rows from those same outlets continue to pass unchanged.
    regulatory_sources = sorted(REGULATORY_SOURCE_IDS)
    q.append(f"AND (p.type <> ? OR COALESCE(n.source_id, '') IN "
             f"({','.join('?' * len(regulatory_sources))}))")
    params.append("regulatory")
    params.extend(regulatory_sources)
    # «Корпоративные» is served from the filings alone (customer, 2026-08-11). Written per
    # TYPE rather than as a flat AND over the whole query, so a request that mixes the
    # groups («economy,corporate_event») still gets its economy items from every source —
    # and so «Все», which asks for no type at all, stays the mixed feed it says it is.
    corporate = [t for t in wanted if t in NEWS_GROUPS["corporate"]]
    disclosure = sorted(disclosure_source_ids())
    if corporate and disclosure:
        q.append(f"AND (p.type NOT IN ({','.join('?' * len(corporate))})"
                 f" OR COALESCE(n.source_id, '') IN ({','.join('?' * len(disclosure))}))")
        params.extend(corporate)
        params.extend(disclosure)
    q.append("ORDER BY COALESCE(n.published_at, n.collected_at) DESC LIMIT ?")
    params.append(fetch)
    rows = conn.execute(" ".join(q), params).fetchall()
    conn.close()
    items = [_row_to_item(r) for r in rows]
    # Before ranking, not after: the rank window exists so a strong item just
    # outside the newest N can still surface, and filtering afterwards would
    # spend that window on stories the reader asked not to see.
    if str(instrument or "").strip().lower() in ("stock", "bond"):
        # `notes` is an out-parameter, deliberately: what the filter could not
        # type is a property of the corpus the caller has to be able to state,
        # and recomputing it there would mean reading the same rows twice.
        if notes is not None:
            notes["untyped_tickers"] = untyped_named_tickers(items, ticker_types)
        items = filter_by_instrument(items, instrument, ticker_types)
    if order != "rank":
        return items[:max(1, min(limit, 200))]

    now = datetime.now()
    items = _drop_noise(items, _MIN_RELEVANCE if min_relevance is None else min_relevance)
    for it in items:
        it["rank"] = rank_score(it, now)
    items.sort(key=lambda it: (-it["rank"], str(it.get("published_at") or "")))
    items = _dedupe_stories(items, _DEDUP_SIMILARITY)
    return _balance_origins(items, max(1, min(limit, 200)))


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
    # The story page too, not only the feed: a card taken off the list whose URL still opens
    # is not removed, it is unlinked — and the customer's example was the story page itself.
    if str(row["source_id"] or "") in hidden_source_ids() or (
            str(row["type"] or "") == "regulatory"
            and str(row["source_id"] or "") not in REGULATORY_SOURCE_IDS):
        return None
    item = _row_to_item(row)
    keys = row.keys()
    item.update({
        "relevant": bool(row["relevant"]),
        "model": row["model"],
        "classified_at": row["classified_at"],
        "collected_at": row["collected_at"],
        # The long read, only on the page that shows it (see _row_to_item).
        "detail_ru": row["detail_ru"] if "detail_ru" in keys else None,
        "detail_en": row["detail_en"] if "detail_en" in keys else None,
        "detail_uz": row["detail_uz"] if "detail_uz" in keys else None,
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
        # A story naming two of these issuers must still be one row. Semi-joining on
        # `IN (SELECT …)` says that directly; the JOIN + `GROUP BY n.id` it replaces
        # only worked because SQLite tolerates selected columns that are not grouped.
        rows = conn.execute(
            f"{select} WHERE n.id IN (SELECT x.news_id FROM news_entities x"
            f"                         WHERE x.ticker IN ({placeholders}))"
            f" AND n.id <> ? AND p.relevant = 1 {recent}",
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
    return drop_hidden(list(picked.values()))[:cap]


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
    return drop_hidden([_row_to_item(r) for r in rows])


def get_news_sentiment(ticker: str, *, days: int = 30) -> dict[str, Any]:
    """Coverage-weighted background tone for an issuer — the §3.4 info-dimension входная точка.

    Returns a weighted mean tone_score plus counts. A statistical aggregate, not a verdict.
    """
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        """
        SELECT p.type, p.tone, p.tone_score, n.coverage_weight, n.source_id
        FROM news n
        JOIN news_entities e ON e.news_id = n.id
        JOIN news_nlp p       ON p.news_id = n.id
        WHERE e.ticker = ? AND p.relevant = 1 AND p.tone_score IS NOT NULL
          AND (n.published_at IS NULL OR n.published_at >= datetime('now', ?))
        """,
        (ticker.strip().upper(), f"-{int(days)} days"),
    ).fetchall()
    conn.close()
    # A story we refuse to publish must not move a number we do publish.
    hidden = hidden_source_ids()
    rows = [r for r in rows
            if str(r["source_id"] or "") not in hidden
            and (str(r["type"] or "") != "regulatory"
                 or str(r["source_id"] or "") in REGULATORY_SOURCE_IDS)]
    if not rows:
        return {"ticker": ticker.upper(), "count": 0, "weighted_tone": None,
                "positive": 0, "neutral": 0, "negative": 0}
    wsum = sum((r["coverage_weight"] or 0.5) for r in rows)
    weighted = sum((r["tone_score"] or 0.0) * (r["coverage_weight"] or 0.5) for r in rows) / (wsum or 1.0)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        counts[r["tone"]] = counts.get(r["tone"], 0) + 1
    return {"ticker": ticker.upper(), "count": len(rows), "weighted_tone": round(weighted, 3), **counts}
