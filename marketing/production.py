"""Convert persisted model drafts into account-scoped, checked candidates."""
from . import content, digest_material, store as s
from .errors import MarketingError, require_owner
from .production_models import ProductionBrief

COORDINATOR = {"id": "coordinator", "role": "coordinator"}


def scope_context(c, value):
    scope = ProductionBrief.model_validate(value).model_dump(mode="json")
    accounts = []
    for target in scope["targets"]:
        account = s.get(c, "account", target["account_id"])
        if target["instagram_link"] != "none" and account["platform"] != "instagram":
            raise MarketingError("LINK_SCOPE", "The Instagram profile route requires an Instagram account", 422)
        if not set(target["languages"]) <= set(account["languages"]):
            raise MarketingError("LANGUAGE_SCOPE", "Requested languages are outside the configured account languages.", 422)
        accounts.append({key: account[key] for key in ("id", "label", "platform", "mode", "languages", "formats", "rubrics")})
    return scope, accounts


def task_key(scope):
    # Language changes must not manufacture another publication identity.
    return "production_" + s.digest([scope["event_id"], sorted(target["account_id"] for target in scope["targets"])])


def validate_output(task, role, result):
    if result.get("strategy") and (role != "cmo" or result["verdict"] != "accept" or task["kind"] not in {"strategy", "dialogue", "report"}):
        raise ValueError("Only an accepted CMO planning result can propose a strategy")
    if role == "cmo" and task["kind"] == "strategy" and result["verdict"] == "accept" and not result.get("strategy"):
        raise ValueError("An accepted strategy task must deliver the full structured plan")
    if result.get("feasibility") and (role != "cmo" or task["kind"] not in {"strategy", "dialogue", "report"}):
        raise ValueError("Only CMO planning work can assess structured feasibility")
    if result.get("experiments"):
        if role not in {"targeting", "cmo"} or task["kind"] not in {"experiment", "strategy"}:
            raise ValueError("Only targeting and CMO can propose paid experiments within a planning task")
        allowed_creatives = {item["id"] for item in task.get("paid_creatives", [])}
        if any(not set(item["candidate_ids"]) <= allowed_creatives for item in result["experiments"]):
            raise ValueError("A paid proposal referenced an unknown creative")
    if result["drafts"] and role != "copywriter":
        raise ValueError("Only the copywriter supplies structured draft text")
    if result["reviews"] and role != "quality":
        raise ValueError("Only the quality role supplies draft reviews")
    if not task.get("production"):
        if result["drafts"] or result["reviews"]:
            raise ValueError("Structured production needs an owner-selected scope")
        return
    if role != "copywriter":
        return
    expected = {(target["account_id"], lang) for target in task["production"]["targets"] for lang in target["languages"]}
    actual = [(draft["account_id"], draft["language"]) for draft in result["drafts"]]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Draft recipients/languages differ from the owner scope")
    evidence_ids = set(task["evidence_versions"])
    for draft in result["drafts"]:
        chart = task['production'].get('chart')
        if chart and chart['evidence_id'] not in draft['evidence_ids']:
            raise ValueError('A chart draft must retain the owner-selected source series')
        occasion = task['production'].get('occasion')
        if occasion and occasion['evidence_id'] not in draft['evidence_ids']:
            raise ValueError('An occasion draft must retain its owner-selected original')
        if not set(draft["evidence_ids"]) <= evidence_ids or not set(draft["founder_fact_ids"]) <= set(task["production"]["founder_fact_ids"]):
            raise ValueError("A draft introduced an unrequested evidence or founder identity")
        if draft.get("digest_items"):
            if task["production"]["rubric"] not in {"digest", "calendar"} or any(not set(entry["evidence_ids"]) <= set(draft["evidence_ids"]) for entry in draft["digest_items"]):
                raise ValueError("Source-bound items must use this draft's selected originals within the digest or calendar rubric")
    # Identical cross-channel copy does not fulfill platform adaptation.
    for language in {language for _, language in expected}:
        bodies = [" ".join(draft["body"].split()).casefold() for draft in result["drafts"] if draft["language"] == language]
        if len(bodies) != len(set(bodies)):
            raise ValueError("Each account needs its own adapted text")


def save_drafts(c, task, drafts):
    for draft in drafts:
        if task["production"]["rubric"] in {"digest", "calendar"}:
            draft = {**draft, "body": digest_material.prepare(c, {**draft, "rubric": task['production']['rubric']})["body"]}
        key = s.digest([task["id"], draft["account_id"], draft["language"]])
        previous = s.get(c, "draft_variant", key, required=False)
        s.put(c, "draft_variant", {**draft, "id": key, "task_id": task["id"], "digest": s.digest(draft),
              "text_digest": s.digest(draft), "status": "draft", "review": None, "assets": []}, actor={"id": "copywriter", "role": "copywriter"},
              action="platform_draft_saved", expected_version=previous["version"] if previous else 0)


def drafts_for(c, task_id):
    return [draft for draft in s.list_items(c, "draft_variant") if draft["task_id"] == task_id]


def finalize(task_id, now):
    """Idempotent recovery also runs when a process stops after the last role."""
    with s.connection(write=True) as c:
        task = s.get(c, "task", task_id)
        if not task.get("production") or task.get("candidate_ids") or task["status"] not in {"complete", "blocked"}:
            return False
        final = task["outputs"][-1] if task["outputs"] else None
        if not final or final["role"] != "quality":
            return False
        reviews = final["result"]["reviews"]
        variants = drafts_for(c, task_id)
        for variant in variants:
            matching = [review for review in reviews if review["draft_id"] == variant["id"] and review["draft_digest"] == variant["digest"]]
            review = matching[0] if len(matching) == 1 else {"verdict": "reject", "reason": "This exact draft has no unique quality review", "fragments": []}
            if final["result"]["verdict"] != "accept":
                review = {**review, "verdict": "reject", "reason": final["result"]["handoff"]}
            variant.update(review=review, status="reviewed" if review["verdict"] == "accept" else "rejected")
            saved = s.put(c, "draft_variant", variant, actor={"id": "quality", "role": "quality"},
                          action="draft_reviewed", expected_version=variant["version"])
            variant.update(saved)
    candidate_ids = []
    for target in task["production"]["targets"]:
        variant = next((v for v in variants if v["account_id"] == target["account_id"] and v["language"] == target["primary_language"]), None)
        if not variant:
            continue
        account = next(a for a in task["accounts"] if a["id"] == target["account_id"])
        data = candidate_data(task, target, variant, account)
        item = content.create_candidate(data, provenance={"origin_task": task_id, "origin_variant": variant["id"],
                                        "editorial_review": variant["review"]})
        # Replayed completion cannot reset a human decision or another task's post.
        if item.get("origin_task") == task_id and not item.get("check"):
            content.check_candidate(item["id"], now)
        candidate_ids.append(item["id"])
    with s.connection(write=True) as c:
        current = s.get(c, "task", task_id)
        if not current.get("candidate_ids"):
            s.put(c, "task", {**current, "candidate_ids": candidate_ids, "status": "complete",
                  "reason": "Варианты сохранены; результаты проверки и выпуска доступны в материалах."}, actor=COORDINATOR,
                  action="production_materialized", expected_version=current["version"])
    return True


def candidate_data(task, target, variant, account):
    scope = task["production"]
    draft = {key: variant[key] for key in ("account_id", "language", "title", "body", "evidence_ids", "claims", "destination_url", "founder_fact_ids", "calculation")}
    draft["digest_items"] = variant.get("digest_items", [])
    return {**draft, "event_id": scope["event_id"], "rubric": scope["rubric"], "entity": scope["entity"],
            'occasion': scope.get('occasion'),
            "period": scope["period"], "expires_at": scope["expires_at"], "not_before": scope.get("not_before"), "format": target["format"], "assets": variant.get("assets", []),
            "mode": "draft" if scope["mode"] == "draft" else account["mode"], "instagram_link": target.get("instagram_link", "none"), "track_visits": True}


def recover_completed(now):
    with s.connection() as c:
        pending = [task["id"] for task in s.list_items(c, "task") if task.get("production") and not task.get("candidate_ids")
                   and task["status"] in {"complete", "blocked"} and task["outputs"] and task["outputs"][-1]["role"] == "quality"]
    return bool(pending and finalize(pending[-1], now))


def select_variant(actor, variant_id, expected_version, *, now=None):
    require_owner(actor)
    with s.connection() as c:
        variant = s.get(c, "draft_variant", variant_id)
        task = s.get(c, "task", variant["task_id"])
        if not variant.get("review") or variant["review"]["verdict"] != "accept":
            raise MarketingError("REVIEW_REQUIRED", "Only a reviewed language variant can replace a manual draft.")
        key = s.digest([task["production"]["event_id"], variant["account_id"], "organic"])
        item = s.get(c, "candidate", key)
        if item.get("origin_task") != task["id"] or item["mode"] == "automatic":
            raise MarketingError("VARIANT_LOCKED", "Automatic candidates and other production tasks cannot be replaced by a language variant.")
    changes = {key: variant[key] for key in ("language", "title", "body", "evidence_ids", "claims", "destination_url", "founder_fact_ids", "calculation")}
    changes["digest_items"] = variant.get("digest_items", [])
    changes['occasion'] = task['production'].get('occasion')
    changes["assets"] = variant.get("assets", [])
    changed = content.revise_candidate(actor, item["id"], changes, expected_version, review_destination=False)
    from datetime import datetime, timezone
    return content.check_candidate(changed["id"], now or datetime.now(timezone.utc))
