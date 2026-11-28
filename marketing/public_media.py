"""Short-lived provider fetch tickets, bound to an approved release and file."""
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import content, credentials, media, meta_oauth, permissions, sources, store as s
from .delivery import StoppedBeforeSend

router = APIRouter(prefix="/api/marketing/media", tags=["marketing-media"])
TTL = timedelta(hours=24)


def now():
    return datetime.now(timezone.utc)


def _asset(c, value, at):
    if value["environment"] != s.environment() or not permissions.timestamp(value["issued_at"]) <= at < permissions.timestamp(value["expires_at"]):
        raise ValueError("Ticket expired")
    job = s.get(c, "delivery", value["release_id"])
    item = s.get(c, "candidate", job["candidate_id"])
    account = s.get(c, "account", job["account_id"])
    asset = s.get(c, "asset", value["asset_id"])
    if (job["status"] not in {"sending", "retry", "submitted", "published", "unknown"}
            or item["status"] not in {"sending", "scheduled", "submitted", "published", "unknown"}
            or job["content_digest"] != value["content_digest"] or content.content_digest(item) != value["content_digest"]
            or account["id"] != value["account_id"] or account["external_id"] != value["external_id"]
            or account["platform"] != value["platform"] or account["connection_status"] != "connected"
            or account.get("connection_fingerprint") != value["grant_id"]
            or not any(ref["id"] == asset["id"] for ref in item["assets"])
            or asset["version"] != value["asset_version"] or asset["sha256"] != value["sha256"]
            or (item.get("check") or {}).get("asset_versions", {}).get(asset["id"]) != {"version": asset["version"], "sha256": asset["sha256"]}
            or meta_oauth.current_grant(account, at, c)["id"] != value["grant_id"]):
        raise ValueError("Release changed")
    # A fetch during unpublished preparation must respect withdrawn authority.
    # An already accepted publication may still be downloading its approved file.
    if job.get("dispatch_phase") == "preparing":
        if (not permissions.can_release(account, item, at)[0]
                or (s.get(c, "settings", "pause", required=False) or {}).get("publications")
                or (s.get(c, "settings", "recovery", required=False) or {}).get("status") == "requires_reconciliation"):
            raise ValueError("Release paused")
        for key, version in item["check"]["evidence_versions"].items():
            evidence = sources.current_evidence(c, key)
            if not evidence or evidence["version"] != version or evidence["status"] != "verified":
                raise ValueError("Evidence changed")
    if asset["mime"] not in {"image/jpeg", "image/png", "video/mp4"}:
        raise ValueError("Unsupported media")
    return asset


def issue(account, item, asset, release_id, claim_token, grant, at):
    value = {"environment": s.environment(), "release_id": release_id, "content_digest": content.content_digest(item),
             "account_id": account["id"], "external_id": account["external_id"], "platform": account["platform"], "grant_id": grant["id"],
             "asset_id": asset["id"], "asset_version": asset["version"], "sha256": asset["sha256"],
             "issued_at": at.isoformat(), "expires_at": (at + TTL).isoformat()}
    with s.connection() as c:
        job = s.get(c, "delivery", release_id)
        if job["status"] != "sending" or job.get("claim_token") != claim_token or job.get("dispatch_phase") != "preparing":
            raise StoppedBeforeSend("The dispatch claim is no longer active")
        _asset(c, value, at)
    origin = urlsplit(meta_oauth._config(account["platform"])["redirect_uri"])
    token = credentials.cipher().encrypt(s.encode(value).encode()).decode()
    return urlunsplit((origin.scheme, origin.netloc, router.prefix + "/" + token, "", ""))


def _range(header, size):
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header, flags=re.ASCII)
    if not match or not any(match.groups()) or len(header) > 80:
        raise ValueError("Invalid range")
    first, last = match.groups()
    start = int(first) if first else max(0, size - int(last))
    end = min(int(last) + 1, size) if first and last else size
    if not 0 <= start < end <= size:
        raise ValueError("Unsatisfiable range")
    return start, end


@router.api_route("/{ticket}", methods=["GET", "HEAD"])
def fetch_media(ticket: str, request: Request):
    try:
        if not ticket.isascii() or len(ticket) > 4096:
            raise ValueError("Invalid ticket")
        value = json.loads(credentials.cipher().decrypt(ticket.encode()))
        with s.connection() as c:
            asset = _asset(c, value, now())
        raw = media.read_asset(asset)
    except Exception:
        raise HTTPException(404, "Media unavailable") from None
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "bytes"}
    status = 200
    if request.headers.get("range"):
        try:
            start, end = _range(request.headers["range"], len(raw))
        except ValueError:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(raw)}"})
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(raw)}"
        raw, status = raw[start:end], 206
    headers["Content-Length"] = str(len(raw))
    return Response(b"" if request.method == "HEAD" else raw, status_code=status, media_type=asset["mime"], headers=headers)
