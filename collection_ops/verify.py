"""Release check: the installed host monitor must publish fresh API observations."""
from __future__ import annotations

import argparse
import json
import time

from collection_ops.model import parse_time
from collection_ops.registry import JOBS


def require_fresh_reports(overview, since):
    if not overview.get("observer", {}).get("online"):
        raise RuntimeError("Collection monitor is offline; inspect its service journal.")
    items = {item["id"]: item for item in overview.get("items", [])}
    for job in JOBS:
        item = items.get(job, {})
        observed = parse_time(item.get("observed_at"))
        if not observed or item.get("schedule_issue") == "monitor_offline":
            raise RuntimeError(f"No fresh collection monitor report for {job}.")
        if observed < since:
            raise RuntimeError(f"Collection monitor report for {job} is from before this check.")
        if item.get("latest", {}).get("load_state") != "loaded":
            raise RuntimeError(f"Collection service is not installed: {job}.")
    return {"monitor_online": True, "observed_jobs": len(JOBS),
            "last_seen": overview["observer"]["last_seen"]}


def exercise_manual_run(store, job, *, timeout=600):
    current = next(item for item in store.overview()["items"] if item["id"] == job)
    if not current["can_run"]:
        raise RuntimeError(f"{job} is unavailable or already has an active run/request; no test submitted.")
    # An explicitly requested root-shell check uses the same durable queue as the
    # admin button. Actor 0 identifies an operator, not a browser user or session.
    request = store.enqueue(job, actor_id=0)
    print(json.dumps({"job": job, "request_id": request["id"], "status": request["status"]}), flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next(item for item in store.overview()["items"] if item["id"] == job)
        tracked = next((r for r in current["requests"] if r["id"] == request["id"]), None)
        if tracked and tracked["status"] == "finished":
            run = store.read_run(job, tracked["invocation"])
            if run["status"] not in ("completed", "no_change"):
                raise RuntimeError(f"Manual collection finished with {run['status']}: {run['reason']}")
            if run["publication"] != "acknowledged" and run["status"] != "no_change":
                raise RuntimeError("Manual collection exited successfully without a confirmed publication receipt.")
            return {"job": job, "request_id": request["id"], "invocation": tracked["invocation"],
                    "status": run["status"], "publication": run["publication"]}
        if tracked and tracked["status"] in ("failed", "uncertain", "expired", "cleared"):
            raise RuntimeError(f"Manual collection {tracked['status']}: {tracked['detail']}")
        time.sleep(5)
    raise RuntimeError(f"Manual collection result not confirmed in {timeout}s; inspect request {request['id']} before retrying.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="UTC time immediately before starting the monitor")
    parser.add_argument("--exercise", choices=["bank-fx"], help="Explicitly enqueue one bank FX collection and verify its result")
    args = parser.parse_args(argv)
    since = parse_time(args.since)
    if since is None:
        parser.error("--since must be an ISO timestamp")
    # Run inside the existing web container, against its actual catalog database.
    from collection_ops import store
    print(json.dumps(require_fresh_reports(store.overview(), since)))
    if args.exercise:
        print(json.dumps(exercise_manual_run(store, args.exercise)))


if __name__ == "__main__":
    main()
