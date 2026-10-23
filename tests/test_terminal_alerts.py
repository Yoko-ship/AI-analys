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
