"""Human-session endpoints. Agent-generated data never supplies the actor."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import Field, ValidationError

from admin_control.api import ControlRoute, reply
from . import agents, catalog, channels, content, delivery, experiments, founder, goals, incidents, media, model_runtime, permissions, production, publishing, reports, reports_api, sources, store as s
from .errors import MarketingError, require_owner
from .models import Account, Candidate, ChartRef, Evidence, Goal, Input, PublicationSchedule, Strategy
from .production_models import ProductionBrief
from . import reconciliation, visibility, website, trends, execution, automation, editorial_experiments, recovery

router = APIRouter(prefix="/api/admin/ai-marketing", tags=["marketing"], route_class=ControlRoute)


def owner_gate(request: Request):
    require_owner(request.state.control_actor)


def actor(request):
    return request.state.control_actor


class Version(Input):
    expected_version: int = Field(ge=0)


class ReleaseDraft(Version):
    account_version: int = Field(ge=1)


class SaveGoal(Version):
    data: Goal


class SaveAccount(Version):
    data: Account


class SaveEvidence(Version):
    data: Evidence


class SaveStrategy(Version):
    data: Strategy


class PlanPause(Version):
    paused: bool


class StepWork(Version):
    data: execution.WorkInputs


class OwnerStepResult(Version):
    data: execution.OwnerResult


class SaveSource(Version):
    data: sources.Source


class SaveTrend(Version):
    data: trends.Review


class SaveEditorialRule(Version):
    data: automation.Rule


class SaveFounderFact(Version):
    data: founder.FounderFact


class SaveCorrection(Version):
    data: incidents.Correction


class SaveExperiment(Version):
    data: experiments.Experiment


class RegisterEditorialExperiment(Input):
    data: editorial_experiments.Design


class ExperimentDecision(Version):
    evaluation_id: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=3, max_length=2000)


class ConfirmMatch(Version):
    match_digest: str = Field(min_length=1, max_length=100)


class ConfirmVisibility(Version):
    review_digest: str = Field(min_length=1, max_length=100)


class SocialCallback(Input):
    state: str = Field(min_length=20, max_length=100)
    code: str | None = Field(default=None, min_length=1, max_length=8192)
    error: str | None = Field(default=None, max_length=200)


class SelectMeta(Version):
    selection_id: str = Field(min_length=1, max_length=100)
    target_id: str = Field(pattern=r"^[1-9][0-9]{0,39}$")


class SourcePermission(Version):
    enabled: bool


class SourceImport(Input):
    materials: list[sources.Material] = Field(min_length=1, max_length=100)


class VerifyEvidence(Version):
    reason: str = Field(min_length=1, max_length=2000)


class Revision(Version):
    changes: dict


class Pause(Input):
    publications: bool | None = None
    processing: bool | None = None


class TaskInput(Input):
    kind: str = Field(max_length=30)
    message: str = Field(min_length=1, max_length=12000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    trend_ids: list[str] = Field(default_factory=list, max_length=10)
    planning_snapshot_ids: list[str] = Field(default_factory=list, max_length=10)
    conversation_id: str | None = None
    production: ProductionBrief | None = None


class RenderRequest(Version):
    chart: ChartRef | None = None


@router.get("/workspace")
def workspace(request: Request):
    from . import telegram_news
    with s.connection() as c:
        data = {plural: s.list_items(c, kind) for plural, kind in (
            ("accounts", "account"), ("strategies", "strategy"), ("evidence", "evidence"),
            ("candidates", "candidate"), ("deliveries", "delivery"), ("tasks", "task"), ("snapshots", "snapshot"),
            ("sources", "source"), ("topics", "topic"), ("variants", "draft_variant"), ("assets", "asset"), ("renders", "render"), ("founder_facts", "founder_fact"), ("incidents", "incident"), ("experiments", "experiment"), ("uploads", "provider_upload"))}
        data["evidence"] = [sources.current_evidence(c, item["id"]) for item in data["evidence"]]
        data['editorial_experiments'] = s.list_items(c, 'editorial_experiment')
        data['experiment_evaluations'] = s.list_items(c, 'experiment_evaluation')
        data["strategies"] = [goals.current_strategy(c, item, datetime.now(timezone.utc)) for item in data["strategies"]]
        data["plans"] = [execution.current(c, item, datetime.now(timezone.utc)) for item in s.list_items(c, "plan_run")]
        data["editorial_rules"] = [automation.current(c, item, datetime.now(timezone.utc)) for item in s.list_items(c, "editorial_rule")]
        data["editorial_rubrics"] = [rubric for rubric in catalog.RUBRICS if rubric["id"] in automation.RUBRICS]
        data["trends"] = [trends.current(c, item, datetime.now(timezone.utc)) for item in s.list_items(c, "trend")]
        data["channel_setup"] = {account["id"]: channels.setup(account, c=c) for account in data["accounts"]}
        data["provider_setup"] = {platform["id"]: channels.setup({"platform": platform["id"]}) for platform in catalog.PLATFORMS}
        data["reconciliation"] = reconciliation.cases(c)
        data["visibility_reviews"] = visibility.pending(c)
        data["reconciliation_read"] = s.get(c, "settings", "telegram_updates", required=False)
        data['website'] = website.status(c)
        data['telegram_news'] = telegram_news.status(c, datetime.now(timezone.utc))
        data.update(goal=s.get(c, "goal", "primary", required=False), active_goal=goals.active_goal(c),
                    pause=s.get(c, "settings", "pause", required=False) or {"publications": False, "processing": False},
                    roles=catalog.ROLES, rubrics=catalog.RUBRICS, platforms=catalog.PLATFORMS,
                    model=model_runtime.status(), worker=s.get(c, "runtime", "worker", required=False),
                    recovery=recovery.inspect(c),
                    analytics_settings=reports.settings(c), report_period=reports.current_week(datetime.now(timezone.utc)),
                    environment=s.environment(), timezone="Asia/Tashkent")
    return reply(request, data)


@router.post('/recovery/complete')
def complete_recovery(request: Request, body: recovery.Review):
    return reply(request, {'item': recovery.complete(actor(request), body.model_dump(mode='json'), now=datetime.now(timezone.utc))})


@router.get("/history/{kind}/{record_id}")
def history(request: Request, kind: str, record_id: str):
    if kind not in {"goal", "strategy", "plan_run", "plan_step", "editorial_rule", "editorial_runtime", "account", "evidence", "candidate", "delivery", "task", "snapshot", "settings", "conversation", "source", "topic", "trend", "draft_variant", "asset", "render", "founder_fact", "incident", "experiment", "editorial_experiment", "experiment_evaluation", "provider_upload"}:
        raise MarketingError("NOT_FOUND", "Unknown history category.", 404)
    with s.connection() as c:
        return reply(request, {"items": s.history(c, kind, record_id)})


@router.put("/editorial-rules/{rule_id}")
def save_editorial_rule(request: Request, rule_id: str, body: SaveEditorialRule):
    return reply(request, {"item": automation.save(actor(request), rule_id, body.data.model_dump(mode="json"), body.expected_version,
                                                   now=datetime.now(timezone.utc))})


@router.post("/incidents/scan")
def scan_incidents(request: Request):
    return reply(request, {"changed": incidents.scan(datetime.now(timezone.utc))})


@router.post("/incidents/{incident_id}/correction")
def prepare_correction(request: Request, incident_id: str, body: SaveCorrection):
    try:
        item = incidents.prepare(actor(request), incident_id, body.expected_version, body.data.model_dump(mode="json"), datetime.now(timezone.utc))
    except ValidationError:
        raise MarketingError("INVALID_CORRECTION", "Check the clarification fields and timestamp format.", 422) from None
    return reply(request, {"item": item})


@router.post("/incidents/{incident_id}/dismiss")
def dismiss_incident(request: Request, incident_id: str, body: VerifyEvidence):
    return reply(request, {"item": incidents.dismiss(actor(request), incident_id, body.expected_version, body.reason)})


@router.post('/editorial-experiments')
def register_editorial_experiment(request: Request, body: RegisterEditorialExperiment):
    return reply(request, {'item': editorial_experiments.register(actor(request), body.data.model_dump(mode='json'), now=datetime.now(timezone.utc))})


@router.post('/editorial-experiments/{experiment_id}/evaluate')
def evaluate_editorial_experiment(request: Request, experiment_id: str, body: Version):
    return reply(request, {'item': editorial_experiments.evaluate(actor(request), experiment_id, body.expected_version, now=datetime.now(timezone.utc))})


@router.post('/editorial-experiments/{experiment_id}/decide')
def decide_editorial_experiment(request: Request, experiment_id: str, body: ExperimentDecision):
    return reply(request, {'item': editorial_experiments.decide(actor(request), experiment_id, body.expected_version, body.evaluation_id, body.action, body.reason)})


@router.post("/experiments")
def create_experiment(request: Request, body: SaveExperiment):
    return reply(request, {"item": experiments.save(actor(request), body.data.model_dump(mode="json"), expected_version=body.expected_version)})


@router.put("/experiments/{experiment_id}")
def save_experiment(request: Request, experiment_id: str, body: SaveExperiment):
    return reply(request, {"item": experiments.save(actor(request), body.data.model_dump(mode="json"), experiment_id, body.expected_version)})


@router.post("/experiments/{experiment_id}/approve")
def approve_experiment(request: Request, experiment_id: str, body: Version):
    return reply(request, {"item": experiments.approve(actor(request), experiment_id, body.expected_version, datetime.now(timezone.utc))})


@router.post("/experiments/{experiment_id}/revoke")
def revoke_experiment(request: Request, experiment_id: str, body: VerifyEvidence):
    return reply(request, {"item": experiments.revoke(actor(request), experiment_id, body.expected_version, body.reason)})


@router.post("/experiments/{experiment_id}/action")
def request_paid_action(request: Request, experiment_id: str, body: Version):
    return reply(request, {"item": experiments.request_action(actor(request), experiment_id, body.expected_version, datetime.now(timezone.utc))})


@router.post("/accounts/{account_id}/probe")
def probe_account(request: Request, account_id: str, body: Version):
    return reply(request, {"item": channels.probe(actor(request), account_id, body.expected_version, datetime.now(timezone.utc))})


class TelegramConnect(Version):
    channel: str = Field(pattern=r'^-100[0-9]+$')
    account_id: str | None = None


@router.post('/telegram/connect')
def connect_telegram(request: Request, body: TelegramConnect):
    from . import telegram_news
    return reply(request, {'item': telegram_news.connect(actor(request), body.channel, body.expected_version,
                  datetime.now(timezone.utc), body.account_id)})


class TelegramPause(Version):
    paused: bool


class TelegramSchedule(Version):
    data: PublicationSchedule


@router.put('/telegram/{account_id}/schedule')
def save_telegram_schedule(request: Request, account_id: str, body: TelegramSchedule):
    with s.connection() as c:
        account = s.get(c, 'account', account_id)
    if account['platform'] != 'telegram':
        raise MarketingError('ACCOUNT_PLATFORM', 'Choose a Telegram channel.', 422)
    value = {key: account[key] for key in Account.model_fields if key in account}
    return reply(request, {'item': permissions.save_account(actor(request), account_id,
                  {**value, **body.data.model_dump(mode='json')}, body.expected_version)})


@router.post('/telegram/{account_id}/pause')
def pause_telegram(request: Request, account_id: str, body: TelegramPause):
    with s.connection() as c:
        account = s.get(c, 'account', account_id)
    if account['platform'] != 'telegram':
        raise MarketingError('ACCOUNT_PLATFORM', 'Choose a Telegram channel.', 422)
    value = {key: account[key] for key in Account.model_fields if key in account}
    return reply(request, {'item': permissions.save_account(actor(request), account_id,
                  {**value, 'paused': body.paused}, body.expected_version)})


@router.post("/accounts/{account_id}/linkedin/start")
def start_linkedin(request: Request, response: Response, account_id: str, body: Version):
    from . import linkedin_oauth as oauth
    result = oauth.begin(actor(request), account_id, body.expected_version, datetime.now(timezone.utc))
    response.set_cookie(oauth.COOKIE, result.pop("binding"), max_age=oauth.TTL, httponly=True, secure=True, samesite="lax", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return reply(request, result)


@router.post("/oauth/linkedin/finish")
def finish_linkedin(request: Request, response: Response, body: SocialCallback):
    from . import linkedin_oauth as oauth
    result = oauth.finish(actor(request), state=body.state, code=body.code, error=body.error,
                          binding=request.cookies.get(oauth.COOKIE), now=datetime.now(timezone.utc))
    response.delete_cookie(oauth.COOKIE, path="/api", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return reply(request, {"item": result})


@router.post("/accounts/{account_id}/linkedin/disconnect")
def disconnect_linkedin(request: Request, account_id: str, body: Version):
    from . import linkedin_oauth
    return reply(request, {"item": linkedin_oauth.disconnect(actor(request), account_id, body.expected_version)})


@router.post("/accounts/{account_id}/meta/start")
def start_meta(request: Request, response: Response, account_id: str, body: Version):
    from . import meta_oauth as oauth
    result = oauth.begin(actor(request), account_id, body.expected_version, datetime.now(timezone.utc))
    response.set_cookie(oauth.COOKIE, result.pop("binding"), max_age=oauth.TTL, httponly=True, secure=True, samesite="lax", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return reply(request, result)


@router.post("/oauth/meta/finish")
def finish_meta(request: Request, response: Response, body: SocialCallback):
    from . import meta_oauth as oauth
    result = oauth.finish(actor(request), state=body.state, code=body.code, error=body.error,
                          binding=request.cookies.get(oauth.COOKIE), now=datetime.now(timezone.utc))
    response.delete_cookie(oauth.COOKIE, path="/api", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return reply(request, {"selection": result})


@router.post("/accounts/{account_id}/meta/select")
def select_meta(request: Request, account_id: str, body: SelectMeta):
    from . import meta_oauth as oauth
    return reply(request, {"item": oauth.select(actor(request), account_id, body.expected_version,
        body.selection_id, body.target_id, datetime.now(timezone.utc))})


@router.post("/accounts/{account_id}/meta/disconnect")
def disconnect_meta(request: Request, account_id: str, body: Version):
    from . import meta_oauth as oauth
    return reply(request, {"item": oauth.disconnect(actor(request), account_id, body.expected_version)})


@router.post("/channels/telegram/reconcile")
def reconcile_telegram(request: Request, body: Input | None = None):
    return reply(request, reconciliation.poll(actor(request), datetime.now(timezone.utc)))


@router.post("/deliveries/{delivery_id}/confirm-match")
def confirm_publication_match(request: Request, delivery_id: str, body: ConfirmMatch):
    return reply(request, {"item": reconciliation.confirm(actor(request), delivery_id, body.expected_version, body.match_digest, datetime.now(timezone.utc))})


@router.post("/deliveries/{delivery_id}/confirm-visible")
def confirm_publication_visibility(request: Request, delivery_id: str, body: ConfirmVisibility):
    return reply(request, {"item": visibility.confirm(actor(request), delivery_id, body.expected_version, body.review_digest, datetime.now(timezone.utc))})


@router.get("/candidates/{candidate_id}/publication-preview")
def publication_preview(request: Request, candidate_id: str):
    with s.connection() as c:
        return reply(request, publishing.preview(c, s.get(c, "candidate", candidate_id)))


@router.put("/goal")
def save_goal(request: Request, body: SaveGoal):
    return reply(request, {"item": goals.save_goal(actor(request), body.data.model_dump(mode="json"), body.expected_version)})


@router.post("/goal/approve")
def approve_goal(request: Request, body: Version):
    return reply(request, {"item": goals.approve_goal(actor(request), body.expected_version)})


@router.post("/strategies")
def propose_strategy(request: Request, body: SaveStrategy):
    return reply(request, {"item": goals.save_strategy(actor(request), body.data.model_dump(mode="json"))})


@router.post("/strategies/{strategy_id}/approve")
def approve_strategy(request: Request, strategy_id: str, body: Version):
    return reply(request, {"item": goals.approve_strategy(actor(request), strategy_id, body.expected_version)})


@router.post("/strategies/{strategy_id}/work")
def activate_plan(request: Request, strategy_id: str, body: Version):
    return reply(request, {"item": execution.activate(actor(request), strategy_id, body.expected_version)})


@router.post("/plans/{run_id}/pause")
def pause_plan(request: Request, run_id: str, body: PlanPause):
    return reply(request, {"item": execution.set_paused(actor(request), run_id, body.expected_version, body.paused)})


@router.post("/plan-steps/{step_id}/start")
def start_plan_step(request: Request, step_id: str, body: StepWork):
    return reply(request, {"item": execution.launch(actor(request), step_id, body.expected_version, body.data.model_dump(mode="json"))})


@router.post("/plan-steps/{step_id}/prepare")
def prepare_plan_step(request: Request, step_id: str, body: StepWork):
    from . import scheduling
    return reply(request, {"item": scheduling.prepare(actor(request), step_id, body.expected_version, body.data.model_dump(mode="json"))})


@router.post("/plan-steps/{step_id}/cancel-preparation")
def cancel_plan_preparation(request: Request, step_id: str, body: Version):
    from . import scheduling
    return reply(request, {"item": scheduling.cancel(actor(request), step_id, body.expected_version)})


@router.post("/plan-steps/{step_id}/owner-result")
def record_owner_step(request: Request, step_id: str, body: OwnerStepResult):
    return reply(request, {"item": execution.record_owner_result(actor(request), step_id, body.expected_version, body.data.model_dump(mode="json"))})


@router.post("/plan-steps/{step_id}/review-drafts")
def review_plan_drafts(request: Request, step_id: str, body: Version):
    return reply(request, {"item": execution.submit_drafts(actor(request), step_id, body.expected_version)})


@router.put("/accounts/{account_id}")
def save_account(request: Request, account_id: str, body: SaveAccount):
    return reply(request, {"item": permissions.save_account(actor(request), account_id, body.data.model_dump(mode="json"), body.expected_version)})


@router.put("/evidence/{evidence_id}")
def save_evidence(request: Request, evidence_id: str, body: SaveEvidence):
    return reply(request, {"item": content.save_evidence(actor(request), evidence_id, body.data.model_dump(mode="json"), body.expected_version)})


@router.put("/sources/{source_id}")
def save_source(request: Request, source_id: str, body: SaveSource):
    return reply(request, {"item": sources.save_source(actor(request), source_id, body.data.model_dump(mode="json"), body.expected_version)})


@router.put("/trends/{trend_id}")
def save_trend(request: Request, trend_id: str, body: SaveTrend):
    return reply(request, {"item": trends.save(actor(request), trend_id, body.data.model_dump(mode="json"), body.expected_version, datetime.now(timezone.utc))})


@router.post("/sources/{source_id}/permission")
def source_permission(request: Request, source_id: str, body: SourcePermission):
    return reply(request, {"item": sources.enable_source(actor(request), source_id, body.expected_version, body.enabled)})


@router.post("/sources/{source_id}/import")
def import_source(request: Request, source_id: str, body: SourceImport):
    return reply(request, sources.import_materials(actor(request), source_id,
                 [value.model_dump(mode="json") for value in body.materials], datetime.now(timezone.utc)))


@router.post("/evidence/{evidence_id}/verify")
def verify_evidence(request: Request, evidence_id: str, body: VerifyEvidence):
    return reply(request, {"item": sources.verify_evidence(actor(request), evidence_id, body.expected_version, body.reason)})


@router.post("/candidates")
def create_candidate(request: Request, body: Candidate):
    return reply(request, {"item": content.create_candidate(body.model_dump(mode="json"))})


@router.patch("/candidates/{candidate_id}")
def revise_candidate(request: Request, candidate_id: str, body: Revision):
    try:
        item = content.revise_candidate(actor(request), candidate_id, body.changes, body.expected_version)
    except ValidationError:
        raise MarketingError("INVALID_CONTENT", "Check the content fields and timestamp format.", 422) from None
    return reply(request, {"item": item})


@router.post("/candidates/{candidate_id}/check")
def check_candidate(request: Request, candidate_id: str):
    return reply(request, {"item": content.check_candidate(candidate_id, datetime.now(timezone.utc))})


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(request: Request, candidate_id: str, body: Version):
    return reply(request, {"item": content.approve_candidate(actor(request), candidate_id, body.expected_version)})


@router.post("/candidates/{candidate_id}/release-draft")
def release_draft(request: Request, candidate_id: str, body: ReleaseDraft):
    return reply(request, {"item": content.release_draft(actor(request), candidate_id, body.expected_version,
                        body.account_version, datetime.now(timezone.utc))})


@router.post("/candidates/{candidate_id}/cancel")
def cancel_candidate(request: Request, candidate_id: str, body: Version):
    return reply(request, {"item": content.cancel_candidate(actor(request), candidate_id, body.expected_version)})


@router.post("/candidates/{candidate_id}/schedule")
def schedule_candidate(request: Request, candidate_id: str):
    return reply(request, {"item": delivery.schedule(candidate_id, datetime.now(timezone.utc))})


@router.put("/pause")
def pause(request: Request, body: Pause):
    return reply(request, {"item": delivery.set_pause(actor(request), **body.model_dump())})


@router.post("/tasks")
def start_task(request: Request, body: TaskInput):
    return reply(request, {"item": agents.start(actor(request), **body.model_dump())})


@router.post("/tasks/{task_id}/cancel")
def cancel_task(request: Request, task_id: str, body: Version):
    return reply(request, {"item": agents.cancel(actor(request), task_id, body.expected_version)})


@router.post("/tasks/{task_id}/retry")
def retry_task(request: Request, task_id: str, body: Version):
    return reply(request, {"item": agents.retry(actor(request), task_id, body.expected_version)})


@router.post("/drafts/{variant_id}/select")
def select_variant(request: Request, variant_id: str, body: Version):
    return reply(request, {"item": production.select_variant(actor(request), variant_id, body.expected_version)})


@router.post("/candidates/{candidate_id}/render")
def render_candidate(request: Request, candidate_id: str, body: RenderRequest):
    return reply(request, {"item": media.request_candidate(actor(request), candidate_id, body.expected_version,
                           chart=body.chart.model_dump() if body.chart else None)})


@router.post("/renders/{render_id}/retry")
def retry_render(request: Request, render_id: str, body: Version):
    return reply(request, {"item": media.retry(actor(request), render_id, body.expected_version)})


def download(data, mime, name):
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"',
                    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/assets/{asset_id}/file")
def asset_file(request: Request, asset_id: str):
    with s.connection() as c:
        asset = s.get(c, "asset", asset_id)
    return download(media.read_asset(asset), asset["mime"], media.asset_path(asset).name)


@router.get("/assets/{asset_id}/data")
def asset_data(request: Request, asset_id: str):
    with s.connection() as c:
        asset = s.get(c, "asset", asset_id)
    if not asset.get("chart"):
        raise MarketingError("NO_CHART_DATA", "У этого файла нет ряда для выгрузки.", 404)
    return download(media.asset_csv(asset).encode("utf-8-sig"), "text/csv", f"{asset['id']}.csv")


@router.get("/candidates/{candidate_id}/export")
def export_candidate(request: Request, candidate_id: str):
    return download(media.export_candidate(candidate_id), "application/zip", f"{s.digest(candidate_id)[:20]}.zip")


@router.put("/founder-facts/{fact_id}")
def save_founder_fact(request: Request, fact_id: str, body: SaveFounderFact):
    return reply(request, {"item": founder.save(actor(request), fact_id, body.data.model_dump(mode="json"), body.expected_version)})


@router.post("/founder-facts/{fact_id}/revoke")
def revoke_founder_fact(request: Request, fact_id: str, body: Version):
    return reply(request, {"item": founder.revoke(actor(request), fact_id, body.expected_version)})


router.include_router(reports_api.router)
