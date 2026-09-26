"""Users."""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from dataclasses import dataclass
import identity.clock as identity_clock
import os


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _admin_emails() -> set[str]:
    """Allowlist of admin emails (env ADMIN_EMAILS, comma-separated, case-insensitive)."""
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin_email(email: str | None) -> bool:
    """True if this email is an allowlisted admin. Empty allowlist => nobody is admin."""
    return bool(email) and _normalize_email(email) in _admin_emails()


class EmailNotVerified(Exception):
    """Correct credentials, but the address has not been proven yet."""

    def __init__(self, email: str):
        super().__init__("Email address is not verified")
        self.email = email


class AccountLocked(Exception):
    """Too many wrong passwords: sign-in is paused for this account."""

    def __init__(self, email: str, retry_after: int, newly_locked: bool, language: str = "ru"):
        super().__init__("Too many failed sign-in attempts")
        self.email = email
        self.retry_after = int(retry_after)
        self.newly_locked = newly_locked
        self.language = language


class EmailCodeThrottled(Exception):
    """A code was sent too recently (or too often this hour)."""

    def __init__(self, retry_after: int):
        super().__init__(f"Try again in {retry_after} seconds")
        self.retry_after = int(retry_after)


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
        return self.subscription_until is None or self.subscription_until > identity_clock._utcnow()

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


def row_to_user( row) -> WebUser:
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


def normalize_avatar_data_url( avatar_data_url: str | None) -> str | None:
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
