"""Account access and publication authorization are separate facts."""
from datetime import datetime, timezone, timedelta

from . import store as s
from .errors import require_owner
from .models import Account

TASHKENT = timezone(timedelta(hours=5), name="Asia/Tashkent")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def save_account(actor, account_id, data, expected_version):
    require_owner(actor)
    value = Account.model_validate(data).model_dump(mode="json")
    with s.connection(write=True) as c:
        previous = s.get(c, "account", account_id, required=False)
        # Changing the recipient invalidates the previous connectivity proof.
        same = previous and all(previous[k] == value[k] for k in ("platform", "external_id"))
        proof = {k: previous[k] for k in ("connection_status", "connection_checked_at", "connection_fingerprint", "connection_identity", "connection_reason") if k in previous} if same else {}
        return s.put(c, "account", {**value, "id": account_id, "connection_status": "not_connected", **proof},
                     actor=actor, action="account_permission_changed", expected_version=expected_version)


def can_release(account, item, now, *, transport=False):
    if not account or account["mode"] == "draft":
        return False, "Account is not authorized for publication"
    if account["paused"]:
        return False, "Account is paused"
    if item["publication_type"] != "organic":
        return False, "Paid campaigns require their own owner decision"
    ongoing_news = account['platform'] == 'telegram' and account.get('automatic_news') and item['rubric'] == 'news'
    if (not account["valid_until"] and not ongoing_news) or (account['valid_until'] and timestamp(account["valid_until"]) <= now):
        return False, "Account permission expired"
    if item["rubric"] not in account["rubrics"] or item["format"] not in account["formats"] or item["language"] not in account["languages"]:
        return False, "Content is outside the account's approved scope"
    if transport:
        if account["connection_status"] != "connected":
            return False, "Account login and connection verification are required"
        local_time = now.astimezone(TASHKENT).strftime("%H:%M:%S")
        if not account["window_start"] <= local_time < account["window_end"]:
            return False, "Waiting for the permitted Asia/Tashkent release window"
    return True, "Authorized organic release"


def requires_approval(account, item):
    return bool(account and (account["mode"] == "manual" or item["mode"] == "manual"
                or (item.get("correction_incident") and account["correction_policy"] == "manual")))


def release_recipient_matches(account, item):
    decision = item.get("release_decision") or {}
    return bool(account and decision.get("actor") is not None and decision.get("account_id") == item["account_id"]
                and decision.get("platform") == account["platform"] and decision.get("external_id") == account["external_id"])
