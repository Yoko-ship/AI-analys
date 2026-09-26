"""Accounts persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from datetime import timedelta
from password_policy import validate_new_password
from typing import Any
import identity.clock as identity_clock
import identity.credentials as identity_credentials
import identity.settings as identity_settings
import identity.users as identity_users
import secrets


class Accounts:
    _CODE_USER_COLUMNS = (
        "id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, "
        "email_verified, tier, subscription_until, two_factor_enabled"
    )

    def __init__(self, database, oauth, sessions):
        self.database = database
        self.oauth = oauth
        self.sessions = sessions

    def get_user_by_email(self, email: str) -> identity_users.WebUser | None:
        normalized = identity_users._normalize_email(email)
        if not normalized:
            return None
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                FROM web_users
                WHERE email = %s
                """,
                (normalized,),
            ).fetchone()
        return identity_users.row_to_user(row) if row else None


    def register_user(
        self,
        email: str,
        password: str,
        full_name: str = "",
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[identity_users.WebUser, str]:
        normalized = identity_users._normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")
        validate_new_password(password, email=normalized, full_name=full_name)

        full_name = (full_name or "").strip()
        password_encoded = identity_credentials._password_hash(password)
        now = identity_clock._utcnow()

        with self.database.connect() as conn:
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

            token = self.sessions._issue_session(conn, row["id"], user_agent, ip_address)
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
        return identity_users.row_to_user(public_row), token


    def login_user(
        self,
        email: str,
        password: str,
        otp: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        *,
        require_verified_email: bool = False,
    ) -> tuple[identity_users.WebUser, str]:
        normalized = identity_users._normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")

        # Failure bookkeeping must be committed even though the attempt is
        # refused, so the outcome is decided inside the transaction and raised
        # only after it closes (an exception inside would roll it back).
        outcome, detail = "ok", None
        now = identity_clock._utcnow()
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, password_hash, created_at,
                       last_login_at, is_active, email_verified, tier, subscription_until,
                       two_factor_enabled, two_factor_secret, preferences,
                       failed_login_count, failed_login_started, locked_until
                FROM web_users
                WHERE email = %s
                FOR UPDATE
                """,
                (normalized,),
            ).fetchone()

            def record_failure():
                started = row.get("failed_login_started")
                count = int(row.get("failed_login_count") or 0)
                if started is None or now - started > timedelta(minutes=identity_settings.LOGIN_FAILURE_WINDOW_MINUTES):
                    count, started = 0, now
                count += 1
                if count >= identity_settings.LOGIN_FAILURE_LIMIT:
                    # A fresh budget after the pause, not one attempt left.
                    conn.execute(
                        "UPDATE web_users SET failed_login_count = 0, failed_login_started = NULL, locked_until = %s WHERE id = %s",
                        (now + timedelta(minutes=identity_settings.LOGIN_LOCK_MINUTES), row["id"]),
                    )
                    return True
                conn.execute(
                    "UPDATE web_users SET failed_login_count = %s, failed_login_started = %s WHERE id = %s",
                    (count, started, row["id"]),
                )
                return False

            locked_until = row.get("locked_until") if row else None
            if not row or not row["is_active"]:
                outcome = "invalid"
            elif locked_until is not None and locked_until > now:
                outcome, detail = "locked", (int((locked_until - now).total_seconds()) + 1, False)
            elif not identity_credentials._password_verify(password, row["password_hash"]):
                outcome = "locked" if record_failure() else "invalid"
                detail = (identity_settings.LOGIN_LOCK_MINUTES * 60, True)
            elif require_verified_email and not row.get("email_verified"):
                outcome = "unverified"
            elif row.get("two_factor_enabled") and not otp:
                outcome = "otp_required"
            elif row.get("two_factor_enabled") and not identity_credentials._verify_totp(row.get("two_factor_secret"), otp):
                # A wrong authenticator code counts: the password alone must
                # not allow unlimited guessing of six digits.
                outcome = "locked" if record_failure() else "otp_invalid"
                detail = (identity_settings.LOGIN_LOCK_MINUTES * 60, True)
            else:
                updates = ["last_login_at = %s", "failed_login_count = 0", "failed_login_started = NULL", "locked_until = NULL"]
                params: list[Any] = [now]
                if identity_credentials.password_needs_rehash(row["password_hash"]):
                    updates.append("password_hash = %s")
                    params.append(identity_credentials._password_hash(password))
                conn.execute(f"UPDATE web_users SET {', '.join(updates)} WHERE id = %s", (*params, row["id"]))
                token = self.sessions._issue_session(conn, row["id"], user_agent, ip_address)

        if outcome == "invalid":
            raise ValueError("Invalid email or password")
        if outcome == "locked":
            preferences = row.get("preferences") or {}
            language = preferences.get("language") if isinstance(preferences, dict) else None
            raise identity_users.AccountLocked(row["email"], retry_after=detail[0], newly_locked=detail[1], language=language or "ru")
        if outcome == "unverified":
            raise identity_users.EmailNotVerified(row["email"])
        if outcome == "otp_required":
            raise ValueError("Two-factor code required")
        if outcome == "otp_invalid":
            raise ValueError("Invalid two-factor code")

        public_row = {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "avatar_data_url": row.get("avatar_data_url"),
            "created_at": row["created_at"],
            "last_login_at": identity_clock._utcnow(),
            "is_active": row["is_active"],
            "email_verified": row.get("email_verified", False),
            "tier": row.get("tier"),
            "subscription_until": row.get("subscription_until"),
        }
        return identity_users.row_to_user(public_row), token


    def _consume_email_code(self, email: str, purpose: str, code: str):
        """Check a code; on success return the user row with the code deleted.

        A wrong guess is committed on its own — raising inside the same
        transaction would roll the attempt counter back and make it useless.
        """
        normalized = identity_users._normalize_email(email)
        with self.database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT c.*, u.{', u.'.join(self._CODE_USER_COLUMNS.split(', '))}
                FROM web_email_codes c JOIN web_users u ON u.id = c.user_id
                WHERE u.email = %s AND c.purpose = %s AND u.is_active
                FOR UPDATE OF c
                """,
                (normalized, purpose),
            ).fetchone()
            verdict = identity_credentials.check_email_code(row, code, identity_clock._utcnow())
            if verdict == "invalid" and row:
                conn.execute(
                    "UPDATE web_email_codes SET attempts = attempts + 1 WHERE user_id = %s AND purpose = %s",
                    (row["user_id"], purpose),
                )
            if verdict == "ok":
                conn.execute(
                    "DELETE FROM web_email_codes WHERE user_id = %s AND purpose = %s",
                    (row["user_id"], purpose),
                )
                return row
        if verdict == "locked":
            raise ValueError("Too many wrong codes — request a new one")
        if verdict == "expired":
            raise ValueError("The code has expired — request a new one")
        raise ValueError("Invalid or expired code")


    def _finish_code_sign_in(self, conn, row, user_agent, ip_address) -> tuple[identity_users.WebUser, str | None]:
        """Mark proven, and sign in unless two-factor still has to be satisfied."""
        now = identity_clock._utcnow()
        conn.execute(
            """
            UPDATE web_users SET email_verified = TRUE, last_login_at = %s,
                   failed_login_count = 0, failed_login_started = NULL, locked_until = NULL
            WHERE id = %s
            """,
            (now, row["id"]),
        )
        token = None
        if not row.get("two_factor_enabled"):
            token = self.sessions._issue_session(conn, row["id"], user_agent, ip_address)
        user = dict(row)
        user["email_verified"] = True
        user["last_login_at"] = now
        return identity_users.row_to_user(user), token


    def _store_email_code(self, conn, user_id: int, purpose: str) -> str:
        """Replace this user's code for ``purpose`` and return the new plain code."""
        now = identity_clock._utcnow()
        row = conn.execute(
            "SELECT * FROM web_email_codes WHERE user_id = %s AND purpose = %s FOR UPDATE",
            (user_id, purpose),
        ).fetchone()
        wait = identity_credentials.email_code_send_wait(row, now)
        if wait:
            raise identity_users.EmailCodeThrottled(wait)
        if row and (now - row["window_started_at"]).total_seconds() < 3600:
            send_count, window_started_at = int(row["send_count"] or 0) + 1, row["window_started_at"]
        else:
            send_count, window_started_at = 1, now
        code, salt = identity_credentials.new_email_code(), secrets.token_hex(16)
        conn.execute(
            """
            INSERT INTO web_email_codes
                (user_id, purpose, salt, code_hash, attempts, expires_at, sent_at, send_count, window_started_at)
            VALUES (%s, %s, %s, %s, 0, %s, %s, %s, %s)
            ON CONFLICT (user_id, purpose) DO UPDATE SET
                salt = EXCLUDED.salt, code_hash = EXCLUDED.code_hash, attempts = 0,
                expires_at = EXCLUDED.expires_at, sent_at = EXCLUDED.sent_at,
                send_count = EXCLUDED.send_count, window_started_at = EXCLUDED.window_started_at
            """,
            (user_id, purpose, salt, identity_credentials.email_code_hash(salt, code),
             now + timedelta(minutes=identity_settings.EMAIL_CODE_TTL_MINUTES), now, send_count, window_started_at),
        )
        return code


    def issue_email_code(self, email: str, purpose: str) -> str | None:
        """A fresh code for an eligible account, or None when there is nothing to send.

        ``verify`` is only for accounts not yet proven; ``reset`` for any active
        account.  Callers must answer identically either way so the response
        never reveals whether an address is registered.
        """
        if purpose not in identity_settings.EMAIL_CODE_PURPOSES:
            raise ValueError(f"Unknown code purpose: {purpose}")
        normalized = identity_users._normalize_email(email)
        if not normalized:
            return None
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT id, is_active, email_verified FROM web_users WHERE email = %s",
                (normalized,),
            ).fetchone()
            if not row or not row["is_active"]:
                return None
            if purpose == "verify" and row["email_verified"]:
                return None
            return self._store_email_code(conn, row["id"], purpose)


    def reset_password_with_code(
        self,
        email: str,
        code: str,
        new_password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[identity_users.WebUser, str | None]:
        """Set a new password from an emailed code; every old session ends."""
        validate_new_password(new_password, email=identity_users._normalize_email(email))
        row = self._consume_email_code(email, "reset", code)
        now = identity_clock._utcnow()
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE web_users SET password_hash = %s, password_changed_at = %s WHERE id = %s",
                (identity_credentials._password_hash(new_password), now, row["id"]),
            )
            conn.execute(
                "UPDATE web_sessions SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
                (now, row["id"]),
            )
            conn.execute("DELETE FROM web_email_codes WHERE user_id = %s", (row["id"],))
            return self._finish_code_sign_in(conn, row, user_agent, ip_address)


    def start_registration(self, email: str, password: str, full_name: str = "") -> str:
        """Create (or re-claim) an unverified account and return its first code.

        No session is issued: the account is unusable until the code proves the
        inbox.  An address that nobody has proven can be registered again — the
        earlier registrant may be a stranger squatting it — and nothing on the
        existing row changes until someone verifies (see ``verify_email_code``).
        """
        normalized = identity_users._normalize_email(email)
        if not normalized:
            raise ValueError("Email is required")
        validate_new_password(password, email=normalized, full_name=full_name)
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT id, email_verified FROM web_users WHERE email = %s",
                (normalized,),
            ).fetchone()
            if row and row["email_verified"]:
                raise ValueError("Email already registered")
            if row:
                user_id = row["id"]
            else:
                user_id = self.oauth._create_user(
                    conn, normalized, (full_name or "").strip(), identity_credentials._password_hash(password))["id"]
            return self._store_email_code(conn, user_id, "verify")


    def verify_email_code(
        self,
        email: str,
        code: str,
        password: str | None = None,
        full_name: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[identity_users.WebUser, str | None]:
        """Prove the inbox and sign in.  Returns ``(user, token)``; the token is
        None for a two-factor account, which must then sign in normally.

        The browser that holds the code is the inbox owner, so the password (and
        name) it submits become the account's — whatever an earlier, unproven
        registrant chose is discarded, together with any session they hold.
        """
        if password is not None:
            validate_new_password(password, email=identity_users._normalize_email(email), full_name=full_name or "")
        row = self._consume_email_code(email, "verify", code)
        now = identity_clock._utcnow()
        with self.database.connect() as conn:
            if password is not None:
                conn.execute(
                    "UPDATE web_users SET password_hash = %s, password_changed_at = %s WHERE id = %s",
                    (identity_credentials._password_hash(password), now, row["id"]),
                )
            name = (full_name or "").strip()
            if name:
                conn.execute("UPDATE web_users SET full_name = %s WHERE id = %s", (name[:120], row["id"]))
                row = {**row, "full_name": name[:120]}
            if not row.get("email_verified"):
                conn.execute(
                    "UPDATE web_sessions SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
                    (now, row["id"]),
                )
            return self._finish_code_sign_in(conn, row, user_agent, ip_address)
