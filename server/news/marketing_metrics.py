"""Session-entry attribution and fixed-cohort landing-page experiments."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from math import sqrt

import web_analytics as analytics


def _sessions(rows):
    # Include the landing page in page depth; refreshing it is not a second page.
    ordered = sorted(rows, key=lambda r: (r["visitor_id"], r["session_id"], r["ts"], r.get("id", 0)))
    by_reader = defaultdict(list)
    for (reader, _), events in groupby(ordered, key=lambda r: (r["visitor_id"], r["session_id"])):
        first = next(events)
        pages = {first["path"], *(event["path"] for event in events)}
        by_reader[reader].append((first["ts"], first["utm_campaign"], len(pages)))
    return by_reader


def summarize(rows, tags, since):
    result = {tag: dict(visits=0, readers=0, pages=0, continued=0, returned=0) for tag in tags}
    for sessions in _sessions(rows).values():
        seen, returned = set(), set()
        for start, tag, pages in sorted(sessions, key=lambda s: s[0]):
            returned.update(seen)
            if start >= since and tag in result:
                counts = result[tag]
                counts["visits"] += 1
                counts["pages"] += pages
                counts["continued"] += int(pages > 1)
                seen.add(tag)
        for tag in seen:
            result[tag]["readers"] += 1
        for tag in returned:
            result[tag]["returned"] += 1
    return result


def _interval(successes, n):
    p, z = successes / n, 1.96
    denominator = 1 + z*z/n
    center = (p + z*z/(2*n)) / denominator
    margin = z * sqrt(p*(1-p)/n + z*z/(4*n*n)) / denominator
    return center-margin, center+margin


SAMPLE = 100


def compare(a, b):
    if min(len(a), len(b)) < SAMPLE:
        return "collecting"
    low_a, high_a = _interval(sum(a[:SAMPLE]), SAMPLE)
    low_b, high_b = _interval(sum(b[:SAMPLE]), SAMPLE)
    if low_a > high_b:
        return "a"
    if low_b > high_a:
        return "b"
    return "inconclusive"


def _events(conn, tags, since, until):
    if not tags:
        return []
    # Retrieve all pageviews for the matching readers' sessions, including a
    # landing before the window or a later return with no campaign tag.
    return conn.execute("""
        WITH readers AS (SELECT DISTINCT visitor_id FROM ev WHERE event='pageview'
                        AND ts >= %s AND ts < %s AND utm_campaign = ANY(%s)),
        sessions AS (SELECT DISTINCT e.visitor_id,e.session_id FROM ev e JOIN readers USING(visitor_id)
                     WHERE event='pageview' AND ts >= %s AND ts < %s)
        SELECT id,ts,visitor_id,session_id,path,utm_campaign FROM ev JOIN sessions USING(visitor_id,session_id)
        WHERE event='pageview' AND ts < %s ORDER BY ts,id
    """, (since, until, list(tags), since, until, until)).fetchall()


def measurements(tags, experiments):
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    if not analytics._available():
        return {"available": False}
    with analytics._conn() as conn:
        analytics._scope(conn, now)
        weekly = summarize(_events(conn, tags, week, now), tags, week)
        trials = {}
        for experiment in experiments:
            arms = [f"exp-{experiment['id']}-{arm}" for arm in ("a", "b")]
            start = datetime.fromisoformat(experiment["created"])
            events = _events(conn, arms, start, now)
            # Allow a full 24h for each first landing, and measure only the first
            # session's distinct pages within those 24h. Fix cohort at 100/arm.
            cohort = {tag: [] for tag in arms}
            ordered = sorted(events, key=lambda r: (r["visitor_id"], r["session_id"], r["ts"], r["id"]))
            readers = defaultdict(list)
            for (reader, _), values in groupby(ordered, key=lambda r: (r["visitor_id"], r["session_id"])):
                first = next(values)
                if first["utm_campaign"] in arms and start <= first["ts"] <= now-timedelta(days=1):
                    second = any(v["path"] != first["path"] and v["ts"] < first["ts"]+timedelta(days=1) for v in values)
                    readers[reader].append((first["ts"], first["id"], first["utm_campaign"], second))
            for _, _, tag, converted in sorted(min(sessions) for sessions in readers.values()):
                if len(cohort[tag]) < SAMPLE:
                    cohort[tag].append(converted)
            a, b = (cohort[tag] for tag in arms)
            trials[experiment["id"]] = dict(result=compare(a,b), a=[sum(a),len(a)], b=[sum(b),len(b)])
    return dict(available=True, since=week.isoformat(), until=now.isoformat(), weekly=weekly, trials=trials)
