"""Oauth persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
import identity.clock as identity_clock
import identity.credentials as identity_credentials
import identity.settings as identity_settings
import identity.users as identity_users
import secrets


class Oauth:
    def __init__(self, database, sessions):
        self.database = database
        self.sessions = sessions

    def _make_fallback_email(self, provider: str, provider_user_id: str) -> str:
        provider_safe = "".join(ch if ch.isalnum() else "-" for ch in provider.lower()).strip("-")
        provider_safe = provider_safe or "oauth"
        return f"{provider_safe}-{provider_user_id}@{identity_settings.OAUTH_FALLBACK_DOMAIN}"


    def _create_user(
        self,
        conn,
        email: str,
        full_name: str,
        password_hash: str | None = None,
    ):
        now = identity_clock._utcnow()
        row = conn.execute(
            """
            INSERT INTO web_users (email, full_name, avatar_data_url, password_hash, created_at, last_login_at, is_active)
            VALUES (%s, %s, NULL, %s, %s, NULL, TRUE)
            RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
            """,
            (
                identity_users._normalize_email(email),
                full_name or "",
                password_hash or identity_credentials._password_hash(secrets.token_urlsafe(32)),
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


    def get_user_by_oauth(self, provider: str, provider_user_id: str) -> identity_users.WebUser | None:
        if not provider or not provider_user_id:
            return None
        with self.database.connect() as conn:
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
        return identity_users.row_to_user(row) if row else None


    def oauth_login(
        self,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
        full_name: str = "",
        email_verified: bool = False,
    ) -> tuple[identity_users.WebUser, str]:
        """Sign in through an identity provider.

        ``email_verified`` is the provider's own claim that it proved the inbox.
        Only a proven address may join an existing account by email — otherwise
        anyone could attach their Google login to someone else's account.
        """
        provider = (provider or "").strip().lower()
        provider_user_id = (provider_user_id or "").strip()
        if not provider or not provider_user_id:
            raise ValueError("OAuth account details are incomplete")

        normalized_email = identity_users._normalize_email(email or "")
        if not normalized_email:
            normalized_email = self._make_fallback_email(provider, provider_user_id)
        full_name = (full_name or "").strip()

        now = identity_clock._utcnow()
        with self.database.connect() as conn:
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
                token = self.sessions._issue_session(conn, existing["id"])
                verified_by_provider = bool(email and email_verified)
                conn.execute(
                    "UPDATE web_users SET last_login_at = %s, email_verified = email_verified OR %s WHERE id = %s",
                    (now, verified_by_provider, existing["id"]),
                )
                existing = dict(existing)
                existing["last_login_at"] = now
                existing["email_verified"] = bool(existing.get("email_verified")) or verified_by_provider
                return identity_users.row_to_user(existing), token

            row = conn.execute(
                "SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until FROM web_users WHERE email = %s",
                (normalized_email,),
            ).fetchone()

            verified_by_provider = bool(email and email_verified)
            if row:
                user_id = row["id"]
                if not verified_by_provider:
                    raise ValueError("This email is already registered — sign in with your password")
                if not row.get("email_verified"):
                    # Nobody ever proved this inbox, so whoever set the password
                    # may be a stranger who registered the address first.  The
                    # provider just proved ownership: evict their credentials.
                    conn.execute(
                        "UPDATE web_users SET password_hash = %s, password_changed_at = %s WHERE id = %s",
                        (identity_credentials._password_hash(secrets.token_urlsafe(32)), now, user_id),
                    )
                    conn.execute(
                        "UPDATE web_sessions SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
                        (now, user_id),
                    )
                    conn.execute("DELETE FROM web_email_codes WHERE user_id = %s", (user_id,))
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
            if verified_by_provider:
                conn.execute("UPDATE web_users SET email_verified = TRUE WHERE id = %s", (user_id,))
            token = self.sessions._issue_session(conn, user_id)
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
            "email_verified": verified_by_provider or bool(row.get("email_verified") if row else False),
            "tier": row.get("tier") if row else "free",
            "subscription_until": row.get("subscription_until") if row else None,
        }
        return identity_users.row_to_user(public_row), token
