"""Local news discovery checks using the real HTML renderer and a fixed story.

Run uvicorn e2e.seo_news_app:app --lifespan off after npm run build.
The production app never imports this module or reads this fixture.
"""
import json
from pathlib import Path

from api import app
import news_store

ITEM = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/news-search.json").read_text())

news_store.get_news_feed = lambda **kwargs: [dict(ITEM)]
news_store.get_news_item = lambda news_id: dict(ITEM) if news_id == ITEM["id"] else None

