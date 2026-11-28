"""Collect bounded Telegram observations without sending, editing or forwarding."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from . import channels, permissions, store as s
from .errors import MarketingError

OBSERVER = {"id": "telegram_observer", "role": "connection_verifier"}
POLL_ID = "telegram_updates"


def post_url(channel_id, message_id, username=""):
    name = username if isinstance(username, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username) else "c/" + channel_id[4:]
    return f"https://t.me/{name}/{message_id}"


def normalize(update, targets):
    direct = update.get("edited_channel_post") or update.get("channel_post")
    message = direct or update.get("message")
    if not isinstance(message, dict):
        return None
    origin = message if direct else message.get("forward_origin", {})
    if not direct and origin.get("type") != "channel":
        return None
    chat = origin.get("chat", {})
    target = str(chat.get("id", ""))
    message_id, stamp = origin.get("message_id"), origin.get("date")
    if (chat.get("type") != "channel" or target not in targets or not re.fullmatch(r"-100[0-9]+", target)
            or type(message_id) is not int or message_id <= 0 or type(stamp) is not int or stamp <= 0):
        return None
    # Preserve only a channel observation, never sender/private-chat metadata.
    kind = "photo" if message.get("photo") else "video" if message.get("video") else "post"
    copy = message.get("text", "") if kind == "post" else message.get("caption", "")
    if not isinstance(copy, str) or len(copy) > 20000:
        return None
    entities = message.get('entities' if kind == 'post' else 'caption_entities', [])
    if not isinstance(entities, list):
        return None
    links = []
    for entity in entities:
        if not isinstance(entity, dict) or entity.get('type') != 'text_link':
            continue
        offset, length, url = entity.get('offset'), entity.get('length'), entity.get('url')
        if (type(offset) is not int or type(length) is not int or offset < 0 or length <= 0
                or offset + length > len(copy.encode('utf-16-le')) // 2
                or not isinstance(url, str) or not 1 <= len(url) <= 2048):
            return None
        links.append({'type': 'text_link', 'offset': offset, 'length': length, 'url': url})
    if kind == "post" and any(message.get(key) for key in ("document", "animation", "audio", "sticker", "voice")):
        return None
    group = message.get("media_group_id")
    # Forwarding a whole album creates a new group identity in the recipient
    # chat. Hash that envelope instead of retaining its private chat identity.
    group_key = s.digest(["direct" if direct else "forward", message.get("chat", {}).get("id"), group]) if group else None
    try:
        published_at = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None
    return {"id": s.digest([target, str(message_id)]), "channel_id": target, "external_id": str(message_id),
            "published_at": published_at, "text": copy, "kind": kind, "group_keys": [group_key] if group_key else [],
            **({'text_links': sorted(links, key=lambda link: link['offset'])} if links else {}),
            "url": post_url(target, message_id, chat.get("username", "")), "observation_type": "channel" if direct else "forward",
            "edited": "edited_channel_post" in update, "update_id": update["update_id"]}


def collect(now):
    with s.connection(write=True) as c:
        accounts = [a for a in s.list_items(c, "account") if a["platform"] == "telegram" and channels.setup(a)["ready"]]
        if not accounts:
            raise MarketingError("RECONCILIATION_CONNECTION", "Verify the dedicated Telegram connection before reconciliation.")
        token = channels._credential()
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        old = s.get(c, "settings", POLL_ID, required=False) or {"id": POLL_ID, "version": 0}
        if old.get("status") == "running" and permissions.timestamp(old["claimed_at"]) + timedelta(minutes=2) > now:
            raise MarketingError("RECONCILIATION_BUSY", "A Telegram reconciliation read is already running.")
        cursor = old.get("cursor", 0) if old.get("fingerprint") == fingerprint else 0
        claim = s.put(c, "settings", {**old, "status": "running", "claimed_at": now.isoformat(), "claim_token": s.uid("poll"),
                      "fingerprint": fingerprint, "cursor": cursor}, actor=OBSERVER,
                      action="telegram_read_started", expected_version=old["version"])
        targets = {a["external_id"] for a in accounts}
        targets.update(job["external_account_id"] for job in s.list_items(c, "delivery") if job.get("platform") == "telegram" and job["status"] == "unknown")
    try:
        from .telegram_transport import Telegram
        adapter = Telegram(token)
        webhook = adapter._request("getWebhookInfo", read=True)
        if not isinstance(webhook, dict) or webhook.get("url") != "":
            raise MarketingError("RECONCILIATION_WEBHOOK", "This bot has an active or unverified webhook. Its existing integration was not changed.")
        updates = adapter._request("getUpdates", {"offset": cursor + 1 if cursor else 0, "limit": 100, "timeout": 5,
                                   "allowed_updates": json.dumps(["channel_post", "edited_channel_post", "message"])}, read=True)
        if (not isinstance(updates, list) or len(updates) > 100
                or any(not isinstance(row, dict) or type(row.get("update_id")) is not int or row["update_id"] < 0 for row in updates)
                or len({row["update_id"] for row in updates}) != len(updates)):
            raise MarketingError("RECONCILIATION_RESPONSE", "Telegram did not return a valid update batch.")
        receipts = [record for update in sorted(updates, key=lambda row: row["update_id"]) if update["update_id"] > cursor
                    if (record := normalize(update, targets))]
        with s.connection(write=True) as c:
            current = s.get(c, "settings", POLL_ID)
            if current.get("claim_token") != claim["claim_token"] or channels._credential() != token:
                raise MarketingError("RECONCILIATION_CHANGED", "Credentials or reconciliation ownership changed during the read. Check again.")
            saved_count = 0
            for receipt in receipts:
                previous = s.get(c, "telegram_receipt", receipt["id"], required=False)
                if previous and receipt["update_id"] <= previous["update_id"]:
                    continue
                # A forward can expose an older copy of a subsequently edited
                # original. It must not undo a direct edit observation.
                if previous and previous.get("edited") and receipt["observation_type"] == "forward":
                    continue
                groups = list(dict.fromkeys([*(previous or {}).get("group_keys", []), *receipt["group_keys"]]))
                s.put(c, "telegram_receipt", {**receipt, "group_keys": groups, "observed_at": now.isoformat(), "status": "observed"},
                      actor=OBSERVER, action="telegram_message_observed", expected_version=previous["version"] if previous else 0)
                saved_count += 1
            s.put(c, "settings", {**current, "status": "complete", "cursor": max([cursor, *(row["update_id"] for row in updates)]),
                  "checked_at": now.isoformat(), "received": saved_count, "has_more": len(updates) == 100, "reason": "Telegram observations saved; absence is not proof of non-publication"},
                  actor=OBSERVER, action="telegram_read_complete", expected_version=current["version"])
        return {"received": saved_count, "has_more": len(updates) == 100}
    except Exception as exc:
        with s.connection(write=True) as c:
            current = s.get(c, "settings", POLL_ID)
            if current.get("claim_token") == claim["claim_token"]:
                s.put(c, "settings", {**current, "status": "error", "reason": "Telegram reconciliation read failed; no publication outcome changed"},
                      actor=OBSERVER, action="telegram_read_failed", expected_version=current["version"])
        if isinstance(exc, MarketingError):
            raise
        raise MarketingError("RECONCILIATION_UNAVAILABLE", "Telegram reconciliation is unavailable. No post was retried.") from None
