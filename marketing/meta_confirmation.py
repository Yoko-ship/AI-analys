"""Read an accepted Meta post without issuing another publication request."""
from datetime import timedelta

from . import content, incidents, meta_http, meta_oauth, store as s
from .delivery import TemporaryRejection
from .facebook_transport import post_id
from .instagram_story import VisibilityExpired
from .permissions import timestamp

ACTOR = {"id": "meta_confirmation", "role": "publication_verifier"}
FIELDS = "id,from,message,is_published,is_hidden,created_time,attachments{type,media_type,target{id},subattachments.limit(11){media_type,target{id}}}"


def _edge(value):
    if not isinstance(value, dict) or not isinstance(value.get("data"), list) or (value.get("paging") or {}).get("next"):
        raise ValueError("Incomplete media proof")
    return value["data"]


def _photos(receipt):
    attachments = _edge(receipt["attachments"]) if "attachments" in receipt else []
    result = []
    for attachment in attachments:
        kind = attachment.get("media_type")
        if kind == "album" or attachment.get("type") in {"album", "multiple"}:
            if kind not in {None, "photo", "album", "multiple"}:
                raise ValueError("Unexpected group media")
            children = _edge(attachment.get("subattachments"))
            for child in children:
                if child.get("media_type") != "photo" or "subattachments" in child:
                    raise ValueError("Unexpected media")
                result.append(child["target"]["id"])
        elif kind == "photo":
            if "subattachments" in attachment:
                raise ValueError("Unexpected media")
            result.append(attachment["target"]["id"])
        elif kind != "link":
            raise ValueError("Unexpected media")
    return result


def _read(account, job, now):
    if account["platform"] == "instagram":
        from .instagram_confirmation import read
        return read(account, job, now)
    payload = job["dispatch_payload"]
    if payload.get("provider") != "facebook" or payload.get("account_external_id") != account["external_id"]:
        raise ValueError("Recipient changed")
    grant = meta_oauth.current_grant(account, now)
    if payload["format"] == "video":
        from .facebook_reel_confirmation import read
        return read(account, job, grant, meta_oauth._config("facebook")["app_secret"], now)
    identifier = post_id(job["external_id"], account["external_id"])
    receipt = meta_http.request("GET", identifier, grant["choice"]["access_token"], meta_oauth._config("facebook")["app_secret"],
                                now, data={"fields": FIELDS})
    published = timestamp(receipt.get("created_time"))
    if (receipt.get("id") != identifier or receipt.get("from", {}).get("id") != account["external_id"]
            or receipt.get("message") != payload["text"] or receipt.get("is_published") is not True or receipt.get("is_hidden") is not False
            or _photos(receipt) != payload["media_ids"] or len(payload["media_ids"]) != payload["media_count"]
            or not timestamp(job["claimed_at"]) - timedelta(minutes=5) <= published <= now + timedelta(minutes=5)):
        raise ValueError("Visible post does not match the accepted release")
    return {"published_at": published.isoformat()}


def _eligible(job):
    if (job.get("confirmation") or {}).get("status") == "expired_unverified":
        return False
    return (job["status"] == "submitted" and job.get("provider") in {"facebook", "instagram"} or job["status"] == "unknown"
            and job.get("platform") == "facebook" and job.get("dispatch_payload", {}).get("provider") == "facebook"
            and job.get("dispatch_payload", {}).get("format") == "video")


def _due(job, now):
    value = ((job.get("confirmation") or {}).get("next_check_at") or job.get("finished_at")
             or job.get("provider_requested_at") or job.get("claimed_at"))
    return timestamp(value) if value else now


def run_one(now):
    with s.connection() as c:
        jobs = [job for job in s.list_items(c, "delivery") if _eligible(job) and _due(job, now) <= now]
        if not jobs:
            return False
        job = min(jobs, key=lambda row: (_due(row, now), row["id"]))
        account = s.get(c, "account", job["account_id"])
        item = s.get(c, "candidate", job["candidate_id"])
    attempts = (job.get("confirmation") or {}).get("attempts", 0) + 1
    delay, published, expired = min(3600, 60 * 2 ** min(attempts - 1, 6)), None, False
    try:
        if item["status"] != job["status"] or content.content_digest(item) != job["content_digest"] or account["platform"] not in {"facebook", "instagram"}:
            raise ValueError("Release changed")
        published = _read(account, job, now)
    except TemporaryRejection as exc:
        delay = max(delay, exc.retry_after)
    except VisibilityExpired:
        expired = True
    except Exception:
        # Provider responses and credential failures can contain secrets.
        pass
    try:
        next_check = (now + timedelta(seconds=delay)).isoformat()
    except OverflowError:
        next_check = "9999-12-31T23:59:59+00:00"
    with s.connection(write=True) as c:
        current = s.get(c, "delivery", job["id"])
        candidate = s.get(c, "candidate", item["id"])
        current_account = s.get(c, "account", account["id"])
        if current["version"] != job["version"] or candidate["version"] != item["version"] or current_account["version"] != account["version"]:
            return True
        confirmation = {"attempts": attempts, "checked_at": now.isoformat(), "next_check_at": None if expired else next_check,
                        "status": "confirmed" if published else "expired_unverified" if expired else "pending"}
        value = {**current, "confirmation": confirmation}
        if published:
            value.update(**published, status="published", reason="Visible Meta post verified against the accepted release",
                         visibility_confirmation={"method": "provider_read", "at": now.isoformat(), "external_id": published.get("external_id", job.get("external_id"))})
        elif expired:
            value["reason"] = "Instagram Story visibility could not be verified before its display window ended. No resend."
        else:
            value["reason"] = ("Facebook Reel outcome is unknown; verification continues without resending" if job["status"] == "unknown" else
                               "Meta accepted this release; exact visible publication is not yet verified. No resend.")
        saved = s.put(c, "delivery", value, actor=ACTOR, action="meta_visibility_checked", expected_version=job["version"])
        if published:
            candidate = s.put(c, "candidate", {**candidate, "status": "published"}, actor=ACTOR,
                              action="meta_visibility_confirmed", expected_version=candidate["version"])
            incidents.record_publication(c, candidate, saved, account)
    return True
