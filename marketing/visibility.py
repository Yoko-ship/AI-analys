"""Explicit owner observation for a created LinkedIn post with restricted reads."""
import re

from . import content, incidents, store as s
from .errors import MarketingError, require_owner


def _review(c, job):
    item = s.get(c, "candidate", job["candidate_id"])
    identifier = job.get("external_id", "")
    if (job.get("provider") != "linkedin" or job["status"] != "submitted" or item["status"] != "submitted"
            or not re.fullmatch(r"urn:li:(?:share|ugcPost):[1-9][0-9]{0,30}", identifier)
            or content.content_digest(item) != job["content_digest"] or not job.get("dispatch_payload")):
        raise MarketingError("VISIBILITY_CHANGED", "This created post is no longer available for visibility confirmation.")
    return {"delivery_id": job["id"], "delivery_version": job["version"], "title": item["title"],
            "url": "https://www.linkedin.com/feed/update/" + identifier + "/", "external_id": identifier,
            "payload": job["dispatch_payload"], "review_digest": s.digest([job["id"], job["version"], identifier,
                job["content_digest"], job["dispatch_payload"]])}


def pending(c):
    return [_review(c, job) for job in s.list_items(c, "delivery", status="submitted") if job.get("provider") == "linkedin"]


def confirm(actor, delivery_id, expected_version, review_digest, now):
    require_owner(actor)
    with s.connection(write=True) as c:
        job = s.get(c, "delivery", delivery_id)
        review = _review(c, job)
        if expected_version != job["version"] or review_digest != review["review_digest"]:
            raise MarketingError("VISIBILITY_CHANGED", "This created post is no longer available for visibility confirmation.")
        saved = s.put(c, "delivery", {**job, "status": "published", "reason": "Visible LinkedIn post confirmed by owner",
            "visibility_confirmation": {"method": "owner_visual_review", "confirmed_by": actor["id"], "at": now.isoformat(),
                                        "review_digest": review_digest}}, actor=actor, action="publication_visibility_confirmed", expected_version=expected_version)
        item = s.get(c, "candidate", job["candidate_id"])
        item = s.put(c, "candidate", {**item, "status": "published"}, actor=actor, action="publication_visibility_confirmed", expected_version=item["version"])
        incidents.record_publication(c, item, saved, s.get(c, "account", item["account_id"]))
        return saved
