"""Independent video jobs: server direction, leased PC rendering, private export."""
from datetime import timedelta
import secrets

from . import store as s
from .errors import MarketingError, require_owner
from .permissions import timestamp
from .video_contract import DIRECTOR, PAGES, Storyboard, VideoBrief

AGENT = {"id": "video", "role": "creative"}
ACTIVE = {"queued_script", "writing_script", "queued_render", "rendering"}


def public(item):
    return {key: value for key, value in item.items() if key not in {"lease_token", "file_name"}}


def _save(c, item, **changes):
    return s.put(c, "video_project", {**item, **changes}, actor=AGENT,
                 action=changes.get("status", "video_progress"), expected_version=item["version"])


def create(actor, data):
    require_owner(actor)
    brief = VideoBrief.model_validate(data).model_dump()
    with s.connection(write=True) as c:
        if sum(item["status"] in ACTIVE for item in s.list_items(c, "video_project")) >= 20:
            raise MarketingError("VIDEO_QUEUE_FULL", "Сначала дождитесь завершения текущих видеопроектов.")
        return s.put(c, "video_project", {"id": s.uid("video"), **brief, "status": "queued_script",
                     "storyboard": None, "attempts": 0, "reason": ""}, actor=actor,
                     action="video_requested", expected_version=0)


def cancel(actor, identifier, version):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "video_project", identifier)
        if item["status"] not in ACTIVE:
            raise MarketingError("VIDEO_NOT_ACTIVE", "Этот проект уже завершён.")
        return s.put(c, "video_project", {**item, "status": "cancelled", "lease_token": None},
                     actor=actor, action="video_cancelled", expected_version=version)


def retry(actor, identifier, version):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "video_project", identifier)
        if item["status"] not in {"error", "cancelled"}:
            raise MarketingError("VIDEO_NOT_FAILED", "Повтор доступен после ошибки или отмены.")
        return s.put(c, "video_project", {**item, "status": "queued_render" if item["storyboard"] else "queued_script",
                     "reason": "", "attempts": 0, "lease_token": None}, actor=actor,
                     action="video_retried", expected_version=version)


def run_one(model, now):
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return False
        for row in s.list_items(c, "video_project", status="writing_script"):
            if timestamp(row["lease_until"]) <= now:
                _save(c, row, status="error", reason="Работа над сценарием прервана. Повторите попытку.")
        queued = s.list_items(c, "video_project", status="queued_script")
        if not queued:
            return False
        item = _save(c, queued[-1], status="writing_script", lease_until=(now + timedelta(minutes=10)).isoformat())
    try:
        result = model.complete_json(DIRECTOR, s.encode({"brand": "UZStock", "brief": item["brief"], "pages": PAGES}),
                                     response_schema=Storyboard.model_json_schema(), max_tokens=3500)
        storyboard = Storyboard.model_validate(result).model_dump()
        changes = {"storyboard": storyboard, "status": "queued_render", "reason": ""}
    except Exception:
        changes = {"status": "error", "reason": "Агент не смог подготовить корректный сценарий. Повторите попытку."}
    with s.connection(write=True) as c:
        current = s.get(c, "video_project", item["id"])
        if current["version"] == item["version"]:
            _save(c, current, **changes)
    return True


def _heartbeat(c, now):
    previous = s.get(c, "runtime", "video_worker", required=False)
    if not previous or timestamp(previous["last_seen"]) + timedelta(seconds=45) <= now:
        s.put(c, "runtime", {"id": "video_worker", "last_seen": now.isoformat(), "voice": "uzstock-male-v1"},
              actor=AGENT, action="video_worker_heartbeat", expected_version=previous["version"] if previous else 0)


def worker_status(c, now):
    worker = s.get(c, "runtime", "video_worker", required=False)
    return {"online": bool(worker and timestamp(worker["last_seen"]) + timedelta(minutes=3) > now),
            "last_seen": worker["last_seen"] if worker else None, "voice": "uzstock-male-v1"}


def claim(now):
    with s.connection(write=True) as c:
        _heartbeat(c, now)
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return None
        for row in s.list_items(c, "video_project", status="rendering"):
            if timestamp(row["lease_until"]) <= now:
                _save(c, row, status="queued_render" if row["attempts"] < 3 else "error", lease_token=None,
                      reason="Связь с видеоворкером прервалась.")
        queued = s.list_items(c, "video_project", status="queued_render")
        if not queued:
            return None
        item = queued[-1]
        return _save(c, item, status="rendering", stage="narration", reason="", attempts=item["attempts"] + 1,
                     lease_token=secrets.token_urlsafe(32), lease_until=(now + timedelta(hours=1)).isoformat())


def leased(c, identifier, token, now):
    item = s.get(c, "video_project", identifier)
    if (item["status"] != "rendering" or not token or not item.get("lease_token")
            or not secrets.compare_digest(item["lease_token"], token) or timestamp(item["lease_until"]) <= now):
        raise MarketingError("VIDEO_LEASE_EXPIRED", "Задание отменено или передано другому воркеру.")
    return item


def progress(identifier, token, stage, now):
    with s.connection(write=True) as c:
        item = leased(c, identifier, token, now)
        _heartbeat(c, now)
        return _save(c, item, stage=stage, lease_until=(now + timedelta(hours=1)).isoformat())


def fail(identifier, token, now):
    with s.connection(write=True) as c:
        item = leased(c, identifier, token, now)
        return _save(c, item, status="error", lease_token=None,
                     reason="Не удалось создать видео на ПК. Проверьте локальный журнал и повторите попытку.")
