"""Host-only observer/dispatcher. No Docker socket or command endpoint is exposed to the web.

Run by systemd with Python's standard library. Dispatch intents are fsynced before
starting a service; replay publishes the outcome and never starts it a second time.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.request import Request, ProxyHandler, build_opener

from collection_ops.model import MAX_EVIDENCE, parse_receipts, scrub
from collection_ops.registry import JOBS

PROPERTIES = ("LoadState", "ActiveState", "Result", "ExecMainStatus",
              "InactiveExitTimestamp", "InactiveEnterTimestamp",
              "UnitFileState", "NextElapseUSecRealtime")

def command(args, timeout=12):
    result = subprocess.run(args, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, timeout=timeout, check=True,
                            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"})
    return result.stdout

def properties(unit):
    # The default display drops microseconds. Using that rounded finish time as
    # journalctl's upper bound hides receipts/errors emitted in the final second.
    return dict(line.split("=", 1) for line in command(
        ["systemctl", "show", unit, "--timestamp=us+utc",
         "--property=" + ",".join(PROPERTIES)]).splitlines() if "=" in line)

def system_time(value):
    if not value or value in ("n/a", "0"):
        return None
    for format in ("%a %Y-%m-%d %H:%M:%S.%f %Z", "%a %Y-%m-%d %H:%M:%S %Z"):
        try:
            return datetime.strptime(value, format).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None

def invocation(service):
    # InactiveExitTimestamp changes before ExecStartPre, so even preflight failures
    # get an identity. Unlike InvocationID it remains available after deactivation.
    started = system_time(service.get("InactiveExitTimestamp"))
    return hashlib.sha256(started.encode()).hexdigest()[:32] if started else ""

def observation(job, service, timer, entries):
    messages = [str(entry.get("MESSAGE", "")) for entry in entries]
    active = service.get("ActiveState") in ("activating", "active", "deactivating", "reloading")
    return {
        "job": job.id, "invocation": invocation(service),
        "started_at": system_time(service.get("InactiveExitTimestamp")),
        "finished_at": None if active else system_time(service.get("InactiveEnterTimestamp")),
        "active": active, "load_state": service.get("LoadState", "not-found"),
        "result": service.get("Result", ""), "exit_code": int(service.get("ExecMainStatus") or 0),
        "timer_enabled": timer.get("UnitFileState") in ("enabled", "enabled-runtime"),
        "timer_active": timer.get("ActiveState") == "active",
        "next_run": system_time(timer.get("NextElapseUSecRealtime")),
        "evidence": scrub("\n".join(messages))[-MAX_EVIDENCE:],
        "evidence_truncated": len(entries) >= 600 or sum(map(len, messages)) > MAX_EVIDENCE,
        "receipts": parse_receipts(messages),
    }

def journal(job, service):
    start = system_time(service.get("InactiveExitTimestamp"))
    if not start:
        return []
    # Explicit OR: service-manager messages, service stdout, and Docker's journald tag.
    args = ["journalctl", "--no-pager", "--output=json", "-n", "600", "--since", start]
    if service.get("ActiveState") not in ("activating", "active", "deactivating", "reloading"):
        end = system_time(service.get("InactiveEnterTimestamp"))
        if end:
            args.extend(["--until", end])
    args.extend(["_SYSTEMD_UNIT=" + job.unit, "+", "UNIT=" + job.unit,
                 "+", "SYSLOG_IDENTIFIER=uzstock-" + job.id])
    entries = []
    for line in command(args).splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass
    return entries

def collect():
    items = []
    for job in JOBS.values():
        service = properties(job.unit)
        timer = properties(job.unit.replace(".service", ".timer"))
        try:
            entries = journal(job, service)
        except (subprocess.SubprocessError, OSError) as exc:
            entries = [{"MESSAGE": "Journal unavailable: " + type(exc).__name__}]
        items.append(observation(job, service, timer, entries))
    return items

def persist(path, data):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name != "nt":
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

def dispatch(request, directory):
    job = JOBS.get(request.get("job"))
    if not job or not re.fullmatch(r"[a-f0-9]{1,64}", request.get("id", "")):
        raise ValueError("Unknown collector or request.")
    path = directory / (request["id"] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    result = {"id": request["id"], "status": "uncertain", "invocation": "",
              "detail": "Dispatch outcome not yet confirmed. Check the service before retrying."}
    persist(path, result)
    start_accepted = False
    try:
        before = properties(job.unit)
        if before.get("ActiveState") in ("activating", "active", "deactivating", "reloading"):
            result.update(status="failed", detail="The collector is already running; no second start was submitted.")
        else:
            command(["systemctl", "start", "--no-block", job.unit])
            start_accepted = True
            # systemctl returns after queueing. Wait briefly for the new invocation,
            # without waiting for the collection itself to finish.
            for delay in (0, 0.1, 0.2, 0.4, 0.8):
                if delay:
                    time.sleep(delay)
                after = properties(job.unit)
                current = invocation(after)
                if current and current != invocation(before):
                    result.update(status="dispatched", invocation=current,
                                  detail="Start accepted by systemd; awaiting the run result.")
                    break
    except subprocess.CalledProcessError as exc:
        result.update(status="uncertain" if start_accepted else "failed",
                      detail=scrub(exc.stderr or f"systemctl exited {exc.returncode}")[:2000])
    except (subprocess.TimeoutExpired, OSError) as exc:
        # A timeout can happen after systemd accepted the start. Never retry blindly.
        result.update(detail="Dispatch confirmation unavailable: " + type(exc).__name__)
    persist(path, result)
    return result

def tick(post, directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in sorted(directory.glob("*.json")):
        post("/ack", json.loads(path.read_text(encoding="utf-8")))
        path.unlink()
    post("/report", {"items": collect()})
    request = post("/claim", {}).get("request")
    if request:
        result = dispatch(request, directory)
        post("/ack", result)
        (directory / (request["id"] + ".json")).unlink()

def read_environment(path):
    # Docker's env file contains literal KEY=VALUE lines; do not execute a shell.
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().removeprefix("export ").partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            continue
        value = value.strip()
        if value[:1] in ('"', "'"):
            parts = shlex.split(value, comments=True)
            value = parts[0] if parts else ""
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--api-url", required=True,
                        help="API origin reachable from the host, using its published port")
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/uzstock-collections"))
    args = parser.parse_args(argv)
    # Host-only code: no database driver, project dependencies or registry credentials.
    os.environ.update(read_environment(args.env_file))
    secret = os.environ.get("ADMIN_API_SECRET", "")
    if not secret:
        raise RuntimeError("ADMIN_API_SECRET is not configured for collection monitoring.")
    opener = build_opener(ProxyHandler({}))
    def post(path, body):
        request = Request(args.api_url.rstrip("/") + "/api/admin/collections" + path,
                          data=json.dumps(body).encode(), method="POST",
                          headers={"Content-Type": "application/json", "X-Admin-Secret": secret})
        with opener.open(request, timeout=15) as response:
            return json.load(response)
    import fcntl  # Only the production Linux host runs this entry point.
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state_dir / "agent.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        tick(post, args.state_dir)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
