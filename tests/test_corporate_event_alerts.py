
def test_event_alerts_follow_holdings_and_opted_in_watchlist_without_price_predictions(monkeypatch):
    from server.accounts.event_alerts import event_alerts
    import corporate_events as ce
    import web_auth
    monkeypatch.setattr(web_auth.web_auth_store.portfolio,'list_transactions',lambda uid:[])
    source={'story_id':'uzgf','tickers':['UZGF'],'priority':1,'published_at':'2026-10-26','title':{'ru':'Набсовет рекомендовал дивиденды'},'stage':'proposed'}
    monkeypatch.setattr(ce,'feed',lambda *a,**k:{'items':[source,{**source,'story_id':'other','tickers':['OTHER']}]})
    alerts=event_alerts(7,[{'ticker':'UZGF','news_alert_enabled':True}],{'notify_news':True})
    assert len(alerts)==1
    assert alerts[0]['stage']=='proposed'
    assert alerts[0]['href']=='/news?tab=corporate&mode=personal'
    assert event_alerts(7,[{'ticker':'UZGF','news_alert_enabled':False}],{'notify_news':True})==[]
    assert event_alerts(7,[{'ticker':'UZGF'}],{'notify_news':False})==[]
