"""Product decisions from complete Tashkent days, with explicit measurement coverage.

Sources are attributed to the first page of a visit. Registrations require a
server-resolved account and are credited once, to the latest eligible visit.
Feature adoption uses only visits from instrumented clients as its denominator.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import web_analytics as wa

INTERACTIONS = ("financials", "chart", "ratios", "reports", "dividends")
FEATURE_EVENTS = tuple(f"feature_{name}" for name in INTERACTIONS)


def product_report(days: int = 7) -> dict:
    if not wa._available():
        return {"ok": False, "reason": "no database"}
    days = max(1, min(int(days), 90))
    until = wa._day_start(datetime.now(timezone.utc))
    since = until - timedelta(days=days)
    previous = since - timedelta(days=days)
    with wa._conn() as conn:
        # All calculations share one snapshot, even while the beacon buffer flushes.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        wa._scope(conn, until)
        history = conn.execute("SELECT min(ts) FILTER (WHERE event='pageview') AS history, "
                               "min(ts) FILTER (WHERE tracking_version>=1) AS interactions FROM ev").fetchone()
        complete = bool(history["history"] and history["history"] <= previous)
        conn.execute("""
            CREATE TEMP TABLE product_sessions ON COMMIT DROP AS
            WITH candidates AS (
                SELECT DISTINCT visitor_id, session_id FROM ev WHERE ts >= %s
            ), first_page AS (
                SELECT DISTINCT ON (e.visitor_id,e.session_id)
                       e.visitor_id,e.session_id,e.referrer,e.utm_source,e.utm_medium,e.utm_campaign
                FROM ev e JOIN candidates c USING(visitor_id,session_id)
                WHERE e.event='pageview'
                ORDER BY e.visitor_id,e.session_id,e.ts,e.id
            )
            SELECT e.visitor_id,e.session_id,
                   min(e.ts) FILTER (WHERE e.event='pageview') AS started,
                   max(e.ts) AS ended,
                   count(*) FILTER (WHERE e.event='pageview') AS views,
                   coalesce(sum(e.engaged_ms) FILTER (WHERE e.event='leave'),0) AS engaged_ms,
                   bool_or(e.event=ANY(%s)) AS acted,
                   bool_or(e.tracking_version>=1 AND e.event='pageview') AS measured,
                   array_agg(DISTINCT e.user_id) FILTER (WHERE e.user_id IS NOT NULL) AS users,
                   f.referrer,f.utm_source,f.utm_medium,f.utm_campaign
            FROM ev e JOIN candidates c USING(visitor_id,session_id)
            JOIN first_page f USING(visitor_id,session_id)
            GROUP BY e.visitor_id,e.session_id,f.referrer,f.utm_source,f.utm_medium,f.utm_campaign
            HAVING min(e.ts) FILTER (WHERE e.event='pageview') >= %s
        """, (previous, list(FEATURE_EVENTS), previous))
        sessions = conn.execute("SELECT * FROM product_sessions WHERE started >= %s", (since,)).fetchall()
        registrations = conn.execute("""
            SELECT DISTINCT ON (u.id) u.id,s.visitor_id,s.session_id
            FROM product_sessions s JOIN web_users u ON u.id=ANY(s.users)
            WHERE u.created_at >= s.started AND u.created_at <= s.ended
              AND u.created_at >= %s AND u.created_at < %s
            ORDER BY u.id,s.started DESC,s.session_id,s.visitor_id
        """, (since, until)).fetchall()
        company_rows = conn.execute("""
            WITH counts AS (
                SELECT ticker,visitor_id,
                       count(*) FILTER (WHERE ts >= %s) AS views,
                       count(*) FILTER (WHERE ts < %s) AS previous_views
                FROM ev WHERE ts >= %s AND event='pageview' AND ticker IS NOT NULL
                  AND view IN ('company','chart','bond')
                GROUP BY ticker,visitor_id
            )
            SELECT c.ticker,count(*) FILTER (WHERE c.views>0) AS visitors,
                   count(*) FILTER (WHERE c.previous_views>0) AS previous_visitors,
                   sum(c.views) AS pageviews,
                   count(*) FILTER (WHERE c.views>0 AND EXISTS (
                       SELECT 1 FROM ev old WHERE old.visitor_id=c.visitor_id
                       AND old.ticker=c.ticker AND old.event='pageview' AND old.ts < %s
                   )) AS returning_visitors
            FROM counts c GROUP BY c.ticker ORDER BY visitors DESC,c.ticker LIMIT 100
        """, (since, since, previous, since)).fetchall()
        feature_rows = conn.execute("""
            SELECT e.event,e.visitor_id,e.session_id,count(*) AS actions
            FROM ev e JOIN product_sessions s USING(visitor_id,session_id)
            WHERE s.started >= %s AND e.event=ANY(%s) AND e.tracking_version>=1 AND s.measured
            GROUP BY e.event,e.visitor_id,e.session_id
            UNION ALL
            SELECT 'feature_news',e.visitor_id,e.session_id,count(*)
            FROM ev e JOIN product_sessions s USING(visitor_id,session_id)
            WHERE s.started >= %s AND e.event='pageview' AND e.view IN ('news','newsArticle')
            GROUP BY e.visitor_id,e.session_id
        """, (since, list(FEATURE_EVENTS), since)).fetchall()

        retention = _seven_day_return(conn, days, until, history["interactions"])

    credited = defaultdict(int)
    for row in registrations:
        credited[(row["visitor_id"], row["session_id"])] += 1
    sources = {}
    engaged_total = 0
    for s in sessions:
        host = wa.referrer_host(s["referrer"] or "")
        channel = wa.channel_for(host, s["utm_source"], s["utm_medium"])
        source = s["utm_source"] or (host if channel != "direct" else None) or "direct"
        key = (source, s["utm_medium"], s["utm_campaign"])
        row = sources.setdefault(key, {"source": source, "channel": channel,
                                      "medium": s["utm_medium"], "campaign": s["utm_campaign"],
                                      "sessions": 0, "visitors": set(), "engaged_sessions": 0, "registrations": 0, "converted_sessions": 0})
        # A product interaction, two page views, or 30 visible seconds is an
        # engaged visit. Scroll depth alone is not evidence of active reading.
        engaged = bool(s["acted"] or s["views"] >= 2 or s["engaged_ms"] >= 30000)
        row["sessions"] += 1
        row["visitors"].add(s["visitor_id"])
        row["engaged_sessions"] += int(engaged)
        row["registrations"] += credited[(s["visitor_id"], s["session_id"])]
        row["converted_sessions"] += int(credited[(s["visitor_id"], s["session_id"])] > 0)
        engaged_total += int(engaged)
    for row in sources.values():
        row["visitors"] = len(row["visitors"])
        row["registration_rate"] = wa._rate(row.pop("converted_sessions"), row["sessions"])
    measured = sum(bool(s["measured"]) for s in sessions)
    features = []
    for name in (*INTERACTIONS, "news"):
        counts = [r for r in feature_rows if r["event"] == f"feature_{name}"]
        per_user = defaultdict(int)
        for r in counts:
            per_user[r["visitor_id"]] += 1
        denominator = len(sessions) if name == "news" else measured
        available = name == "news" or measured > 0
        features.append({"feature": name, "measurement": "pageview" if name == "news" else "interaction",
                         "users": len(per_user) if available else None,
                         "sessions": len(counts) if available else None,
                         "actions": sum(r["actions"] for r in counts) if available else None,
                         "repeat_users": sum(n > 1 for n in per_user.values()) if available else None,
                         "adoption_rate": wa._rate(len(counts), denominator) if available else None})
    companies = [{**r, "pageviews": int(r["pageviews"]),
                  "change_pct": round(100 * (r["visitors"] - r["previous_visitors"]) / r["previous_visitors"], 1)
                  if complete and r["previous_visitors"] else None} for r in company_rows]

    def day(dt):
        return dt.astimezone(wa.TASHKENT).date().isoformat() if dt else None

    return {"ok": True, "days": days,
            "period": {"start": day(since), "end": day(until - timedelta(days=1)),
                       "previous_start": day(previous), "previous_end": day(since - timedelta(days=1))},
            "coverage": {"history_since": day(history["history"]), "previous_complete": complete,
                         "interaction_since": day(history["interactions"]),
                         "measured_sessions": measured, "total_sessions": len(sessions)},
            "totals": {"visitors": len({s["visitor_id"] for s in sessions}), "sessions": len(sessions),
                       "engaged_sessions": engaged_total, "registrations": len(registrations)},
            "sources": sorted(sources.values(), key=lambda r: (-r["sessions"], r["source"], r["campaign"] or "")),
            "companies": companies, "features": features, "retention": retention}



def _seven_day_return(conn, days, until, history_since):
    """First recorded activation cohorts, with a complete days 1–7 return window.

    Activation uses the established, versioned feature signals and requires a
    page view in that visit. Each browser enters once, over all recorded history.
    A return is the start of a different visit on a later Tashkent calendar day.
    Recent cohorts remain pending even when they have already returned.
    """
    cohort_until = until.astimezone(wa.TASHKENT).date() - timedelta(days=7)
    cohort_since = cohort_until - timedelta(days=days)
    rows = conn.execute("""
        WITH visits AS MATERIALIZED (
            SELECT visitor_id, session_id, min(ts) AS started
            FROM ev WHERE event='pageview' GROUP BY visitor_id, session_id
        ), first_actions AS (
            SELECT DISTINCT ON (e.visitor_id) e.visitor_id, e.session_id,
                   (e.ts AT TIME ZONE 'Asia/Tashkent')::date AS day
            FROM ev e JOIN visits v USING (visitor_id, session_id)
            WHERE e.event=ANY(%s) AND e.tracking_version>=1
              AND e.ticker IS NOT NULL AND v.started<=e.ts
            ORDER BY e.visitor_id, e.ts, e.id
        ), observed AS (
            SELECT f.day, EXISTS (
                SELECT 1 FROM visits v WHERE v.visitor_id=f.visitor_id
                  AND v.session_id<>f.session_id
                  AND v.started>=((f.day+1)::timestamp AT TIME ZONE 'Asia/Tashkent')
                  AND v.started<((f.day+8)::timestamp AT TIME ZONE 'Asia/Tashkent')
            ) AS returned
            FROM first_actions f WHERE f.day>=%s
        )
        SELECT day, count(*) AS visitors, count(*) FILTER (WHERE returned) AS returned
        FROM observed GROUP BY day ORDER BY day DESC
    """, (list(FEATURE_EVENTS), cohort_since)).fetchall()
    mature = {r["day"]: r for r in rows if r["day"] < cohort_until}
    pending = [r for r in rows if r["day"] >= cohort_until]
    cohorts = []
    for offset in range(days):
        day = cohort_until - timedelta(days=offset + 1)
        row = mature.get(day, {"visitors": 0, "returned": 0})
        observed = bool(history_since and day >= history_since.astimezone(wa.TASHKENT).date())
        cohorts.append({"day": day.isoformat(), "observed": observed, "visitors": row["visitors"],
                        "returned": row["returned"],
                        "return_rate": wa._rate(row["returned"], row["visitors"])})
    eligible = sum(r["visitors"] for r in cohorts)
    returned = sum(r["returned"] for r in cohorts)
    return {
        "cohort_period": {"start": cohort_since.isoformat(),
                          "end": (cohort_until - timedelta(days=1)).isoformat()},
        "observed_through": (until.astimezone(wa.TASHKENT).date() - timedelta(days=1)).isoformat(),
        "eligible_visitors": eligible, "returned_visitors": returned,
        "return_rate": wa._rate(returned, eligible),
        "pending_visitors": sum(r["visitors"] for r in pending),
        "next_ready_date": (min(r["day"] for r in pending) + timedelta(days=8)).isoformat() if pending else None,
        "history_since": history_since.astimezone(wa.TASHKENT).date().isoformat() if history_since else None,
        "history_complete": bool(history_since and history_since <= datetime.combine(cohort_since, datetime.min.time(), wa.TASHKENT)),
        "cohorts": cohorts,
    }
