"""Reserve the rolling Page Reels allowance across all local account aliases."""
from datetime import timedelta

from . import store as s
from .permissions import timestamp

REASON = "Waiting for Facebook's rolling Reels publishing limit"


def next_slot(c, page, now, exclude):
    ends = []
    for job in s.list_items(c, "delivery"):
        if (job["id"] == exclude or job.get("platform") != "facebook" or job.get("external_account_id") != page
                or (job.get("format") or job.get("dispatch_payload", {}).get("format")) != "video"
                or job["status"] not in {"sending", "submitted", "published", "unknown"}):
            continue
        if job["status"] == "sending":
            ends.append(now + timedelta(seconds=60))
            continue
        at = job.get("published_at") or job.get("provider_requested_at") or job.get("finished_at") or job.get("claimed_at")
        if not at:
            ends.append(now + timedelta(seconds=60))
            continue
        end = timestamp(at) + timedelta(hours=24)
        if end > now:
            ends.append(end)
    return sorted(ends)[len(ends) - 30] if len(ends) >= 30 else None
