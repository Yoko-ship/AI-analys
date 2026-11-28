from marketing import agents, store, worker
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401


def test_worker_processes_a_saved_task_without_an_open_browser():
    task = agents.start(OWNER, kind="dialogue", message="Explain the next baseline measurement")
    result = worker.tick(model=Model([output("Measure confirmed report opens")]), now=NOW)
    assert result["model_work"]
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "complete"
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
