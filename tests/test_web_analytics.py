"""The pure half of web_analytics: parsing, classification, sanitisation.

The database half is exercised in production behind honest «—» fallbacks; these
tests pin the parts that decide what enters the record at all — a wrong UA
family is a wrong chart, and an unsanitised beacon is stored hostile input.
"""
import web_analytics as wa


# ── bots ────────────────────────────────────────────────────────────────────

def test_empty_ua_is_a_script_not_a_visitor():
    assert wa.is_bot("")


def test_common_bots_are_dropped():
    for ua in (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "python-requests/2.31.0",
        "curl/8.4.0",
        "Mozilla/5.0 (compatible; YandexBot/3.0)",
        "TelegramBot (like TwitterBot)",
    ):
        assert wa.is_bot(ua), ua


def test_real_browsers_are_not_bots():
    for ua in (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ):
        assert not wa.is_bot(ua), ua


# ── UA families ─────────────────────────────────────────────────────────────

def test_windows_chrome_desktop():
    parsed = wa.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    assert parsed == {"os": "Windows", "browser": "Chrome", "device": "desktop"}


def test_iphone_safari_mobile():
    parsed = wa.parse_user_agent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
    assert parsed == {"os": "iOS", "browser": "Safari", "device": "mobile"}


def test_android_phone_is_mobile_android_tablet_is_tablet():
    phone = wa.parse_user_agent(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
    assert phone["device"] == "mobile" and phone["os"] == "Android"
    tablet = wa.parse_user_agent(
        "Mozilla/5.0 (Linux; Android 14; SM-X910) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    assert tablet["device"] == "tablet"


def test_edge_and_yandex_not_reported_as_chrome():
    assert wa.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0")["browser"] == "Edge"
    assert wa.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126.0 YaBrowser/24.6 Safari/537.36")["browser"] == "Yandex"


# ── referrers ───────────────────────────────────────────────────────────────

def test_referrer_host_strips_scheme_www_port_and_path():
    assert wa.referrer_host("https://www.google.com/search?q=uzse") == "google.com"
    assert wa.referrer_host("http://t.me:443/somechannel/42") == "t.me"
    assert wa.referrer_host("") == ""


def test_referrer_classes():
    assert wa.classify_referrer("") == "direct"
    assert wa.classify_referrer("https://www.google.com/search") == "search"
    assert wa.classify_referrer("https://yandex.ru/search/?text=akcii") == "search"
    assert wa.classify_referrer("https://t.me/uzmarkets") == "social"
    assert wa.classify_referrer("https://kun.uz/news/123") == "referral"
    assert wa.classify_referrer("https://example.com/page", own_hosts=("example.com",)) == "internal"


# ── ip hashing ──────────────────────────────────────────────────────────────

def test_ip_hash_is_stable_short_and_never_the_raw_ip():
    a = wa.hash_ip("203.0.113.7")
    assert a == wa.hash_ip("203.0.113.7")
    assert a != wa.hash_ip("203.0.113.8")
    assert len(a) == 16
    assert "203" not in a
    assert wa.hash_ip("") is None


# ── beacon sanitisation ─────────────────────────────────────────────────────

VALID = {
    "vid": "a" * 16, "sid": "b" * 16, "path": "/company/UZTL",
    "view": "company", "ticker": "uztl", "lang": "ru", "w": 1440,
}


def test_valid_payload_passes_and_ticker_uppercased():
    clean = wa.sanitize_payload(dict(VALID))
    assert clean is not None
    assert clean["ticker"] == "UZTL"
    assert clean["event"] == "pageview"
    assert clean["screen_w"] == 1440


def test_missing_or_malformed_ids_reject_the_event():
    assert wa.sanitize_payload({**VALID, "vid": ""}) is None
    assert wa.sanitize_payload({**VALID, "sid": "short"}) is None
    assert wa.sanitize_payload({**VALID, "vid": "has spaces here!"}) is None
    assert wa.sanitize_payload("not a dict") is None


def test_path_must_be_a_site_path():
    assert wa.sanitize_payload({**VALID, "path": "https://evil.example/x"}) is None
    assert wa.sanitize_payload({**VALID, "path": "/" + "a" * 300}) is None


def test_junk_fields_are_dropped_not_fatal():
    clean = wa.sanitize_payload({**VALID, "ticker": "not a ticker!!", "lang": "xx",
                                 "w": "many", "uid": "NaN"})
    assert clean is not None
    assert clean["ticker"] is None
    assert clean["lang"] is None
    assert clean["screen_w"] is None
    assert clean["uid"] is None


def test_unknown_event_name_rejects_but_custom_snake_case_passes():
    assert wa.sanitize_payload({**VALID, "event": "DROP TABLE"}) is None
    clean = wa.sanitize_payload({**VALID, "event": "search_empty"})
    assert clean is not None and clean["event"] == "search_empty"


# ── record path without a database ──────────────────────────────────────────

def test_record_is_a_noop_without_database(monkeypatch):
    monkeypatch.setattr(wa, "DATABASE_URL", "")
    assert wa.record_pageview(dict(VALID), user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/126.0") is False


def test_record_buffers_with_database_configured(monkeypatch):
    monkeypatch.setattr(wa, "DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(wa, "_ensure_flusher", lambda: None)
    wa._buffer.clear()
    ok = wa.record_pageview(dict(VALID),
                            user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/126.0 Safari/537.36",
                            ip="203.0.113.7", country="uz")
    assert ok is True
    assert len(wa._buffer) == 1
    row = wa._buffer.pop()
    # (ts, vid, sid, uid, event, path, view, ticker, referrer, lang, device,
    #  screen_w, browser, os, country, ip_hash)
    assert row[5] == "/company/UZTL"
    assert row[7] == "UZTL"
    assert row[10] == "desktop"
    assert row[14] == "UZ"
    assert row[15] == wa.hash_ip("203.0.113.7")


def test_bot_traffic_never_enters_the_buffer(monkeypatch):
    monkeypatch.setattr(wa, "DATABASE_URL", "postgresql://test")
    wa._buffer.clear()
    assert wa.record_pageview(dict(VALID), user_agent="Googlebot/2.1") is False
    assert not wa._buffer
