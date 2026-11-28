from marketing import content, sources, source_adapters, store
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401
from test_marketing_sources import source_input, article
from test_marketing_source_adapters import ready_report
import pytest


def quarter(**changes):
    return candidate("quarter", rubric="quarterly", analysis_ready=True, period="2026Q3", evidence_ids=["filing"],
        body="Чистая прибыль 900; активы 1200 тыс. сум.", claims=[
            {"evidence_id": "filing", "field": "net_income", "value": 900, "unit": "thousand UZS"},
            {"evidence_id": "filing", "field": "total_assets", "value": 1200, "unit": "thousand UZS"}], **changes)


def test_browser_analysis_ready_flag_cannot_substitute_for_a_published_uzstock_report():
    account()
    evidence("filing", data={"net_income": 900, "total_assets": 1200}, units={"net_income": "thousand UZS", "total_assets": "thousand UZS"},
             period="2026-09-30", standard="nsbu", scope="separate")
    item = quarter()
    result = content.check_candidate(item["id"], NOW)
    assert result["status"] == "skipped"
    assert "published UZStock analysis" in result["check"]["reason"]


@pytest.mark.parametrize("original_scope", [{}, {"period": "2026-06-30"}, {"standard": "ifrs"},
                                           {"scope": "consolidated"}, {"currency": "USD"}])
def test_quarter_uses_actual_published_report_and_is_rechecked_when_that_report_changes(original_scope):
    from reporting import store as reports
    from marketing import delivery
    from test_marketing_delivery import Platform
    a = account()
    delivery.record_connection("tg", a["version"], external_id=a["external_id"], verified=True, now=NOW)
    report = ready_report()
    report["verified_facts"].append({**report["verified_facts"][0], "metric_code": "total_assets", "raw": 1200})
    reports.record_report(report)
    source = sources.save_source(OWNER, "analysis", source_input(method="internal_analysis"), 0)
    sources.enable_source(OWNER, source["id"], source["version"])
    def collected(source):
        batch = source_adapters.fetch(source)
        batch.materials[0].update(original_scope)
        return batch
    sources.collect_one(collected, NOW)
    with store.connection() as c:
        ev = store.list_items(c, "evidence")[0]
    item = candidate("real-quarter", rubric="quarterly", period="2026Q3", evidence_ids=[ev["id"]],
        body="Чистая прибыль 900; активы 1200 тыс. сум.", destination_url=ev["destination_url"],
        claims=[{"evidence_id": ev["id"], "field": key, "value": value, "unit": "thousand UZS"} for key, value in {"net_income": 900, "total_assets": 1200}.items()])
    checked = content.check_candidate(item["id"], NOW)
    if original_scope:
        assert checked["status"] == "skipped"
        assert "financial scope" in checked["check"]["reason"]
        return
    assert checked["status"] == "ready"
    delivery.schedule(item["id"], NOW)
    reports.record_report({**report, "version": "corrected-report"})
    transport = Platform()
    assert not delivery.run_one(transport, NOW)
    assert transport.calls == []


@pytest.mark.parametrize("query", ["report=ai", "report=airplane", "report=ai&report_standard=nsbu", "report=ai&report_standard=ifrs&report_scope=consolidated&report_lang=uz&report_period=2026Q3&report_version=wrong"])
def test_quarter_rejects_links_that_silently_open_another_analysis(query):
    from marketing import rubric_checks
    from reporting import store as reports
    report = ready_report(standard="ifrs", scope="consolidated", language="uz")
    reports.record_report(report)
    item = {"entity": "HMKB", "period": "2026Q3", "destination_url": "https://uzstock.uz/uz/company/HMKB?" + query, "claims": []}
    assert rubric_checks.quarterly(item, [{"analysis_version": report["version"], "id": "original"}], {"net_income", "total_assets"})


@pytest.mark.parametrize("displayed,expected", [(300, "ready"), (3, "skipped")])
def test_quarter_ordinal_is_a_period_label_without_allowing_an_unchecked_financial_number(displayed, expected):
    from reporting import store as reports
    account()
    report = ready_report()
    original = report["verified_facts"][0]
    original.update(raw=300, period_start="2026-07-01", period_kind="standalone_quarter")
    report["verified_facts"].append({**original, "metric_code": "total_assets", "raw": 1200})
    reports.record_report(report)
    source = sources.save_source(OWNER, "analysis", source_input(method="internal_analysis"), 0)
    sources.enable_source(OWNER, source["id"], source["version"])
    sources.collect_one(source_adapters.fetch, NOW)
    with store.connection() as c:
        ev, = store.list_items(c, "evidence")
    item = candidate("standalone-q3", rubric="quarterly", period="2026Q3", title="HMKB: разбор за 3-й квартал",
        body=f"Чистая прибыль за 3-й квартал — {displayed} тыс. сум. Активы — 1200 тыс. сум.",
        evidence_ids=[ev["id"]], destination_url=ev["destination_url"],
        claims=[{"evidence_id": ev["id"], "field": key, "value": value, "unit": "thousand UZS"}
                for key, value in {"net_income": 300, "total_assets": 1200}.items()])
    result = content.check_candidate(item["id"], NOW)
    assert result["status"] == expected, result["check"]


def test_market_requires_complete_closed_session_and_explicit_totals():
    account(rubrics=["market"])
    evidence(data={"turnover": 120, "trades": 3, "session_complete": False, "trade_date": "2026-11-20"},
             units={"turnover": "UZS", "trades": "trades"})
    item = candidate("incomplete-market", rubric="market", body="Оборот 120 сум, сделок 3.", period="2026-11-20", claims=[
        {"evidence_id": "decision", "field": "turnover", "value": 120, "unit": "UZS"},
        {"evidence_id": "decision", "field": "trades", "value": 3, "unit": "trades"}])
    assert content.check_candidate(item["id"], NOW)["status"] == "skipped"
    evidence("closed", data={"turnover": 120, "trades": 3, "session_complete": True, "trade_date": "2026-11-20"}, units={"turnover": "UZS", "trades": "trades"})
    valid = candidate("complete-market", rubric="market", body="Оборот 120 сум, сделок 3.", period="2026-11-20", evidence_ids=["closed"], claims=[
        {"evidence_id": "closed", "field": "turnover", "value": 120, "unit": "UZS"},
        {"evidence_id": "closed", "field": "trades", "value": 3, "unit": "trades"}])
    assert content.check_candidate(valid["id"], NOW)["status"] == "ready"


@pytest.mark.parametrize("identity", ["canonical", "original_url", "transitive"])
def test_digest_requires_distinct_events_instead_of_two_reprints(identity):
    account(rubrics=["digest"])
    source = sources.save_source(OWNER, "manual", source_input(method="manual"), 0)
    materials = [article(), article("reprint", url="https://media.test/reprint")]
    if identity != "canonical":
        materials[1].update(canonical_event_id="media-copy-123", url=materials[0]["url"])
    if identity == "transitive":
        materials.append(article("third-copy", canonical_event_id="media-copy-123", url="https://media.test/reprint"))
    sources.import_materials(OWNER, source["id"], materials, NOW)
    with store.connection() as c:
        records = store.list_items(c, "evidence")
    for item in records:
        sources.verify_evidence(OWNER, item["id"], item["version"], "Checked original")
    item = candidate("digest", rubric="digest", evidence_ids=[ev["id"] for ev in records], claims=[], body="Два сообщения об одном решении.")
    assert content.check_candidate(item["id"], NOW)["status"] == "skipped"


def test_dividend_requires_security_class_and_cannot_turn_approval_into_payment():
    account(rubrics=["dividend"])
    evidence(data={"dividend": 120, "dividend_state": "approved", "share_class": "ordinary"}, units={"dividend": "UZS/share"})
    item = candidate("dividend", rubric="dividend", body="Выплачено 120 сум на простую акцию.")
    assert content.check_candidate(item["id"], NOW)["status"] == "skipped"


def test_calendar_requires_an_announced_future_date_and_event_type():
    account(rubrics=["calendar"])
    evidence(event_at=None, data={"event_type": "meeting"})
    item = candidate("calendar", rubric="calendar", claims=[], body="Ожидается собрание.")
    assert content.check_candidate(item["id"], NOW)["status"] == "skipped"
