import json

import pytest

from marketing import agents, store, worker
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401


@pytest.mark.parametrize("provider", ["injected", "codex_gateway"])
def test_worker_processes_a_saved_task_without_an_open_browser(monkeypatch, provider):
    task = agents.start(OWNER, kind="dialogue", message="Explain the next baseline measurement")
    reply = output("Measure confirmed report opens")
    model = Model([reply])
    if provider == "codex_gateway":
        from fastapi.testclient import TestClient
        import codex_client
        import codex_gateway

        monkeypatch.delenv("MARKETING_MODEL_PROVIDER", raising=False)
        monkeypatch.delenv("MARKETING_MODEL", raising=False)
        monkeypatch.setenv("NEWS_AI_PROVIDER", "codex")
        monkeypatch.setenv("NEWS_CODEX_GATEWAY_URL", "http://codex.internal:8080")
        monkeypatch.setenv("CODEX_GATEWAY_SECRET", "test-gateway-secret")
        monkeypatch.setattr(worker.model_runtime.shutil, "which", lambda _name: None)
        monkeypatch.setattr(codex_gateway, "_SECRET", "test-gateway-secret")
        monkeypatch.setattr(codex_gateway, "auth_status", lambda **kwargs: {"logged_in": True})
        proxy = TestClient(codex_gateway.app)

        def complete(_self, system, user, **options):
            assert json.loads(user)["message"] == task["message"]
            assert "cmo" in system
            assert options["response_schema"]["required"] == ["result_json"]
            return {"result_json": json.dumps(reply)}

        def post(url, **options):
            assert url == "http://codex.internal:8080/v1/json"
            return proxy.post("/v1/json", json=options["json"], headers=options["headers"])

        monkeypatch.setattr(codex_client.CodexClient, "complete_json", complete)
        monkeypatch.setattr("requests.post", post)
        model = None
    result = worker.tick(model=model, now=NOW)
    assert result["model_work"]
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete"
        assert saved["outputs"][0]["result"]["summary"] == reply["summary"]
        assert store.list_items(c, "delivery") == []
        assert store.get(c, "runtime", "worker")["last_completed_at"] == NOW.isoformat()


def test_worker_collects_authorized_sources_and_respects_processing_pause():
    from marketing import delivery, sources
    from test_marketing_sources import source_input, article
    source = sources.save_source(OWNER, "news", source_input(), 0)
    sources.enable_source(OWNER, source["id"], source["version"])
    calls = []
    def fetch(source):
        calls.append(source["id"])
        return [article()]
    delivery.set_pause(OWNER, processing=True)
    assert not worker.tick(fetch=fetch, now=NOW)["source_work"]
    assert calls == []
    delivery.set_pause(OWNER, processing=False)
    assert worker.tick(fetch=fetch, now=NOW)["source_work"]
    assert calls == ["news"]
    with store.connection() as c:
        assert len(store.list_items(c, "topic")) == 1


def test_worker_freezes_closed_week_once_after_owner_opt_in_and_obeys_pause():
    from marketing import reports, delivery
    reports.save_settings(OWNER, {"automatic_weekly": True}, 0)
    delivery.set_pause(OWNER, processing=True)
    assert not worker.tick(now=NOW)["report_work"]
    delivery.set_pause(OWNER, processing=False)
    assert worker.tick(now=NOW)["report_work"]
    assert not worker.tick(now=NOW)["report_work"]
    with store.connection() as c:
        assert len(store.list_items(c, "snapshot")) == 1
