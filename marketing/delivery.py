"""Durable social outbox. Ambiguous acceptance is never automatically retried."""
from datetime import timedelta

from . import checks, content, founder, incidents, permissions, publishing, sources, store as s
from .errors import MarketingError, require_owner

WORKER = {"id": "delivery", "role": "publisher"}
MAX_ATTEMPTS = 3
LEASE_SECONDS = 300


class TemporaryRejection(Exception):
    """Known non-acceptance, including a failed read before any provider write."""
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class PermanentRejection(Exception):
    pass


class StoppedBeforeSend(Exception):
    """Trusted adapter proof that no public post request was started."""
    def __init__(self, reason, invalidated=False):
        super().__init__(reason)
        self.reason = reason
        self.invalidated = invalidated


class PreparationPending(StoppedBeforeSend):
    """Uploaded media is processing; the post attempt has not started."""
    def __init__(self, reason, retry_after):
        super().__init__(reason)
        self.retry_after = retry_after


def record_connection(account_id, expected_version, *, external_id, verified, now):
    """Called by a trusted platform probe, never from a browser-supplied verdict."""
    with s.connection(write=True) as c:
        account = s.get(c, "account", account_id)
        if account["external_id"] != external_id:
            raise MarketingError("ACCOUNT_CHANGED", "The target changed during the connection check.")
        return s.put(c, "account", {**account, "connection_status": "connected" if verified else "error",
                     "connection_checked_at": now.isoformat()}, actor=WORKER,
                     action="connection_checked", expected_version=expected_version)


def set_pause(actor, *, publications=None, processing=None):
    require_owner(actor)
    with s.connection(write=True) as c:
        record = s.get(c, "settings", "pause", required=False) or {"id": "pause", "publications": False, "processing": False, "version": 0}
        if publications is not None:
            record["publications"] = bool(publications)
        if processing is not None:
            record["processing"] = bool(processing)
        return s.put(c, "settings", record, actor=actor, action="pause_changed", expected_version=record["version"])


def schedule(candidate_id, now):
    from . import automation
    with s.connection() as c:
        selected = s.get(c, "candidate", candidate_id)
        failures = (content.release_failures(c, selected) + automation.candidate_failures(c, selected, now)) if selected["status"] == "ready" else []
    if failures:
        content.check_candidate(candidate_id, now)
        raise MarketingError("EDITORIAL_RELEASE_BLOCKED", "; ".join(failures))
    with s.connection(write=True) as c:
        old = s.get(c, "delivery", candidate_id, required=False)
        if old and ((old["attempts"] > 0 and not old.get("confirmed_not_sent")) or old["status"] not in {"scheduled", "retry", "blocked"}):
            return old
        item = s.get(c, "candidate", candidate_id)
        if old and item["status"] == "scheduled" and old["content_digest"] == content.content_digest(item):
            return old
        if item["status"] != "ready" or not item.get("check", {}).get("passed"):
            raise MarketingError("NOT_READY", "Only a checked, authorized candidate can be scheduled.")
        failures = content.release_failures(c, item) + automation.candidate_failures(c, item, now)
        if failures:
            raise MarketingError("EDITORIAL_RELEASE_BLOCKED", "; ".join(failures))
        account = s.get(c, "account", item["account_id"], required=False)
        allowed, reason = permissions.can_release(account, item, now)
        if not allowed:
            raise MarketingError("NOT_AUTHORIZED", reason)
        due = max(now, permissions.timestamp(item["not_before"])) if item.get("not_before") else now
        value = s.put(c, "delivery", {"id": candidate_id, "candidate_id": candidate_id, "account_id": item["account_id"],
                      "content_digest": content.content_digest(item), "external_account_id": account["external_id"], "platform": account["platform"],
                      "status": "scheduled", "attempts": 0, "not_before": item.get("not_before"), "next_attempt_at": due.isoformat(), "reason": "Waiting for dispatch"},
                      actor=WORKER, action="release_rescheduled" if old else "release_scheduled", expected_version=old["version"] if old else 0)
        s.put(c, "candidate", {**item, "status": "scheduled"}, actor=WORKER,
              action="release_scheduled", expected_version=item["version"])
        return value


def _preflight(c, job, item, account, now):
    from . import automation
    if item["status"] not in {"scheduled", "error"}:
        return False, "Content changed or was cancelled; release is blocked", False
    if permissions.timestamp(item["expires_at"]) <= now:
        return False, "Content expired before dispatch", True
    check = item.get("check")
    if not check or not check["passed"] or check["content_digest"] != content.content_digest(item) or job["content_digest"] != check["content_digest"]:
        return False, "This version no longer has a valid fact check", True
    for key, version in check["evidence_versions"].items():
        source = sources.current_evidence(c, key)
        if not source or source["version"] != version or source["status"] != "verified" or permissions.timestamp(source["expires_at"]) <= now:
            return False, "Source evidence changed or expired; release is blocked", True
    evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
    assets = {ref["id"]: s.get(c, "asset", ref["id"], required=False) for ref in item["assets"] if ref.get("id")}
    if assets and check.get("asset_versions") != {key: {"version": asset["version"], "sha256": asset.get("sha256")} for key, asset in assets.items() if asset}:
        return False, "Reviewed media files changed before dispatch", True
    failures = checks.check(item, {key: value for key, value in evidence.items() if value}, now, assets)
    failures.extend(content.release_failures(c, item))
    failures.extend(automation.candidate_failures(c, item, now))
    failures.extend(content.publication_links.check(c, item))
    failures.extend(publishing.check(account, item, evidence))
    failures.extend(incidents.check(c, item, account))
    founder_failures, versions = founder.check(c, item, account, now)
    failures.extend(founder_failures)
    if versions != check.get("founder_versions", {}):
        failures.append("Founder fact versions changed after review; release is blocked")
    if failures:
        return False, "; ".join(failures), True
    if not account or account["external_id"] != job["external_account_id"] or (job.get("platform") and account["platform"] != job["platform"]):
        return False, "The authorized recipient changed", False
    if permissions.requires_approval(account, item):
        approval = item.get("approval")
        if not approval or approval["account_id"] != account["id"] or approval["content_digest"] != job["content_digest"]:
            return False, "Owner approval is required for this version and account", False
    allowed, reason = permissions.can_release(account, item, now, transport=True)
    return allowed, reason, False


def _claim(now, transport=None):
    from . import automation
    with s.connection(write=True) as c:
        pause = s.get(c, "settings", "pause", required=False) or {}
        recovery = s.get(c, "settings", "recovery", required=False) or {}
        if pause.get("publications") or recovery.get("status") == "requires_reconciliation":
            return None
        jobs = s.list_items(c, "delivery")
        for job in automation.order_deliveries(c, list(reversed(jobs))):
            defer_at = None
            if job["status"] not in {"scheduled", "retry"} or permissions.timestamp(job["next_attempt_at"]) > now:
                continue
            item = s.get(c, "candidate", job["candidate_id"])
            account = s.get(c, "account", job["account_id"], required=False)
            allowed, reason, invalidated = _preflight(c, job, item, account, now)
            if allowed and getattr(transport, "ready", None):
                allowed, reason = transport.ready(account, item)
            if invalidated:
                s.put(c, "delivery", {**job, "status": "blocked", "reason": reason}, actor=WORKER,
                      action="dispatch_invalidated", expected_version=job["version"])
                status = "skipped" if item["mode"] == "automatic" else "needs_revision"
                checked = {**(item.get("check") or {}), "passed": False, "reason": reason,
                           "failures": [reason], "invalidated_at": now.isoformat()}
                s.put(c, "candidate", {**item, "status": status, "check": checked, "approval": None}, actor=WORKER,
                      action="dispatch_fact_check_failed", expected_version=item["version"])
                continue
            if allowed:
                recent = [other for other in jobs if other["account_id"] == job["account_id"] and other.get("claimed_at")
                          and not (other["id"] == job["id"] and other.get("dispatch_phase") == "preparing" and other.get("confirmed_not_sent"))
                          and permissions.timestamp(other["claimed_at"]) + timedelta(minutes=account["min_interval_minutes"]) > now]
                if recent:
                    allowed, reason = False, "Waiting for the account's minimum publication interval"
            if allowed and account["platform"] == "facebook" and item["format"] == "video":
                from . import facebook_limits
                defer_at = facebook_limits.next_slot(c, account["external_id"], now, job["id"])
                if defer_at:
                    allowed, reason = False, facebook_limits.REASON
            if not allowed:
                if job["reason"] != reason or defer_at and job["next_attempt_at"] != defer_at.isoformat():
                    s.put(c, "delivery", {**job, "reason": reason, **({"next_attempt_at": defer_at.isoformat()} if defer_at else {})},
                          actor=WORKER, action="dispatch_deferred", expected_version=job["version"])
                continue
            claimed = s.put(c, "delivery", {**job, "status": "sending", "format": item["format"], "attempts": job["attempts"] + 1,
                            "dispatch_phase": "preparing" if callable(getattr(transport, "publish_claimed", None)) else None,
                            "heartbeat_at": now.isoformat(),
                            "claimed_at": now.isoformat(), "claim_token": s.uid("claim"), "reason": "Dispatch in progress", "confirmed_not_sent": False},
                            actor=WORKER, action="dispatch_claimed", expected_version=job["version"])
            s.put(c, "candidate", {**item, "status": "sending"}, actor=WORKER,
                  action="dispatch_claimed", expected_version=item["version"])
            return claimed, account, item
    return None


def run_one(transport, now):
    claimed = _claim(now, transport)
    if not claimed:
        return False
    job, account, item = claimed
    result = {}
    stopped = None
    try:
        if callable(getattr(transport, "publish_claimed", None)):
            result = transport.publish_claimed(account, item, job)
        else:
            result = transport.publish(account, item, job["id"])
        if not isinstance(result, dict) or not result.get("external_id"):
            result = {}
            status, reason = "unknown", "The platform response did not confirm a post ID; reconciliation required"
        else:
            status, reason = (("submitted", "The platform created the post; visible publication still requires confirmation")
                              if result.get("publication_status") == "submitted" else ("published", "Confirmed by platform"))
    except StoppedBeforeSend as exc:
        stopped = exc
        status, reason = ("blocked" if exc.invalidated else "retry"), exc.reason
        job["next_attempt_at"] = (now + timedelta(seconds=getattr(exc, "retry_after", 60))).isoformat()
    except TemporaryRejection as exc:
        status = "retry" if job["attempts"] < MAX_ATTEMPTS else "error"
        reason = "Platform explicitly rejected this attempt; retry limit reached" if status == "error" else "Platform explicitly rejected this attempt; limited retry scheduled"
        try:
            job["next_attempt_at"] = (now + timedelta(seconds=exc.retry_after)).isoformat()
        except OverflowError:
            status, reason = "error", "Provider retry delay cannot be scheduled; no automatic retry"
    except PermanentRejection:
        status, reason = "error", "Platform rejected the release; account or content requires attention"
    except Exception:
        # Includes network timeouts and process interruption after acceptance.
        # Never expose SDK exceptions (they may include tokens or request URLs).
        status, reason = "unknown", "Delivery outcome is unknown; reconcile before any further action"
    with s.connection(write=True) as c:
        current = s.get(c, "delivery", job["id"])
        if current.get("claim_token") != job["claim_token"] or current["status"] not in {"sending", "unknown"}:
            return True
        preparing = current.get("dispatch_phase") == "preparing"
        if status == "unknown" and preparing:
            status = "retry" if job["attempts"] < MAX_ATTEMPTS else "error"
            reason = "Media preparation interrupted before any post request"
            job["next_attempt_at"] = (now + timedelta(seconds=60)).isoformat()
        saved = {**current, "status": status, "reason": reason, "finished_at": now.isoformat(),
                 "next_attempt_at": job["next_attempt_at"], "confirmed_not_sent": bool(stopped) or preparing}
        if isinstance(stopped, PreparationPending):
            saved["attempts"] = max(0, current["attempts"] - 1)
        if status in {"published", "submitted"}:
            saved.update(external_id=str(result["external_id"]), url=str(result.get("url", "")))
            for key in ("external_ids", "provider", "payload_digest"):
                if key in result:
                    saved[key] = result[key]
        saved = s.put(c, "delivery", saved, actor=WORKER, action="dispatch_" + status, expected_version=current["version"])
        candidate = s.get(c, "candidate", item["id"])
        if stopped and stopped.invalidated:
            candidate = {**candidate, "approval": None, "check": {**(candidate.get("check") or {}),
                         "passed": False, "reason": reason, "failures": [reason], "invalidated_at": now.isoformat()}}
            candidate_status = "skipped" if candidate["mode"] == "automatic" else "needs_revision"
        else:
            candidate_status = "scheduled" if isinstance(stopped, PreparationPending) else "error" if status == "retry" else status
        candidate = s.put(c, "candidate", {**candidate, "status": candidate_status}, actor=WORKER,
              action="dispatch_" + status, expected_version=candidate["version"])
        if status == "published":
            incidents.record_publication(c, candidate, saved, account)
    return True


def verify_before_send(release_key, expected_account, expected_item, now, prepared=None, claim_token=None):
    """Revalidate after provider preparation, immediately before the write."""
    with s.connection(write=prepared is not None or claim_token is not None) as c:
        job = s.get(c, "delivery", release_key)
        if claim_token is not None and job.get("claim_token") != claim_token:
            raise StoppedBeforeSend("The dispatch claim is no longer active")
        item = s.get(c, "candidate", job["candidate_id"])
        account = s.get(c, "account", job["account_id"])
        if job["status"] != "sending" or item["status"] != "sending":
            raise StoppedBeforeSend("The dispatch claim is no longer active")
        if (s.get(c, "settings", "pause", required=False) or {}).get("publications"):
            raise StoppedBeforeSend("Publications were paused before the provider request")
        if (s.get(c, "settings", "recovery", required=False) or {}).get("status") == "requires_reconciliation":
            raise StoppedBeforeSend("Restored queue requires reconciliation before publication")
        if any(account[key] != expected_account[key] for key in ("id", "platform", "external_id")):
            raise StoppedBeforeSend("The authorized recipient changed")
        if content.content_digest(item) != content.content_digest(expected_item):
            raise StoppedBeforeSend("Content changed before the provider request", True)
        allowed, reason, invalidated = _preflight(c, job, {**item, "status": "scheduled"}, account, now)
        if not allowed:
            raise StoppedBeforeSend(reason, invalidated)
        if prepared is not None and account["platform"] == "facebook" and item["format"] == "video":
            from math import ceil
            from . import facebook_limits
            next_slot = facebook_limits.next_slot(c, account["external_id"], now, job["id"])
            if next_slot:
                raise PreparationPending(facebook_limits.REASON, max(60, ceil((next_slot - now).total_seconds())))
        if prepared is not None or claim_token is not None:
            value = {**job, "heartbeat_at": now.isoformat()}
            if prepared is not None:
                value.update(dispatch_payload=prepared, dispatch_phase="request_started", provider_requested_at=now.isoformat())
            s.put(c, "delivery", value, actor=WORKER,
                  action="provider_request_prepared" if prepared is not None else "dispatch_preparation_checked", expected_version=job["version"])
        return account


def recover_inflight(now):
    count = 0
    with s.connection(write=True) as c:
        for job in s.list_items(c, "delivery", status="sending"):
            if permissions.timestamp(job.get("heartbeat_at") or job["claimed_at"]) + timedelta(seconds=LEASE_SECONDS) > now:
                continue
            preparing = job.get("dispatch_phase") == "preparing"
            recovered = ({"status": "retry", "reason": "Media preparation interrupted before any post request", "confirmed_not_sent": True,
                          "next_attempt_at": now.isoformat(), "attempts": max(0, job["attempts"] - 1)} if preparing else
                         {"status": "unknown", "reason": "Worker stopped during dispatch; reconciliation required"})
            s.put(c, "delivery", {**job, **recovered},
                  actor=WORKER, action="interrupted_dispatch", expected_version=job["version"])
            item = s.get(c, "candidate", job["candidate_id"])
            s.put(c, "candidate", {**item, "status": "scheduled" if preparing else "unknown"}, actor=WORKER,
                  action="interrupted_dispatch", expected_version=item["version"])
            count += 1
    return count
