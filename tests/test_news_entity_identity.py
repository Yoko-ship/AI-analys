"""Real stock-exchange coverage must not become commodity-exchange issuer news."""
import json
from pathlib import Path

import pytest

import catalogue.storage as storage
import news_store as ns

ARTICLES = json.loads((Path(__file__).parent / 'fixtures/news-exchange-identities.json').read_text())


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, '_catalog_db_path', lambda: str(tmp_path / 'news.db'))


def store(items):
    return ns.upsert_news([{**item, 'relevant': True, 'relevance_score': .9} for item in items])


def test_real_stock_exchange_story_has_no_urts_tag_but_commodity_stories_keep_it(catalog):
    store(ARTICLES)
    items = {item['url']: item for item in ns.get_news_feed(limit=50, days=3650)}
    for article in ARTICLES:
        expected = [] if article['id'] == 7591 else ['URTS']
        assert items[article['url']]['tickers'] == expected
    assert len(ns.get_news_for_ticker('URTS', days=3650)) == 3
    assert ns.get_news_sentiment('URTS', days=3650)['count'] == 3


@pytest.mark.parametrize('title,expected', [
    ('Tashkent Stock Exchange turnover increased', []),
    ('Toshkent Respublika fond birjasi savdolari', []),
    ('«Тошкент» РФБда савдолар ҳажми ошди', []),
    ('Республиканская фондовая биржа опубликовала итоги торгов', []),
    ('Акции URTS торгуются на РФБ «Тошкент»', ['URTS']),
    ('UZEX и UZSE представили итоги торгов', ['URTS']),
    ('УзРТСБ опубликовала итоги торгов', ['URTS']),
    ('O‘zbekiston respublika tovar-xom ashyo birjasi (OʻzRTXB)', ['URTS']),
    ('Uzbek Commodity Exchange publishes results', ['URTS']),
    ('Акции HMKB торгуются на РФБ «Тошкент»', []),
    ('Вырос объём торгов на бирже', ['URTS']),  # No contradictory identity evidence.
])
def test_distinct_exchange_identities_and_dual_mentions(catalog, title, expected):
    item = {**ARTICLES[0], 'title': title, 'snippet': '', 'summary_ru': 'URTS UZEX'}
    store([item])
    assert ns.get_news_feed(days=3650)[0]['tickers'] == expected


def test_source_joined_filings_and_unrelated_issuers_survive(catalog):
    item = {**ARTICLES[0], 'tickers': ['URTS', 'HMKB']}
    store([item])
    assert ns.get_news_feed(days=3650)[0]['tickers'] == ['HMKB']
    store([{**item, 'url': 'https://openinfo.uz/ru/facts/6/123', 'source_id': 'openinfo_facts'}])
    assert len(ns.get_news_for_ticker('URTS', days=3650)) == 1


def test_historical_repair_is_reviewable_idempotent_and_only_changes_wrong_links(catalog):
    store(ARTICLES)
    with storage.get_catalog_conn() as conn:
        wrong_id = conn.execute('SELECT id FROM news WHERE url=?', (ARTICLES[0]['url'],)).fetchone()['id']
        conn.execute('INSERT INTO news_entities (news_id,ticker) VALUES (?,?) ON CONFLICT DO NOTHING', (wrong_id,'URTS'))
    planned = ns.repair_news_entity_links()
    assert planned == [{'news_id': wrong_id, 'ticker': 'URTS'}]
    assert ns.get_news_sentiment('URTS', days=3650)['count'] == 4
    assert ns.repair_news_entity_links(apply=True) == planned
    assert ns.get_news_sentiment('URTS', days=3650)['count'] == 3
    assert ns.repair_news_entity_links(apply=True) == []
    assert len(ns.get_news_feed(days=3650)) == 4
