"""Every statement the news module issues, as PostgreSQL will actually receive it.

The news feed returned 500 for every request after the PostgreSQL cutover, and not
because of one bad query — because four separate SQLite idioms reached the server
verbatim: `datetime('now', ?)`, `GROUP_CONCAT`, `INSERT OR IGNORE`, and a `GROUP BY`
over columns that were never grouped. Each was invisible locally, where the same
statements run on SQLite and pass.

So this file does not check queries by hand. It runs the module against SQLite,
captures every statement that actually executes, and asserts what `dbx` would hand
PostgreSQL carries no SQLite-only construct left in it. A new query added to
news_store is covered the moment a test calls the function that issues it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

import dbx
import news_store
import reports_catalog as rc

# Spellings PostgreSQL has no answer for. Checked against the TRANSLATED statement,
# so a hit means the translation missed it, not that the source is wrong.
SQLITE_ONLY = (
    (re.compile(r"\bdatetime\s*\(", re.I), "datetime() — PostgreSQL has no such function"),
    (re.compile(r"\bGROUP_CONCAT\s*\(", re.I), "GROUP_CONCAT — use string_agg"),
    (re.compile(r"\bINSERT\s+OR\s+(IGNORE|REPLACE)\b", re.I), "INSERT OR … — use ON CONFLICT"),
    (re.compile(r"\bIFNULL\s*\(", re.I), "IFNULL — use COALESCE"),
    (re.compile(r"\bjulianday\s*\(", re.I), "julianday"),
    (re.compile(r"\bstrftime\s*\(", re.I), "strftime"),
    (re.compile(r"\bGLOB\b", re.I), "GLOB — no PostgreSQL equivalent"),
    (re.compile(r"\bAUTOINCREMENT\b", re.I), "AUTOINCREMENT"),
)


@pytest.fixture()
def captured(tmp_path, monkeypatch):
    """Run the news module on a scratch SQLite catalog, recording every statement."""
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    seen: list[str] = []
    original = dbx.Cursor.execute

    def recording(self, sql, params=None):
        seen.append(sql)
        return original(self, sql, params)

    monkeypatch.setattr(dbx.Cursor, "execute", recording)
    return seen


def _assert_translates_clean(statements: list[str]) -> None:
    assert statements, "nothing was captured — the fixture is not wired up"
    for sql in statements:
        translated = dbx.translate(sql, dbx.POSTGRES)
        for pattern, why in SQLITE_ONLY:
            assert not pattern.search(translated), (
                f"{why}\n  source:     {' '.join(sql.split())[:160]}\n"
                f"  translated: {' '.join(translated.split())[:160]}")
        assert "?" not in re.sub(r"'[^']*'", "", translated), (
            f"a placeholder survived translation: {' '.join(translated.split())[:160]}")


ITEM = {
    "url": "https://example.test/a", "source": "Example", "source_id": "example",
    "lang": "ru", "title": "Заголовок", "snippet": "Текст",
    "summary_ru": "Сводка", "summary_en": "", "summary_uz": "",
    "image_url": None, "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "coverage_weight": 0.6,
    "type": "market", "tone": "neutral", "tone_score": 0.0, "impact": "low",
    "direction": "unclear", "sectors": [], "relevant": 1, "relevance_score": 0.5,
    "reason": "", "model": "test", "tickers": ["AGBA"],
}


def test_the_read_path_speaks_postgres(captured):
    """Every query behind /api/news/feed, /news/{id} and the per-issuer block."""
    news_store.get_news_feed(limit=5, days=30)
    news_store.get_news_feed(limit=5, days=30, order="recent", news_type="market")
    news_store.get_news_item(1)
    news_store.get_related_news(1)
    news_store.get_news_for_ticker("AGBA", days=90)
    news_store.get_news_sentiment("AGBA", days=90)
    news_store.rows_without_image(limit=5, days=30)
    _assert_translates_clean(captured)


def test_the_write_path_speaks_postgres(captured):
    """Storing a classified item, its issuer tags, and a later image fill."""
    assert news_store.upsert_news([ITEM]) == 1
    news_store.image_urls_for([ITEM["url"]])
    news_store.set_image_urls({ITEM["url"]: "https://example.test/a.jpg"})
    _assert_translates_clean(captured)


def test_a_stored_item_still_reads_back(captured, tmp_path):
    """The rewritten queries must return the row, not merely parse.

    A semi-join that silently matches nothing looks exactly like a quiet news day,
    which is the failure this whole file exists to make impossible.
    """
    news_store.upsert_news([ITEM])
    feed = news_store.get_news_feed(limit=5, days=30, order="recent")
    assert [it["title"] for it in feed] == ["Заголовок"]
    assert feed[0]["tickers"] == ["AGBA"]

    item = news_store.get_news_item(feed[0]["id"])
    assert item and item["tickers"] == ["AGBA"]

    other = dict(ITEM, url="https://example.test/b", title="Вторая")
    news_store.upsert_news([other])
    stored = {it["title"]: it["id"] for it in news_store.get_news_feed(limit=5, days=30)}
    # Related-by-issuer: both stories tag AGBA, so each is the other's neighbour.
    related = news_store.get_related_news(stored["Заголовок"])
    assert [r["title"] for r in related] == ["Вторая"]
    # Only with rows present does the related-by-issuer query run at all, so its
    # translation is checked here rather than in the empty-database pass above.
    _assert_translates_clean(captured)


def test_issuer_news_collapses_syndicated_copies_of_the_open_story(captured):
    """One event from three sources must not occupy all three issuer-news slots."""
    current = dict(
        ITEM,
        url="https://ratings.test/ipak-yuli-upgrade",
        source="Fitch Ratings",
        source_id="fitch",
        title="Fitch повысило долгосрочный рейтинг Ipak Yuli Bank до B+",
        summary_ru=("Fitch повысило долгосрочный рейтинг банка Ипак Йули до уровня B+ "
                    "и сохранило стабильный прогноз."),
    )
    copy_one = dict(
        current,
        url="https://daily.test/ipak-yuli-upgrade",
        source="UzDaily.uz",
        source_id="uzdaily",
        title="Fitch повысило рейтинг Ipak Yuli до уровня B+",
    )
    copy_two = dict(
        current,
        url="https://ratings.test/ipak-yuli-upgrade-copy",
        title="Fitch повысило долгосрочный рейтинг Ипак Йули до уровня B+",
    )
    distinct = dict(
        ITEM,
        url="https://example.test/ipak-yuli-other",
        title="Банк Ипак Йули запустил новую услугу для клиентов",
        summary_ru="Банк Ипак Йули запустил новую цифровую услугу для розничных клиентов.",
    )
    assert news_store.upsert_news([current, copy_one, copy_two, distinct]) == 4

    conn = rc.get_catalog_conn()
    current_id = conn.execute(
        "SELECT id FROM news WHERE url = ?", (current["url"],)).fetchone()["id"]
    conn.close()

    items = news_store.get_news_for_ticker(
        "AGBA", limit=3, days=90, exclude_news_id=current_id)
    related = news_store.get_related_news(current_id, limit=3, days=90)

    assert [item["title"] for item in items] == [distinct["title"]]
    assert [item["title"] for item in related] == [distinct["title"]]
    _assert_translates_clean(captured)
