"""Credentials."""
from __future__ import annotations

from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import identity.clock as identity_clock
import identity.settings as identity_settings
import secrets
import struct


def _password_hash(password: str, salt: bytes | None = None, iterations: int | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    rounds = int(iterations or identity_settings.PBKDF2_ITERATIONS)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def password_needs_rehash(encoded: str | None) -> bool:
    try:
        algorithm, rounds, _salt, _digest = str(encoded or "").split("$", 3)
        return algorithm != "pbkdf2_sha256" or int(rounds) < identity_settings.PBKDF2_ITERATIONS
    except ValueError:
        return True


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
    moment = at or identity_clock._utcnow()
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
    moment = at or identity_clock._utcnow()
    return any(
        hmac.compare_digest(_totp_code(secret, moment + timedelta(seconds=step * 30)), candidate)
        for step in (-1, 0, 1)
    )


def new_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def email_code_hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _clean_code(code: str | None) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def check_email_code(row: dict | None, code: str | None, now: datetime) -> str:
    """``ok`` | ``invalid`` | ``expired`` | ``locked`` for a stored code row."""
    if not row:
        return "invalid"
    if int(row["attempts"] or 0) >= identity_settings.EMAIL_CODE_MAX_ATTEMPTS:
        return "locked"
    if row["expires_at"] <= now:
        return "expired"
    candidate = _clean_code(code)
    if len(candidate) != 6:
        return "invalid"
    if not hmac.compare_digest(email_code_hash(row["salt"], candidate), row["code_hash"]):
        return "invalid"
    return "ok"


def email_code_send_wait(row: dict | None, now: datetime) -> int:
    """Seconds until another code may be sent for this row (0 = send now)."""
    if not row:
        return 0
    waits = [0]
    since_sent = (now - row["sent_at"]).total_seconds()
    if since_sent < identity_settings.EMAIL_CODE_RESEND_SECONDS:
        waits.append(identity_settings.EMAIL_CODE_RESEND_SECONDS - since_sent)
    window_age = (now - row["window_started_at"]).total_seconds()
    if window_age < 3600 and int(row["send_count"] or 0) >= identity_settings.EMAIL_CODE_MAX_SENDS_PER_HOUR:
        waits.append(3600 - window_age)
    return int(-(-max(waits) // 1))  # ceil
