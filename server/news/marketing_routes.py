"""Private editorial drafts, tied to the published source and its current text."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

import news_lang
import news_store
from catalogue.storage import get_catalog_conn
from news_marketing import Pitches
from server.auth.access import _admin_panel_gate, _require_admin
from server.seo.routes import SITE_URL, localized

router = APIRouter(prefix="/api/admin/marketing")


class Submission(Pitches):
    revision: str = Field(min_length=64, max_length=64)


def _stories():
    now = datetime.now(timezone.utc)
    result = []
    for item in news_store.get_news_feed(limit=60, days=3):
        try:
            stamp = datetime.fromisoformat(item["published_at"] or "")
        except ValueError:
            continue
        if not stamp.tzinfo:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if not now - timedelta(days=2) <= stamp <= now:
            continue
        story = {key: item[key] for key in ("id", "title", "source", "url", "published_at")}
        story["snippet"] = (item.get("snippet") or "")[:1800]
        result.append(story)
        if len(result) == 12:
            break
    return result


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
            path = localized(f"/news/{pitch.id}", lang)
            link = f"{SITE_URL}{path}?utm_source=telegram&utm_medium=social&utm_campaign=news-{pitch.id}-{lang}"
            idea[lang] = {"reason": copy.reason, "text": f"{copy.headline}\n\n{copy.body}\n\n{cta}\n{link}"}
        result.append(idea)
        del by_id[pitch.id]
    return result


@router.get("/candidates", dependencies=[Depends(_require_admin)])
def candidates():
    stories = _stories()
    revision = _revision(stories)
    saved = _snapshot()
    return {"revision": revision, "stories": [] if saved and saved["revision"] == revision else stories}


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
    if not saved:
        return {"items": []}
    current = {_revision(story) for story in _stories()}
    return {"items": [idea for idea in json.loads(saved["drafts"]) if idea["source_revision"] in current]}
