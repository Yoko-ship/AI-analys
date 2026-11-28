"""Stories are confirmed only while the known media ID belongs to the active edge."""
from datetime import timedelta
import re
from urllib.parse import urlsplit, urlunsplit

from . import meta_http, meta_identity
from .permissions import timestamp


class VisibilityExpired(ValueError):
    """The display window ended without proof; this is never a retry to publish."""


def window(job, now):
    requested = timestamp(job.get("provider_requested_at") or job["claimed_at"])
    if now >= requested + timedelta(hours=24, minutes=5):
        raise VisibilityExpired()


def read(account, job, receipt, grant, secret, now):
    payload, identifier = job["dispatch_payload"], job["external_id"]
    published = timestamp(receipt["timestamp"])
    expires = published + timedelta(hours=24)
    if expires <= now:
        raise VisibilityExpired()
    if payload["text"] or payload["alt_texts"] or payload["media_count"] != 1 or receipt.get("children"):
        raise ValueError("Unexpected Story media")
    after, seen = None, set()
    for _ in range(10):
        value = meta_http.request("GET", account["external_id"] + "/stories", grant["user"]["access_token"], secret, now,
            data={"fields": "id", "limit": 100, **({"after": after} if after else {})})
        rows = value.get("data")
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Incomplete Story proof")
        identifiers = [meta_identity.identifier(row.get("id")) for row in rows]
        if identifier in identifiers:
            break
        paging = value.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        if not paging.get("next") or not isinstance(after, str) or not re.fullmatch(r"[!-~]{1,2048}", after) or after in seen:
            raise ValueError("Story is not in the selected account's active Stories")
        seen.add(after)
    else:
        raise ValueError("Story visibility scan limit reached")
    url = ""
    if receipt.get("permalink"):
        parsed = urlsplit(receipt["permalink"])
        if (parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"} or parsed.port not in {None, 443}
                or parsed.username or parsed.password or parsed.fragment
                or not re.fullmatch(r"/stories/[A-Za-z0-9_.]{1,30}/[1-9][0-9]{0,39}/", parsed.path)):
            raise ValueError("Invalid Story link")
        url = urlunsplit(("https", "www.instagram.com", parsed.path, "", ""))
    return {"published_at": published.isoformat(), "visibility_expires_at": expires.isoformat(), "url": url}
