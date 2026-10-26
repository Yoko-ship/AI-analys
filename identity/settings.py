"""Settings."""
from __future__ import annotations

from typing import Any
import logging
import os


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


SESSION_TTL_DAYS = int(os.getenv("WEB_SESSION_TTL_DAYS", "30"))


PBKDF2_ITERATIONS = int(os.getenv("WEB_PASSWORD_ITERATIONS", "600000"))


LOGIN_FAILURE_LIMIT = 10


LOGIN_FAILURE_WINDOW_MINUTES = 15


LOGIN_LOCK_MINUTES = 15


# How fresh a session must be to stand in for a password when a Google-linked
# account (which never chose one) deletes itself: signing in again with Google
# is the proof (identity/profile.py, delete_account).
RECENT_SIGN_IN_MINUTES = 10


OAUTH_FALLBACK_DOMAIN = os.getenv("WEB_OAUTH_FALLBACK_DOMAIN", "oauth.local").strip() or "oauth.local"


DEFAULT_PROFILE_PREFERENCES: dict[str, Any] = {
    "terminal_layout": [],
    "investment_interests": [],
    "saved_screeners": [],
    "language": "ru",
    "theme": "dark",
    "text_scale": 100,
    "timezone": "Asia/Tashkent",
    "default_report_language": "ru",
    "default_analysis_period": "latest",
    "notify_reports": True,
    "notify_news": True,
    "notify_price": True,
    "notify_analysis": True,
    # Chart patterns completed on a watchlist company's last sessions. The type
    # list is what the reader chose; empty means every chart figure (candle
    # models are opt-in — they fire most days on a liquid share).
    "notify_patterns": True,
    "pattern_alert_types": [],
}


EMAIL_CODE_TTL_MINUTES = 15


EMAIL_CODE_MAX_ATTEMPTS = 5


EMAIL_CODE_RESEND_SECONDS = 60


EMAIL_CODE_MAX_SENDS_PER_HOUR = 5


EMAIL_CODE_PURPOSES = ("verify", "reset")
