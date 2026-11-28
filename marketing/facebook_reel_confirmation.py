"""A published Reel requires both processing proof and membership on its Page."""
from datetime import datetime, timedelta, timezone

from . import meta_http, meta_identity
from .permissions import timestamp


def read(account, job, grant, secret, now):
    payload = job["dispatch_payload"]
    if payload["media_count"] != 1 or len(payload["media_ids"]) != 1:
        raise ValueError("Incomplete Reel identity")
    identifier = meta_identity.identifier(payload["media_ids"][0])
    if job.get("external_id", identifier) != identifier:
        raise ValueError("Reel identity changed")
    token = grant["choice"]["access_token"]
    value = meta_http.request("GET", identifier, token, secret, now, data={"fields": "status"})
    status = value["status"]
    phases = [status[name] for name in ("uploading_phase", "processing_phase", "publishing_phase")]
    if (value.get("id") != identifier or status.get("video_status") != "ready"
            or any(phase.get("status") not in {"completed", "complete"} or phase.get("error") or phase.get("errors") for phase in phases)
            or phases[2].get("publish_status") != "published"):
        raise ValueError("Reel publication is not confirmed")
    value = phases[2].get("publish_time")
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 12:
        value = int(value)
    if type(value) is not int or value <= 0:
        raise ValueError("Reel publication time is missing")
    published = datetime.fromtimestamp(value, timezone.utc)
    start = timestamp(job.get("provider_requested_at") or job["claimed_at"]) - timedelta(minutes=5)
    if not start <= published <= now + timedelta(minutes=5):
        raise ValueError("Reel publication time differs from this release")
    params = {"fields": "id,description", "limit": 100, "since": int(start.timestamp()), "until": int((now + timedelta(minutes=5)).timestamp())}
    seen = set()
    for _ in range(10):
        page = meta_http.request("GET", account["external_id"] + "/video_reels", token, secret, now, data=params)
        rows = page.get("data")
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Unusable Page Reel listing")
        matches = [row for row in rows if row.get("id") == identifier]
        if matches:
            if len(matches) != 1 or matches[0].get("description") != payload["text"]:
                raise ValueError("Page Reel copy differs from the accepted release")
            return {"external_id": identifier, "external_ids": [identifier], "provider": "facebook",
                    "url": "https://www.facebook.com/reel/" + identifier + "/", "published_at": published.isoformat()}
        paging = page.get("paging") or {}
        if not paging.get("next"):
            break
        after = (paging.get("cursors") or {}).get("after")
        if not isinstance(after, str) or not 1 <= len(after) <= 2048 or not all(33 <= ord(ch) <= 126 for ch in after) or after in seen:
            raise ValueError("Invalid Page Reel cursor")
        seen.add(after)
        params["after"] = after  # Rebuild on the fixed Graph host; never follow next.
    raise ValueError("The accepted Reel is not visible on the selected Page")
