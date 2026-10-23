from datetime import datetime, timedelta
from server.terminal import journal


def test_critical_delivery_is_persistent_deduplicated_and_retries_failed_send():
    from server.terminal.alerts import dispatch
    at=datetime(2026,10,23,8,0,tzinfo=journal.TASHKENT)
    journal.emit('load_empty',ticker='SQBN',period='2024',at=at)
    delivered=[]
    assert dispatch(delivered.append,at=at)['sent']==1
    journal.emit('load_empty',ticker='SQBN',period='2024',at=at+timedelta(minutes=1))
    assert dispatch(delivered.append,at=at+timedelta(minutes=2))['sent']==0
    journal.emit('load_empty',ticker='SQBN',period='2024',at=at+timedelta(hours=1,minutes=1))
    def broken(payload):raise OSError('delivery unavailable')
    assert dispatch(broken,at=at+timedelta(hours=1,minutes=1))['failed']>=1
    assert dispatch(delivered.append,at=at+timedelta(hours=1,minutes=2))['sent']>=1
    assert all('user_id' not in str(payload) for payload in delivered)


def test_digest_is_sent_once_at_nine_tashkent_not_before():
    from server.terminal.alerts import dispatch
    before=datetime(2026,10,23,8,59,tzinfo=journal.TASHKENT)
    delivered=[]
    assert dispatch(delivered.append,at=before)['sent']==0
    assert dispatch(delivered.append,at=before+timedelta(minutes=1))['sent']==1
    assert delivered[0]['kind']=='daily_digest'
    assert dispatch(delivered.append,at=before+timedelta(minutes=2))['sent']==0


def test_telegram_delivery_uses_configured_admin_and_email_fallback(monkeypatch):
    from server.terminal import alerts
    import email_delivery
    monkeypatch.setenv('TERMINAL_ALERT_CHANNEL','telegram')
    monkeypatch.setenv('TELEGRAM_TOKEN','test-token')
    monkeypatch.setenv('ADMIN_TELEGRAM_ID','123')
    monkeypatch.setenv('TERMINAL_ALERT_EMAIL','admin@example.test')
    sent=[]
    def telegram(url,**kwargs):
        assert url.endswith('/sendMessage')
        assert kwargs['json']['chat_id']=='123'
        assert 'SQBN' in kwargs['json']['text']
        raise OSError('Telegram unavailable')
    monkeypatch.setattr(alerts.requests,'post',telegram)
    monkeypatch.setattr(email_delivery,'send_email',lambda to,subject,text:sent.append((to,subject,text)))
    alerts.deliver({'kind':'critical','event':{'event':'load_empty','ticker':'SQBN','period':'2024','count':1}})
    assert sent[0][0]=='admin@example.test' and 'SQBN' in sent[0][2]


def test_different_errors_in_same_screen_are_not_silently_suppressed():
    from server.terminal.alerts import dispatch
    at=datetime(2026,10,23,8,0,tzinfo=journal.TASHKENT)
    journal.emit('screen_error',ticker='HMKB',function='RAT',error_id='missing-report',at=at)
    journal.emit('screen_error',ticker='HMKB',function='RAT',error_id='missing-cbu',at=at)
    delivered=[]
    assert dispatch(delivered.append,at=at)['sent']==2


def test_telegram_falls_back_to_existing_primary_admin_email(monkeypatch):
    from server.terminal import alerts
    import email_delivery
    monkeypatch.setenv('TERMINAL_ALERT_CHANNEL','telegram')
    monkeypatch.delenv('TERMINAL_ALERT_EMAIL',raising=False)
    monkeypatch.setenv('ADMIN_EMAILS','primary@example.test, second@example.test')
    monkeypatch.delenv('TELEGRAM_TOKEN',raising=False)
    sent=[]
    monkeypatch.setattr(email_delivery,'send_email',lambda to,subject,text:sent.append(to))
    alerts.deliver({'kind':'daily_digest','summary':{}})
    assert sent==['primary@example.test']
