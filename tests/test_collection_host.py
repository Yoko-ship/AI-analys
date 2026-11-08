"""The host dispatcher uses fixed argv and never repeats an uncertain start."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from collection_ops import host
from collection_ops.registry import JOBS

def test_parse_systemd_records_a_timeout_and_real_next_run():
    service = {"LoadState": "loaded", "ActiveState": "failed", "Result": "timeout",
               "ExecMainStatus": "15", "InactiveExitTimestamp": "Sat 2026-11-07 09:30:00 UTC",
               "InactiveEnterTimestamp": "Sat 2026-11-07 10:00:00 UTC"}
    timer = {"UnitFileState": "enabled", "ActiveState": "active",
             "NextElapseUSecRealtime": "Sat 2026-11-07 13:00:00 UTC"}
    result = host.observation(JOBS["quotes-catchup"], service, timer, [])
    assert result["result"] == "timeout"
    assert result["started_at"] == "2026-11-07T09:30:00+00:00"
    assert result["next_run"] == "2026-11-07T13:00:00+00:00"
    assert result["invocation"]

def test_active_run_and_finished_run_have_the_same_identity():
    properties = {"InactiveExitTimestamp": "Sat 2026-11-07 09:30:00 UTC", "ActiveState": "activating"}
    first = host.observation(JOBS["quotes-catchup"], properties, {}, [])
    properties.update(ActiveState="inactive", InvocationID="")
    second = host.observation(JOBS["quotes-catchup"], properties, {}, [])
    assert first["invocation"] == second["invocation"]


def test_bank_fx_receipt_in_final_fraction_of_second_is_retained(monkeypatch):
    """2026-11-08: 174 writes at 14:00:00.093 disappeared behind --until 14:00:00."""
    from datetime import datetime
    from collection_ops.model import MARKER, outcome

    entries = [
        ("2026-11-08T14:00:00.093000+00:00", {"MESSAGE": MARKER + json.dumps({
            "stage": "/api/admin/bank-fx", "ok": True, "counts": {"upserted": 174}})}),
        # A later invocation within the same second must not contaminate this run.
        ("2026-11-08T14:00:00.900000+00:00", {"MESSAGE": MARKER + json.dumps({
            "stage": "/api/admin/bank-fx", "ok": False, "reason": "next run failed"})}),
    ]

    def command(args, **kwargs):
        if args[0] == "systemctl":
            precise = "--timestamp=us+utc" in args
            return ("LoadState=loaded\nActiveState=inactive\nResult=success\nExecMainStatus=0\n"
                    "InactiveExitTimestamp=Sun 2026-11-08 13:59:56" + (".010000" if precise else "") + " UTC\n"
                    "InactiveEnterTimestamp=Sun 2026-11-08 14:00:00" + (".300000" if precise else "") + " UTC\n")
        until = datetime.fromisoformat(args[args.index("--until") + 1])
        return "\n".join(json.dumps(entry) for stamp, entry in entries if datetime.fromisoformat(stamp) <= until)

    monkeypatch.setattr(host, "command", command)
    job = JOBS["bank-fx"]
    service = host.properties(job.unit)
    result = outcome(host.observation(job, service, {}, host.journal(job, service)))
    assert result["status"] == "completed"
    assert result["publication"] == "acknowledged"
    assert result["receipts"][0]["counts"] == {"upserted": 174}

def test_dispatch_unknown_service_never_executes(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "command", lambda *a, **k: pytest.fail("must not execute"))
    with pytest.raises(ValueError):
        host.dispatch({"id": "abc", "job": "quotes; reboot"}, tmp_path)

def test_start_rechecks_current_service_and_does_not_restart_a_running_job(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "properties", lambda unit: {"ActiveState": "activating"})
    monkeypatch.setattr(host, "command", lambda *a, **k: pytest.fail("must not execute"))
    result = host.dispatch({"id": "abc", "job": "quotes-catchup"}, tmp_path)
    assert result["status"] == "failed"
    assert "running" in result["detail"]

def test_ack_replay_does_not_start_twice(monkeypatch, tmp_path):
    calls = []
    states = iter([{"ActiveState": "inactive", "InactiveExitTimestamp": ""},
                   {"ActiveState": "activating", "InactiveExitTimestamp": "Sat 2026-11-07 10:00:00 UTC"}])
    monkeypatch.setattr(host, "properties", lambda unit: next(states))
    monkeypatch.setattr(host, "command", lambda args, **kw: calls.append(args) or "")
    request = {"id": "abc", "job": "quotes-catchup"}
    first = host.dispatch(request, tmp_path)
    assert first["status"] == "dispatched"
    assert host.dispatch(request, tmp_path) == first
    assert calls == [["systemctl", "start", "--no-block", "uzstock-quotes-catchup.service"]]

def test_process_crash_between_start_and_ack_is_not_automatically_retried(monkeypatch, tmp_path):
    (tmp_path / "abc.json").write_text(json.dumps({"id": "abc", "status": "uncertain",
        "invocation": "", "detail": "Dispatch outcome not yet confirmed."}))
    monkeypatch.setattr(host, "command", lambda *a, **kw: pytest.fail("must not execute"))
    result = host.dispatch({"id": "abc", "job": "quotes-catchup"}, tmp_path)
    assert result["status"] == "uncertain"

def test_unknown_start_outcome_after_timeout_stays_uncertain(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "properties", lambda unit: {"ActiveState": "inactive"})
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("systemctl", 15)
    monkeypatch.setattr(host, "command", timeout)
    assert host.dispatch({"id": "abc", "job": "quotes-catchup"}, tmp_path)["status"] == "uncertain"

def test_agent_replays_outbox_before_claiming_another_request(monkeypatch, tmp_path):
    (tmp_path / "abc.json").write_text(json.dumps({"id": "abc", "status": "failed", "invocation": "", "detail": "service missing"}))
    calls = []
    def post(path, body):
        calls.append((path, body))
        return {"request": None} if path.endswith("/claim") else {"ok": True}
    monkeypatch.setattr(host, "collect", lambda: [])
    host.tick(post, tmp_path)
    assert [path for path, _ in calls] == ["/ack", "/report", "/claim"]
    assert not (tmp_path / "abc.json").exists()

def test_failed_inspection_after_accepted_start_must_not_allow_a_duplicate(monkeypatch, tmp_path):
    calls = []
    def properties(unit):
        if calls:
            raise subprocess.CalledProcessError(1, "systemctl", stderr="D-Bus unavailable")
        return {"ActiveState": "inactive"}
    monkeypatch.setattr(host, "properties", properties)
    monkeypatch.setattr(host, "command", lambda args: calls.append(args) or "")
    assert host.dispatch({"id": "abc", "job": "quotes-catchup"}, tmp_path)["status"] == "uncertain"

def test_dispatch_waits_only_for_confirmation_with_bounded_pacing(monkeypatch, tmp_path):
    delays = []
    monkeypatch.setattr(host.time, "sleep", delays.append)
    monkeypatch.setattr(host, "properties", lambda unit: {"ActiveState": "inactive"})
    monkeypatch.setattr(host, "command", lambda *args: "")
    assert host.dispatch({"id": "abc", "job": "quotes-catchup"}, tmp_path)["status"] == "uncertain"
    assert delays == [0.1, 0.2, 0.4, 0.8]


def test_host_reports_and_claims_through_its_configured_api(monkeypatch, tmp_path):
    """Exercise real HTTP, not a mocked opener that misses host/container ports."""
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.headers.get("X-Admin-Secret"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"request": None} if self.path.endswith("/claim")
                                        else {"ok": True}).encode())

        def log_message(self, *args):
            pass

    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(
        LOCK_EX=2, LOCK_NB=4, flock=lambda *args: None))
    monkeypatch.setattr(host, "collect", lambda: [{"job": "quotes-catchup"}])
    env = tmp_path / ".env"
    env.write_text("ADMIN_API_SECRET=monitor-test-secret\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_API_SECRET", "original-test-value")
    # Proxy variables and the container's push URL must not redirect the host agent.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("FINANCIALS_PUSH_URL", "http://uzstock-web:8000")
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert host.main(["--env-file", str(env), "--state-dir", str(tmp_path / "state"),
                              "--api-url", f"http://127.0.0.1:{server.server_port}/"]) == 0
        finally:
            server.shutdown()
            thread.join()
    assert received == [
        ("/api/admin/collections/report", "monitor-test-secret", {"items": [{"job": "quotes-catchup"}]}),
        ("/api/admin/collections/claim", "monitor-test-secret", {}),
    ]
