"""Security persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from password_policy import validate_new_password
import base64
import identity.clock as identity_clock
import identity.credentials as identity_credentials
import re
import secrets


class Security:
    def __init__(self, database):
        self.database = database

    def change_password(self, user_id: int, current_password: str, new_password: str, current_token: str) -> int:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT password_hash, email, full_name FROM web_users WHERE id = %s AND is_active = TRUE",
                (user_id,),
            ).fetchone()
            if not row or not identity_credentials._password_verify(current_password or "", row["password_hash"]):
                raise ValueError("Current password is incorrect")
            validate_new_password(new_password, email=row["email"], full_name=row["full_name"] or "")
            conn.execute(
                "UPDATE web_users SET password_hash = %s, password_changed_at = %s WHERE id = %s",
                (identity_credentials._password_hash(new_password), identity_clock._utcnow(), user_id),
            )
            current_hash = identity_credentials._token_hash(current_token)
            cursor = conn.execute(
                """
                UPDATE web_sessions SET revoked_at = %s
                WHERE user_id = %s AND token_hash <> %s AND revoked_at IS NULL
                """,
                (identity_clock._utcnow(), user_id, current_hash),
            )
        return int(cursor.rowcount or 0)


    def begin_two_factor(self, user_id: int) -> dict[str, str]:
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
        with self.database.connect() as conn:
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
        with self.database.connect() as conn:
            row = conn.execute("SELECT two_factor_enabled,two_factor_secret FROM web_users WHERE id=%s", (user_id,)).fetchone()
        return bool(row and row.get("two_factor_enabled") and identity_credentials._verify_totp(row.get("two_factor_secret"), code))


    def enable_two_factor(self, user_id: int, code: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT two_factor_secret FROM web_users WHERE id = %s", (user_id,)).fetchone()
            if not row or not identity_credentials._verify_totp(row.get("two_factor_secret"), code):
                raise ValueError("Invalid two-factor code")
            conn.execute("UPDATE web_users SET two_factor_enabled = TRUE WHERE id = %s", (user_id,))
        return True


    def disable_two_factor(self, user_id: int, code: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT two_factor_enabled, two_factor_secret FROM web_users WHERE id = %s",
                (user_id,),
            ).fetchone()
            if not row:
                raise ValueError("User not found")
            if row.get("two_factor_enabled") and not identity_credentials._verify_totp(row.get("two_factor_secret"), code):
                raise ValueError("Invalid two-factor code")
            conn.execute(
                "UPDATE web_users SET two_factor_enabled = FALSE, two_factor_secret = NULL WHERE id = %s",
                (user_id,),
            )
        return True
