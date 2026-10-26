"""Personal corporate-event alerts from stored disclosures and owned positions."""
from datetime import datetime, timedelta, timezone
import logging


def event_alerts(user_id, favorites, preferences):
    if not preferences.get('notify_news', True):
        return []
    import web_auth
    import corporate_events
    from identity.portfolio_math import calculate_ledger
    tickers={str(f['ticker']).upper() for f in favorites if f.get('ticker') and f.get('news_alert_enabled',True)}
    try:
        positions=calculate_ledger(web_auth.web_auth_store.portfolio.list_transactions(user_id))['items']
        tickers.update(p['ticker'] for p in positions)
        if not tickers:
            return []
        today=datetime.now(timezone(timedelta(hours=5))).date()
        stories=corporate_events.feed((today-timedelta(days=7)).isoformat(),today.isoformat())['items']
    except Exception:
        logging.getLogger(__name__).warning('Corporate event alerts unavailable',exc_info=True)
        return []
    language=preferences.get('language','ru')
    return [{'ticker':next(t for t in s.get('tickers',[]) if t in tickers), 'kind':'corporate_event',
             'report_form':'EVENT', 'title':s['title'].get(language) or s['title'].get('ru'),
             'detected_at':s['published_at'], 'stage':s['stage'], 'priority':s['priority'],
             'story_id':s['story_id'], 'href':'/news?tab=corporate&mode=personal'}
            for s in stories if tickers.intersection(s.get('tickers',[])) and s['priority']<=1][:40]
