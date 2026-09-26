"""Sessions persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from datetime import timedelta
from typing import Any
import hmac
import identity.clock as identity_clock
import identity.credentials as identity_credentials
import identity.settings as identity_settings
import identity.users as identity_users
import secrets


class Sessions:
    def __init__(self, database):
        self.database = database

    def _issue_session(
        self,
        conn,
        user_id: int,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = identity_credentials._token_hash(token)
        expires_at = identity_clock._utcnow() + timedelta(days=identity_settings.SESSION_TTL_DAYS)
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
                identity_clock._utcnow(),
            ),
        )
        return token


    def get_user_by_token(self, token: str) -> identity_users.WebUser | None:
        if not token:
            return None
        token_hash = identity_credentials._token_hash(token)
        now = identity_clock._utcnow()
        with self.database.connect() as conn:
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
        return identity_users.row_to_user(row) if row else None


    def revoke_token(self, token: str) -> bool:
        token_hash = identity_credentials._token_hash(token)
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE token_hash = %s AND revoked_at IS NULL
                """,
                (identity_clock._utcnow(), token_hash),
            )
        return cursor.rowcount > 0


    def list_sessions(self, user_id: int, current_token: str | None = None) -> list[dict[str, Any]]:
        current_hash = identity_credentials._token_hash(current_token) if current_token else ""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, token_hash, created_at, expires_at, revoked_at,
                       user_agent, ip_address, last_seen_at
                FROM web_sessions
                WHERE user_id = %s AND revoked_at IS NULL AND expires_at > %s
                ORDER BY COALESCE(last_seen_at, created_at) DESC
                """,
                (user_id, identity_clock._utcnow()),
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
        current_hash = identity_credentials._token_hash(current_token) if current_token else ""
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                  AND (%s = '' OR token_hash <> %s)
                """,
                (identity_clock._utcnow(), session_id, user_id, current_hash, current_hash),
            )
        return cursor.rowcount > 0


    def revoke_other_sessions(self, user_id: int, current_token: str) -> int:
        current_hash = identity_credentials._token_hash(current_token)
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE web_sessions
                SET revoked_at = %s
                WHERE user_id = %s AND token_hash <> %s AND revoked_at IS NULL
                """,
                (identity_clock._utcnow(), user_id, current_hash),
            )
        return int(cursor.rowcount or 0)
