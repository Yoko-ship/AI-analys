"""A profile CTA is an approved route, never a boolean assertion or model promise."""
from urllib.parse import urlsplit

import pytest
from PIL import ImageDraw

from marketing import content, media, publishing, store, worker
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401
from test_marketing_instagram import queued_instagram, IG_ID
from test_marketing_facebook import current


@pytest.mark.parametrize("format", ["image", "story"])
@pytest.mark.parametrize("language,body,cta", [
    ("ru", "Утверждено 120 сум на простую акцию.", "Подробнее — по ссылке в профиле."),
    ("uz", "Oddiy aksiya uchun 120 so‘m dividend tasdiqlandi.", "Batafsil — profildagi havola orqali."),
])
def test_profile_route_is_rendered_reviewed_and_verified_again_before_publication(monkeypatch, format, language, body, cta):
    drawn, original = [], ImageDraw.ImageDraw.text
    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    peer, job, files = queued_instagram(monkeypatch, format, instagram_link="profile", language=language, body=body)
    assert cta in " ".join(" ".join(drawn).split())
    assert cta in files[0]["alt_text"]
    with store.connection() as c:
        item = store.get(c, "candidate", job["candidate_id"])
        preview = publishing.preview(c, item)
    assert preview["instagram_link"] == "profile"
    assert preview["link_destination"] == item["destination_url"]
    import io
    import json
    import zipfile
    with zipfile.ZipFile(io.BytesIO(media.export_candidate(item['id']))) as archive:
        assert archive.read('draft.txt').decode() == preview['text']
        assert json.loads(archive.read('material.json'))['publication']['link_destination'] == preview['link_destination']
    assert (cta in preview["text"]) is (format != "story")
    assert worker.tick(now=NOW)["delivery_work"]
    saved = current(job)
    assert saved["status"] == "submitted", saved["reason"]
    assert saved["dispatch_payload"]["profile_link"]["url"] == item["destination_url"]
    assert saved["dispatch_payload"]["profile_link"]["account_external_id"] == IG_ID
    paths = [(r.method, urlsplit(r.url).path) for r in peer.calls]
    assert paths.count(("GET", "/v25.0/" + IG_ID)) == 2
    assert paths.index(("GET", "/v25.0/" + IG_ID)) < paths.index(("POST", f"/v25.0/{IG_ID}/media"))
    assert len(peer.publishes) == 1


@pytest.mark.parametrize("profile", [
    {"id": IG_ID}, {"id": IG_ID, "website": "https://uzstock.uz/"},
    {"id": IG_ID, "website": "https://uzstock.uz/news/different"},
    {"id": IG_ID, "website": "https://uzstock.uz/news/decision-123?lang=uz"},
    {"id": IG_ID, "website": "http://uzstock.uz/news/decision-123"},
    {"id": IG_ID, "website": "https://uzstock.uz.evil.example/news/decision-123"},
    {"id": "555", "website": "https://uzstock.uz/news/decision-123"},
])
def test_legacy_ready_flag_cannot_replace_exact_profile_route_proof(monkeypatch, profile):
    peer, job, _ = queued_instagram(monkeypatch, instagram_link="profile")
    peer.profile = profile
    worker.tick(now=NOW)
    assert current(job)["status"] == "blocked"
    assert not peer.containers and not peer.publishes
    assert "profile link" in current(job)["reason"]
    with store.connection() as c:
        assert store.get(c, "candidate", job["candidate_id"])["status"] == "skipped"


def test_profile_route_changed_during_media_preparation_is_not_published(monkeypatch):
    peer, job, _ = queued_instagram(monkeypatch, instagram_link="profile")
    peer.after_fetch = lambda: peer.profile.update(website="https://uzstock.uz/news/newer")
    worker.tick(now=NOW)
    assert current(job)["status"] == "blocked" and peer.fetched and not peer.publishes
    assert current(job)["confirmed_not_sent"]


@pytest.mark.parametrize("body", [
    "Подробнее по ссылке в профиле.", "Переходите в профиль и читайте разбор.",
    "Profilimizdagi havola orqali batafsil o‘qing.", "Havola bio’da.",
    "Read more: link in bio.", "Follow the link in our profile.",
    "Нажмите на ссылку-стикер в Stories.", "Swipe up to open the report.",
])
def test_freeform_promises_cannot_bypass_the_structured_route(body):
    item = candidate(body=body)
    assert "Instagram link instructions must use the selected route, not freeform copy" in publishing.check({"platform": "instagram"}, {**item, "format": "image"}, {})


@pytest.mark.parametrize("body", ["Профиль компании содержит финансовые показатели.", "Company profile data changed.", "Kompaniya profili yangilandi."])
def test_discussing_a_company_profile_is_not_a_link_promise(body):
    item = candidate(body=body)
    assert publishing.check({"platform": "instagram"}, {**item, "format": "image"}, {}) == []


def test_route_revision_invalidates_media_and_manual_approval_without_changing_legacy_digests():
    account(platform="instagram", formats=["image"], mode="manual")
    evidence()
    item = candidate(format="image", mode="manual")
    old = {key: value for key, value in item.items() if key != "instagram_link"}
    expected = store.digest({key: old.get(key) for key in content.Candidate.model_fields if key != "instagram_link"})
    assert content.content_digest(old) == expected
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    approved = content.approve_candidate(OWNER, item["id"], checked["version"])
    revised = content.revise_candidate(OWNER, item["id"], {"instagram_link": "profile"}, approved["version"])
    assert revised["approval"] is None and revised["check"] is None
    assert media.basis(revised) != media.basis(approved)
    assert content.content_digest(revised) != content.content_digest(approved)
    assert content.check_candidate(item["id"], NOW)["status"] == "needs_revision"


def test_profile_cta_does_not_push_three_financial_fact_units_out_of_their_cards(monkeypatch, tmp_path):
    from marketing import media_renderer
    panels, texts = [], []
    rectangle, text = ImageDraw.ImageDraw.rounded_rectangle, ImageDraw.ImageDraw.text
    def capture_panel(draw, xy, *args, **kwargs):
        if xy[0] == 72 and xy[1] >= 550:
            panels.append(xy)
        return rectangle(draw, xy, *args, **kwargs)
    def capture_text(draw, xy, value, *args, **kwargs):
        if str(value) in {"1000000", "900000", "50000", "UZS"}:
            texts.append(draw.textbbox(xy, value, font=kwargs["font"]))
        return text(draw, xy, value, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "rounded_rectangle", capture_panel)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    item = candidate(format="image", instagram_link="profile", rubric="news", claims=[
        {"evidence_id": "report", "field": field, "value": amount, "unit": "UZS"}
        for field, amount in [("total_assets", 1000000), ("revenue", 900000), ("net_income", 50000)]])
    snapshot = {"item": item, "evidence": {"report": {"url": "https://openinfo.uz/reports/123", "data": {}}}}
    media_renderer.render(snapshot, tmp_path, "three-facts")
    assert len(texts) == 6 and len(panels) == 3
    assert all(any(left <= x1 < x2 <= right and top <= y1 < y2 <= bottom for left, top, right, bottom in panels)
               for x1, y1, x2, y2 in texts)


def test_production_route_is_owner_scoped_and_reaches_the_render_snapshot():
    from marketing import agents, production
    from test_marketing_production import brief, prepare_accounts, ProductionModel, run_team
    prepare_accounts()
    scope = brief(targets=[{"account_id": "instagram", "languages": ["ru"], "primary_language": "ru", "format": "image", "instagram_link": "profile"}])
    task = agents.start(OWNER, kind="content", message="Переход через настроенный профиль", evidence_ids=["decision"], production=scope)
    run_team(ProductionModel(), count=6)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        variant = production.drafts_for(c, task["id"])[0]
    draft = production.candidate_data(saved, saved["production"]["targets"][0], variant, saved["accounts"][0])
    assert draft["instagram_link"] == "profile"
    with store.connection() as c, pytest.raises(Exception, match="Instagram"):
        production.scope_context(c, brief(targets=[{**scope["targets"][0], "account_id": "telegram"}]))
