"""Sector-monitor access, compatible with the optional extended admin console."""
import json
import os

CAPABILITIES = {
    "viewer": {"read", "export"},
    "analyst": {"read", "export", "retry", "comment"},
    "rule_editor": {"read", "export", "retry", "comment", "draft", "test", "approve", "activate", "rollback"},
    "administrator": {"read", "export", "retry", "comment", "draft", "test", "approve", "activate", "rollback", "access"},
}


def configured_role_for(email):
    from web_auth import is_admin_email
    email = str(email or "").strip().lower()
    if not email:
        return None
    try:
        configured = json.loads(os.getenv("ADMIN_ROLES", "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(configured, dict):
        return None
    if email in configured:
        role = configured[email]
        return role if isinstance(role, str) and role in CAPABILITIES else None
    return "administrator" if is_admin_email(email) else None


def role_for(email):
    # Honor persisted access decisions when the extended console is installed.
    # The sector feature also works on the existing API branch without shipping
    # that separate console or any of its unrelated background workers.
    try:
        from admin_control.service import role_for as shared_role_for
    except ModuleNotFoundError as exc:
        if exc.name not in {"admin_control", "admin_control.service"}:
            raise
        return configured_role_for(email)
    return shared_role_for(email)
