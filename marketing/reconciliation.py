"""Match actual provider observations; only an exact owner decision binds a post."""
from datetime import timedelta

from . import content, incidents, permissions, publishing, store as s, telegram_receipts
from .errors import MarketingError, require_owner


def poll(actor, now):
    require_owner(actor)
    return telegram_receipts.collect(now)


def _case(c, job, receipts, used):
    base = {"delivery_id": job["id"], "delivery_version": job["version"], "status": "no_confirmation", "external_ids": [], "publications": []}
    if job.get("platform") != "telegram":
        return {**base, "status": "unsupported"}
    item = s.get(c, "candidate", job["candidate_id"])
    if not job.get("claimed_at") or content.content_digest(item) != job["content_digest"]:
        return {**base, "status": "basis_unavailable"}
    expected = job.get("dispatch_payload") or {"text": publishing.preview(c, item)["text"], "format": item["format"], "media_count": len(item["assets"])}
    claimed = permissions.timestamp(job["claimed_at"])
    kind = {"image": "photo", "carousel": "photo", "video": "video", "post": "post"}.get(expected["format"])
    nearby = [row for row in receipts if row["channel_id"] == job["external_account_id"]
              and claimed - timedelta(seconds=1) <= permissions.timestamp(row["published_at"]) <= claimed + timedelta(minutes=5)]
    heads = [row for row in nearby if row["kind"] == kind and row["text"] == expected["text"]]
    if len(heads) > 1:
        return {**base, "status": "ambiguous"}
    bundles = []
    incomplete = False
    for head in heads:
        if expected["format"] == "carousel":
            group_bundles = []
            for group in head["group_keys"]:
                members = sorted([row for row in nearby if group in row["group_keys"]], key=lambda row: int(row["external_id"]))
                if (len(members) == expected["media_count"] and members[0]["id"] == head["id"]
                        and all(row["kind"] == "photo" and not row["text"] for row in members[1:])):
                    group_bundles.append(members)
            if not group_bundles:
                incomplete = True
            bundles.extend(group_bundles)
        elif not head["group_keys"]:
            bundles.append([head])
    # Direct and forwarded observations of the same album share message IDs.
    unique = {tuple(row["id"] for row in bundle): bundle for bundle in bundles}
    if len(unique) != 1:
        return {**base, "status": "ambiguous" if len(unique) > 1 else "incomplete_media" if incomplete else "no_confirmation"}
    bundle = next(iter(unique.values()))
    if any((row["channel_id"], row["external_id"]) in used for row in bundle):
        return {**base, "status": "already_linked"}
    proof = {"delivery_id": job["id"], "delivery_version": job["version"], "content_digest": job["content_digest"],
             "receipts": [{"id": row["id"], "version": row["version"]} for row in bundle]}
    return {**base, "status": "matched", "external_ids": [row["external_id"] for row in bundle],
            "receipt_ids": [row["id"] for row in bundle], "match_digest": s.digest(proof),
            "publications": [{"external_id": row["external_id"], "url": row["url"], "published_at": row["published_at"],
                              "kind": row["kind"], "text": row["text"]} for row in bundle], "media_review_required": kind != "post"}


def cases(c):
    jobs = s.list_items(c, "delivery")
    receipts = s.list_items(c, "telegram_receipt")
    used = {(job["external_account_id"], str(ref)) for job in jobs if job["status"] == "published"
            for ref in job.get("external_ids", [job.get("external_id")])}
    found = [_case(c, job, receipts, used) for job in jobs if job["status"] == "unknown"]
    # Two indistinguishable pending releases cannot claim the same observation.
    for row in found:
        if row["status"] == "matched" and any(other is not row and set(row.get("receipt_ids", [])) & set(other.get("receipt_ids", [])) for other in found):
            row["status"] = "ambiguous"
            row.pop("match_digest", None)
    return found


def confirm(actor, delivery_id, expected_version, match_digest, now):
    require_owner(actor)
    with s.connection(write=True) as c:
        job = s.get(c, "delivery", delivery_id)
        if job["version"] != expected_version or job["status"] != "unknown":
            raise MarketingError("RECONCILIATION_CHANGED", "The delivery changed. Reload its current outcome.")
        found = next(row for row in cases(c) if row["delivery_id"] == delivery_id)
        if found["status"] != "matched" or found["match_digest"] != match_digest:
            raise MarketingError("RECONCILIATION_PROOF", "An exact current platform match is required; no post was retried.")
        first = found["publications"][0]
        saved = s.put(c, "delivery", {**job, "status": "published", "external_id": first["external_id"],
              "external_ids": found["external_ids"], "url": first["url"], "provider": "telegram", "finished_at": now.isoformat(),
              "published_at": first["published_at"], "reason": "Publication matched to Telegram observations and confirmed by owner",
              "reconciliation": {"match_digest": match_digest, "receipt_ids": found["receipt_ids"], "confirmed_by": actor["id"], "at": now.isoformat()}},
              actor=actor, action="publication_reconciled", expected_version=expected_version)
        item = s.get(c, "candidate", job["candidate_id"])
        item = s.put(c, "candidate", {**item, "status": "published"}, actor=actor,
                     action="publication_reconciled", expected_version=item["version"])
        incidents.record_publication(c, item, saved, s.get(c, "account", item["account_id"]))
        return saved
