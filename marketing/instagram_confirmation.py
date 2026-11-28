"""Read the known Instagram media ID; never infer a lost ID from similar copy."""
from datetime import timedelta
import re
from urllib.parse import urlsplit, urlunsplit

from . import meta_http, meta_identity, meta_oauth
from .permissions import timestamp

FIELDS = "id,owner,caption,media_type,media_product_type,timestamp,permalink,alt_text,children.limit(11){id,media_type,alt_text}"
VIDEO_FIELDS = "id,owner,caption,media_type,media_product_type,timestamp,permalink"
STORY_FIELDS = "id,owner,media_type,media_product_type,timestamp,permalink"


def read(account, job, now):
    payload = job["dispatch_payload"]
    identifier = meta_identity.identifier(job["external_id"])
    if payload["provider"] != "instagram" or payload["account_external_id"] != account["external_id"]:
        raise ValueError("Recipient changed")
    video = payload["format"] == "video"
    story = payload["format"] == "story"
    if story:
        from . import instagram_story
        instagram_story.window(job, now)
    grant = meta_oauth.current_grant(account, now)
    receipt = meta_http.request("GET", identifier, grant["user"]["access_token"], meta_oauth._config("instagram")["app_secret"],
                                now, data={"fields": STORY_FIELDS if story else VIDEO_FIELDS if video else FIELDS})
    published = timestamp(receipt["timestamp"])
    carousel = payload["format"] == "carousel"
    if (receipt.get("id") != identifier or receipt.get("owner", {}).get("id") != account["external_id"]
            or (not story and receipt.get("caption") != payload["text"]) or receipt.get("media_type") != ("VIDEO" if video else "CAROUSEL_ALBUM" if carousel else "IMAGE")
            or receipt.get("media_product_type") != ("STORY" if story else "REELS" if video else "FEED")
            or not timestamp(job.get("provider_requested_at") or job["claimed_at"]) - timedelta(minutes=5) <= published <= now + timedelta(minutes=5)):
        raise ValueError("Published Instagram media does not match the release")
    if story:
        return instagram_story.read(account, job, receipt, grant, meta_oauth._config("instagram")["app_secret"], now)
    if carousel:
        edge = receipt["children"]
        children = edge["data"]
        if ((edge.get("paging") or {}).get("next") or len(children) != payload["media_count"]
                or len({child["id"] for child in children}) != len(children)
                or any(child.get("media_type") != "IMAGE" for child in children)
                or [child.get("alt_text") for child in children] != payload["alt_texts"]):
            raise ValueError("Carousel order or media proof changed")
    elif payload["media_count"] != 1 or (not video and [receipt.get("alt_text")] != payload["alt_texts"]) or receipt.get("children"):
        raise ValueError("Image proof changed")
    url = urlsplit(receipt["permalink"])
    if (url.scheme != "https" or url.hostname not in {"instagram.com", "www.instagram.com"} or url.port not in {None, 443}
            or url.username or url.password or url.fragment or not re.fullmatch((r"/reel/" if video else r"/p/") + r"[A-Za-z0-9_-]+/", url.path)):
        raise ValueError("Invalid Instagram permalink")
    return {"published_at": published.isoformat(), "url": urlunsplit(("https", "www.instagram.com", url.path, "", ""))}
