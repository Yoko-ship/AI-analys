"""web_analytics.py — the site's own visit record, and the queries the admin
panel's product half reads.

Before this module nothing in the project recorded that a human opened the
site: the API had no request log, and every public page — the board, company
pages, news — left no trace (see ADMIN_PANEL_RESEARCH.md §0). The frontend now
sends one small beacon per page view to ``/api/track``; this module stores it
and answers the questions the panel asks: how many came, from where, on what,
and what they looked at.

Design constraints, in order:

* **Tracking must never slow a page.** ``record_pageview`` only appends to an
  in-memory buffer; a daemon thread flushes it to Postgres in one batched
  ``executemany`` every few seconds (row-at-a-time writes are the cost model —
  see postgres-round-trip-cost). A failed flush drops the batch and logs; the
  site never notices.
* **No raw IPs.** The address is salted-hashed before it enters the buffer and
  the raw form is never stored (ЗРУ-547 data-localisation caution). The hash
  exists only to tell visitors apart server-side if the client id is absent.
* **Zero and unknown are different facts.** Every aggregate returns ``None``
  where it cannot measure, and the panel renders «—».

The day boundary for "today/DAU" is Asia/Tashkent (UTC+5), because that is the
audience's day, not the server's.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# Salt for the IP hash. Falls back to the admin secret so the hash is stable
# across restarts without introducing a new required variable.
_IP_SALT = os.getenv("ANALYTICS_IP_SALT", "") or os.getenv("ADMIN_API_SECRET", "")

TASHKENT = timezone(timedelta(hours=5))

# Idle minutes after which the client rotates its session id; kept here only
# for documentation — the client owns the rotation.
SESSION_IDLE_MINUTES = 30

_FLUSH_SECONDS = float(os.getenv("ANALYTICS_FLUSH_SECONDS", "5"))
_MAX_BUFFER = 4000  # beyond this new events are dropped, counted, and logged

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _conn():
    from psycopg import connect
    from psycopg.rows import dict_row

    conn = connect(DATABASE_URL)
    conn.row_factory = dict_row
    return conn


def init_db() -> bool:
    """Create the events table. Additive and idempotent; safe on every boot."""
    if not DATABASE_URL:
        logger.warning("DATABASE_URL is not configured; web analytics is disabled")
        return False
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_events (
                id          BIGSERIAL PRIMARY KEY,
                ts          TIMESTAMPTZ NOT NULL,
                visitor_id  TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                user_id     BIGINT,
                event       TEXT NOT NULL DEFAULT 'pageview',
                path        TEXT NOT NULL,
                view        TEXT,
                ticker      TEXT,
                referrer    TEXT,
                lang        TEXT,
                device      TEXT,
                screen_w    INTEGER,
                browser     TEXT,
                os          TEXT,
                country     TEXT,
                ip_hash     TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_events_ts ON web_events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_events_visitor_ts ON web_events(visitor_id, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_events_session ON web_events(session_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_events_ticker_ts ON web_events(ticker, ts) WHERE ticker IS NOT NULL"
        )
        # Administrative mutations need a durable, attributable trail.  This is
        # deliberately separate from application logs: deploys rotate those,
        # while an account deletion must remain reconstructable afterwards.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_admin_audit_log (
                id              BIGSERIAL PRIMARY KEY,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                actor_user_id   BIGINT,
                actor_email     TEXT NOT NULL,
                action          TEXT NOT NULL,
                target_type     TEXT NOT NULL,
                target_id       TEXT,
                target_label    TEXT,
                outcome         TEXT NOT NULL,
                request_id      TEXT NOT NULL,
                ip_hash         TEXT,
                details         JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_admin_audit_created "
            "ON web_admin_audit_log(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_admin_audit_actor "
            "ON web_admin_audit_log(actor_user_id, created_at DESC)"
        )
    return True


# ---------------------------------------------------------------------------
# Parsing helpers (pure functions — tested without a database)
# ---------------------------------------------------------------------------

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|embedly|quora link"
    r"|pinterest|whatsapp|telegrambot|vkshare|okhttp|headless|phantom|lighthouse"
    r"|python-requests|python-urllib|aiohttp|httpx|curl/|wget/|go-http-client"
    r"|apache-httpclient|feedfetcher|preview|monitor|uptime|scan",
    re.IGNORECASE,
)


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or "").strip()
    if not ua:
        return True  # a browser always sends one; an empty UA is a script
    return bool(_BOT_RE.search(ua))


def parse_user_agent(user_agent: str) -> dict[str, str]:
    """Family-level UA parse. Families are all the panel charts; versions are noise."""
    ua = user_agent or ""

    if "Windows NT" in ua:
        os_name = "Windows"
    elif "iPhone" in ua or "iPad" in ua or "iPod" in ua:
        os_name = "iOS"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Android" in ua:
        os_name = "Android"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    # Order matters: Chrome's token appears inside almost every derivative UA.
    if "Edg/" in ua or "EdgA/" in ua or "EdgiOS/" in ua:
        browser = "Edge"
    elif "YaBrowser/" in ua:
        browser = "Yandex"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "SamsungBrowser/" in ua:
        browser = "Samsung"
    elif "Firefox/" in ua or "FxiOS/" in ua:
        browser = "Firefox"
    elif "CriOS/" in ua or "Chrome/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Other"

    if "iPad" in ua or ("Android" in ua and "Mobile" not in ua):
        device = "tablet"
    elif "iPhone" in ua or "iPod" in ua or "Mobi" in ua or "Android" in ua:
        device = "mobile"
    else:
        device = "desktop"

    return {"os": os_name, "browser": browser, "device": device}


_SEARCH_HOSTS = ("google.", "yandex.", "bing.com", "duckduckgo.com", "go.mail.ru", "search.")
_SOCIAL_HOSTS = ("t.me", "telegram.", "facebook.", "fb.com", "instagram.", "twitter.",
                 "x.com", "linkedin.", "ok.ru", "vk.com", "youtube.", "youtu.be")


def referrer_host(referrer: str) -> str:
    """The bare host of a referrer URL, lowercased, without www."""
    text = (referrer or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    host = text.split("/", 1)[0].split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def classify_referrer(referrer: str, own_hosts: tuple[str, ...] = ()) -> str:
    """direct / search / social / internal / referral — the acquisition split."""
    host = referrer_host(referrer)
    if not host:
        return "direct"
    if host in own_hosts:
        return "internal"
    if any(host == h or host.endswith("." + h.rstrip(".")) or host.startswith(h) for h in _SEARCH_HOSTS):
        return "search"
    if any(host == h or host.endswith("." + h.rstrip(".")) or host.startswith(h) for h in _SOCIAL_HOSTS):
        return "social"
    return "referral"


def hash_ip(ip: str) -> Optional[str]:
    ip = (ip or "").strip()
    if not ip:
        return None
    digest = hashlib.sha256(f"{_IP_SALT}|{ip}".encode("utf-8")).hexdigest()
    return digest[:16]


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,16}$")
_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def sanitize_payload(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Validate and clamp what the beacon sent. None means: not storable.

    The beacon is unauthenticated public input; everything is treated as
    hostile. Ids must look like ids, the path must be a site path, and every
    free-text field is clamped hard.
    """
    if not isinstance(data, dict):
        return None
    vid = str(data.get("vid") or "").strip()
    sid = str(data.get("sid") or "").strip()
    if not _ID_RE.match(vid) or not _ID_RE.match(sid):
        return None

    path = str(data.get("path") or "").strip()
    if not path.startswith("/") or len(path) > 200 or "\n" in path:
        return None

    event = str(data.get("event") or "pageview").strip()
    if not _EVENT_RE.match(event):
        return None

    ticker = str(data.get("ticker") or "").strip().upper()
    if ticker and not _TICKER_RE.match(ticker):
        ticker = ""

    view = str(data.get("view") or "").strip()[:32]
    lang = str(data.get("lang") or "").strip().lower()[:5]
    if lang not in {"ru", "uz", "en"}:
        lang = ""
    referrer = str(data.get("ref") or "").strip()[:300]

    uid = data.get("uid")
    try:
        uid = int(uid) if uid is not None else None
        if uid is not None and not (0 < uid < 10**12):
            uid = None
    except (TypeError, ValueError):
        uid = None

    width = data.get("w")
    try:
        width = int(width) if width is not None else None
        if width is not None and not (0 < width < 20000):
            width = None
    except (TypeError, ValueError):
        width = None

    return {
        "vid": vid, "sid": sid, "uid": uid, "event": event, "path": path,
        "view": view or None, "ticker": ticker or None, "referrer": referrer or None,
        "lang": lang or None, "screen_w": width,
    }


# ---------------------------------------------------------------------------
# The write path: buffer + flusher thread
# ---------------------------------------------------------------------------

_buffer: list[tuple] = []
_buffer_lock = threading.Lock()
_dropped = 0
_flusher_started = False
_flusher_lock = threading.Lock()


def _ensure_flusher() -> None:
    global _flusher_started
    if _flusher_started:
        return
    with _flusher_lock:
        if _flusher_started:
            return
        thread = threading.Thread(target=_flush_loop, name="web-analytics-flush", daemon=True)
        thread.start()
        _flusher_started = True


def _flush_loop() -> None:
    while True:
        time.sleep(_FLUSH_SECONDS)
        try:
            flush()
        except Exception:
            logger.exception("web analytics flush failed")


def flush() -> int:
    """Write everything buffered in one batch. Returns rows written."""
    global _dropped
    with _buffer_lock:
        batch = _buffer[:]
        _buffer.clear()
        dropped, _dropped = _dropped, 0
    if dropped:
        logger.warning("web analytics dropped %d events (buffer full)", dropped)
    if not batch or not DATABASE_URL:
        return 0
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO web_events
                        (ts, visitor_id, session_id, user_id, event, path, view, ticker,
                         referrer, lang, device, screen_w, browser, os, country, ip_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    batch,
                )
        return len(batch)
    except Exception:
        logger.exception("web analytics: failed to write %d events, batch dropped", len(batch))
        return 0


def record_pageview(data: dict[str, Any], *, user_agent: str = "", ip: str = "",
                    country: str | None = None) -> bool:
    """Buffer one event from the beacon. Fast path — no I/O, no exceptions out."""
    global _dropped
    if not DATABASE_URL:
        return False
    if is_bot(user_agent):
        return False
    clean = sanitize_payload(data)
    if clean is None:
        return False
    ua = parse_user_agent(user_agent)
    country_code = (country or "").strip().upper()[:2] or None
    row = (
        datetime.now(timezone.utc),
        clean["vid"], clean["sid"], clean["uid"], clean["event"], clean["path"],
        clean["view"], clean["ticker"], clean["referrer"], clean["lang"],
        ua["device"], clean["screen_w"], ua["browser"], ua["os"],
        country_code, hash_ip(ip),
    )
    with _buffer_lock:
        if len(_buffer) >= _MAX_BUFFER:
            _dropped += 1
            return False
        _buffer.append(row)
    _ensure_flusher()
    return True


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _day_start(now: datetime, days_back: int = 0) -> datetime:
    local = now.astimezone(TASHKENT)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return start.astimezone(timezone.utc)


def _scalar(conn, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return next(iter(row.values()), None)


def _uniq_visitors(conn, since: datetime, until: datetime | None = None) -> Optional[int]:
    if until is None:
        value = _scalar(conn, "SELECT COUNT(DISTINCT visitor_id) FROM web_events WHERE ts >= %s", (since,))
    else:
        value = _scalar(conn, "SELECT COUNT(DISTINCT visitor_id) FROM web_events WHERE ts >= %s AND ts < %s",
                        (since, until))
    return int(value) if value is not None else None


def _available() -> bool:
    return bool(DATABASE_URL)


# ---------------------------------------------------------------------------
# §1 Обзор — the morning numbers
# ---------------------------------------------------------------------------

def overview() -> dict[str, Any]:
    """People first: visitors, DAU/WAU/MAU, stickiness, live-now, product use."""
    if not _available():
        return {"ok": False, "reason": "no database"}
    now = datetime.now(timezone.utc)
    today = _day_start(now)
    with _conn() as conn:
        d7 = now - timedelta(days=7)
        d14 = now - timedelta(days=14)
        d30 = now - timedelta(days=30)
        d60 = now - timedelta(days=60)

        visitors = {
            "today": _uniq_visitors(conn, today),
            "yesterday": _uniq_visitors(conn, _day_start(now, 1), today),
            "d7": _uniq_visitors(conn, d7),
            "prev7": _uniq_visitors(conn, d14, d7),
            "d30": _uniq_visitors(conn, d30),
            "prev30": _uniq_visitors(conn, d60, d30),
        }
        pageviews_today = _scalar(conn, "SELECT COUNT(*) FROM web_events WHERE ts >= %s AND event = 'pageview'",
                                  (today,))
        live_now = _scalar(conn, "SELECT COUNT(DISTINCT visitor_id) FROM web_events WHERE ts >= %s",
                           (now - timedelta(minutes=5),))

        # Stickiness on the average DAU of the last 7 full days, not today's
        # partial one — today at 9 a.m. would understate it every morning.
        avg_dau = _scalar(
            conn,
            """
            SELECT AVG(dau) FROM (
                SELECT ((ts + INTERVAL '5 hour')::date) AS day, COUNT(DISTINCT visitor_id) AS dau
                FROM web_events WHERE ts >= %s AND ts < %s
                GROUP BY 1
            ) days
            """,
            (_day_start(now, 7), today),
        )
        mau = visitors["d30"]
        stickiness = (float(avg_dau) / mau) if (avg_dau and mau) else None

        signed_in = {
            "today": _scalar(conn, "SELECT COUNT(DISTINCT user_id) FROM web_events WHERE ts >= %s AND user_id IS NOT NULL", (today,)),
            "d7": _scalar(conn, "SELECT COUNT(DISTINCT user_id) FROM web_events WHERE ts >= %s AND user_id IS NOT NULL", (d7,)),
        }

        registrations = {
            "today": _scalar(conn, "SELECT COUNT(*) FROM web_users WHERE created_at >= %s", (today,)),
            "d7": _scalar(conn, "SELECT COUNT(*) FROM web_users WHERE created_at >= %s", (d7,)),
            "d30": _scalar(conn, "SELECT COUNT(*) FROM web_users WHERE created_at >= %s", (d30,)),
            "total": _scalar(conn, "SELECT COUNT(*) FROM web_users"),
        }
        analyses = {
            "today": _scalar(conn, "SELECT COUNT(*) FROM web_analysis_history WHERE created_at >= %s", (today,)),
            "d7": _scalar(conn, "SELECT COUNT(*) FROM web_analysis_history WHERE created_at >= %s", (d7,)),
        }

        # 14-day daily visitors strip for the header chart.
        daily = conn.execute(
            """
            SELECT ((ts + INTERVAL '5 hour')::date) AS day,
                   COUNT(DISTINCT visitor_id) AS visitors,
                   COUNT(*) FILTER (WHERE event = 'pageview') AS pageviews
            FROM web_events WHERE ts >= %s
            GROUP BY 1 ORDER BY 1
            """,
            (_day_start(now, 13),),
        ).fetchall()

    return {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "visitors": {k: (int(v) if v is not None else None) for k, v in visitors.items()},
        "pageviews_today": int(pageviews_today) if pageviews_today is not None else None,
        "live_now": int(live_now) if live_now is not None else None,
        "stickiness": round(stickiness, 4) if stickiness is not None else None,
        "avg_dau_7d": round(float(avg_dau), 1) if avg_dau is not None else None,
        "mau": mau,
        "signed_in": {k: (int(v) if v is not None else None) for k, v in signed_in.items()},
        "registrations": {k: (int(v) if v is not None else None) for k, v in registrations.items()},
        "analyses": {k: (int(v) if v is not None else None) for k, v in analyses.items()},
        "daily": [{"day": str(r["day"]), "visitors": int(r["visitors"]), "pageviews": int(r["pageviews"])}
                  for r in daily],
    }


# ---------------------------------------------------------------------------
# §2 Аудитория
# ---------------------------------------------------------------------------

def audience(days: int = 30) -> dict[str, Any]:
    if not _available():
        return {"ok": False, "reason": "no database"}
    days = max(1, min(int(days or 30), 365))
    now = datetime.now(timezone.utc)
    since = _day_start(now, days - 1)
    with _conn() as conn:
        daily = conn.execute(
            """
            SELECT ((ts + INTERVAL '5 hour')::date) AS day,
                   COUNT(DISTINCT visitor_id) AS visitors,
                   COUNT(DISTINCT session_id) AS sessions,
                   COUNT(*) FILTER (WHERE event = 'pageview') AS pageviews
            FROM web_events WHERE ts >= %s
            GROUP BY 1 ORDER BY 1
            """,
            (since,),
        ).fetchall()

        totals = conn.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) AS visitors,
                   COUNT(DISTINCT session_id) AS sessions,
                   COUNT(*) FILTER (WHERE event = 'pageview') AS pageviews
            FROM web_events WHERE ts >= %s
            """,
            (since,),
        ).fetchone()

        session_stats = conn.execute(
            """
            SELECT COUNT(*) AS sessions,
                   COUNT(*) FILTER (WHERE views = 1) AS bounced,
                   AVG(views)::NUMERIC(10,2) AS pages_per_session,
                   AVG(seconds) FILTER (WHERE seconds > 0)::NUMERIC(10,1) AS avg_seconds
            FROM (
                SELECT session_id,
                       COUNT(*) FILTER (WHERE event = 'pageview') AS views,
                       EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) AS seconds
                FROM web_events WHERE ts >= %s
                GROUP BY session_id
            ) s
            """,
            (since,),
        ).fetchone()

        new_visitors = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT visitor_id, MIN(ts) AS first_seen
                FROM web_events GROUP BY visitor_id
            ) v WHERE first_seen >= %s
            """,
            (since,),
        )

        referrers = conn.execute(
            """
            SELECT COALESCE(NULLIF(split_part(split_part(
                       regexp_replace(COALESCE(referrer, ''), '^[a-z]+://', ''), '/', 1), ':', 1), ''),
                   '(direct)') AS host,
                   COUNT(DISTINCT session_id) AS sessions
            FROM web_events
            WHERE ts >= %s AND event = 'pageview'
            GROUP BY 1 ORDER BY sessions DESC LIMIT 15
            """,
            (since,),
        ).fetchall()

        def breakdown(column: str, limit: int = 8):
            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF({column}, ''), '(unknown)') AS name,
                       COUNT(DISTINCT visitor_id) AS visitors
                FROM web_events WHERE ts >= %s
                GROUP BY 1 ORDER BY visitors DESC LIMIT {int(limit)}
                """,  # noqa: S608 - column names are fixed call sites below
                (since,),
            ).fetchall()
            return [{"name": r["name"], "visitors": int(r["visitors"])} for r in rows]

        screens = conn.execute(
            """
            SELECT CASE
                     WHEN screen_w IS NULL THEN '(unknown)'
                     WHEN screen_w < 380 THEN '<380'
                     WHEN screen_w < 420 THEN '380–419'
                     WHEN screen_w < 768 THEN '420–767'
                     WHEN screen_w < 1280 THEN '768–1279'
                     ELSE '1280+'
                   END AS bucket,
                   COUNT(DISTINCT visitor_id) AS visitors
            FROM web_events WHERE ts >= %s
            GROUP BY 1 ORDER BY visitors DESC
            """,
            (since,),
        ).fetchall()

        # Materialise the closure-based breakdowns while the connection is
        # still open — the return statement below runs after the `with` block
        # has closed it.
        devices = breakdown("device")
        browsers = breakdown("browser")
        oses = breakdown("os")
        languages = breakdown("lang")
        countries = breakdown("country", 12)

    total_visitors = int(totals["visitors"]) if totals and totals["visitors"] is not None else None
    sessions_total = int(session_stats["sessions"]) if session_stats and session_stats["sessions"] else 0
    bounced = int(session_stats["bounced"] or 0) if session_stats else 0

    ref_rows = []
    for r in referrers:
        host = r["host"]
        kind = "direct" if host == "(direct)" else classify_referrer(f"https://{host}/")
        ref_rows.append({"host": host, "sessions": int(r["sessions"]), "kind": kind})

    return {
        "ok": True,
        "days": days,
        "daily": [{"day": str(r["day"]), "visitors": int(r["visitors"]),
                   "sessions": int(r["sessions"]), "pageviews": int(r["pageviews"])} for r in daily],
        "totals": {
            "visitors": total_visitors,
            "sessions": int(totals["sessions"]) if totals and totals["sessions"] is not None else None,
            "pageviews": int(totals["pageviews"]) if totals and totals["pageviews"] is not None else None,
            "new_visitors": int(new_visitors) if new_visitors is not None else None,
            "returning_visitors": (total_visitors - int(new_visitors))
                if (total_visitors is not None and new_visitors is not None) else None,
            "pages_per_session": float(session_stats["pages_per_session"])
                if session_stats and session_stats["pages_per_session"] is not None else None,
            "avg_session_seconds": float(session_stats["avg_seconds"])
                if session_stats and session_stats["avg_seconds"] is not None else None,
            "bounce_rate": round(bounced / sessions_total, 4) if sessions_total else None,
        },
        "referrers": ref_rows,
        "devices": devices,
        "browsers": browsers,
        "os": oses,
        "languages": languages,
        "countries": countries,
        "screens": [{"name": r["bucket"], "visitors": int(r["visitors"])} for r in screens],
    }


# ---------------------------------------------------------------------------
# §3 Вовлечённость
# ---------------------------------------------------------------------------

def engagement(days: int = 30) -> dict[str, Any]:
    if not _available():
        return {"ok": False, "reason": "no database"}
    days = max(1, min(int(days or 30), 365))
    since = _day_start(datetime.now(timezone.utc), days - 1)
    with _conn() as conn:
        views = conn.execute(
            """
            SELECT COALESCE(NULLIF(view, ''), '(other)') AS view,
                   COUNT(*) AS pageviews,
                   COUNT(DISTINCT visitor_id) AS visitors
            FROM web_events WHERE ts >= %s AND event = 'pageview'
            GROUP BY 1 ORDER BY pageviews DESC LIMIT 20
            """,
            (since,),
        ).fetchall()

        tickers = conn.execute(
            """
            SELECT ticker,
                   COUNT(*) AS pageviews,
                   COUNT(DISTINCT visitor_id) AS visitors
            FROM web_events
            WHERE ts >= %s AND event = 'pageview' AND ticker IS NOT NULL
            GROUP BY 1 ORDER BY pageviews DESC LIMIT 25
            """,
            (since,),
        ).fetchall()

        news = conn.execute(
            """
            SELECT path, COUNT(*) AS pageviews, COUNT(DISTINCT visitor_id) AS visitors
            FROM web_events
            WHERE ts >= %s AND event = 'pageview' AND path LIKE '/news/%%'
            GROUP BY 1 ORDER BY pageviews DESC LIMIT 15
            """,
            (since,),
        ).fetchall()

        events = conn.execute(
            """
            SELECT event, COUNT(*) AS count, COUNT(DISTINCT visitor_id) AS visitors
            FROM web_events WHERE ts >= %s AND event <> 'pageview'
            GROUP BY 1 ORDER BY count DESC LIMIT 20
            """,
            (since,),
        ).fetchall()

    return {
        "ok": True,
        "days": days,
        "views": [{"view": r["view"], "pageviews": int(r["pageviews"]), "visitors": int(r["visitors"])}
                  for r in views],
        "tickers": [{"ticker": r["ticker"], "pageviews": int(r["pageviews"]), "visitors": int(r["visitors"])}
                    for r in tickers],
        "news": [{"path": r["path"], "pageviews": int(r["pageviews"]), "visitors": int(r["visitors"])}
                 for r in news],
        "events": [{"event": r["event"], "count": int(r["count"]), "visitors": int(r["visitors"])}
                   for r in events],
    }


# ---------------------------------------------------------------------------
# §4 AI-анализ — usage and the bill
# ---------------------------------------------------------------------------

def analysis_usage(days: int = 30) -> dict[str, Any]:
    if not _available():
        return {"ok": False, "reason": "no database"}
    days = max(1, min(int(days or 30), 365))
    now = datetime.now(timezone.utc)
    since = _day_start(now, days - 1)
    month_start = now.astimezone(TASHKENT).replace(day=1, hour=0, minute=0, second=0,
                                                   microsecond=0).astimezone(timezone.utc)
    with _conn() as conn:
        daily = conn.execute(
            """
            SELECT ((created_at + INTERVAL '5 hour')::date) AS day,
                   COUNT(*) AS analyses,
                   COUNT(DISTINCT user_id) AS users,
                   COUNT(*) FILTER (WHERE from_cache) AS cached,
                   COALESCE(SUM(cost) FILTER (WHERE NOT from_cache), 0)::NUMERIC(12,4) AS cost
            FROM web_analysis_history WHERE created_at >= %s
            GROUP BY 1 ORDER BY 1
            """,
            (since,),
        ).fetchall()

        totals = conn.execute(
            """
            SELECT COUNT(*) AS analyses,
                   COUNT(DISTINCT user_id) AS users,
                   COUNT(*) FILTER (WHERE from_cache) AS cached,
                   COALESCE(SUM(cost) FILTER (WHERE NOT from_cache), 0)::NUMERIC(12,4) AS cost
            FROM web_analysis_history WHERE created_at >= %s
            """,
            (since,),
        ).fetchone()

        mtd = conn.execute(
            """
            SELECT COUNT(*) AS analyses,
                   COALESCE(SUM(cost) FILTER (WHERE NOT from_cache), 0)::NUMERIC(12,4) AS cost
            FROM web_analysis_history WHERE created_at >= %s
            """,
            (month_start,),
        ).fetchone()

        top = conn.execute(
            """
            SELECT COALESCE(NULLIF(ticker, ''), COALESCE(NULLIF(company_name, ''), company_input)) AS name,
                   COUNT(*) AS analyses,
                   COUNT(DISTINCT user_id) AS users
            FROM web_analysis_history WHERE created_at >= %s
            GROUP BY 1 ORDER BY analyses DESC LIMIT 15
            """,
            (since,),
        ).fetchall()

        models = conn.execute(
            """
            SELECT COALESCE(NULLIF(model, ''), '(unknown)') AS model,
                   COUNT(*) AS analyses,
                   COALESCE(SUM(cost) FILTER (WHERE NOT from_cache), 0)::NUMERIC(12,4) AS cost
            FROM web_analysis_history WHERE created_at >= %s
            GROUP BY 1 ORDER BY analyses DESC
            """,
            (since,),
        ).fetchall()

        grades = conn.execute(
            """
            SELECT COALESCE(NULLIF(grade, ''), '(none)') AS grade, COUNT(*) AS analyses
            FROM web_analysis_history WHERE created_at >= %s
            GROUP BY 1 ORDER BY analyses DESC
            """,
            (since,),
        ).fetchall()

    analyses_total = int(totals["analyses"] or 0)
    cached = int(totals["cached"] or 0)
    local_now = now.astimezone(TASHKENT)
    days_elapsed = local_now.day
    # naive month length: last day of this month
    next_month = (local_now.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - local_now.replace(day=1)).days
    mtd_cost = float(mtd["cost"] or 0)
    projection = round(mtd_cost / days_elapsed * days_in_month, 2) if days_elapsed else None

    return {
        "ok": True,
        "days": days,
        "daily": [{"day": str(r["day"]), "analyses": int(r["analyses"]), "users": int(r["users"]),
                   "cached": int(r["cached"]), "cost": float(r["cost"] or 0)} for r in daily],
        "totals": {
            "analyses": analyses_total,
            "users": int(totals["users"] or 0),
            "cached": cached,
            "cache_rate": round(cached / analyses_total, 4) if analyses_total else None,
            "cost": float(totals["cost"] or 0),
            "cost_per_analysis": round(float(totals["cost"] or 0) / analyses_total, 4)
                if analyses_total else None,
        },
        "month_to_date": {"analyses": int(mtd["analyses"] or 0), "cost": mtd_cost,
                          "projected_cost": projection},
        "top_companies": [{"name": r["name"], "analyses": int(r["analyses"]), "users": int(r["users"])}
                          for r in top],
        "models": [{"model": r["model"], "analyses": int(r["analyses"]), "cost": float(r["cost"] or 0)}
                   for r in models],
        "grades": [{"grade": r["grade"], "analyses": int(r["analyses"])} for r in grades],
    }


# ---------------------------------------------------------------------------
# §5 Пользователи — the back-office half
# ---------------------------------------------------------------------------

def users_list(query: str = "", limit: int = 50, offset: int = 0,
               only: str = "") -> dict[str, Any]:
    if not _available():
        return {"ok": False, "reason": "no database"}
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    where = ["TRUE"]
    params: list[Any] = []
    text = (query or "").strip().lower()
    if text:
        where.append("(LOWER(u.email) LIKE %s OR LOWER(u.full_name) LIKE %s)")
        params.extend([f"%{text}%", f"%{text}%"])
    if only == "active":
        where.append("u.is_active")
    elif only == "inactive":
        where.append("NOT u.is_active")
    elif only == "analysed":
        where.append("EXISTS (SELECT 1 FROM web_analysis_history h WHERE h.user_id = u.id)")

    with _conn() as conn:
        total = _scalar(conn, f"SELECT COUNT(*) FROM web_users u WHERE {' AND '.join(where)}",
                        tuple(params))
        rows = conn.execute(
            f"""
            SELECT u.id, u.email, u.full_name, u.is_active, u.tier, u.subscription_until, u.created_at, u.last_login_at,
                   (SELECT COUNT(*) FROM web_analysis_history h WHERE h.user_id = u.id) AS analyses,
                   (SELECT COUNT(*) FROM web_favorite_companies f WHERE f.user_id = u.id) AS favorites,
                   (SELECT COUNT(*) FROM web_sessions s WHERE s.user_id = u.id
                        AND s.revoked_at IS NULL AND s.expires_at > NOW()) AS active_sessions,
                   (SELECT STRING_AGG(DISTINCT provider, ', ') FROM web_oauth_accounts o
                        WHERE o.user_id = u.id) AS oauth_providers
            FROM web_users u
            WHERE {' AND '.join(where)}
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,  # noqa: S608 - `where` is assembled from fixed fragments above
            tuple(params) + (limit, offset),
        ).fetchall()

    # The allowlist is configuration rather than a database role. Return the
    # effective permission so the UI can mark protected accounts, but enforce
    # the protection again in ``user_action``; UI state is never authority.
    from identity.users import is_admin_email

    return {
        "ok": True,
        "total": int(total) if total is not None else None,
        "items": [{
            "id": r["id"], "email": r["email"], "full_name": r["full_name"],
            "is_active": bool(r["is_active"]),
            "tier": r.get("tier") or "free",
            "subscription_until": r["subscription_until"].isoformat() if r.get("subscription_until") else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
            "analyses": int(r["analyses"] or 0),
            "favorites": int(r["favorites"] or 0),
            "active_sessions": int(r["active_sessions"] or 0),
            "oauth_providers": r["oauth_providers"],
            "is_admin": is_admin_email(r["email"]),
        } for r in rows],
    }


def users_funnel(days: int = 30) -> dict[str, Any]:
    """visited → registered → ran first analysis → came back after a day."""
    if not _available():
        return {"ok": False, "reason": "no database"}
    days = max(1, min(int(days or 30), 365))
    since = _day_start(datetime.now(timezone.utc), days - 1)
    with _conn() as conn:
        visitors = _uniq_visitors(conn, since)
        registered = _scalar(conn, "SELECT COUNT(*) FROM web_users WHERE created_at >= %s", (since,))
        activated = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM web_users u
            WHERE u.created_at >= %s
              AND EXISTS (SELECT 1 FROM web_analysis_history h WHERE h.user_id = u.id)
            """,
            (since,),
        )
        returned = _scalar(
            conn,
            """
            SELECT COUNT(*) FROM web_users u
            WHERE u.created_at >= %s
              AND EXISTS (SELECT 1 FROM web_sessions s
                          WHERE s.user_id = u.id
                            AND s.created_at > u.created_at + INTERVAL '24 hours')
            """,
            (since,),
        )
    return {
        "ok": True,
        "days": days,
        "steps": [
            {"key": "visited", "count": visitors},
            {"key": "registered", "count": int(registered) if registered is not None else None},
            {"key": "activated", "count": int(activated) if activated is not None else None},
            {"key": "returned", "count": int(returned) if returned is not None else None},
        ],
    }


def user_detail(user_id: int) -> dict[str, Any]:
    if not _available():
        return {"ok": False, "reason": "no database"}
    with _conn() as conn:
        user = conn.execute(
            """
            SELECT id, email, full_name, is_active, tier, subscription_until, created_at, last_login_at
            FROM web_users WHERE id = %s
            """,
            (user_id,),
        ).fetchone()
        if not user:
            return {"ok": False, "reason": "not found"}
        sessions = conn.execute(
            """
            SELECT created_at, expires_at, revoked_at
            FROM web_sessions WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 10
            """,
            (user_id,),
        ).fetchall()
        analyses = conn.execute(
            """
            SELECT company_input, company_name, ticker, score, grade, from_cache, model,
                   cost, created_at
            FROM web_analysis_history WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 20
            """,
            (user_id,),
        ).fetchall()
        favorites = conn.execute(
            """
            SELECT ticker, company_name, created_at
            FROM web_favorite_companies WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        oauth = conn.execute(
            "SELECT provider, provider_email, created_at FROM web_oauth_accounts WHERE user_id = %s",
            (user_id,),
        ).fetchall()
    from identity.users import is_admin_email

    return {
        "ok": True,
        "user": {
            "id": user["id"], "email": user["email"], "full_name": user["full_name"],
            "is_active": bool(user["is_active"]),
            "tier": user.get("tier") or "free",
            "subscription_until": user["subscription_until"].isoformat() if user.get("subscription_until") else None,
            "created_at": user["created_at"].isoformat() if user["created_at"] else None,
            "last_login_at": user["last_login_at"].isoformat() if user["last_login_at"] else None,
            "is_admin": is_admin_email(user["email"]),
        },
        "sessions": [{
            "created_at": s["created_at"].isoformat() if s["created_at"] else None,
            "expires_at": s["expires_at"].isoformat() if s["expires_at"] else None,
            "revoked": bool(s["revoked_at"]),
        } for s in sessions],
        "analyses": [{
            "company": a["company_name"] or a["company_input"], "ticker": a["ticker"],
            "score": float(a["score"]) if a["score"] is not None else None,
            "grade": a["grade"], "from_cache": bool(a["from_cache"]), "model": a["model"],
            "cost": float(a["cost"]) if a["cost"] is not None else None,
            "created_at": a["created_at"].isoformat() if a["created_at"] else None,
        } for a in analyses],
        "favorites": [{
            "ticker": f["ticker"], "company_name": f["company_name"],
            "created_at": f["created_at"].isoformat() if f["created_at"] else None,
        } for f in favorites],
        "oauth": [{
            "provider": o["provider"], "email": o["provider_email"],
            "created_at": o["created_at"].isoformat() if o["created_at"] else None,
        } for o in oauth],
    }


def _write_admin_audit(conn, *, actor_user_id: int, actor_email: str,
                       action: str, target_type: str, target_id: str | None,
                       target_label: str | None, outcome: str, request_id: str,
                       source_ip_hash: str | None = None,
                       details: dict[str, Any] | None = None) -> None:
    """Append one administrative action inside the mutation's transaction."""
    conn.execute(
        """
        INSERT INTO web_admin_audit_log
            (actor_user_id, actor_email, action, target_type, target_id,
             target_label, outcome, request_id, ip_hash, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (actor_user_id, actor_email, action, target_type, target_id,
         target_label, outcome, request_id, source_ip_hash,
         json.dumps(details or {}, ensure_ascii=False)),
    )


def admin_audit_log(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Recent privileged mutations, newest first; secrets never enter this log."""
    if not _available():
        return {"ok": False, "reason": "no database"}
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    with _conn() as conn:
        total = _scalar(conn, "SELECT COUNT(*) FROM web_admin_audit_log")
        rows = conn.execute(
            """
            SELECT id, created_at, actor_user_id, actor_email, action,
                   target_type, target_id, target_label, outcome, request_id
            FROM web_admin_audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
    return {
        "ok": True,
        "total": int(total) if total is not None else None,
        "items": [{
            "id": r["id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "actor_user_id": r["actor_user_id"],
            "actor_email": r["actor_email"],
            "action": r["action"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "target_label": r["target_label"],
            "outcome": r["outcome"],
            "request_id": r["request_id"],
        } for r in rows],
    }


def user_action(user_id: int, action: str, *, actor_user_id: int,
                actor_email: str, request_id: str,
                source_ip_hash: str | None = None) -> dict[str, Any]:
    """Mutate one account and append an attributable audit record atomically."""
    if not _available():
        return {"ok": False, "reason": "no database"}
    action = (action or "").strip()
    from identity.users import is_admin_email

    with _conn() as conn:
        exists = conn.execute("SELECT id, email FROM web_users WHERE id = %s", (user_id,)).fetchone()
        if not exists:
            _write_admin_audit(
                conn, actor_user_id=actor_user_id, actor_email=actor_email,
                action=action, target_type="user", target_id=str(user_id),
                target_label=None, outcome="not_found", request_id=request_id,
                source_ip_hash=source_ip_hash,
            )
            return {"ok": False, "reason": "not found"}
        # An allowlisted admin cannot be disabled or deleted from the panel.
        # Remove the address from ADMIN_EMAILS first: changing that control-plane
        # configuration is an explicit, reviewable act and prevents lockout.
        if action in {"deactivate", "delete"} and is_admin_email(exists["email"]):
            _write_admin_audit(
                conn, actor_user_id=actor_user_id, actor_email=actor_email,
                action=action, target_type="user", target_id=str(user_id),
                target_label=exists["email"], outcome="denied_protected_admin",
                request_id=request_id, source_ip_hash=source_ip_hash,
            )
            return {"ok": False, "reason": "protected admin"}
        if action == "deactivate":
            conn.execute("UPDATE web_users SET is_active = FALSE WHERE id = %s", (user_id,))
            conn.execute(
                "UPDATE web_sessions SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
        elif action == "reactivate":
            conn.execute("UPDATE web_users SET is_active = TRUE WHERE id = %s", (user_id,))
        elif action == "revoke_sessions":
            conn.execute(
                "UPDATE web_sessions SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
        elif action == "delete":
            # ON DELETE CASCADE takes sessions, oauth links, history and favourites.
            conn.execute("DELETE FROM web_users WHERE id = %s", (user_id,))
        else:
            return {"ok": False, "reason": f"unknown action: {action}"}
        _write_admin_audit(
            conn, actor_user_id=actor_user_id, actor_email=actor_email,
            action=action, target_type="user", target_id=str(user_id),
            target_label=exists["email"], outcome="success", request_id=request_id,
            source_ip_hash=source_ip_hash,
        )
    logger.info("admin user action: %s on user %s (%s) by %s",
                action, user_id, exists["email"], actor_email)
    return {"ok": True, "action": action, "user_id": user_id}


def set_subscription(user_id: int, tier: str, subscription_until: datetime | None, *,
                     reason: str, actor_user_id: int, actor_email: str,
                     request_id: str, source_ip_hash: str | None = None) -> dict[str, Any]:
    """Set a web entitlement and journal the exact before/after state.

    Payment processing is intentionally outside the product specification.  An
    administrator still needs a controlled way to provision a paid account
    after an external payment or an approved trial, and that action must be as
    attributable as every other privileged account change.
    """
    if not _available():
        return {"ok": False, "reason": "no database"}
    tier = (tier or "").strip().lower()
    if tier not in {"free", "pro"}:
        return {"ok": False, "reason": "invalid tier"}
    reason = (reason or "").strip()
    if len(reason) < 3:
        return {"ok": False, "reason": "reason required"}
    if tier == "free":
        subscription_until = None
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, email, tier, subscription_until FROM web_users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not row:
            _write_admin_audit(
                conn, actor_user_id=actor_user_id, actor_email=actor_email,
                action="set_subscription", target_type="user", target_id=str(user_id),
                target_label=None, outcome="not_found", request_id=request_id,
                source_ip_hash=source_ip_hash,
            )
            return {"ok": False, "reason": "not found"}
        old = {"tier": row.get("tier") or "free", "subscription_until": row.get("subscription_until")}
        updated = conn.execute(
            """
            UPDATE web_users SET tier = %s, subscription_until = %s
            WHERE id = %s
            RETURNING tier, subscription_until
            """,
            (tier, subscription_until, user_id),
        ).fetchone()
        new = {"tier": updated["tier"], "subscription_until": updated["subscription_until"]}
        _write_admin_audit(
            conn, actor_user_id=actor_user_id, actor_email=actor_email,
            action="set_subscription", target_type="user", target_id=str(user_id),
            target_label=row["email"], outcome="success", request_id=request_id,
            source_ip_hash=source_ip_hash,
            details={
                "reason": reason,
                "before": {**old, "subscription_until": old["subscription_until"].isoformat() if old["subscription_until"] else None},
                "after": {**new, "subscription_until": new["subscription_until"].isoformat() if new["subscription_until"] else None},
            },
        )
    return {
        "ok": True, "user_id": user_id, "tier": new["tier"],
        "subscription_until": new["subscription_until"].isoformat() if new["subscription_until"] else None,
    }
