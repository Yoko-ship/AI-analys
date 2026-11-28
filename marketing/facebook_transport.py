"""Page posts and Reels, with durable preparation before one public request."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import re
from time import monotonic

from PIL import Image

from . import media, meta_http as http, meta_identity, meta_oauth, publishing, sources, store as s
from .delivery import PermanentRejection, StoppedBeforeSend
from .errors import MarketingError
from .permissions import timestamp
from .upload_journal import UploadJournal


def post_id(value, page):
    if not isinstance(value, str) or not re.fullmatch(re.escape(page) + r"_[1-9][0-9]{0,39}", value):
        raise ValueError("Meta did not confirm a post on the selected Page")
    return value


def _files(item):
    with s.connection() as c:
        assets = [s.get(c, "asset", ref["id"]) for ref in item["assets"]]
    count = len(assets)
    valid = count == 0 if item["format"] == "post" else count == 1 if item["format"] == "image" else 2 <= count <= 10
    if not valid or len({asset["id"] for asset in assets}) != count:
        raise PermanentRejection("Facebook requires the complete set of rendered photos")
    result = []
    for asset in assets:
        try:
            raw = media.read_asset(asset)
            if len(raw) > 10_000_000 or not isinstance(asset.get("alt_text"), str) or not asset["alt_text"].strip():
                raise ValueError("Invalid image size or description")
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format not in {"PNG", "JPEG"} or picture.width * picture.height >= 36_152_320:
                    raise ValueError("Invalid image")
                if asset["mime"] != {"PNG": "image/png", "JPEG": "image/jpeg"}[picture.format]:
                    raise ValueError("Image type mismatch")
                picture.verify()
        except Exception:
            raise PermanentRejection("Facebook photos require valid files and descriptions") from None
        result.append((asset, raw))
    return result


class Facebook:
    def __init__(self, grant, now=None):
        self.grant = grant
        self.now = now or datetime.now(timezone.utc)
        self.started = monotonic()
        self.config = meta_oauth._config("facebook")

    def at(self):
        return self.now + timedelta(seconds=monotonic() - self.started)

    def _verify(self):
        try:
            choice, expires = meta_identity.verify_choice(self.config, self.grant["user"], "facebook", self.grant["choice"], self.at())
            if timestamp(expires) <= self.at() + timedelta(seconds=60):
                raise ValueError("Grant expired during verification")
        except (MarketingError, ValueError):
            raise StoppedBeforeSend("Facebook could not verify the selected Page and its publishing permissions") from None
        self.grant = {**self.grant, "choice": choice, "expires_at": expires}

    def _photos(self, account, item, files, release_key, claim_token, before_send):
        identifiers = []
        for asset, raw in files:
            before_send()
            journal = UploadJournal(account, item, self.grant, asset, release_key, claim_token, self.at(), provider="facebook")
            saved = journal.load()
            # Unpublished photos last about a day; retain only a conservative 23h.
            if not saved or timestamp(saved["expires_at"]) <= self.at():
                value = http.request("POST", account["external_id"] + "/photos", self.grant["choice"]["access_token"],
                    self.config["app_secret"], self.at(), data={"published": "false", "alt_text_custom": asset["alt_text"]},
                    files={"source": (asset["file_name"], raw, asset["mime"])})
                try:
                    identifier = meta_identity.identifier(value.get("id"))
                except MarketingError:
                    raise PermanentRejection("Meta did not return a valid unpublished photo") from None
                saved = journal.save({"remote_id": identifier, "phase": "uploaded", "parts": [{}], "completed": [0],
                    "expires_at": (self.at() + timedelta(hours=23)).isoformat()})
            identifiers.append(saved["remote_id"])
        if len(set(identifiers)) != len(identifiers):
            raise PermanentRejection("Facebook returned the same photo for different rendered files")
        return identifiers

    def publish(self, account, item, release_key, *, before_send, claim_token):
        from .facebook_reels import local_video, ReelUpload
        with s.connection() as c:
            evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
        if publishing.check(account, item, evidence):
            raise PermanentRejection("Facebook content limits require a revision")
        video = item["format"] == "video"
        files = [local_video(item)] if video else _files(item)
        copy = publishing.text(item, evidence)
        self._verify()
        if video:
            identifiers = [ReelUpload(self.grant, self.config, self.at, before_send).prepare(account, item, files[0], release_key, claim_token)]
        else:
            identifiers = self._photos(account, item, files, release_key, claim_token, before_send)
        if files:
            self._verify()
        before_send({"provider": "facebook", "account_external_id": account["external_id"], "text": copy,
            "format": item["format"], "media_count": len(files), "media_ids": identifiers,
            **({"audience": "PUBLIC", "is_ai_generated": True} if video else {}),
            "assets": [{"id": ref["id"], **item["check"]["asset_versions"][ref["id"]]} for ref in item["assets"]]})
        if video:
            value = http.request("POST", account["external_id"] + "/video_reels", self.grant["choice"]["access_token"],
                self.config["app_secret"], self.at(), data={"upload_phase": "finish", "video_id": identifiers[0], "video_state": "PUBLISHED",
                    "description": copy, "is_ai_generated": "true"}, public_write=True)
            if value.get("success") is not True:
                raise RuntimeError("Meta did not confirm Reel publication acceptance")
            return {"provider": "facebook", "publication_status": "submitted", "external_id": identifiers[0], "external_ids": identifiers,
                    "url": "https://www.facebook.com/reel/" + identifiers[0] + "/", "payload_digest": hashlib.sha256(copy.encode()).hexdigest()}
        data = {"message": copy, "published": "true"}
        if identifiers:
            data["attached_media"] = json.dumps([{"media_fbid": identifier} for identifier in identifiers])
        value = http.request("POST", account["external_id"] + "/feed", self.grant["choice"]["access_token"],
                             self.config["app_secret"], self.at(), data=data, public_write=True)
        identifier = post_id(value.get("id"), account["external_id"])
        return {"provider": "facebook", "publication_status": "submitted", "external_id": identifier, "external_ids": [identifier],
                "url": "https://www.facebook.com/" + account["external_id"] + "/posts/" + identifier.split("_")[1] + "/",
                "payload_digest": hashlib.sha256(copy.encode()).hexdigest()}
