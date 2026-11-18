"""Private editorial drafts, tied to the published source and its current text."""
from contextlib import closing
import hashlib
import json
from typing import Literal
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

import news_lang
from server.news import market_movers
from server.news import marketing_workspace_routes as workspace
from catalogue.storage import get_catalog_conn
from news_marketing import Pitches, campaign_tag
from server.auth.access import _admin_panel_gate, _require_admin
from server.seo.routes import SITE_URL, localized

router = APIRouter(prefix="/api/admin/marketing")


router.include_router(workspace.private)


class Submission(Pitches):
    revision: str = Field(min_length=64, max_length=64)


def _stories():
    return market_movers.stories(SITE_URL, post_link)


def _revision(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _snapshot():
    with closing(get_catalog_conn()) as conn:
        return conn.execute("SELECT revision, drafts FROM news_marketing WHERE slot = 1").fetchone()


def _valid_copy(copy, lang):
    for text in copy.model_dump().values():
        if not news_lang.in_own_script(text, lang) or re.search(r'https?://', text, re.I):
            return False
        # An otherwise Latin Uzbek sentence can still contain a mixed word like "hisobлади".
        if lang == "uz" and re.search(r'[a-z][\u0400-\u04ff]|[\u0400-\u04ff][a-z]', text, re.I):
            return False
    return True


def post_link(story_id, edition):
    path = localized("/market" if story_id < 0 else f"/news/{story_id}", edition)
    return f"{SITE_URL}{path}?utm_source=telegram&utm_medium=social&utm_campaign={campaign_tag(story_id, edition)}"


def verified_pitches(pitches, stories):
    by_id = {story["id"]: story for story in stories}
    result = []
    for pitch in pitches:
        story = by_id.get(pitch.id)
        if not story or not any(pitch.excerpt in story[key] for key in ("title", "snippet")):
            continue
        if not (_valid_copy(pitch.ru, "ru") and _valid_copy(pitch.uz, "uz")):
            continue
        idea = {**story, "excerpt": pitch.excerpt, "source_revision": _revision(story)}
        for lang, cta in (("ru", "Читайте на UZStock"), ("uz", "UZStock’da o‘qing")):
            copy = getattr(pitch, lang)
            link = post_link(pitch.id, lang)
            text = story[lang]["text"] if "ticker" in story else f"{copy.headline}\n\n{copy.body}\n\n{cta}\n{link}"
            idea[lang] = {"reason": copy.reason, "text": text}
        result.append(idea)
        del by_id[pitch.id]
    return result


@router.get("/candidates", dependencies=[Depends(_require_admin)])
def candidates():
    stories = _stories()
    revision = _revision(stories)
    saved = _snapshot()
    fields = ("id", "title", "snippet", "published_at", "source", "url")
    candidates = [] if saved and saved["revision"] == revision else [
        {k: story[k] for k in fields} for story in stories]
    return {"feedback": workspace.feedback(), "revision": revision, "stories": candidates}


@router.post("/candidates", dependencies=[Depends(_require_admin)])
def save(submission: Submission):
    stories = _stories()
    if submission.revision != _revision(stories):
        raise HTTPException(409, "Source stories changed during drafting")
    ideas = verified_pitches(submission.items, stories)
    if submission.items and not ideas:
        raise HTTPException(422, "Drafts must match distinct source stories and their evidence")
    with closing(get_catalog_conn()) as conn, conn:
        conn.execute("""INSERT INTO news_marketing(slot, revision, drafts) VALUES(1, ?, ?)
                        ON CONFLICT(slot) DO UPDATE SET revision=excluded.revision, drafts=excluded.drafts""",
                     (submission.revision, json.dumps(ideas, ensure_ascii=False)))
    return {"count": len(ideas)}


@router.get("", dependencies=[Depends(_admin_panel_gate)])
def desk():
    saved = _snapshot()
    enriched = {idea["source_revision"]: idea for idea in json.loads(saved["drafts"])} if saved else {}
    ideas = []
    for story in _stories():
        revision = _revision(story)
        if revision in enriched:
            ideas.append(enriched[revision])
        elif "ticker" in story:
            ideas.append({**story, "source_revision": revision})
    return {"items": workspace.decisions(ideas)}


@router.put("/posts/{story_id}/{edition}", dependencies=[Depends(_admin_panel_gate)])
def decide_post(story_id: int, edition: Literal["ru", "uz"], decision: workspace.Decision):
    idea = next((i for i in desk()["items"] if i["id"] == story_id), None)
    if not idea or idea["source_revision"] != decision.source_revision:
        raise HTTPException(409, "Source has changed. Refresh the drafts.")
    link = post_link(story_id, edition)
    if decision.status == "published" and link not in (line.strip() for line in decision.text.splitlines()):
        raise HTTPException(422, "Keep the tracking link in the published post.")
    now = workspace.stamp()
    with closing(get_catalog_conn()) as conn, conn:
        conn.execute("""INSERT INTO marketing_decisions(story_id,edition,revision,title,status,body,reason,updated,published)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(story_id,edition) DO UPDATE SET
                        revision=excluded.revision,title=excluded.title,status=excluded.status,body=excluded.body,
                        reason=excluded.reason,updated=excluded.updated,published=COALESCE(marketing_decisions.published,excluded.published)""",
                     (story_id, edition, decision.source_revision, idea["title"], decision.status, decision.text,
                      decision.reason.strip(), now, now if decision.status=="published" else None))
    return {"status":decision.status, "reason":decision.reason.strip()}
