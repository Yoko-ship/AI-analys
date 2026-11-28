"""Durable local rendering and file integrity. Model output never names a file."""
import csv
from datetime import timedelta
import hashlib
import io
import os
from pathlib import Path
import zipfile

from db import APP_DATA_DIR
from . import checks, content, publishing, sources, store as s
from .errors import MarketingError, require_owner
from .permissions import timestamp

RENDERER = {"id": "renderer", "role": "creative"}
MEDIA_FORMATS = {"image", "carousel", "video", "story"}
RENDER_VERSION = "uzstock-media-v9"
BASIS_FIELDS = ("title", "body", "language", "format", "entity", "period", "claims", "evidence_ids", "destination_url", "instagram_link")


def basis(item):
    value = {key: item.get(key) for key in BASIS_FIELDS}
    if item.get('occasion'):
        value['occasion'] = item['occasion']
    return s.digest({"renderer": RENDER_VERSION, "content": value})


def directory():
    database = Path(os.getenv("MARKETING_DB") or APP_DATA_DIR / "marketing.sqlite3")
    root = Path(os.getenv("MARKETING_MEDIA_DIR") or database.parent / "marketing-media") / s.digest(s.environment())[:16]
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def asset_path(asset):
    name = asset.get("file_name", "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise MarketingError("INVALID_ASSET", "Invalid media file identity.")
    return directory() / name


def valid_asset(asset):
    try:
        path = asset_path(asset)
        return (asset.get("status") == "ready" and 0 < path.stat().st_size <= 30_000_000
                and hashlib.sha256(path.read_bytes()).hexdigest() == asset.get("sha256"))
    except (OSError, MarketingError):
        return False


def read_asset(asset):
    try:
        path = asset_path(asset)
        if asset.get("status") != "ready" or not 0 < path.stat().st_size <= 30_000_000:
            raise OSError("Invalid asset size or status")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == asset.get("sha256"):
            return data
    except OSError:
        pass
    raise MarketingError("ASSET_UNAVAILABLE", "Медиафайл недоступен или изменён. Создайте новую проверенную версию.")


def _queue(c, kind, record, item, chart=None):
    evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
    versions = {key: value["version"] for key, value in evidence.items() if value}
    snapshot = {"item": item, "evidence": evidence, "source_versions": versions, "chart": chart, "basis": basis(item)}
    key = s.digest([kind, record["id"], snapshot["basis"], versions, chart])
    old = s.get(c, "render", key, required=False)
    if old:
        if old["status"] == "complete":
            assets = [s.get(c, "asset", key, required=False) for key in old["asset_ids"]]
            if not assets or not all(asset and valid_asset(asset) for asset in assets):
                return s.put(c, "render", {**old, "status": "queued", "attempts": 0, "reason": "Восстановление утраченного файла по сохранённым данным"},
                             actor=RENDERER, action="file_repair_requested", expected_version=old["version"])
            _attach(c, old, old["asset_ids"])
        elif old["status"] == "cancelled":
            return s.put(c, "render", {**old, "status": "queued", "attempts": 0, "reason": "Повторно запрошен рендер текущей версии"},
                         actor=RENDERER, action="current_render_requested", expected_version=old["version"])
        return old
    return s.put(c, "render", {"id": key, "target_kind": kind, "target_id": record["id"],
                 "task_id": record.get("task_id"), "snapshot": snapshot, "status": "queued", "attempts": 0,
                 "reason": "Ожидает локального рендера", "asset_ids": []}, actor=RENDERER,
                 action="render_requested", expected_version=0)


def request_candidate(actor, candidate_id, expected_version, *, chart=None):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "candidate", candidate_id)
        if item["version"] != expected_version:
            raise MarketingError("VERSION_CONFLICT", "This record changed. Reload before saving.")
        if item["status"] in content.TERMINAL or item["status"] == "sending":
            raise MarketingError("TERMINAL_CANDIDATE", "Finished or sending material cannot be rendered again.")
        if item["format"] not in MEDIA_FORMATS:
            raise MarketingError("MEDIA_FORMAT", "Choose an image, carousel, story or video format.", 422)
        return _queue(c, "candidate", item, item, chart)


def request_variants(c, task):
    from .production import candidate_data, drafts_for
    for variant in drafts_for(c, task["id"]):
        target = next(t for t in task["production"]["targets"] if t["account_id"] == variant["account_id"])
        if target["format"] in MEDIA_FORMATS:
            account = next(a for a in task["accounts"] if a["id"] == target["account_id"])
            _queue(c, "draft_variant", variant, candidate_data(task, target, variant, account), task['production'].get('chart'))


def variants_pending(c, task):
    """Only the jobs for the current copy count after an internal revision."""
    from .production import candidate_data, drafts_for
    for variant in drafts_for(c, task["id"]):
        target = next(t for t in task["production"]["targets"] if t["account_id"] == variant["account_id"])
        if target["format"] not in MEDIA_FORMATS:
            continue
        account = next(a for a in task["accounts"] if a["id"] == target["account_id"])
        item_basis = basis(candidate_data(task, target, variant, account))
        jobs = [job for job in s.list_items(c, "render") if job["target_kind"] == "draft_variant"
                and job["target_id"] == variant["id"] and job["snapshot"]["basis"] == item_basis]
        if not jobs or not any(job["status"] == "complete" for job in jobs):
            return True
    return False


def _current_item(c, job):
    record = s.get(c, job["target_kind"], job["target_id"])
    if job["target_kind"] == "candidate":
        return record, record
    from .production import candidate_data
    task = s.get(c, "task", record["task_id"])
    if task["status"] == "cancelled":
        return record, None
    target = next(t for t in task["production"]["targets"] if t["account_id"] == record["account_id"])
    account = next(a for a in task["accounts"] if a["id"] == record["account_id"])
    return record, candidate_data(task, target, record, account)


def _attach(c, job, asset_ids):
    record, item = _current_item(c, job)
    if not item or basis(item) != job["snapshot"]["basis"] or record["status"] in content.TERMINAL | {"sending"}:
        return False
    for key, version in job["snapshot"]["source_versions"].items():
        current = sources.current_evidence(c, key)
        if not current or current["version"] != version or current["status"] != "verified":
            return False
    refs = [{"id": key} for key in asset_ids]
    if record.get("assets") == refs:
        return True
    updates = {"assets": refs}
    if job["target_kind"] == "candidate":
        content._stop_pending_delivery(c, record, RENDERER, "blocked")
        updates.update(status="draft", check=None, approval=None)
        updates['tracking'] = content.publication_links.issue(c, {**record, **updates})
    else:
        proof = [{"id": key, "sha256": s.get(c, "asset", key)["sha256"]} for key in asset_ids]
        updates.update(digest=s.digest([record["text_digest"], proof]), review=None, status="draft")
    s.put(c, job["target_kind"], {**record, **updates}, actor=RENDERER,
          action="render_attached", expected_version=record["version"])
    return True


def _claim(now):
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return None
        if s.list_items(c, "render", status="running"):
            return None
        for job in reversed(s.list_items(c, "render", status="queued")):
            return s.put(c, "render", {**job, "status": "running", "claimed_at": now.isoformat(),
                         "claim_token": s.uid("render"), "attempts": job["attempts"] + 1,
                         "reason": "Создаётся локальный медиафайл"}, actor=RENDERER,
                         action="render_started", expected_version=job["version"])
    return None


def run_one(now, *, renderer=None):
    from .media_renderer import render
    job = _claim(now)
    if not job:
        return False
    try:
        snapshot = job["snapshot"]
        # Rendering is not the final rubric check. Check the shared facts/text
        # first, before drawing. The complete rubric and file proof run later.
        failures = checks.check({**snapshot["item"], "format": "post", "rubric": "news", "assets": []},
                                {key: value for key, value in snapshot["evidence"].items() if value}, now, {})
        if failures:
            raise MarketingError("RENDER_INPUT", "; ".join(failures))
        files = (renderer or render)({**snapshot, "rendered_at": now.isoformat()}, directory(), job["id"])
        if not files:
            raise ValueError("No files were rendered")
        with s.connection(write=True) as c:
            current = s.get(c, "render", job["id"])
            if current["status"] != "running" or current["claim_token"] != job["claim_token"]:
                return True
            ids = []
            for index, file in enumerate(files):
                key = s.digest([job["id"], index])
                asset = {**file, "id": key, "status": "ready", "basis": snapshot["basis"], "render_id": job["id"],
                         "source_versions": snapshot["source_versions"], "rights": "owned", "render_version": RENDER_VERSION}
                if not valid_asset(asset):
                    raise ValueError("Renderer did not produce a valid file")
                previous = s.get(c, "asset", key, required=False)
                s.put(c, "asset", asset, actor=RENDERER, action="file_rendered", expected_version=previous["version"] if previous else 0)
                ids.append(key)
            attached = _attach(c, job, ids)
            s.put(c, "render", {**current, "asset_ids": ids, "status": "complete" if attached else "cancelled",
                  "reason": "Медиафайл создан и связан с материалом" if attached else "Материал или оригинал изменился во время рендера; файл не присоединён"},
                  actor=RENDERER, action="render_finished", expected_version=current["version"])
    except Exception as exc:
        reason = exc.message if isinstance(exc, MarketingError) else "Локальный рендер не завершён. Входные данные сохранены; готового файла нет."
        with s.connection(write=True) as c:
            current = s.get(c, "render", job["id"])
            if current.get("claim_token") == job["claim_token"]:
                s.put(c, "render", {**current, "status": "error", "reason": reason}, actor=RENDERER,
                      action="render_failed", expected_version=current["version"])
    return True


def retry(actor, render_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        job = s.get(c, "render", render_id)
        if job["status"] != "error" or job["attempts"] >= 3:
            raise MarketingError("RETRY_UNAVAILABLE", "Render retry is unavailable or exhausted.")
        return s.put(c, "render", {**job, "status": "queued", "reason": "Повтор рендера по сохранённым входным данным"},
                     actor=actor, action="render_retry", expected_version=expected_version)


def recover(now):
    count = 0
    with s.connection(write=True) as c:
        for job in s.list_items(c, "render", status="running"):
            if timestamp(job["claimed_at"]) + timedelta(minutes=15) <= now:
                s.put(c, "render", {**job, "status": "queued" if job["attempts"] < 3 else "error",
                      "reason": "Восстановлен рендер по сохранённым входным данным"}, actor=RENDERER,
                      action="render_recovered", expected_version=job["version"])
                count += 1
    return count


def asset_csv(asset):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    chart = asset.get("chart") or {}
    writer.writerow(["date", "value", "unit"])
    for point in chart.get("series", []):
        writer.writerow([point["date"], point["value"], chart["unit"]])
    return output.getvalue()


def export_candidate(candidate_id):
    with s.connection() as c:
        item = s.get(c, "candidate", candidate_id)
        assets = [s.get(c, "asset", ref["id"]) for ref in item["assets"]]
        evidence = publishing.evidence_for(c, item)
        publication = publishing.preview(c, item, evidence=evidence)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("material.json", s.encode({"material": item, "evidence": list(evidence.values()), "assets": assets, "publication": publication}))
        archive.writestr("draft.txt", publication['text'])
        for asset in assets:
            archive.writestr("media/" + asset_path(asset).name, read_asset(asset))
            archive.writestr(f"media/{asset['id']}-alt.txt", asset["alt_text"])
            if asset.get("chart"):
                archive.writestr(f"data/{asset['id']}.csv", asset_csv(asset))
    return output.getvalue()
