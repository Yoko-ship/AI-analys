from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
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
    avatar_data_url: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    is_active: bool

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "avatar_data_url": self.avatar_data_url,
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
                    avatar_data_url TEXT,
                    password_hash   TEXT NOT NULL,
                    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
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

    def _row_to_user(self, row) -> WebUser:
        return WebUser(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            avatar_data_url=row.get("avatar_data_url"),
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            is_active=bool(row["is_active"]),
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
            RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at, u.last_login_at, u.is_active
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
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at, u.last_login_at, u.is_active
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
                conn.execute(
                    "UPDATE web_users SET last_login_at = %s WHERE id = %s",
                    (now, existing["id"]),
                )
                existing = dict(existing)
                existing["last_login_at"] = now
                return self._row_to_user(existing), token

            row = conn.execute(
                "SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active FROM web_users WHERE email = %s",
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
        }
        return self._row_to_user(public_row), token

    def get_user_by_email(self, email: str) -> WebUser | None:
        normalized = _normalize_email(email)
        if not normalized:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
                SELECT u.id, u.email, u.full_name, u.avatar_data_url, u.created_at, u.last_login_at, u.is_active
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
            INSERT INTO web_users (email, full_name, avatar_data_url, password_hash, created_at, last_login_at, is_active)
            VALUES (%s, %s, NULL, %s, %s, NULL, TRUE)
            RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
            "avatar_data_url": row["avatar_data_url"],
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
            "avatar_data_url": row["avatar_data_url"] if "avatar_data_url" in row else None,
            "created_at": row["created_at"],
            "last_login_at": _utcnow(),
            "is_active": row["is_active"],
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
                    SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
                RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
                SELECT ticker, company_name, created_at
                FROM web_favorite_companies
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
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

    def get_profile(self, user_id: int, recent_limit: int = 8) -> dict[str, Any]:
        limit = max(1, min(int(recent_limit or 8), 20))
        with self._conn() as conn:
            user_row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active
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
                SELECT ticker, company_name, created_at
                FROM web_favorite_companies
                WHERE user_id = %s
                ORDER BY created_at DESC
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
            }
            for row in favorites_rows
        ]

        recent_analyses = []
        for row in recent_rows:
            recent_analyses.append(
                {
                    "company_input": row["company_input"],
                    "company_name": row["company_name"],
                    "ticker": row["ticker"],
                    "score": float(row["score"]) if row["score"] is not None else None,
                    "grade": row["grade"],
                    "verdict": row["verdict"],
                    "summary_text": row["summary_text"],
                    "from_cache": bool(row["from_cache"]),
                    "model": row["model"],
                    "cost": float(row["cost"]) if row["cost"] is not None else None,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )

        return {
            "user": self._row_to_user(user_row).to_public_dict(),
            "stats": stats,
            "favorites": favorites,
            "recent_analyses": recent_analyses,
        }


web_auth_store = WebAuthStore()
