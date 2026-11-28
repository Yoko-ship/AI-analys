"""Instagram publishing with one durable public-write boundary."""
from datetime import datetime, timedelta, timezone
import hashlib
from time import monotonic

from . import instagram_links, instagram_media, meta_http, meta_identity, meta_oauth, publishing, sources, store as s
from .delivery import PermanentRejection, PreparationPending, StoppedBeforeSend
from .permissions import timestamp


class Instagram:
    def __init__(self, grant, now=None):
        self.grant, self.now, self.started = grant, now or datetime.now(timezone.utc), monotonic()
        self.config = meta_oauth._config("instagram")

    def at(self):
        return self.now + timedelta(seconds=monotonic() - self.started)

    def _verify(self):
        try:
            choice, expires = meta_identity.verify_choice(self.config, self.grant["user"], "instagram", self.grant["choice"], self.at())
            if timestamp(expires) <= self.at() + timedelta(seconds=60):
                raise ValueError("Grant expired")
        except Exception:
            raise StoppedBeforeSend("Instagram could not verify the selected professional account and its publishing permissions") from None
        self.grant = {**self.grant, "choice": choice, "expires_at": expires}

    def _quota(self, account, release_id, request):
        value = request("GET", account["external_id"] + "/content_publishing_limit", data={"fields": "quota_usage,config"})
        try:
            if len(value["data"]) != 1:
                raise ValueError()
            row = value["data"][0]
            usage, total, duration = row["quota_usage"], row["config"]["quota_total"], row["config"]["quota_duration"]
            if any(type(v) is not int for v in (usage, total, duration)) or usage < 0 or not 0 < total <= 100 or duration != 86400:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise PreparationPending("Instagram publishing quota could not be verified", 300) from None
        with s.connection() as c:
            reservations = sum(1 for job in s.list_items(c, "delivery") if job["id"] != release_id and job.get("platform") == "instagram"
                and job.get("external_account_id") == account["external_id"] and job["status"] in {"sending", "unknown"}
                and timestamp(job.get("provider_requested_at") or job["claimed_at"]) + timedelta(hours=24) > self.at())
        if usage + reservations >= total:
            raise PreparationPending("Waiting for Instagram's rolling publication quota", 3600)

    def publish(self, account, item, release_key, *, before_send, claim_token):
        with s.connection() as c:
            evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
        if publishing.check(account, item, evidence):
            raise PermanentRejection("Instagram content limits require a revision")
        assets = instagram_media.files(item)
        copy = publishing.payload_text(account, item, evidence)
        self._verify()
        def request(method, path, *, data):
            before_send()
            return meta_http.request(method, path, self.grant["user"]["access_token"], self.config["app_secret"], self.at(), data=data)
        self._quota(account, release_key, request)
        instagram_links.verify(account, item, request, self.at)
        identifier = instagram_media.prepare(account, item, assets, self.grant, release_key, claim_token, copy, self.at, before_send, request)
        self._verify()
        self._quota(account, release_key, request)
        profile_link = instagram_links.verify(account, item, request, self.at)
        before_send({"provider": "instagram", "account_external_id": account["external_id"], "text": copy, "format": item["format"],
            "media_count": len(assets), "container_id": identifier, "alt_texts": [] if item["format"] in {"video", "story"} else [asset["alt_text"] for asset in assets],
            "is_ai_generated": True, **({"share_to_feed": False} if item["format"] == "video" else {}),
            **({"profile_link": profile_link} if profile_link else {}),
            "assets": [{"id": ref["id"], **item["check"]["asset_versions"][ref["id"]]} for ref in item["assets"]]})
        value = meta_http.request("POST", account["external_id"] + "/media_publish", self.grant["user"]["access_token"],
            self.config["app_secret"], self.at(), data={"creation_id": identifier}, public_write=True)
        try:
            external_id = meta_identity.identifier(value.get("id"))
        except Exception:
            raise RuntimeError("Instagram publication outcome is unknown") from None
        return {"provider": "instagram", "publication_status": "submitted", "external_id": external_id,
                "external_ids": [external_id], "payload_digest": hashlib.sha256(copy.encode()).hexdigest()}
