from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg import connect
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SESSION_TTL_DAYS = int(os.getenv("WEB_SESSION_TTL_DAYS", "30"))
PBKDF2_ITERATIONS = int(os.getenv("WEB_PASSWORD_ITERATIONS", "210000"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


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


@dataclass
class WebUser:
    id: int
    email: str
    full_name: str
    created_at: datetime
    last_login_at: Optional[datetime]
    is_active: bool

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "created_at": self.created_at.isoformat(),
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_active": self.is_active,
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
                    password_hash   TEXT NOT NULL,
                    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_login_at   TIMESTAMPTZ
                )
                """
            )
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

    def _row_to_user(self, row) -> WebUser:
        return WebUser(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            is_active=bool(row["is_active"]),
        )

    def _issue_session(self, conn, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = _token_hash(token)
        expires_at = _utcnow() + timedelta(days=SESSION_TTL_DAYS)
        conn.execute(
            """
            INSERT INTO web_sessions (user_id, token_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, token_hash, expires_at),
        )
        return token

    def get_user_by_email(self, email: str) -> WebUser | None:
        normalized = _normalize_email(email)
        if not normalized:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, created_at, last_login_at, is_active
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
                SELECT u.id, u.email, u.full_name, u.created_at, u.last_login_at, u.is_active
                FROM web_sessions s
                JOIN web_users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.revoked_at IS NULL
                  AND s.expires_at > %s
                  AND u.is_active = TRUE
                """,
                (token_hash, now),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def register_user(self, email: str, password: str, full_name: str = "") -> tuple[WebUser, str]:
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
                INSERT INTO web_users (email, full_name, password_hash, created_at, last_login_at, is_active)
                VALUES (%s, %s, %s, %s, NULL, TRUE)
                RETURNING id, email, full_name, created_at, last_login_at, is_active
                """,
                (normalized, full_name, password_encoded, now),
            ).fetchone()

            token = self._issue_session(conn, row["id"])
            conn.execute(
                "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                (now, row["id"]),
            )

        public_row = {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "created_at": row["created_at"],
            "last_login_at": now,
            "is_active": row["is_active"],
        }
        return self._row_to_user(public_row), token

    def login_user(self, email: str, password: str) -> tuple[WebUser, str]:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, password_hash, created_at, last_login_at, is_active
                FROM web_users
                WHERE email = %s
                """,
                (normalized,),
            ).fetchone()

            if not row or not row["is_active"]:
                raise ValueError("Invalid email or password")
            if not _password_verify(password, row["password_hash"]):
                raise ValueError("Invalid email or password")

            token = self._issue_session(conn, row["id"])
            conn.execute(
                "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                (_utcnow(), row["id"]),
            )

        public_row = {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "created_at": row["created_at"],
            "last_login_at": _utcnow(),
            "is_active": row["is_active"],
        }
        return self._row_to_user(public_row), token

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


web_auth_store = WebAuthStore()
