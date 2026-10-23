"""Durable alert delivery; run once a minute using the host's scheduler.

No endpoint is configured by default. Failed deliveries remain retryable.
The sender is injected in tests; production posts only to the operator's
explicitly configured webhook. Journal rows remain immutable.
"""
from datetime import timedelta
import hashlib
import json
import os
import requests
from server.terminal import journal
from server.terminal.dashboard import dashboard


def _claim(key, at, cutoff):
    with journal.connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS terminal_alert_delivery (key TEXT PRIMARY KEY, sent_at TEXT, lease_until TEXT)')
        c.execute('INSERT INTO terminal_alert_delivery(key) VALUES (?) ON CONFLICT(key) DO NOTHING',(key,))
        updated=c.execute('UPDATE terminal_alert_delivery SET lease_until=? WHERE key=? AND (sent_at IS NULL OR sent_at<=?) AND (lease_until IS NULL OR lease_until<=?)',
                          ((at+timedelta(minutes=2)).isoformat(),key,cutoff.isoformat(),at.isoformat()))
        c.commit()
        return updated.rowcount==1


def _finish(key, at, sent):
    with journal.connection() as c:
        if sent:c.execute('UPDATE terminal_alert_delivery SET sent_at=?, lease_until=NULL WHERE key=?',(at.isoformat(),key))
        else:c.execute('UPDATE terminal_alert_delivery SET lease_until=NULL WHERE key=?',(key,))
        c.commit()


def dispatch(send, *, at=None):
    at=(at or journal.now()).astimezone(journal.TASHKENT)
    journal.flush()
    since=journal.stamp(at-timedelta(hours=1))
    with journal.connection() as c:
        events=c.execute("SELECT event,ticker,standard,period,function,MAX(ts) AS latest,COUNT(*) AS count FROM terminal_events WHERE level='critical' AND ts>=? AND ts<=? GROUP BY event,ticker,standard,period,function",(since,journal.stamp(at))).fetchall()
    pending=[]
    for row in events:
        item=dict(row)
        key='critical:'+hashlib.sha256(json.dumps([item[k] for k in ('event','ticker','standard','period','function')]).encode()).hexdigest()
        pending.append((key, {'kind':'critical','as_of':at.isoformat(),'event':item},at-timedelta(hours=1)))
    if at.hour==9:
        key='digest:'+at.date().isoformat()
        pending.append((key, {'kind':'daily_digest',**dashboard(at=at)},at-timedelta(days=1)))
    result={'sent':0,'failed':0}
    for key,payload,cutoff in pending:
        if not _claim(key,at,cutoff):continue
        sent=False
        try:
            send(payload);sent=True;result['sent']+=1
        except Exception:
            result['failed']+=1
        finally:_finish(key,at,sent)
    return result


def webhook(payload):
    url=os.environ.get('TERMINAL_ALERT_WEBHOOK','')
    if not url.startswith('https://'):raise ValueError('Configure TERMINAL_ALERT_WEBHOOK with an HTTPS endpoint')
    headers={}
    if os.environ.get('TERMINAL_ALERT_TOKEN'):headers['Authorization']='Bearer '+os.environ['TERMINAL_ALERT_TOKEN']
    response=requests.post(url,json=payload,headers=headers,timeout=15,allow_redirects=False)
    if not 200<=response.status_code<300:raise RuntimeError('Alert destination did not accept delivery')


if __name__=='__main__':
    if not os.environ.get('TERMINAL_ALERT_WEBHOOK'):raise SystemExit('TERMINAL_ALERT_WEBHOOK is not configured')
    result=dispatch(webhook)
    print(json.dumps(result))
    raise SystemExit(1 if result['failed'] else 0)
