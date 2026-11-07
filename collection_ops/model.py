"""Interpret recorded facts conservatively; an exit code is not a publication receipt."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
import re
import uuid

MARKER = "COLLECTION_RECEIPT "
MAX_EVIDENCE = 12000
WRITE_COUNTS = frozenset({"upserted", "inserted", "updated", "replaced", "written", "history", "intraday", "coupons", "key_rate", "ratios"})

def utcnow():
    return datetime.now(timezone.utc)

def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def scrub(value: str, secrets=()) -> str:
    text = str(value)
    private = list(secrets) + [v for k, v in os.environ.items()
        if re.search(r"SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY|DATABASE_URL|DEPLOY_SSH", k, re.I)]
    for secret in sorted(set(private), key=len, reverse=True):
        if len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)", "[redacted key]", text)
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer|basic)?\s*[^\s,;]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(r"""(?ix)((?:[?&]|\b)(?:token|key|password|secret|api[_-]?key|x-admin-secret|access_token)\s*['"]?\s*[:=]\s*['"]?)[^&\s,'"}]+""",
                  r"\1[redacted]", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)

def receipt(stage, *, ok, counts=None, reason="", unchanged=False, phase="collection"):
    """Emit only publication metadata, never rows, response bodies or credentials."""
    event = {"stage": str(stage)[:160], "ok": bool(ok), "phase": phase, "event_id": uuid.uuid4().hex}
    if counts:
        event["counts"] = {str(k)[:60]: v for k, v in counts.items()
                           if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
    if reason:
        event["reason"] = scrub(reason)[:1000]
    if unchanged:
        event["unchanged"] = True
    print(MARKER + json.dumps(event, ensure_ascii=True), flush=True)
    return event

def parse_receipts(lines):
    events = []
    for line in lines:
        if not line.startswith(MARKER):
            continue
        try:
            event = json.loads(line.split(MARKER, 1)[1])
            if isinstance(event, dict) and isinstance(event.get("ok"), bool) and isinstance(event.get("stage"), str):
                events.append(event)
        except (ValueError, TypeError):
            continue
    return events[-100:]

def outcome(observation):
    def clean(value):
        if isinstance(value, str):
            return scrub(value)
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    value = clean(observation)
    receipts = value.get("receipts") or []
    # Meta heartbeat writes prove only that the heartbeat endpoint worked.
    material = [r for r in receipts if r.get("stage") != "heartbeat"]
    failed = [r for r in material if r.get("ok") is False]
    accepted = [r for r in material if r.get("ok") and any(
        k in WRITE_COUNTS and isinstance(n, int) and n > 0 for k, n in (r.get("counts") or {}).items())]
    quiet = [r for r in material if r.get("unchanged") and r.get("ok")]
    publication_errors = [r for r in failed if r.get("phase") != "collection"]
    publication = "partial" if publication_errors and accepted else "failed" if publication_errors else "acknowledged" if accepted else "unverified"
    status, code, reason, stage = "unknown", "not_observed", "No execution has been observed yet.", None
    if value.get("active"):
        status, code, reason = "running", "running", "Collection is still running."
    elif value.get("invocation"):
        result, exit_code = value.get("result"), value.get("exit_code")
        if result not in ("success", "") or exit_code not in (0, None):
            status = "failed"
            code, reason = {
                "timeout": ("timeout", "The service exceeded its time limit."),
                "oom-kill": ("memory_limit", "The service was terminated for exceeding its memory limit."),
                "signal": ("terminated", "The service was terminated by a signal."),
            }.get(result, ("failed", f"The service failed: {result or 'exit-code'}; exit code {exit_code}."))
        elif failed:
            status, code, reason = ("partial" if accepted else "failed"), "publication_failed", failed[-1].get("reason") or "Publication failed."
        elif exit_code == 0:
            status, code, reason = "completed", "completed", "Process completed; publication has not been verified."
            if accepted:
                reason = "The server acknowledged writes. These may include unchanged rows."
            elif quiet:
                status, code, reason = "no_change", "no_change", quiet[-1].get("reason") or "No new data was found."
    if failed:
        stage = failed[-1].get("stage")
        if status == "failed" and code == "failed":
            reason = failed[-1].get("reason") or reason
    evidence = str(value.get("evidence") or "")[-MAX_EVIDENCE:]
    return {**value, "status": status, "reason_code": code, "reason": reason,
            "failed_stage": stage, "publication": publication, "evidence": evidence}
