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
from typing import Any

import reports_catalog as rc

logger = logging.getLogger(__name__)

# Whitelisted so a pushed row can never smuggle arbitrary columns.
_NEWS_FIELDS = ("url", "source", "source_id", "lang", "title", "snippet", "summary_ru",
                "published_at", "coverage_weight")
_NLP_FIELDS = ("relevant", "relevance_score", "type", "tone", "tone_score",
               "impact", "direction", "reason", "model")


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
                                  published_at, coverage_weight, collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(url) DO UPDATE SET
                    title           = excluded.title,
                    snippet         = excluded.snippet,
                    summary_ru      = excluded.summary_ru,
                    published_at    = COALESCE(excluded.published_at, news.published_at),
                    coverage_weight = excluded.coverage_weight
                """,
                (url, it.get("source", ""), it.get("source_id"), it.get("lang"),
                 it.get("title", "").strip(), it.get("snippet"), it.get("summary_ru"),
                 it.get("published_at"), float(it.get("coverage_weight") or 0.5)),
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


def _row_to_item(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"], "url": r["url"], "source": r["source"], "source_id": r["source_id"],
        "lang": r["lang"], "title": r["title"], "snippet": r["snippet"],
        "summary_ru": r["summary_ru"], "published_at": r["published_at"],
        "type": r["type"], "tone": r["tone"], "tone_score": r["tone_score"],
        "impact": r["impact"], "direction": r["direction"],
        "sectors": json.loads(r["sectors_json"]) if r["sectors_json"] else [],
    }


def get_news_feed(
    *, limit: int = 60, days: int = 30, only_relevant: bool = True,
    news_type: str | None = None,
) -> list[dict[str, Any]]:
    """Public editorial feed: relevant, classified items, newest first."""
    conn = rc.get_catalog_conn()
    q = [
        "SELECT n.*, p.type, p.tone, p.tone_score, p.impact, p.direction, p.sectors_json, p.relevant",
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
    params.append(max(1, min(limit, 200)))
    rows = conn.execute(" ".join(q), params).fetchall()
    conn.close()
    return [_row_to_item(r) for r in rows]


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
