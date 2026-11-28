"""Background orchestration, also runnable as ``python -m marketing.worker``."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os

from . import agents, automation, channels, delivery, execution, incidents, media, meta_confirmation, model_runtime, news_review, production, reports, scheduling, source_adapters, sources, store as s, telegram_news, website
from .errors import MarketingError
from .permissions import timestamp

log = logging.getLogger(__name__)
ACTOR = {"id": "worker", "role": "coordinator"}


def tick(*, model=None, transport=None, fetch=None, now=None):
    supplied_now = now
    now = now or datetime.now(timezone.utc)
    agents.recover(now)
    production.recover_completed(now)
    execution.reconcile(now)
    plan_work = scheduling.run_one(now)
    delivery.recover_inflight(now)
    media.recover(now)
    confirmation_work = meta_confirmation.run_one(now)
    telegram_news.upgrade(now)
    telegram_news.ensure_source(now)
    source_work = sources.collect_one(fetch if fetch is not None else source_adapters.fetch, now)
    model = model if model is not None else model_runtime.get_model()
    review_work = news_review.run_one(model, now)
    editorial_work = automation.run_one(now) or telegram_news.run_one(now)
    with s.connection() as c:
        ready = s.list_items(c, "candidate", status="ready")
        pause = s.get(c, "settings", "pause", required=False) or {}
    if not pause.get("publications"):
        for candidate in ready:
            try:
                delivery.schedule(candidate["id"], now)
            except MarketingError:
                # Permission can be revoked between read and schedule.
                continue
    dispatched = delivery.run_one(transport if transport is not None else channels.Transport(now), now)
    incident_work = incidents.scan(now)
    media_work = media.run_one(now)
    model_work = agents.run_one(model, now) or review_work
    website_work = website.run_one(supplied_now)
    report_work = not pause.get("processing") and reports.freeze_closed_week(supplied_now or datetime.now(timezone.utc))
    completed_at = supplied_now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        old = s.get(c, "runtime", "worker", required=False)
        if model_work or dispatched or source_work or media_work or report_work or incident_work or confirmation_work or website_work or plan_work or editorial_work or not old or timestamp(old["last_completed_at"]) + timedelta(seconds=60) <= now:
            s.put(c, "runtime", {"id": "worker", "status": "running", "last_completed_at": completed_at.isoformat(),
                  "model_work": model_work, "delivery_work": dispatched, "source_work": source_work, "media_work": media_work, "report_work": report_work, "incident_work": incident_work, "confirmation_work": confirmation_work, "website_work": website_work, "plan_work": plan_work, "editorial_work": editorial_work}, actor=ACTOR,
                  action="worker_heartbeat", expected_version=old["version"] if old else 0)
    return {"model_work": model_work, "delivery_work": dispatched, "source_work": source_work, "media_work": media_work, "report_work": report_work, "incident_work": incident_work, "confirmation_work": confirmation_work, "website_work": website_work, "plan_work": plan_work, "editorial_work": editorial_work}


async def run_loop():
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log raw provider exceptions or request bodies.
            log.error("Marketing worker cycle failed; durable work remains available")
        await asyncio.sleep(5)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv("MARKETING_WORKER", "1") != "1":
        raise SystemExit("MARKETING_WORKER is disabled")
    asyncio.run(run_loop())
