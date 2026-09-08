from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from psycopg import connect
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SESSION_TTL_DAYS = int(os.getenv("WEB_SESSION_TTL_DAYS", "30"))
PBKDF2_ITERATIONS = int(os.getenv("WEB_PASSWORD_ITERATIONS", "210000"))
OAUTH_FALLBACK_DOMAIN = os.getenv("WEB_OAUTH_FALLBACK_DOMAIN", "oauth.local").strip() or "oauth.local"

DEFAULT_PROFILE_PREFERENCES: dict[str, Any] = {
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
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _admin_emails() -> set[str]:
    """Allowlist of admin emails (env ADMIN_EMAILS, comma-separated, case-insensitive)."""
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin_email(email: str | None) -> bool:
    """True if this email is an allowlisted admin. Empty allowlist => nobody is admin."""
    return bool(email) and _normalize_email(email) in _admin_emails()


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _password_verify(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_str, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _totp_code(secret: str, at: datetime | None = None) -> str:
    """Return the RFC 6238 six-digit code for a base32 secret."""
    moment = at or _utcnow()
    counter = int(moment.timestamp()) // 30
    padded = (secret or "").strip().upper()
    padded += "=" * ((8 - len(padded) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _verify_totp(secret: str | None, code: str | None, at: datetime | None = None) -> bool:
    candidate = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not secret or len(candidate) != 6:
        return False
    moment = at or _utcnow()
    return any(
        hmac.compare_digest(_totp_code(secret, moment + timedelta(seconds=step * 30)), candidate)
        for step in (-1, 0, 1)
    )


@dataclass
class WebUser:
    id: int
    email: str
    full_name: str
    avatar_data_url: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    is_active: bool
    email_verified: bool = False
    tier: str = "free"
    subscription_until: Optional[datetime] = None

    @property
    def has_pro_access(self) -> bool:
        """Whether this signed-in account may open paid analytical features.

        The allowlisted platform administrator is deliberately treated as PRO
        too: an administrator must be able to verify a closed feature without
        granting their own account a consumer subscription.  A ``NULL`` end
        date is a deliberately provisioned non-expiring entitlement; normal
        grants use an explicit end date.
        """
        if is_admin_email(self.email):
            return True
        if self.tier != "pro":
            return False
        return self.subscription_until is None or self.subscription_until > _utcnow()

    def to_public_dict(self) -> dict:
        from admin_control.service import role_for
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "avatar_data_url": self.avatar_data_url,
            "created_at": self.created_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_active": self.is_active,
            "email_verified": self.email_verified,
            "tier": self.tier,
            "subscription_until": self.subscription_until.isoformat() if self.subscription_until else None,
            "pro_access": self.has_pro_access,
            "is_admin": is_admin_email(self.email),
            "admin_role": role_for(self.email),
        }


class WebAuthStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = (database_url or DATABASE_URL).strip()
        if self.database_url:
            self._init_db()
        else:
            logger.warning("DATABASE_URL is not configured; web auth is disabled")

    def _ensure_ready(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for website authentication")

    def _conn(self):
        self._ensure_ready()
        conn = connect(self.database_url)
        conn.row_factory = dict_row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_users (
                    id              BIGSERIAL PRIMARY KEY,
                    email           TEXT NOT NULL UNIQUE,
                    full_name       TEXT NOT NULL DEFAULT '',
                    avatar_data_url TEXT,
                    password_hash   TEXT NOT NULL,
                    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                    tier            TEXT NOT NULL DEFAULT 'free',
                    subscription_until TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_login_at   TIMESTAMPTZ
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE web_users
                ADD COLUMN IF NOT EXISTS avatar_data_url TEXT
                """
            )
            for statement in (
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS two_factor_secret TEXT",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'free'",
                "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS subscription_until TIMESTAMPTZ",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_sessions (
                    id           BIGSERIAL PRIMARY KEY,
                    user_id      BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    token_hash   TEXT NOT NULL UNIQUE,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at   TIMESTAMPTZ NOT NULL,
                    revoked_at   TIMESTAMPTZ
                )
                """
            )
            for statement in (
                "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS user_agent TEXT",
                "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS ip_address TEXT",
                "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_oauth_accounts (
                    id                  BIGSERIAL PRIMARY KEY,
                    user_id             BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    provider            TEXT NOT NULL,
                    provider_user_id    TEXT NOT NULL,
                    provider_email      TEXT,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(provider, provider_user_id),
                    UNIQUE(user_id, provider)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_analysis_history (
                    id              BIGSERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    company_input   TEXT NOT NULL,
                    company_name    TEXT,
                    ticker          TEXT,
                    score           NUMERIC,
                    grade           TEXT,
                    verdict         TEXT,
                    summary_text    TEXT,
                    from_cache      BOOLEAN NOT NULL DEFAULT FALSE,
                    model           TEXT,
                    cost            NUMERIC,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for statement in (
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS title TEXT",
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS bookmarked BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS folder TEXT",
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS pinned_note TEXT",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_favorite_companies (
                    id              BIGSERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    ticker          TEXT NOT NULL,
                    company_name    TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, ticker)
                )
                """
            )
            for statement in (
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_above NUMERIC",
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_below NUMERIC",
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS news_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE",
                "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS report_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            ):
                conn.execute(statement)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_saved_notes (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    analysis_id BIGINT REFERENCES web_analysis_history(id) ON DELETE SET NULL,
                    title       TEXT NOT NULL DEFAULT '',
                    body        TEXT NOT NULL DEFAULT '',
                    pinned      BOOLEAN NOT NULL DEFAULT FALSE,
                    tags        JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_notification_state (
                    user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    notification_id TEXT NOT NULL,
                    read_at         TIMESTAMPTZ,
                    dismissed_at    TIMESTAMPTZ,
                    PRIMARY KEY (user_id, notification_id)
                )
                """
            )
            # A portfolio is deliberately separate from a watchlist.  A saved
            # ticker is a research preference; a position has quantities and a
            # user-entered cost basis, so conflating the two would manufacture
            # holdings for every favourite.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_portfolio_positions (
                    id              BIGSERIAL PRIMARY KEY,
                    user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    ticker          TEXT NOT NULL,
                    quantity        NUMERIC NOT NULL CHECK (quantity > 0),
                    average_cost    NUMERIC NOT NULL CHECK (average_cost >= 0),
                    currency        TEXT NOT NULL DEFAULT 'UZS',
                    note            TEXT NOT NULL DEFAULT '',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, ticker)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_support_requests (
                    id         BIGSERIAL PRIMARY KEY,
                    user_id    BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                    subject    TEXT NOT NULL,
                    message    TEXT NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_sessions_user_id
                ON web_sessions(user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_sessions_expires_at
                ON web_sessions(expires_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_oauth_accounts_user_id
                ON web_oauth_accounts(user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_analysis_history_user_created_at
                ON web_analysis_history(user_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_analysis_history_user_company
                ON web_analysis_history(user_id, company_input)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_favorites_user_created_at
                ON web_favorite_companies(user_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_favorites_user_ticker
                ON web_favorite_companies(user_id, ticker)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_saved_notes_user_updated
                ON web_saved_notes(user_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_portfolio_positions_user_updated
                ON web_portfolio_positions(user_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_support_user_created
                ON web_support_requests(user_id, created_at DESC)
                """
            )

    def _row_to_user(self, row) -> WebUser:
        return WebUser(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            avatar_data_url=row.get("avatar_data_url"),
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            is_active=bool(row["is_active"]),
            email_verified=bool(row.get("email_verified", False)),
            tier=str(row.get("tier") or "free").lower(),
            subscription_until=row.get("subscription_until"),
        )

    def _normalize_avatar_data_url(self, avatar_data_url: str | None) -> str | None:
        if avatar_data_url is None:
            return None
        value = str(avatar_data_url).strip()
        if not value:
            return None
        if len(value) > 750_000:
            raise ValueError("Avatar image is too large")
        if not value.startswith("data:image/"):
            raise ValueError("Avatar must be a data URL")
        return value

    def _issue_session(
        self,
        conn,
        user_id: int,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = _token_hash(token)
        expires_at = _utcnow() + timedelta(days=SESSION_TTL_DAYS)
        conn.execute(
            """
            INSERT INTO web_sessions (user_id, token_hash, expires_at, user_agent, ip_address, last_seen_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                token_hash,
                expires_at,
                (user_agent or "")[:500] or None,
                (ip_address or "")[:120] or None,
                _utcnow(),
            ),
        )
        return token

    def _make_fallback_email(self, provider: str, provider_user_id: str) -> str:
        provider_safe = "".join(ch if ch.isalnum() else "-" for ch in provider.lower()).strip("-")
        provider_safe = provider_safe or "oauth"
        return f"{provider_safe}-{provider_user_id}@{OAUTH_FALLBACK_DOMAIN}"

    def _create_user(
        self,
        conn,
        email: str,
        full_name: str,
        password_hash: str | None = None,
    ):
        now = _utcnow()
        row = conn.execute(
            """
            INSERT INTO web_users (email, full_name, avatar_data_url, password_hash, created_at, last_login_at, is_active)
            VALUES (%s, %s, NULL, %s, %s, NULL, TRUE)
            RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
            """,
            (
                _normalize_email(email),
                full_name or "",
                password_hash or _password_hash(secrets.token_urlsafe(32)),
                now,
            ),
        ).fetchone()
        return row

    def _link_oauth_account(
        self,
        conn,
        user_id: int,
        provider: str,
        provider_user_id: str,
        provider_email: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO web_oauth_accounts (user_id, provider, provider_user_id, provider_email)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (provider, provider_user_id)
            DO UPDATE SET user_id = EXCLUDED.user_id,
                          provider_email = EXCLUDED.provider_email
            """,
            (user_id, provider, provider_user_id, provider_email),
        )

    def get_user_by_oauth(self, provider: str, provider_user_id: str) -> WebUser | None:
        if not provider or not provider_user_id:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at, u.last_login_at, u.is_active, u.email_verified, u.tier, u.subscription_until
                FROM web_oauth_accounts a
                JOIN web_users u ON u.id = a.user_id
                WHERE a.provider = %s
                  AND a.provider_user_id = %s
                  AND u.is_active = TRUE
                """,
                (provider, provider_user_id),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def oauth_login(
        self,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
        full_name: str = "",
    ) -> tuple[WebUser, str]:
        provider = (provider or "").strip().lower()
        provider_user_id = (provider_user_id or "").strip()
        if not provider or not provider_user_id:
            raise ValueError("OAuth account details are incomplete")

        normalized_email = _normalize_email(email or "")
        if not normalized_email:
            normalized_email = self._make_fallback_email(provider, provider_user_id)
        full_name = (full_name or "").strip()

        now = _utcnow()
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at, u.last_login_at, u.is_active, u.email_verified, u.tier, u.subscription_until
                FROM web_oauth_accounts a
                JOIN web_users u ON u.id = a.user_id
                WHERE a.provider = %s
                  AND a.provider_user_id = %s
                  AND u.is_active = TRUE
                """,
                (provider, provider_user_id),
            ).fetchone()
            if existing:
                token = self._issue_session(conn, existing["id"])
                verified_by_provider = bool(email and provider in {"google"})
                conn.execute(
                    "UPDATE web_users SET last_login_at = %s, email_verified = email_verified OR %s WHERE id = %s",
                    (now, verified_by_provider, existing["id"]),
                )
                existing = dict(existing)
                existing["last_login_at"] = now
                existing["email_verified"] = bool(existing.get("email_verified")) or verified_by_provider
                return self._row_to_user(existing), token

            row = conn.execute(
                "SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until FROM web_users WHERE email = %s",
                (normalized_email,),
            ).fetchone()

            if row:
                user_id = row["id"]
                if full_name and not (row["full_name"] or "").strip():
                    conn.execute(
                        "UPDATE web_users SET full_name = %s WHERE id = %s",
                        (full_name, user_id),
                    )
            else:
                created = self._create_user(conn, normalized_email, full_name)
                user_id = created["id"]
                row = created

            self._link_oauth_account(conn, user_id, provider, provider_user_id, email)
            if email and provider in {"google"}:
                conn.execute("UPDATE web_users SET email_verified = TRUE WHERE id = %s", (user_id,))
            token = self._issue_session(conn, user_id)
            conn.execute(
                "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                (now, user_id),
            )

        public_row = {
            "id": row["id"] if row else user_id,
            "email": row["email"] if row else normalized_email,
            "full_name": full_name or (row["full_name"] if row else ""),
            "avatar_data_url": row["avatar_data_url"] if row else None,
            "created_at": row["created_at"] if row else now,
            "last_login_at": now,
            "is_active": True,
            "email_verified": bool(email and provider in {"google"}) or bool(row.get("email_verified") if row else False),
            "tier": row.get("tier") if row else "free",
            "subscription_until": row.get("subscription_until") if row else None,
        }
        return self._row_to_user(public_row), token

    def get_user_by_email(self, email: str) -> WebUser | None:
        normalized = _normalize_email(email)
        if not normalized:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                FROM web_users
                WHERE email = %s
                """,
                (normalized,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_token(self, token: str) -> WebUser | None:
        if not token:
            return None
        token_hash = _token_hash(token)
        now = _utcnow()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at,
                       u.last_login_at, u.is_active, u.email_verified, u.tier, u.subscription_until
                FROM web_sessions s
                JOIN web_users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > %s
                  AND u.is_active = TRUE
                """,
                (token_hash, now),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE web_sessions SET last_seen_at = %s WHERE token_hash = %s",
                    (now, token_hash),
                )
        return self._row_to_user(row) if row else None

    def register_user(
        self,
        email: str,
        password: str,
        full_name: str = "",
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[WebUser, str]:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters long")

        full_name = (full_name or "").strip()
        password_encoded = _password_hash(password)
        now = _utcnow()

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM web_users WHERE email = %s",
                (normalized,),
            ).fetchone()
            if existing:
                raise ValueError("Email already registered")

            row = conn.execute(
                """
            INSERT INTO web_users (email, full_name, avatar_data_url, password_hash, created_at, last_login_at, is_active)
            VALUES (%s, %s, NULL, %s, %s, NULL, TRUE)
            RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                """,
                (normalized, full_name, password_encoded, now),
            ).fetchone()

            token = self._issue_session(conn, row["id"], user_agent, ip_address)
            conn.execute(
                "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                (now, row["id"]),
            )

        public_row = {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "avatar_data_url": row["avatar_data_url"],
            "created_at": row["created_at"],
            "last_login_at": now,
            "is_active": row["is_active"],
            "email_verified": bool(row.get("email_verified")),
            "tier": row.get("tier"),
            "subscription_until": row.get("subscription_until"),
        }
        return self._row_to_user(public_row), token

    def login_user(
        self,
        email: str,
        password: str,
        otp: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[WebUser, str]:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, password_hash, created_at,
                       last_login_at, is_active, email_verified, tier, subscription_until,
                       two_factor_enabled, two_factor_secret
                FROM web_users
                WHERE email = %s
                """,
                (normalized,),
            ).fetchone()

            if not row or not row["is_active"]:
                raise ValueError("Invalid email or password")
            if not _password_verify(password, row["password_hash"]):
                raise ValueError("Invalid email or password")
            if row.get("two_factor_enabled"):
                if not otp:
                    raise ValueError("Two-factor code required")
                if not _verify_totp(row.get("two_factor_secret"), otp):
                    raise ValueError("Invalid two-factor code")

            token = self._issue_session(conn, row["id"], user_agent, ip_address)
            conn.execute(
                "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                (_utcnow(), row["id"]),
            )

        public_row = {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "avatar_data_url": row.get("avatar_data_url"),
            "created_at": row["created_at"],
            "last_login_at": _utcnow(),
            "is_active": row["is_active"],
            "email_verified": row.get("email_verified", False),
            "tier": row.get("tier"),
            "subscription_until": row.get("subscription_until"),
        }
        return self._row_to_user(public_row), token

    def update_profile(
        self,
        user_id: int,
        full_name: str | None = None,
        avatar_data_url: str | None = None,
        *,
        set_full_name: bool = False,
        set_avatar: bool = False,
    ) -> WebUser:
        updates: list[str] = []
        params: list[Any] = []

        if set_full_name:
            normalized_name = (full_name or "").strip()
            if not normalized_name:
                raise ValueError("Full name cannot be empty")
            updates.append("full_name = %s")
            params.append(normalized_name)

        if set_avatar:
            normalized_avatar = self._normalize_avatar_data_url(avatar_data_url)
            updates.append("avatar_data_url = %s")
            params.append(normalized_avatar)

        if not updates:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                    FROM web_users
                    WHERE id = %s
                    """,
                    (user_id,),
                ).fetchone()
            if not row:
                raise ValueError("User not found")
            return self._row_to_user(row)

        params.append(user_id)
        with self._conn() as conn:
            row = conn.execute(
                f"""
                UPDATE web_users
                SET {", ".join(updates)}
                WHERE id = %s
                RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                """,
                params,
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return self._row_to_user(row)

    def list_favorites(self, user_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT ticker, company_name, created_at, position,
                       price_alert_enabled, price_alert_above, price_alert_below,
                       news_alert_enabled, report_alert_enabled
                FROM web_favorite_companies
                WHERE user_id = %s
                ORDER BY position ASC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "position": int(row.get("position") or 0),
                "price_alert_enabled": bool(row.get("price_alert_enabled")),
                "price_alert_above": float(row["price_alert_above"]) if row.get("price_alert_above") is not None else None,
                "price_alert_below": float(row["price_alert_below"]) if row.get("price_alert_below") is not None else None,
                "news_alert_enabled": bool(row.get("news_alert_enabled", True)),
                "report_alert_enabled": bool(row.get("report_alert_enabled", True)),
            }
            for row in rows
        ]

    def toggle_favorite(self, user_id: int, ticker: str, company_name: str | None = None) -> dict[str, Any]:
        ticker_value = (ticker or "").strip().upper()
        if not ticker_value:
            raise ValueError("Ticker is required")
        company_value = (company_name or "").strip() or None

        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM web_favorite_companies
                WHERE user_id = %s AND ticker = %s
                """,
                (user_id, ticker_value),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    DELETE FROM web_favorite_companies
                    WHERE user_id = %s AND ticker = %s
                    """,
                    (user_id, ticker_value),
                )
                return {"favorited": False, "ticker": ticker_value, "company_name": company_value}

            conn.execute(
                """
                INSERT INTO web_favorite_companies (user_id, ticker, company_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, ticker)
                DO UPDATE SET company_name = COALESCE(EXCLUDED.company_name, web_favorite_companies.company_name)
                """,
                (user_id, ticker_value, company_value),
            )
        return {"favorited": True, "ticker": ticker_value, "company_name": company_value}

    def revoke_token(self, token: str) -> bool:
        token_hash = _token_hash(token)
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE token_hash = %s AND revoked_at IS NULL
                """,
                (_utcnow(), token_hash),
            )
        return cursor.rowcount > 0

    def list_sessions(self, user_id: int, current_token: str | None = None) -> list[dict[str, Any]]:
        current_hash = _token_hash(current_token) if current_token else ""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, token_hash, created_at, expires_at, revoked_at,
                       user_agent, ip_address, last_seen_at
                FROM web_sessions
                WHERE user_id = %s AND revoked_at IS NULL AND expires_at > %s
                ORDER BY COALESCE(last_seen_at, created_at) DESC
                """,
                (user_id, _utcnow()),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "current": bool(current_hash and hmac.compare_digest(row["token_hash"], current_hash)),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                "last_seen_at": (row["last_seen_at"] or row["created_at"]).isoformat() if (row["last_seen_at"] or row["created_at"]) else None,
                "user_agent": row.get("user_agent"),
                "ip_address": row.get("ip_address"),
            }
            for row in rows
        ]

    def revoke_session(self, user_id: int, session_id: int, current_token: str | None = None) -> bool:
        current_hash = _token_hash(current_token) if current_token else ""
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                  AND (%s = '' OR token_hash <> %s)
                """,
                (_utcnow(), session_id, user_id, current_hash, current_hash),
            )
        return cursor.rowcount > 0

    def revoke_other_sessions(self, user_id: int, current_token: str) -> int:
        current_hash = _token_hash(current_token)
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE user_id = %s AND token_hash <> %s AND revoked_at IS NULL
                """,
                (_utcnow(), user_id, current_hash),
            )
        return int(cursor.rowcount or 0)

    def change_password(self, user_id: int, current_password: str, new_password: str, current_token: str) -> int:
        if len(new_password or "") < 8:
            raise ValueError("Password must be at least 8 characters long")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM web_users WHERE id = %s AND is_active = TRUE",
                (user_id,),
            ).fetchone()
            if not row or not _password_verify(current_password or "", row["password_hash"]):
                raise ValueError("Current password is incorrect")
            conn.execute(
                "UPDATE web_users SET password_hash = %s, password_changed_at = %s WHERE id = %s",
                (_password_hash(new_password), _utcnow(), user_id),
            )
            current_hash = _token_hash(current_token)
            cursor = conn.execute(
                """
                UPDATE web_sessions SET revoked_at = %s
                WHERE user_id = %s AND token_hash <> %s AND revoked_at IS NULL
                """,
                (_utcnow(), user_id, current_hash),
            )
        return int(cursor.rowcount or 0)

    def begin_two_factor(self, user_id: int) -> dict[str, str]:
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        with self._conn() as conn:
            row = conn.execute("SELECT email FROM web_users WHERE id = %s", (user_id,)).fetchone()
            if not row:
                raise ValueError("User not found")
            conn.execute(
                "UPDATE web_users SET two_factor_secret = %s, two_factor_enabled = FALSE WHERE id = %s",
                (secret, user_id),
            )
        label = row["email"].replace(" ", "%20")
        uri = f"otpauth://totp/UZ%20Stock%20Analyzer:{label}?secret={secret}&issuer=UZ%20Stock%20Analyzer"
        return {"secret": secret, "otpauth_uri": uri}

    def verify_admin_two_factor(self, user_id: int, code: str) -> bool:
        """Step-up verification without disclosing or changing the MFA secret."""
        if not re.fullmatch(r"\d{6}", str(code or "")):
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT two_factor_enabled,two_factor_secret FROM web_users WHERE id=%s", (user_id,)).fetchone()
        return bool(row and row.get("two_factor_enabled") and _verify_totp(row.get("two_factor_secret"), code))

    def enable_two_factor(self, user_id: int, code: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT two_factor_secret FROM web_users WHERE id = %s", (user_id,)).fetchone()
            if not row or not _verify_totp(row.get("two_factor_secret"), code):
                raise ValueError("Invalid two-factor code")
            conn.execute("UPDATE web_users SET two_factor_enabled = TRUE WHERE id = %s", (user_id,))
        return True

    def disable_two_factor(self, user_id: int, code: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT two_factor_enabled, two_factor_secret FROM web_users WHERE id = %s",
                (user_id,),
            ).fetchone()
            if not row:
                raise ValueError("User not found")
            if row.get("two_factor_enabled") and not _verify_totp(row.get("two_factor_secret"), code):
                raise ValueError("Invalid two-factor code")
            conn.execute(
                "UPDATE web_users SET two_factor_enabled = FALSE, two_factor_secret = NULL WHERE id = %s",
                (user_id,),
            )
        return True

    def update_preferences(self, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_PROFILE_PREFERENCES)
        clean = {key: value for key, value in (updates or {}).items() if key in allowed and value is not None}
        if clean.get("language") not in (None, "ru", "en", "uz"):
            raise ValueError("Unsupported language")
        if clean.get("theme") not in (None, "light", "dark"):
            raise ValueError("Unsupported theme")
        if "text_scale" in clean:
            clean["text_scale"] = max(80, min(130, int(clean["text_scale"])))
        if "timezone" in clean:
            clean["timezone"] = str(clean["timezone"]).strip()[:80] or "Asia/Tashkent"
        if "default_analysis_period" in clean and clean["default_analysis_period"] not in ("latest", "quarterly", "annual"):
            raise ValueError("Unsupported analysis period")
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE web_users
                SET preferences = COALESCE(preferences, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                RETURNING preferences
                """,
                (json.dumps(clean), user_id),
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return {**DEFAULT_PROFILE_PREFERENCES, **dict(row.get("preferences") or {})}

    def get_preferences(self, user_id: int) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT preferences FROM web_users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise ValueError("User not found")
        return {**DEFAULT_PROFILE_PREFERENCES, **dict(row.get("preferences") or {})}

    @staticmethod
    def _analysis_row(row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "company_input": row["company_input"],
            "company_name": row.get("company_name"),
            "ticker": row.get("ticker"),
            "title": row.get("title"),
            "score": float(row["score"]) if row.get("score") is not None else None,
            "grade": row.get("grade"),
            "verdict": row.get("verdict"),
            "summary_text": row.get("summary_text"),
            "from_cache": bool(row.get("from_cache")),
            "model": row.get("model"),
            "cost": float(row["cost"]) if row.get("cost") is not None else None,
            "archived": bool(row.get("archived")),
            "bookmarked": bool(row.get("bookmarked")),
            "folder": row.get("folder"),
            "tags": list(row.get("tags") or []),
            "pinned_note": row.get("pinned_note"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }

    def get_analysis(self, user_id: int, analysis_id: int) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM web_analysis_history WHERE id = %s AND user_id = %s",
                (analysis_id, user_id),
            ).fetchone()
        if not row:
            raise ValueError("Analysis not found")
        return self._analysis_row(row)

    def update_analysis(self, user_id: int, analysis_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "archived", "bookmarked", "folder", "tags", "pinned_note"}
        parts: list[str] = []
        params: list[Any] = []
        for key, value in (updates or {}).items():
            if key not in allowed:
                continue
            if key == "tags":
                tags = [str(tag).strip()[:40] for tag in (value or []) if str(tag).strip()][:12]
                parts.append("tags = %s::jsonb")
                params.append(json.dumps(tags))
            elif key in {"title", "folder", "pinned_note"}:
                limit = 160 if key != "pinned_note" else 4000
                parts.append(f"{key} = %s")
                params.append(str(value or "").strip()[:limit] or None)
            else:
                parts.append(f"{key} = %s")
                params.append(bool(value))
        if not parts:
            return self.get_analysis(user_id, analysis_id)
        params.extend([analysis_id, user_id])
        with self._conn() as conn:
            row = conn.execute(
                f"UPDATE web_analysis_history SET {', '.join(parts)} WHERE id = %s AND user_id = %s RETURNING *",
                params,
            ).fetchone()
        if not row:
            raise ValueError("Analysis not found")
        return self._analysis_row(row)

    def delete_analysis(self, user_id: int, analysis_id: int) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM web_analysis_history WHERE id = %s AND user_id = %s",
                (analysis_id, user_id),
            )
        return cursor.rowcount > 0

    def clear_analysis_history(self, user_id: int) -> int:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM web_analysis_history WHERE user_id = %s", (user_id,))
        return int(cursor.rowcount or 0)

    def list_notes(self, user_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, analysis_id, title, body, pinned, tags, created_at, updated_at
                FROM web_saved_notes WHERE user_id = %s
                ORDER BY pinned DESC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [{
            "id": int(row["id"]),
            "analysis_id": int(row["analysis_id"]) if row.get("analysis_id") else None,
            "title": row["title"],
            "body": row["body"],
            "pinned": bool(row["pinned"]),
            "tags": list(row.get("tags") or []),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        } for row in rows]

    def save_note(self, user_id: int, note_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()[:160]
        body = str(payload.get("body") or "").strip()[:8000]
        if not title and not body:
            raise ValueError("Note cannot be empty")
        tags = [str(tag).strip()[:40] for tag in (payload.get("tags") or []) if str(tag).strip()][:12]
        analysis_id = payload.get("analysis_id")
        with self._conn() as conn:
            if analysis_id:
                linked = conn.execute(
                    "SELECT id FROM web_analysis_history WHERE id = %s AND user_id = %s",
                    (analysis_id, user_id),
                ).fetchone()
                if not linked:
                    raise ValueError("Analysis not found")
            if note_id:
                row = conn.execute(
                    """
                    UPDATE web_saved_notes
                    SET analysis_id = %s, title = %s, body = %s, pinned = %s,
                        tags = %s::jsonb, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    RETURNING id
                    """,
                    (analysis_id, title, body, bool(payload.get("pinned")), json.dumps(tags), _utcnow(), note_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    INSERT INTO web_saved_notes (user_id, analysis_id, title, body, pinned, tags)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id
                    """,
                    (user_id, analysis_id, title, body, bool(payload.get("pinned")), json.dumps(tags)),
                ).fetchone()
        if not row:
            raise ValueError("Note not found")
        return next(note for note in self.list_notes(user_id) if note["id"] == int(row["id"]))

    def delete_note(self, user_id: int, note_id: int) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM web_saved_notes WHERE id = %s AND user_id = %s", (note_id, user_id))
        return cursor.rowcount > 0

    def create_support_request(self, user_id: int, subject: str, message: str) -> dict[str, Any]:
        clean_subject = str(subject or "").strip()[:160]
        clean_message = str(message or "").strip()[:6000]
        if not clean_subject or not clean_message:
            raise ValueError("Subject and message are required")
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO web_support_requests (user_id, subject, message)
                VALUES (%s, %s, %s)
                RETURNING id, status, created_at
                """,
                (user_id, clean_subject, clean_message),
            ).fetchone()
        return {
            "id": int(row["id"]),
            "subject": clean_subject,
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }

    def update_favorite(self, user_id: int, ticker: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "position", "price_alert_enabled", "price_alert_above", "price_alert_below",
            "news_alert_enabled", "report_alert_enabled",
        }
        parts: list[str] = []
        params: list[Any] = []
        for key, value in (updates or {}).items():
            if key not in allowed:
                continue
            parts.append(f"{key} = %s")
            if key == "position":
                params.append(max(0, int(value or 0)))
            elif key in {"price_alert_above", "price_alert_below"}:
                params.append(float(value) if value not in (None, "") else None)
            else:
                params.append(bool(value))
        if not parts:
            raise ValueError("No favorite settings supplied")
        params.extend([(ticker or "").strip().upper(), user_id])
        with self._conn() as conn:
            row = conn.execute(
                f"UPDATE web_favorite_companies SET {', '.join(parts)} WHERE ticker = %s AND user_id = %s RETURNING ticker",
                params,
            ).fetchone()
        if not row:
            raise ValueError("Favorite not found")
        return next(item for item in self.list_favorites(user_id) if item["ticker"] == row["ticker"])

    def list_portfolio_positions(self, user_id: int) -> list[dict[str, Any]]:
        """Return only explicit holdings, newest edit first.

        Price, valuation and P/L are calculated by the API from the reconciled
        market board.  This storage layer owns just the user's declarations.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT ticker, quantity, average_cost, currency, note, created_at, updated_at
                FROM web_portfolio_positions
                WHERE user_id = %s
                ORDER BY updated_at DESC, ticker ASC
                """,
                (user_id,),
            ).fetchall()
        return [{
            "ticker": row["ticker"],
            "quantity": float(row["quantity"]),
            "average_cost": float(row["average_cost"]),
            "currency": row["currency"],
            "note": row["note"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        } for row in rows]

    def upsert_portfolio_position(self, user_id: int, ticker: str, *, quantity: float,
                                  average_cost: float, currency: str = "UZS",
                                  note: str = "") -> dict[str, Any]:
        ticker = str(ticker or "").strip().upper()
        if not ticker:
            raise ValueError("Ticker is required")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero")
        if average_cost < 0:
            raise ValueError("Average cost cannot be negative")
        currency = str(currency or "UZS").strip().upper()
        if currency != "UZS":
            raise ValueError("Only UZS cost basis is currently supported")
        note = str(note or "").strip()[:1000]
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO web_portfolio_positions
                    (user_id, ticker, quantity, average_cost, currency, note, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, ticker) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    average_cost = EXCLUDED.average_cost,
                    currency = EXCLUDED.currency,
                    note = EXCLUDED.note,
                    updated_at = NOW()
                RETURNING ticker, quantity, average_cost, currency, note, created_at, updated_at
                """,
                (user_id, ticker, quantity, average_cost, currency, note),
            ).fetchone()
        return {
            "ticker": row["ticker"], "quantity": float(row["quantity"]),
            "average_cost": float(row["average_cost"]), "currency": row["currency"],
            "note": row["note"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }

    def delete_portfolio_position(self, user_id: int, ticker: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM web_portfolio_positions WHERE user_id = %s AND ticker = %s",
                (user_id, str(ticker or "").strip().upper()),
            )
        return cursor.rowcount > 0

    def notification_states(self, user_id: int) -> dict[str, dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT notification_id, read_at, dismissed_at FROM web_notification_state WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        return {
            row["notification_id"]: {
                "read": bool(row["read_at"]),
                "dismissed": bool(row["dismissed_at"]),
            }
            for row in rows
        }

    def set_notification_state(self, user_id: int, notification_ids: list[str], *, dismissed: bool = False) -> int:
        ids = [str(value).strip()[:160] for value in notification_ids if str(value).strip()][:200]
        if not ids:
            return 0
        now = _utcnow()
        with self._conn() as conn:
            for notification_id in ids:
                conn.execute(
                    """
                    INSERT INTO web_notification_state (user_id, notification_id, read_at, dismissed_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, notification_id)
                    DO UPDATE SET read_at = COALESCE(web_notification_state.read_at, EXCLUDED.read_at),
                                  dismissed_at = COALESCE(EXCLUDED.dismissed_at, web_notification_state.dismissed_at)
                    """,
                    (user_id, notification_id, now, now if dismissed else None),
                )
        return len(ids)

    def export_user_data(self, user_id: int, current_token: str | None = None) -> dict[str, Any]:
        profile = self.get_profile(user_id, recent_limit=100)
        return {
            "exported_at": _utcnow().isoformat(),
            **profile,
            "sessions": self.list_sessions(user_id, current_token),
            "notes": self.list_notes(user_id),
        }

    def delete_account(self, user_id: int, confirmation: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT email FROM web_users WHERE id = %s", (user_id,)).fetchone()
            if not row:
                raise ValueError("User not found")
            if (confirmation or "").strip().lower() != str(row["email"]).strip().lower():
                raise ValueError("Enter your email address to confirm account deletion")
            cursor = conn.execute("DELETE FROM web_users WHERE id = %s", (user_id,))
        return cursor.rowcount > 0

    def record_analysis(self, user_id: int, payload: dict[str, Any], result: dict[str, Any]) -> None:
        company_input = (payload.get("company") or "").strip()
        summary = result.get("summary") or {}
        metrics = result.get("metrics") or {}
        total_score = metrics.get("total_score") or {}
        score = summary.get("score", total_score.get("score"))
        grade = summary.get("grade", total_score.get("grade"))
        verdict = summary.get("verdict") or summary.get("itog") or ""
        summary_text = summary.get("itog") or summary.get("score_summary") or verdict or ""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO web_analysis_history (
                    user_id,
                    company_input,
                    company_name,
                    ticker,
                    score,
                    grade,
                    verdict,
                    summary_text,
                    from_cache,
                    model,
                    cost,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    company_input,
                    result.get("company_name"),
                    result.get("ticker"),
                    score,
                    grade,
                    verdict,
                    summary_text,
                    bool(result.get("from_cache", False)),
                    result.get("model"),
                    result.get("cost"),
                    _utcnow(),
                ),
            )

    def get_profile(self, user_id: int, recent_limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(recent_limit or 50), 100))
        with self._conn() as conn:
            user_row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at,
                       is_active, email_verified, tier, subscription_until, preferences, two_factor_enabled,
                       password_changed_at
                FROM web_users
                WHERE id = %s
                """,
                (user_id,),
            ).fetchone()
            if not user_row:
                raise ValueError("User not found")

            stats_row = conn.execute(
                """
                SELECT
                    COUNT(*)::BIGINT AS total_analyses,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::BIGINT AS analyses_7d,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')::BIGINT AS analyses_30d,
                    COUNT(*) FILTER (WHERE from_cache)::BIGINT AS cached_analyses,
                    COUNT(DISTINCT ticker) FILTER (WHERE ticker IS NOT NULL AND ticker <> '')::BIGINT AS analyzed_companies,
                    AVG(score)::NUMERIC(10, 2) AS avg_score,
                    MAX(score)::NUMERIC(10, 2) AS best_score,
                    MIN(created_at) AS first_analysis_at,
                    MAX(created_at) AS last_analysis_at
                FROM web_analysis_history
                WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()

            favorites_rows = conn.execute(
                """
                SELECT ticker, company_name, created_at, position,
                       price_alert_enabled, price_alert_above, price_alert_below,
                       news_alert_enabled, report_alert_enabled
                FROM web_favorite_companies
                WHERE user_id = %s
                ORDER BY position ASC, created_at DESC
                """,
                (user_id,),
            ).fetchall()

            top_row = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(company_name, ''), company_input) AS company_label,
                    COUNT(*)::BIGINT AS analysis_count
                FROM web_analysis_history
                WHERE user_id = %s
                GROUP BY 1
                ORDER BY analysis_count DESC, MAX(created_at) DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            recent_rows = conn.execute(
                """
                SELECT
                    id,
                    company_input,
                    company_name,
                    ticker,
                    title,
                    score,
                    grade,
                    verdict,
                    summary_text,
                    from_cache,
                    model,
                    cost,
                    archived,
                    bookmarked,
                    folder,
                    tags,
                    pinned_note,
                    created_at
                FROM web_analysis_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()

        stats = {
            "total_analyses": int(stats_row["total_analyses"] or 0),
            "analyses_7d": int(stats_row["analyses_7d"] or 0),
            "analyses_30d": int(stats_row["analyses_30d"] or 0),
            "cached_analyses": int(stats_row["cached_analyses"] or 0),
            "analyzed_companies": int(stats_row["analyzed_companies"] or 0),
            "avg_score": float(stats_row["avg_score"]) if stats_row["avg_score"] is not None else None,
            "best_score": float(stats_row["best_score"]) if stats_row["best_score"] is not None else None,
            "first_analysis_at": stats_row["first_analysis_at"].isoformat() if stats_row["first_analysis_at"] else None,
            "last_analysis_at": stats_row["last_analysis_at"].isoformat() if stats_row["last_analysis_at"] else None,
            "top_company": top_row["company_label"] if top_row else None,
            "top_company_count": int(top_row["analysis_count"] or 0) if top_row else 0,
        }

        favorites = [
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "position": int(row.get("position") or 0),
                "price_alert_enabled": bool(row.get("price_alert_enabled")),
                "price_alert_above": float(row["price_alert_above"]) if row.get("price_alert_above") is not None else None,
                "price_alert_below": float(row["price_alert_below"]) if row.get("price_alert_below") is not None else None,
                "news_alert_enabled": bool(row.get("news_alert_enabled", True)),
                "report_alert_enabled": bool(row.get("report_alert_enabled", True)),
            }
            for row in favorites_rows
        ]

        recent_analyses = [self._analysis_row(row) for row in recent_rows]
        preferences = {**DEFAULT_PROFILE_PREFERENCES, **dict(user_row.get("preferences") or {})}
        security = {
            "email_verified": bool(user_row.get("email_verified")),
            "two_factor_enabled": bool(user_row.get("two_factor_enabled")),
            "password_changed_at": user_row["password_changed_at"].isoformat() if user_row.get("password_changed_at") else None,
        }

        return {
            "user": self._row_to_user(user_row).to_public_dict(),
            "stats": stats,
            "favorites": favorites,
            "recent_analyses": recent_analyses,
            "notes": self.list_notes(user_id),
            "preferences": preferences,
            "security": security,
        }


web_auth_store = WebAuthStore()
