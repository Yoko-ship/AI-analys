"""Owner-bounded event selection never turns a reprint into a new release."""
from datetime import timedelta
import json

import pytest

from marketing import agents, content, delivery, goals, sources, store, worker
from marketing.errors import MarketingError
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, CMO, NOW, account, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_sources import article, source_input
from test_marketing_strategy import approve_goal, proposal
from test_marketing_production import ProductionModel
from test_marketing_delivery import Platform
from test_marketing_scheduling import workspace_backend  # noqa: F401
from test_postgres_accounts import pg_store  # noqa: F401


def setup_rule(*, initial_material=True, allowed_rubrics=None, formats=None, languages=None, **changes):
    from marketing import automation
    approve_goal()
    rubrics = allowed_rubrics or ["news", "quarterly", "market", "dividend", "calendar", "digest"]
    plan = goals.save_strategy(OWNER, proposal(rubrics=rubrics), now=NOW)
    plan = goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW)
    account(rubrics=rubrics, formats=formats or ['post'], languages=languages or ['ru'])
    source = sources.save_source(OWNER, "disclosures", source_input(), 0)
    if initial_material:
        sources.import_materials(OWNER, source["id"], [article()], now=NOW)
    data = {"title": "Verified issuer news", "strategy_id": plan["id"], "strategy_version": plan["version"],
            "source_ids": [source["id"]], "target": {"account_id": "tg", "languages": ["ru"], "primary_language": "ru", "format": "post"},
            "rubric": "news", "starts_on": "2026-11-23", "ends_on": "2026-11-29", "max_daily": 2,
            "max_age_hours": 48, "mode": "draft", "priority": "normal", "enabled": True, **changes}
    rule = automation.save(OWNER, "issuer-news", data, 0, now=NOW)
    return rule


def verified(key="original", **changes):
    sources.import_materials(OWNER, "disclosures", [article(key, **{"destination_url": "https://uzstock.uz/news/123", **changes})], now=NOW)
    with store.connection() as c:
        original = store.get(c, "evidence", store.digest(["disclosures", key]))
    return sources.verify_evidence(OWNER, original["id"], original["version"], "Compared the original signed disclosure")


def rows(kind):
    with store.connection() as c:
        return store.list_items(c, kind)


def update_rule(rule, **changes):
    from marketing import automation
    data = {key: rule[key] for key in automation.Rule.model_fields}
    return automation.save(OWNER, rule["id"], {**data, **changes}, rule["version"], now=NOW)


def test_only_owner_can_enable_selection_within_a_current_approved_strategy():
    from marketing import automation
    rule = setup_rule()
    data = {key: rule[key] for key in automation.Rule.model_fields}
    with pytest.raises(MarketingError) as denied:
        automation.save(CMO, rule["id"], data, rule["version"], now=NOW)
    assert denied.value.status == 403
    for change in ({"rubric": "product"}, {"strategy_version": 1}, {"ends_on": "2027-01-01"},
                   {"rubric": "quarterly", "priority": "urgent"}):
        with pytest.raises((MarketingError, ValueError)):
            update_rule(rule, **change)
    assert rows("task") == [] and rows("delivery") == []


@pytest.mark.parametrize("rubric", ["education", "holiday", "product"])
def test_single_event_rule_does_not_offer_a_pack_that_requires_other_editorial_inputs(rubric):
    from marketing import automation
    rule = setup_rule(enabled=False)
    with pytest.raises(ValueError):
        update_rule(rule, rubric=rubric)


def analysis_source(report):
    from marketing import source_adapters
    from reporting import store as reports
    reports.record_report(report)
    source = sources.save_source(OWNER, "analysis", source_input(method="internal_analysis"), 0)
    sources.enable_source(OWNER, source["id"], source["version"])
    assert sources.collect_one(source_adapters.fetch, NOW)


def quarterly_report(**changes):
    from test_marketing_source_adapters import ready_report
    report = ready_report(**changes)
    report["verified_facts"].append({**report["verified_facts"][0], "metric_code": "total_assets", "raw": 1200,
                                     "source_original_line": "Активы"})
    return report


@pytest.mark.parametrize("age_hours,expected", [(0, True), (72, False)])
def test_quarter_selection_uses_published_analysis_freshness_not_the_filing_date(age_hours, expected):
    from marketing import automation
    from reporting.links import url
    report = quarterly_report(generated_at=(NOW - timedelta(hours=age_hours)).isoformat())
    analysis_source(report)
    rule = setup_rule(rubric="quarterly", source_ids=["analysis"], max_age_hours=48)
    assert automation.run_one(NOW) is expected
    if not expected:
        assert rows("task") == []
        return
    task, = rows("task")
    assert task["production"]["period"] == "2026Q3"
    assert task["production"]["entity"] == "HMKB"
    assert task["production"]["destination_url"] == url(report)
    assert task["editorial"]["rule_id"] == rule["id"]
    original = next(item for item in rows("evidence") if item["id"] in task["evidence_versions"])
    assert original["period"] == "2026-09-30"
    assert original["published_at"].startswith("2026-10-25")
    assert not automation.run_one(NOW)


def test_quarter_selection_stops_when_the_selected_published_analysis_is_replaced():
    from marketing import automation
    from reporting import store as reports
    report = quarterly_report()
    analysis_source(report)
    setup_rule(rubric="quarterly", source_ids=["analysis"])
    assert automation.run_one(NOW)
    reports.record_report(quarterly_report(version="corrected-published-analysis"))
    model = Model([output("Must not process the replaced report")])
    assert not agents.run_one(model, NOW)
    assert not model.calls and rows("task")[0]["status"] == "blocked"


def test_quarter_selection_does_not_merge_distinct_periods_with_one_original_url():
    from marketing import automation, source_adapters
    from reporting import store as reports
    half = quarterly_report(version="report-hmkb-q2", period="2026Q2", financial_as_of="2026-06-30")
    for fact in half["verified_facts"]:
        fact["period_end"] = "2026-06-30"
    analysis_source(half)
    setup_rule(rubric="quarterly", source_ids=["analysis"], max_daily=2, max_age_hours=48)
    assert automation.run_one(NOW)
    reports.record_report(quarterly_report())
    assert sources.collect_one(source_adapters.fetch, NOW + timedelta(hours=1))
    assert automation.run_one(NOW + timedelta(hours=1))
    tasks = rows("task")
    assert {task["production"]["period"] for task in tasks} == {"2026Q2", "2026Q3"}
    assert len({task["production"]["event_id"] for task in tasks}) == 2


def test_quarter_selection_records_an_unavailable_report_store_and_continues_other_rules(monkeypatch):
    from marketing import automation
    from reporting import store as reports
    analysis_source(quarterly_report())
    quarter = setup_rule(rubric="quarterly", source_ids=["analysis"])
    verified()
    data = {key: quarter[key] for key in automation.Rule.model_fields}
    automation.save(OWNER, "other-news", {**data, "rubric": "news", "source_ids": ["disclosures"]}, 0, now=NOW)
    def unavailable(version):
        raise OSError("Controlled report database outage")
    monkeypatch.setattr(reports, "get_run", unavailable)
    assert automation.run_one(NOW)
    assert rows("task")[0]["production"]["rubric"] == "news"
    runtime = next(row for row in rows("editorial_runtime") if row["id"] == quarter["id"])
    assert runtime["status"] == "blocked" and "analysis store" in runtime["reason"]


def test_quarter_regeneration_does_not_make_a_previously_available_analysis_new():
    from marketing import automation, source_adapters
    from reporting import store as reports
    analysis_source(quarterly_report(generated_at=(NOW - timedelta(days=3)).isoformat()))
    setup_rule(rubric="quarterly", source_ids=["analysis"], max_age_hours=48)
    later = NOW + timedelta(hours=1)
    reports.record_report(quarterly_report(version="fresh-commentary-old-quarter", generated_at=later.isoformat()))
    assert sources.collect_one(source_adapters.fetch, later)
    assert not automation.run_one(later)
    assert rows("task") == []


def test_worker_requires_verified_original_and_creates_one_pinned_scoped_task():
    from marketing import automation
    rule = setup_rule()
    assert not automation.run_one(NOW)
    original = verified()
    assert automation.run_one(NOW)
    assert not automation.run_one(NOW)
    task, = rows("task")
    assert task["requested_by"] == "coordinator"
    assert task["production"]["mode"] == "draft"
    assert task["production"]["targets"][0]["account_id"] == "tg"
    assert task["evidence_versions"] == {original["id"]: original["version"]}
    assert task["editorial"]["rule_id"] == rule["id"] and task["editorial"]["rule_version"] == rule["version"]
    assert rows("delivery") == []


def test_transitive_reprints_and_new_canonical_keys_cannot_restart_an_assigned_event():
    from marketing import automation
    setup_rule()
    verified()
    assert automation.run_one(NOW)
    verified("reprint", canonical_event_id="alternate-key", published_at=NOW.isoformat(), event_at=NOW.isoformat())
    verified("reprint-two", canonical_event_id="alternate-key", url="https://openinfo.uz/facts/other", published_at=NOW.isoformat())
    assert not automation.run_one(NOW)
    assert len(rows("task")) == 1


@pytest.mark.parametrize("old_status", ["verified", "unverified"])
def test_current_reprint_does_not_make_an_old_original_fresh(old_status):
    from marketing import automation
    setup_rule(priority="urgent", max_age_hours=24)
    sources.import_materials(OWNER, "disclosures", [article(event_at="2026-10-20T08:00:00Z", published_at="2026-10-20T08:00:00Z")], now=NOW)
    if old_status == "verified":
        with store.connection() as c:
            first, = store.list_items(c, "evidence")
        sources.verify_evidence(OWNER, first["id"], first["version"], "Compared original")
    verified("new-copy", canonical_event_id="new-key", event_at=NOW.isoformat(), published_at=NOW.isoformat())
    assert not automation.run_one(NOW)
    assert rows("task") == []


def test_daily_limit_and_pause_apply_while_independent_events_continue_next_local_day():
    from marketing import automation
    rule = setup_rule(max_daily=1, max_age_hours=96)
    verified()
    verified("other", canonical_event_id="decision-other", url="https://openinfo.uz/facts/456")
    delivery.set_pause(OWNER, processing=True)
    assert not automation.run_one(NOW)
    delivery.set_pause(OWNER, processing=False)
    assert automation.run_one(NOW)
    assert not automation.run_one(NOW + timedelta(hours=10))  # still November 23 in Tashkent
    assert automation.run_one(NOW + timedelta(hours=12))
    assert len(rows("task")) == 2
    update_rule(rule, enabled=False)
    assert not automation.run_one(NOW + timedelta(days=1))


@pytest.mark.parametrize("when", ["before_claim", "during_model"])
def test_revised_selected_evidence_blocks_work_before_accepting_model_results(when):
    from marketing import automation
    setup_rule()
    verified()
    automation.run_one(NOW)
    def change_original():
        sources.import_materials(OWNER, "disclosures", [article(excerpt="The original was corrected")], now=NOW)
    if when == "before_claim":
        change_original()
    class ChangingModel(Model):
        def complete_json(self, *args, **kwargs):
            if when == "during_model":
                change_original()
            return super().complete_json(*args, **kwargs)
    model = ChangingModel([output("Based on the original version")])
    agents.run_one(model, NOW)
    task, = rows("task")
    assert task["status"] == "blocked" and task["outputs"] == []
    assert len(model.calls) == (1 if when == "during_model" else 0)
    assert not automation.run_one(NOW)


def test_rule_can_be_disabled_after_goal_changes_and_old_work_cannot_run():
    from marketing import automation
    rule = setup_rule()
    verified()
    automation.run_one(NOW)
    old = goals.active_goal()
    data = {key: old[key] for key in goals.Goal.model_fields}
    new = goals.save_goal(OWNER, {**data, "target": 150}, old["version"])
    goals.approve_goal(OWNER, new["version"])
    disabled = update_rule(rule, enabled=False)
    assert disabled["enabled"] is False
    model = Model([output("Should not be requested")])
    assert not agents.run_one(model, NOW)
    assert rows("task")[0]["status"] == "blocked" and not model.calls


def test_worker_collects_and_assigns_without_an_open_browser():
    setup_rule()
    verified()
    model = Model([output("Read the selected original")])
    result = worker.tick(model=model, transport=Platform(), now=NOW)
    assert result["editorial_work"] and result["model_work"]
    assert len(model.calls) == 1 and rows("task")[0]["step"] == 1


def test_new_contradictory_original_blocks_the_existing_assignment():
    from marketing import automation
    setup_rule()
    verified()
    automation.run_one(NOW)
    verified("correction", data={"dividend": 150}, url="https://openinfo.uz/facts/corrected")
    model = Model([output("Must not ignore the second original")])
    assert not agents.run_one(model, NOW)
    assert rows("task")[0]["status"] == "blocked" and not model.calls


class SelectedOriginalModel(ProductionModel):
    """The existing controlled model, citing the actual selected source IDs."""
    def complete_json(self, system, user, **options):
        value = super().complete_json(system, user, **options)
        context = json.loads(user)
        for draft in value.get("drafts", []):
            key = context["evidence"][0]["id"]
            draft["evidence_ids"] = [key]
            for claim in draft["claims"]:
                claim["evidence_id"] = key
        return value


class QuarterlyModel(ProductionModel):
    def __init__(self, *, quarter_wording=False):
        super().__init__()
        self.quarter_wording = quarter_wording

    def complete_json(self, system, user, **options):
        value = super().complete_json(system, user, **options)
        context = json.loads(user)
        for draft in value.get("drafts", []):
            original = next(row for row in context["evidence"] if row["period"] == "2026-09-30")
            period = "III квартал" if self.quarter_wording else "девять месяцев"
            draft.update(title="HMKB · разбор отчётности", body=f"Чистая прибыль за {period} — 900 тыс. сум. Активы на 30 сентября — 1200 тыс. сум.",
                         evidence_ids=[original["id"]], destination_url=context["production"]["destination_url"],
                         claims=[{"evidence_id": original["id"], "field": field, "value": number, "unit": "thousand UZS"}
                                 for field, number in (("net_income", 900), ("total_assets", 1200))])
        return value


@pytest.mark.parametrize("quarter_wording,expected", [(False, "ready"), (True, "skipped")])
def test_selected_quarter_analysis_cannot_label_nine_month_profit_as_one_quarter(quarter_wording, expected):
    from marketing import automation
    report = quarterly_report()
    for fact in report["verified_facts"]:
        fact.update(period_start="2026-01-01", period_kind="cumulative",
                    comparison_basis="opening" if fact["metric_code"] == "total_assets" else "previous")
    analysis_source(report)
    setup_rule(rubric="quarterly", source_ids=["analysis"], mode="account")
    assert automation.run_one(NOW)
    model = QuarterlyModel(quarter_wording=quarter_wording)
    for _ in range(8):
        assert agents.run_one(model, NOW)
    item, = rows("candidate")
    assert item["status"] == expected, item["check"]
    assert rows("delivery") == []


@pytest.mark.parametrize("changed", ["login", "rule", "original"])
def test_explicit_owner_release_of_rule_drafts_preserves_editorial_guards(changed):
    from marketing import automation
    rule = setup_rule()
    verified(data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})
    assert automation.run_one(NOW)
    for _ in range(8):
        assert agents.run_one(SelectedOriginalModel(), NOW)
    item, = rows("candidate")
    assert item["status"] == "draft" and item["check"]["passed"]
    target, = rows("account")
    connected = delivery.record_connection("tg", target["version"], external_id=target["external_id"], verified=True, now=NOW)
    if changed == "rule":
        update_rule(rule, enabled=False)
    if changed == "original":
        verified("correction", url="https://openinfo.uz/facts/corrected", data={"dividend": 150})
    released = content.release_draft(OWNER, item["id"], item["version"], connected["version"], NOW)
    assert released["status"] == ("ready" if changed == "login" else "skipped"), released["check"]
    assert rows("delivery") == []
    if changed == "login":
        delivery.record_connection("tg", connected["version"], external_id=connected["external_id"], verified=True, now=NOW)
        assert content.check_candidate(item["id"], NOW)["status"] == "ready"
        delivery.schedule(item["id"], NOW)
        update_rule(rule, enabled=False)
        transport = Platform()
        assert not delivery.run_one(transport, NOW) and not transport.calls
        assert rows("candidate")[0]["status"] == "skipped"


def make_priority_pair():
    from marketing import automation
    rule = setup_rule(mode="account", max_daily=1)
    target, = rows("account")
    delivery.record_connection("tg", target["version"], external_id=target["external_id"], verified=True, now=NOW)
    facts = {"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"}
    verified(data=facts)
    assert automation.run_one(NOW)
    normal, = rows("task")
    verified("urgent", canonical_event_id="urgent-decision", event_at="2026-11-23T07:00:00Z", published_at="2026-11-23T07:30:00Z",
             url="https://openinfo.uz/facts/789", data=facts)
    data = {key: rule[key] for key in automation.Rule.model_fields}
    urgent = automation.save(OWNER, "urgent-news", {**data, "priority": "urgent", "max_age_hours": 24}, 0, now=NOW)
    assert automation.run_one(NOW)
    return rule, urgent, normal


def test_urgent_verified_news_precedes_ordinary_model_work_and_cannot_bypass_release_window_or_interval():
    _, _, normal = make_priority_pair()
    model = SelectedOriginalModel()
    assert agents.run_one(model, NOW)
    assert model.calls[0][1]["production"]["event_id"] == "urgent-decision"
    for _ in range(15):
        assert agents.run_one(model, NOW)
    items = rows("candidate")
    assert len(items) == 2 and all(item["status"] == "ready" for item in items)
    old = next(item for item in items if item["origin_task"] == normal["id"])
    urgent = next(item for item in items if item["id"] != old["id"])
    delivery.schedule(old["id"], NOW)
    delivery.schedule(urgent["id"], NOW)
    transport = Platform()
    assert not delivery.run_one(transport, NOW + timedelta(hours=8))  # 21:00 Tashkent
    assert not transport.calls
    next_window = NOW + timedelta(hours=20)
    assert delivery.run_one(transport, next_window)
    assert transport.calls[0][1] == urgent["id"]
    assert not delivery.run_one(transport, next_window + timedelta(minutes=29))
    assert delivery.run_one(transport, next_window + timedelta(minutes=30))
    assert transport.calls[1][1] == old["id"]


@pytest.mark.parametrize("stage", ["before_check", "before_schedule", "before_dispatch", "during_preparation"])
def test_revoked_rule_invalidates_even_previously_accepted_production(stage):
    from marketing import automation
    rule = setup_rule(mode="account")
    target, = rows("account")
    delivery.record_connection("tg", target["version"], external_id=target["external_id"], verified=True, now=NOW)
    verified(data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})
    automation.run_one(NOW)
    model = SelectedOriginalModel()
    for _ in range(8):
        assert agents.run_one(model, NOW)
    item, = rows("candidate")
    assert item["status"] == "ready"
    if stage in {"before_dispatch", "during_preparation"}:
        delivery.schedule(item["id"], NOW)
    if stage != "during_preparation":
        update_rule(rule, enabled=False)
    transport = Platform()
    if stage == "before_check":
        item = content.check_candidate(item["id"], NOW)
    elif stage == "before_schedule":
        with pytest.raises(MarketingError):
            delivery.schedule(item["id"], NOW)
        assert not rows("delivery") and rows("candidate")[0]["status"] == "skipped"
        return
    elif stage == "during_preparation":
        class PreparingPlatform(Platform):
            def publish_claimed(self, account, candidate, job):
                update_rule(rule, enabled=False)
                delivery.verify_before_send(job['id'], account, candidate, NOW, claim_token=job['claim_token'])
                return self.publish(account, candidate, job['id'])
        transport = PreparingPlatform()
        assert delivery.run_one(transport, NOW)
        item, = rows("candidate")
    else:
        assert not delivery.run_one(transport, NOW)
        item, = rows("candidate")
    assert item["status"] == "skipped" and not item["check"]["passed"] and not transport.calls
    assert not automation.run_one(NOW)


def test_failed_automatic_material_is_terminal_but_next_independent_event_continues():
    from marketing import automation
    setup_rule(mode="account")
    verified(data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})
    automation.run_one(NOW)
    model = SelectedOriginalModel(reject="tg")
    for _ in range(8):
        agents.run_one(model, NOW)
    rejected, = rows("candidate")
    assert rejected["status"] == "skipped"
    assert not automation.run_one(NOW)
    verified("independent", canonical_event_id="other-event", url="https://openinfo.uz/facts/independent",
             data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})
    assert automation.run_one(NOW)
    for _ in range(8):
        agents.run_one(SelectedOriginalModel(), NOW)
    assert sorted(item["status"] for item in rows("candidate")) == ["ready", "skipped"]
    assert len(rows("task")) == 2


@pytest.mark.parametrize("workspace_backend", ["sqlite", "postgres"], indirect=True)
def test_two_workers_cannot_select_the_same_event_twice(workspace_backend):
    from concurrent.futures import ThreadPoolExecutor
    from marketing import automation
    setup_rule()
    verified()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: automation.run_one(NOW), range(2)))
    assert sum(results) == 1 and len(rows("task")) == 1


def test_revised_publication_date_cannot_turn_the_same_old_original_into_urgent_news():
    from marketing import automation
    setup_rule(priority="urgent", max_age_hours=24)
    verified(event_at="2026-10-20T08:00:00Z", published_at="2026-10-20T08:00:00Z")
    verified(event_at="2026-11-23T07:00:00Z", published_at="2026-11-23T07:30:00Z", excerpt="A republished copy with updated dates")
    assert not automation.run_one(NOW)
    assert rows("task") == []


@pytest.mark.parametrize("offset", [-1, 7])
def test_rule_does_not_assign_outside_its_tashkent_dates(offset):
    from marketing import automation
    setup_rule()
    verified()
    assert not automation.run_one(NOW + timedelta(days=offset))
    assert not rows("task")
    assert rows("editorial_runtime")[0]["status"] == ("waiting" if offset < 0 else "expired")


@pytest.mark.parametrize("rubric,data,units,body", [
    ("market", {"session_complete": True, "trade_date": "2026-11-23", "turnover": 1200, "trades": 10}, {"turnover": "UZS", "trades": "trades"},
     "Объём торгов 1200 сум; сделок 10."),
    ("dividend", {"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"}, {"dividend": "UZS/share"},
     "Утверждено 120 сум на простую акцию."),
    ("calendar", {"event_type": "meeting"}, {}, "Объявлено собрание акционеров."),
])
def test_supported_individual_event_rubrics_produce_checked_account_candidates(rubric, data, units, body):
    from marketing import automation
    setup_rule(rubric=rubric, mode="account")
    original = verified(suggested_rubric=rubric, data=data, units=units, excerpt=body,
                        event_at=(NOW + timedelta(days=1) if rubric == "calendar" else NOW - timedelta(hours=1)).isoformat(),
                        period="2026-11-23" if rubric == "market" else "")
    assert automation.run_one(NOW)
    class EventModel(SelectedOriginalModel):
        def complete_json(self, system, user, **options):
            result = super().complete_json(system, user, **options)
            for draft in result.get("drafts", []):
                draft.update(title="Подтверждённое событие", body=body,
                             claims=[{"evidence_id": original["id"], "field": field, "value": value, "unit": units.get(field, "")}
                                     for field, value in data.items() if field not in {"session_complete", "trade_date"}])
            return result
    for _ in range(8):
        assert agents.run_one(EventModel(), NOW)
    item, = rows("candidate")
    assert item["rubric"] == rubric and item["status"] == "ready", item["check"]
    assert not rows("delivery")


def test_oversized_original_bundle_cannot_stop_an_independent_event_or_worker_cycle():
    from marketing import automation
    rule = setup_rule()
    for index in range(5):
        verified("original" if index == 0 else f"long-{index}", excerpt="Original text. " * 1300,
                 url=f"https://openinfo.uz/facts/long-{index}")
    verified("independent", canonical_event_id="independent-event", url="https://openinfo.uz/facts/independent",
             event_at="2026-11-23T07:00:00Z")
    result = worker.tick(model=Model([output("The independent event continues")]), transport=Platform(), now=NOW)
    assert result["editorial_work"] and result["model_work"]
    task, = rows("task")
    assert task["production"]["event_id"] == "independent-event"
    assert not automation.run_one(NOW)
    runtime, = rows("editorial_runtime")
    assert runtime["status"] == "blocked" and "shorter source" in runtime["reason"]
    with store.connection() as c:
        history = store.history(c, "editorial_runtime", rule["id"])
    assert not automation.run_one(NOW)
    with store.connection() as c:
        assert store.history(c, "editorial_runtime", rule["id"]) == history
    assert not rows("delivery")


@pytest.mark.parametrize("destination", ["", "https://uzstock.uz/news/another-decision"])
def test_selected_event_cannot_publish_a_model_invented_or_unrelated_destination(destination):
    from marketing import automation
    setup_rule(mode="account")
    verified(destination_url=destination, data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"})
    assert automation.run_one(NOW)
    model = SelectedOriginalModel()  # Emits /news/123, independently of the selected original's destination.
    for _ in range(8):
        assert agents.run_one(model, NOW)
    item, = rows("candidate")
    assert item["status"] == "skipped" and not item["check"]["passed"]
    assert "destination" in item["check"]["reason"].lower()
    with pytest.raises(MarketingError):
        delivery.schedule(item["id"], NOW)
    assert not rows("delivery") and not automation.run_one(NOW)
