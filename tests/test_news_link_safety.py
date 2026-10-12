"""News URLs become links readers click, so only http(s) ones are stored or rendered."""
from __future__ import annotations

import pytest


def _item(url: str) -> dict:
    return {
        "url": url, "source": "S", "source_id": "napp", "lang": "ru",
        "title": "ЦБ сохранил ставку", "snippet": "", "summary_ru": "Центробанк сохранил ставку.",
        "relevant": True, "relevance_score": 0.8, "type": "regulatory", "tone": "neutral",
        "tone_score": 0.0, "impact": "high", "direction": "unclear", "sectors": [],
        "reason": "r", "model": "test", "tickers": [],
    }


def test_upsert_news_skips_items_whose_url_is_not_a_web_link(tmp_path, monkeypatch):
    import catalogue.storage as catalogue_storage
    import news_store

    # Patch the path function: anything else writes to the developer's real catalog.
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))

    written = news_store.upsert_news([
        _item("javascript:alert(document.cookie)"),
        _item(" JavaScript:alert(1)"),
        _item("data:text/html,<script>alert(1)</script>"),
        _item("https:no-host"),
        _item("https://example.test/kept"),
    ])

    urls = {item["url"] for item in news_store.get_news_feed(limit=50, days=3650)}
    assert written == 1
    assert urls == {"https://example.test/kept"}


@pytest.mark.parametrize("value, expected", [
    ("https://example.test/a", "https://example.test/a"),
    ("HTTP://example.test/a", "HTTP://example.test/a"),
    ("javascript:alert(1)", None),
    ("  javascript:alert(1)", None),
    ("data:text/html,x", None),
    ("/relative", None),
    (None, None),
])
def test_seo_page_links_only_web_urls(value, expected):
    from server.seo.routes import _web_url

    assert _web_url(value) == expected
