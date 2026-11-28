"""Isolated real API adapter for browser acceptance; no live accounts or model."""
import json
import os
import sys
from pathlib import Path

os.environ["MARKETING_DB"] = sys.argv[1]
os.environ["MARKETING_ENVIRONMENT"] = "browser-test"
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ['DATABASE_URL'] = ''
os.environ['DATABASE_PUBLIC_URL'] = ''
os.environ['ADMIN_CONTROL_DB'] = str(Path(sys.argv[1]).with_suffix('.control.sqlite3'))
os.environ['SECTOR_ANALYSIS_DB'] = str(Path(sys.argv[1]).with_suffix('.reports.sqlite3'))
os.environ["MARKETING_MODEL_PROVIDER"] = "disabled"
os.environ.pop("MARKETING_TELEGRAM_BOT_TOKEN", None)
os.environ.pop("MARKETING_ANALYTICS_ID_KEY", None)
for setting in ("MARKETING_CREDENTIAL_KEY", "MARKETING_LINKEDIN_CLIENT_ID", "MARKETING_LINKEDIN_CLIENT_SECRET", "MARKETING_LINKEDIN_REDIRECT_URI",
                "MARKETING_META_APP_ID", "MARKETING_META_APP_SECRET", "MARKETING_META_REDIRECT_URI", "MARKETING_META_FACEBOOK_CONFIG_ID", "MARKETING_META_INSTAGRAM_CONFIG_ID"):
    os.environ.pop(setting, None)
recovery_fixture = Path(sys.argv[1]).with_suffix(".recovered-fixture")
if recovery_fixture.exists():
    os.environ["MARKETING_ENVIRONMENT"] = "browser-recovered"

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from marketing.api import router, owner_gate


def test_owner(request: Request):
    request.state.control_actor = {"id": 1, "role": "administrator"}


app = FastAPI()
app.include_router(router, dependencies=[Depends(test_owner), Depends(owner_gate)])
request = json.loads(sys.argv[2])
from marketing_website import prepare as prepare_website_fixture
website_reader = prepare_website_fixture(request, sys.argv[1])
if request.get('path') == '/api/track/actions':
    assert website_reader == 'postgres', 'Product receipts require the isolated local PostgreSQL fixture'
    import web_analytics
    from product_events_api import router as actions_router
    web_analytics.DATABASE_URL = os.environ['DATABASE_URL']
    app.include_router(actions_router)
meta_fixture = Path(sys.argv[1]).with_suffix(".meta-fixture")
if request["method"] == "VIDEO_DIRECTOR":
    from datetime import datetime, timezone
    from marketing import video_studio
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from test_marketing_video_studio import Director
    video_studio.run_one(Director(), datetime.now(timezone.utc))
    print(json.dumps({"status": 200, "body": {"ok": True}}))
    sys.exit(0)
if request["method"] == "META_CONFIGURE":
    from cryptography.fernet import Fernet
    meta_fixture.write_text(Fernet.generate_key().decode(), encoding="utf-8")
if meta_fixture.exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from pytest import MonkeyPatch
    from datetime import datetime, timezone
    from test_marketing_facebook_reels import ReelPeer
    if request["method"] == "DISPATCH_INSTAGRAM":
        from test_marketing_instagram import InstagramPeer
        meta_peer = InstagramPeer(MonkeyPatch(), now=datetime.now(timezone.utc))
    else:
        meta_peer = ReelPeer(MonkeyPatch(), now=datetime.now(timezone.utc))
    os.environ["MARKETING_CREDENTIAL_KEY"] = meta_fixture.read_text(encoding="utf-8")
linkedin_fixture = Path(sys.argv[1]).with_suffix(".linkedin-fixture")
if request["method"] == "LINKEDIN_CONFIGURE":
    from cryptography.fernet import Fernet
    linkedin_fixture.write_text(Fernet.generate_key().decode(), encoding="utf-8")
if linkedin_fixture.exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from pytest import MonkeyPatch
    from datetime import datetime, timezone
    from test_marketing_linkedin_media import MediaPeer
    linkedin_peer = MediaPeer(MonkeyPatch(), now=datetime.now(timezone.utc))
    os.environ["MARKETING_CREDENTIAL_KEY"] = linkedin_fixture.read_text(encoding="utf-8")
telegram_fixture = Path(sys.argv[1]).with_suffix(".telegram-fixture")
if request["method"] == "TELEGRAM_CONFIGURE":
    telegram_fixture.write_text("enabled", encoding="utf-8")
if telegram_fixture.exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from pytest import MonkeyPatch
    from test_marketing_reconciliation import ReceiptPeer
    telegram_peer = ReceiptPeer(MonkeyPatch())
    telegram_peer.outcome = None
    updates_fixture = Path(sys.argv[1]).with_suffix(".telegram-updates.json")
    if updates_fixture.exists():
        telegram_peer.updates = json.loads(updates_fixture.read_text(encoding="utf-8"))
if request["method"] == "META_CONFIGURE":
    print(json.dumps({"status": 200, "body": {"configured": True}}))
elif request["method"] == "META_EXPIRE":
    from marketing import credentials, store
    with store.connection(write=True) as c:
        grant = credentials.read(c, request["account_id"], "meta")
        credentials.save(c, request["account_id"], "meta", {**grant, "expires_at": "2000-01-01T00:00:00+00:00"})
    print(json.dumps({"status": 200, "body": {"expired": True}}))
elif request["method"] == "DISPATCH_INSTAGRAM":
    from datetime import datetime
    from urllib.parse import urlsplit
    from marketing import worker
    state_file = Path(sys.argv[1]).with_suffix(".instagram-state.json")
    if state_file.exists():
        for key, value in json.loads(state_file.read_text(encoding="utf-8")).items():
            setattr(meta_peer, key, value)
    if request.get("hidden") and meta_peer.receipt:
        if meta_peer.receipt.get("media_product_type") == "STORY":
            meta_peer.story_ids = []
        else:
            meta_peer.receipt["caption"] = "synthetic unconfirmed caption"
    meta_peer.processing = request.get("processing", "FINISHED")
    if "profile_url" in request:
        meta_peer.profile["website"] = request["profile_url"]
    meta_peer.now = datetime.fromisoformat(request["at"].replace("Z", "+00:00"))
    result = worker.tick(now=meta_peer.now)
    if not request.get("hidden"):
        state_file.write_text(json.dumps({key: getattr(meta_peer, key) for key in ("containers", "publishes", "receipt")}), encoding="utf-8")
    print(json.dumps({"status": 200, "body": {**result, "requests": [call.method + " " + urlsplit(call.url).path for call in meta_peer.calls]}}))
elif request["method"] == "DISPATCH_FACEBOOK":
    import base64
    import requests
    from datetime import datetime
    from urllib.parse import urlsplit
    from marketing import worker
    receipt_file = Path(sys.argv[1]).with_suffix(".facebook-receipt.json")
    if receipt_file.exists():
        meta_peer.receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if request.get("hidden") and meta_peer.receipt:
        meta_peer.receipt["is_hidden"] = True
    reel_file = Path(sys.argv[1]).with_suffix(".facebook-reel.json")
    if reel_file.exists():
        saved = json.loads(reel_file.read_text(encoding="utf-8"))
        meta_peer.uploaded = base64.b64decode(saved.pop("uploaded"))
        for key, value in saved.items():
            setattr(meta_peer, key, value)
    meta_peer.processing = request.get("processing", "completed")
    meta_peer.publication = "draft" if request.get("hidden") else "published"
    if request.get("lose_finish"):
        meta_peer.finish_outcome = requests.Timeout("synthetic lost Reel finish response")
    finishes_before = len(meta_peer.finishes)
    result = worker.tick(now=datetime.fromisoformat(request["at"].replace("Z", "+00:00")))
    if meta_peer.receipt and not request.get("hidden"):
        receipt_file.write_text(json.dumps(meta_peer.receipt), encoding="utf-8")
    reel_file.write_text(json.dumps({"uploaded": base64.b64encode(meta_peer.uploaded).decode(), **{
        key: getattr(meta_peer, key) for key in ("reported_size", "registrations", "finishes", "reel_description")}}), encoding="utf-8")
    print(json.dumps({"status": 200, "body": {**result, "reel_finishes": len(meta_peer.finishes) - finishes_before,
        "requests": [r.method + " " + urlsplit(r.url).path for r in meta_peer.calls]}}))
elif request['method'] in {'WEBSITE_CONFIGURE', 'WEBSITE_ERROR', 'WEBSITE_RECOVER', 'WEBSITE_CLEANUP'}:
    print(json.dumps({'status': 200, 'body': {'configured': True, 'reader': website_reader}}))
elif request["method"] == "LINKEDIN_CONFIGURE":
    print(json.dumps({"status": 200, "body": {"configured": True}}))
elif request["method"] == "LINKEDIN_EXPIRE":
    from marketing import credentials, store
    with store.connection(write=True) as c:
        grant = credentials.read(c, "linkedin", "linkedin")
        credentials.save(c, "linkedin", "linkedin", {**grant, "expires_at": "2000-01-01T00:00:00+00:00"})
    print(json.dumps({"status": 200, "body": {"expired": True}}))
elif request["method"] == "DISPATCH_LINKEDIN":
    from datetime import datetime
    from urllib.parse import urlsplit
    from marketing import worker
    linkedin_peer.video_status = request.get("video_status", "AVAILABLE")
    result = worker.tick(now=datetime.fromisoformat(request["at"].replace("Z", "+00:00")))
    print(json.dumps({"status": 200, "body": {**result, "requests": [r.method + " " + urlsplit(r.url).path for r in linkedin_peer.calls]}}))
elif request["method"] == "RESTORE_REHEARSAL":
    from marketing import backup
    if request.get('prepared'):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
        from test_marketing_delivery import prepare, Platform
        from test_marketing_core import candidate, NOW
        from marketing import delivery, store
        prepare()
        candidate('draft-before-backup', title='Старый внутренний черновик')
        original_clock = store.now
        store.now = lambda: NOW.isoformat()
    archive = Path(sys.argv[1]).with_suffix(".backup.zip")
    backup.create(archive)
    if request.get('prepared'):
        from datetime import timedelta
        delivery.run_one(Platform(), NOW + timedelta(minutes=1))
        store.now = original_clock
    os.environ["MARKETING_ENVIRONMENT"] = "browser-recovered"
    result = backup.restore(archive)
    recovery_fixture.write_text("restored", encoding="utf-8")
    print(json.dumps({"status": 200, "body": result}))
elif request["method"] == "TELEGRAM_CONFIGURE":
    print(json.dumps({"status": 200, "body": {"configured": True}}))
elif request["method"] == "DISPATCH_TELEGRAM":
    from datetime import datetime
    from marketing import worker
    if request.get("outcome") == "timeout":
        import requests
        telegram_peer.outcome = requests.Timeout("Controlled lost response")
    result = worker.tick(now=datetime.fromisoformat(request["at"].replace("Z", "+00:00")))
    print(json.dumps({"status": 200, "body": {**result, "methods": [value[0] for value in telegram_peer.calls]}}))
elif request["method"] == "TELEGRAM_OBSERVE":
    from datetime import datetime
    from marketing import store
    from test_marketing_reconciliation import observation
    with store.connection() as c:
        job = store.get(c, "delivery", request["candidate_id"])
    update = observation(job["dispatch_payload"]["text"], forwarded=True)
    update["message"]["forward_origin"]["date"] = int(datetime.fromisoformat(job["claimed_at"]).timestamp())
    updates_fixture.write_text(json.dumps([update]), encoding="utf-8")
    print(json.dumps({"status": 200, "body": {"ok": True}}))
elif request["method"] == "DISPATCH_STEP":
    from datetime import datetime
    from marketing import delivery, store
    at = datetime.fromisoformat(request["at"].replace("Z", "+00:00"))
    with store.connection() as c:
        accounts = store.list_items(c, "account")
    for account in accounts:
        delivery.record_connection(account["id"], account["version"], external_id=account["external_id"], verified=True, now=at)
    class FixtureTransport:
        def publish(self, account, item, key):
            return {"external_id": "fixture-" + key, "url": "https://t.me/marketing_fixture/123"}
    dispatched = delivery.run_one(FixtureTransport(), at)
    print(json.dumps({"status": 200, "body": {"dispatched": dispatched}}))
elif request["method"] == "EDITORIAL_EXPERIMENT_FIXTURE":
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from test_marketing_editorial_experiments import prepared, measured
    at = datetime.now(timezone.utc)
    start = (at-timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    design, drafts, events = prepared(start=start)
    measured(design, events, at=at)
    print(json.dumps({"status": 200, "body": {"design": design}}))
elif request["method"] == "REPORT_GOAL_FIXTURE":
    from datetime import date, datetime, timedelta, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from marketing import goals, reports
    from test_marketing_core import OWNER, goal_input
    from test_marketing_reports import configured, coverage
    from test_marketing_analytics import fixture
    configured()
    period = reports.current_week(datetime.now(timezone.utc))
    if request.get("closed"):
        period = {key: (date.fromisoformat(value) - timedelta(days=7)).isoformat() for key, value in period.items()}
    goal = goals.save_goal(OWNER, goal_input(metric="registrations", unit="users", target=100,
        starts_on=period["starts_on"], deadline=period["ends_on"]), 0)
    goals.approve_goal(OWNER, goal["version"])
    cut = datetime.now(timezone.utc)
    at = period["starts_on"] + "T12:00:00Z" if request.get("closed") else cut.isoformat()
    events = [{**row, "at": at} for row in fixture() if row["kind"] == "registration"]
    reports.import_events(OWNER, events, [coverage(through=cut.isoformat())], now=cut)
    snapshot = reports.freeze(OWNER, "Завершённая неделя" if request.get("closed") else "Незавершённая неделя", period, 1, now=cut)
    print(json.dumps({"status": 200, "body": {"snapshot_id": snapshot["id"], "period": period}}, ensure_ascii=False))
elif request["method"] == "DIGEST_SOURCE_FIXTURE":
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from test_marketing_digest import originals
    now = datetime.now(timezone.utc)
    rows = originals(now, count=request.get("count", 2))
    if request.get("plan"):
        from marketing import goals
        from test_marketing_core import OWNER, account
        from test_marketing_strategy import approve_goal, proposal
        approve_goal()
        plan = goals.save_strategy(OWNER, proposal(rubrics=["news", "digest"]), now=now)
        goals.approve_strategy(OWNER, plan["id"], plan["version"], now=now)
        account(rubrics=["news", "digest"], label="Telegram · дайджест")
    print(json.dumps({"status": 200, "body": {"evidence": rows}}, ensure_ascii=False))
elif request['method'] == 'OCCASION_SOURCE_FIXTURE':
    from datetime import datetime, timezone, timedelta
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
    from test_marketing_occasions import occasion
    from test_marketing_core import account
    now = datetime.now(timezone.utc)
    account(mode='draft', languages=['ru', 'uz'], formats=['post', 'image'])
    ref = occasion(request['kind'], published_at=(now - timedelta(hours=2)).isoformat(),
        event_at=(now - timedelta(hours=3)).isoformat(), retrieved_at=(now - timedelta(hours=1)).isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat())
    print(json.dumps({'status': 200, 'body': {'occasion': ref}}, ensure_ascii=False))
elif request['method'] == 'CALENDAR_SOURCE_FIXTURE':
    from datetime import datetime, timezone, timedelta
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
    import test_marketing_automation as fixture
    import test_marketing_calendar as calendar
    from marketing.permissions import TASHKENT
    now = datetime.now(timezone.utc)
    fixture.NOW = calendar.NOW = now
    calendar.rule(enabled=False)
    local = now.astimezone(TASHKENT)
    start = local.date() - timedelta(days=local.weekday())
    if local.weekday() == 6:
        start += timedelta(days=7)
    at = max(local + timedelta(hours=1), datetime.combine(start, datetime.min.time(), TASHKENT) + timedelta(hours=12))
    records = [calendar.announcement('meeting', at=at),
               calendar.announcement('report', at=at + timedelta(minutes=30), entity='UZTL', data={'event_type': 'report'})]
    print(json.dumps({'status': 200, 'body': {'evidence': records, 'weekday': local.weekday(), 'week': start.isoformat()}}, ensure_ascii=False))
elif request['method'] == 'CHART_SOURCE_FIXTURE':
    from datetime import datetime, timezone, timedelta
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
    import test_marketing_automation as fixture
    from test_marketing_chart_selection import chart_rule, original
    fixture.NOW = datetime.now(timezone.utc)
    chart_rule(enabled=False)
    stamp = (fixture.NOW - timedelta(hours=1)).isoformat()
    row = original(published_at=stamp, event_at=stamp)
    print(json.dumps({'status': 200, 'body': {'evidence': row}}, ensure_ascii=False))
elif request["method"] == "QUARTER_SOURCE_FIXTURE":
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from test_marketing_source_adapters import ready_report
    from test_marketing_sources import source_input
    from test_marketing_core import OWNER
    from reporting import store as reports
    from marketing import sources, source_adapters
    now = datetime.now(timezone.utc)
    report = ready_report(generated_at=now.isoformat())
    fact = report["verified_facts"][0]
    fact.update(period_start="2026-01-01", period_kind="cumulative_ytd")
    report["verified_facts"].extend([{**fact, "metric_code": "total_assets", "raw": 1200, "source_original_line": "Активы"},
                                     {**fact, "period_end": "2026-06-30", "raw": 600}])
    reports.record_report(report)
    source = sources.save_source(OWNER, "analysis", source_input(method="internal_analysis", name="Готовые разборы UZStock"), 0)
    sources.enable_source(OWNER, source["id"], source["version"])
    sources.collect_one(source_adapters.fetch, now)
    result = {"ok": True}
    if request.get("plan"):
        from marketing import goals
        from test_marketing_core import account
        from test_marketing_strategy import approve_goal, proposal
        approve_goal()
        plan = goals.save_strategy(OWNER, proposal(rubrics=["news", "quarterly"]), now=now)
        plan = goals.approve_strategy(OWNER, plan["id"], plan["version"], now=now)
        account(rubrics=["news", "quarterly"], label="Telegram · квартальные разборы")
        result["strategy_id"] = plan["id"]
    print(json.dumps({"status": 200, "body": result}))
elif request["method"] == "QUARTER_LEGACY_SCOPE":
    from marketing import store
    with store.connection(write=True) as c:
        original = store.get(c, "evidence", request["evidence_id"])
        store.put(c, "evidence", {**original, "period": "2026-06-30"}, actor={"id": "fixture", "role": "test"},
                  action="legacy_collector_fixture", expected_version=original["version"])
    print(json.dumps({"status": 200, "body": {"ok": True}}))
elif request["method"] == "MODEL_PRODUCTION":
    from pathlib import Path
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
    from marketing import agents, media
    from test_marketing_production import ProductionModel
    model = ProductionModel()
    if request.get("quarterly"):
        from test_marketing_automation import QuarterlyModel
        model = QuarterlyModel(quarter_wording=request.get("quarter_wording", False))
    if request.get("digest"):
        from test_marketing_digest import DigestModel
        model = DigestModel(omit_last=request.get("omit_event", False))
    if request.get('chart'):
        from test_marketing_chart_selection import ChartModel
        model = ChartModel()
    if request.get('calendar'):
        from test_marketing_calendar import CalendarModel
        model = CalendarModel(omit_last=request.get('omit_event', False))
    if request.get('occasion'):
        from test_marketing_occasions import OccasionModel
        model = OccasionModel()
    for _ in range(30):
        rendered = media.run_one(datetime.now(timezone.utc))
        if not agents.run_one(model, datetime.now(timezone.utc)) and not rendered:
            break
    print(json.dumps({"status": 200, "body": {"ok": True}}))
elif request["method"] == "RENDER_STEP":
    from datetime import datetime, timezone
    from marketing import media
    media.run_one(datetime.now(timezone.utc))
    print(json.dumps({"status": 200, "body": {"ok": True}}))
elif request["method"] in {"MODEL_STEP", "WORKER_STEP"}:
    from datetime import datetime, timezone
    from marketing import agents
    class FixtureModel:
        def complete_json(self, system, user, **kwargs):
            context = json.loads(user)
            if 'result' in request:
                return request['result']
            result = {"summary": "Сначала замерим открытия отчётов. Бюджет остаётся без изменений.",
                    "questions": ["Какой период используем для исходной базы?"], "risks": [],
                    "recommendations": ["Разметить ссылку на конкретный разбор"], "verdict": "accept", "handoff": context["message"]}
            if context["kind"] == "report" and system.startswith("You are UZStock's cmo "):
                from datetime import timedelta
                from marketing.permissions import TASHKENT
                sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
                from test_marketing_report_decisions import review
                value = review()
                value["hypotheses"].append({**value["hypotheses"][0], "id": "question", "parent_id": "cover",
                    "statement": "Конкретный вопрос на обложке может помочь выбрать разбор."})
                for row in [*value["decisions"], *value["hypotheses"]]:
                    row["check_on"] = (datetime.fromisoformat(context["current_time"]).astimezone(TASHKENT).date() + timedelta(days=7)).isoformat()
                result["cmo_review"] = value
            if request.get("experiment_id") and context["kind"] == "experiment" and not context["outputs"]:
                from marketing import experiments, store
                with store.connection() as c:
                    saved = store.get(c, "experiment", request["experiment_id"])
                proposal = {key: saved[key] for key in experiments.Experiment.model_fields}
                result["experiments"] = [{**proposal, "title": "Вариант команды: " + proposal["title"]}]
            return result
    if request["method"] == "WORKER_STEP":
        from marketing import worker
        result = worker.tick(model=FixtureModel(), now=datetime.now(timezone.utc))
    else:
        agents.run_one(FixtureModel(), datetime.now(timezone.utc))
        result = {"ok": True}
    print(json.dumps({"status": 200, "body": result}))
else:
    response = TestClient(app, base_url="https://testserver").request(request["method"], request["path"], json=request.get("body"), headers={"Cookie": request.get("cookie", ""), **request.get('headers', {})})
    if response.headers.get("content-type", "").startswith("application/json"):
        result = {"status": response.status_code, "body": response.json(), "headers": dict(response.headers)}
    else:
        import base64
        result = {"status": response.status_code, "base64": base64.b64encode(response.content).decode(), "headers": dict(response.headers)}
    print(json.dumps(result, ensure_ascii=False))
