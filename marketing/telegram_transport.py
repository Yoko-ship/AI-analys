"""Dedicated Telegram Bot API adapter. No updates polling or paid broadcasting."""
import hashlib
import io
import json
import re

import requests
from PIL import Image

from . import media, publication_links, publishing, sources, store as s
from .delivery import PermanentRejection, TemporaryRejection

FORMATS = ["post", "image", "carousel", "video"]


class UnknownOutcome(Exception):
    """Do not retry an unconfirmed send, including malformed success receipts."""


class Telegram:
    def __init__(self, token):
        if not re.fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{20,}", token):
            raise PermanentRejection("Invalid Telegram credential format")
        self._token = token

    def _request(self, method, data=None, files=None, *, read=False):
        try:
            with requests.Session() as session:
                # requests has no retry policy by default. Never follow a redirect
                # carrying a bot token or replay an ambiguous write automatically.
                response = session.post(f"https://api.telegram.org/bot{self._token}/{method}", data=data or {}, files=files,
                                        timeout=(5, 45), allow_redirects=False)
            if len(response.content) > 2_000_000:
                raise ValueError("Oversized response")
            result = response.json()
        except Exception:
            if read:
                raise TemporaryRejection("Connection verification unavailable before send", retry_after=60) from None
            raise UnknownOutcome("Telegram send response unavailable") from None
        if isinstance(result, dict) and result.get("ok") is False and response.status_code < 500:
            code = result.get("error_code")
            if code == 429:
                delay = (result.get("parameters") or {}).get("retry_after", 60)
                if not isinstance(delay, int) or isinstance(delay, bool) or delay <= 0:
                    delay = 60
                raise TemporaryRejection("Telegram explicitly rejected this request", retry_after=delay)
            raise PermanentRejection("Telegram rejected this request")
        if response.status_code != 200 or not isinstance(result, dict) or result.get("ok") is not True or "result" not in result:
            if read:
                raise TemporaryRejection("Connection verification unavailable before send", retry_after=60)
            raise UnknownOutcome("Unconfirmed Telegram response")
        return result["result"]

    def probe(self, account):
        target = account["external_id"]
        if not re.fullmatch(r"-100[0-9]+", target):
            raise PermanentRejection("Use the immutable numeric channel ID")
        bot = self._request("getMe", read=True)
        if not isinstance(bot, dict) or bot.get("is_bot") is not True or type(bot.get("id")) is not int:
            raise PermanentRejection("Invalid bot identity")
        chat = self._request("getChat", {"chat_id": target}, read=True)
        if not isinstance(chat, dict) or chat.get("type") != "channel" or str(chat.get("id")) != target:
            raise PermanentRejection("Channel identity does not match")
        member = self._request("getChatMember", {"chat_id": target, "user_id": bot["id"]}, read=True)
        if (not isinstance(member, dict) or (member.get("user") or {}).get("id") != bot["id"]
                or member.get("status") != "administrator" or member.get("can_post_messages") is not True):
            raise PermanentRejection("Bot cannot post to this channel")
        return {"target_id": target, "bot_id": str(bot["id"]), "title": str(chat.get("title", ""))[:200], "formats": FORMATS}

    def publish(self, account, item, release_key, *, before_send, claim_token=None):
        with s.connection() as c:
            evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
            assets = [s.get(c, "asset", ref["id"]) for ref in item["assets"]]
        copy = publishing.payload_text(account, item, evidence)
        links = publishing.telegram_links(account, item, copy)
        if publishing.check(account, item, evidence):
            raise PermanentRejection("Telegram content limits require a revision")
        data = {"chat_id": account["external_id"]}
        files = None
        if item["format"] == "post":
            if assets:
                raise PermanentRejection("Choose a media format for attachments")
            method = "sendMessage"
            data["text"] = copy
            if links:
                data['entities'] = json.dumps(links, ensure_ascii=False)
            if publication_links.valid_destination(item['destination_url']):
                data['link_preview_options'] = json.dumps({
                    'url': publication_links.destination(item), 'prefer_large_media': True, 'show_above_text': True})
        else:
            expected = (2 <= len(assets) <= 10) if item["format"] == "carousel" else len(assets) == 1
            if not expected:
                raise PermanentRejection("Invalid media count")
            files, entries = {}, []
            for index, asset in enumerate(assets):
                try:
                    raw = media.read_asset(asset)
                    if item["format"] == "video":
                        if asset.get("mime") != "video/mp4" or len(raw) > 30_000_000:
                            raise ValueError("Invalid video")
                        kind, name, mime = "video", "clip.mp4", "video/mp4"
                    else:
                        with Image.open(io.BytesIO(raw)) as picture:
                            width, height = picture.size
                            if len(raw) > 10_000_000 or width + height > 10000 or max(width, height) > 20 * min(width, height):
                                raise ValueError("Invalid image dimensions")
                            if picture.format not in {"PNG", "JPEG"}:
                                raise ValueError("Unsupported photo")
                            name, mime = ("image.png", "image/png") if picture.format == "PNG" else ("image.jpg", "image/jpeg")
                        kind = "photo"
                except Exception:
                    raise PermanentRejection("Verified media is unavailable or outside Telegram limits") from None
                key = f"media{index}" if item["format"] == "carousel" else kind
                files[key] = (name, raw, mime)
                entry = {'type': kind, 'media': 'attach://' + key}
                if index == 0:
                    entry['caption'] = copy
                    if links:
                        entry['caption_entities'] = links
                entries.append(entry)
            if item["format"] == "carousel":
                method = "sendMediaGroup"
                data["media"] = json.dumps(entries, ensure_ascii=False)
            else:
                method = "sendVideo" if item["format"] == "video" else "sendPhoto"
                data["caption"] = copy
                if links:
                    data['caption_entities'] = json.dumps(links, ensure_ascii=False)
        # Verify platform rights again outside the database transaction, before
        # any mutating request. A failed read is known not to have sent the post.
        self.probe(account)
        before_send({"text": copy, "format": item["format"], "media_count": len(assets), **({'text_links': links} if links else {})})
        result = self._request(method, data, files)
        messages = result if isinstance(result, list) else [result]
        count = len(assets) if item["format"] == "carousel" else 1
        ids = []
        for message in messages:
            if (not isinstance(message, dict) or type(message.get("message_id")) is not int or message["message_id"] <= 0
                    or str((message.get("chat") or {}).get("id")) != account["external_id"]):
                raise UnknownOutcome("Telegram receipt does not identify this channel's publication")
            ids.append(str(message["message_id"]))
        if len(ids) != count or len(set(ids)) != count:
            raise UnknownOutcome("Telegram did not confirm every album item")
        username = (messages[0].get("chat") or {}).get("username", "")
        channel = username if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username) else "c/" + account["external_id"][4:]
        return {"external_id": ids[0], "external_ids": ids, "url": f"https://t.me/{channel}/{ids[0]}",
                "provider": "telegram", "payload_digest": s.digest({'text': copy, 'text_links': links}) if links else hashlib.sha256(copy.encode()).hexdigest()}
