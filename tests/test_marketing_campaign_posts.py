from uuid import uuid4

from fastapi.testclient import TestClient

import api
from tests.test_marketing_workspace import BASE, desk


def brief(**changes):
    return {"request_id": str(uuid4()), "destination": "/heatmap", "edition": "uz",
            "channel": "telegram", **changes}


def test_launch_from_a_feature_persists_edits_and_attributes_reader_visits(desk, monkeypatch):
    from server.news import marketing_workspace_routes as workspace

    url = BASE + "/campaign-posts"
    params = brief()
    response = desk.post(url, json=params)
    assert response.status_code == 201, response.text
    post = response.json()
    tag = "feature-" + params["request_id"]
    assert post["tag"] == tag and post["status"] == "draft"
    assert post["link"].endswith("/uz/heatmap?utm_source=telegram&utm_medium=social&utm_campaign=" + tag)
    assert "xarita" in (post["headline"] + post["body"]).lower()
    assert desk.post(url, json=params).json() == post
    assert desk.post(url, json={**params, "edition": "en"}).status_code == 409
    path = url + "/" + post["id"]
    edit = dict(headline="Sektorlar bo‘yicha taqqoslang", body=post["body"], version=post["version"], publish=False)
    saved = desk.put(path, json=edit).json()
    assert saved["headline"] == edit["headline"] and saved["version"] > post["version"]
    assert desk.put(path, json={**edit, "body": "Stale browser text"}).status_code == 409
    published = desk.put(path, json={**edit, "version": saved["version"], "publish": True}).json()
    assert published["status"] == "published" and published["published"]
    assert desk.get(url).json()["items"] == [published]
    assert desk.put(path, json={**edit, "version": published["version"]}).status_code == 409
    captured = []
    monkeypatch.setattr(workspace, "measurements", lambda tags, trials: captured.extend(tags) or {"available": True})
    workspace = desk.get(BASE + "/workspace").json()
    assert tag in captured and workspace["campaign_names"][tag] == edit["headline"]


def test_approved_plan_supplies_real_destination_and_grounded_ai_brief(desk, monkeypatch):
    from server.news import campaign_post_routes, marketing_workspace_routes as workspace

    plan = {"audience": "First-time readers", "channel": "Telegram", "destination": "/uz/issuers",
            "schedule": ["Introduce company profiles on Friday"]}
    class Model:
        def complete_json(self, system, user, **kwargs):
            if kwargs["response_schema"]["title"] == "Plan":
                return plan
            assert "First-time readers" in user and "company profiles" in user and "/issuers" in user
            assert "short" in user
            return {"headline": "Who stands behind a ticker?", "body": "Open the issuer directory and choose a company to explore its profile."}
    monkeypatch.setattr(workspace, "get_classifier_client", lambda: Model())
    monkeypatch.setattr(campaign_post_routes, "get_classifier_client", lambda: Model())
    plan_id = desk.post(BASE + "/plans", json={"goal":"Introduce company profiles", "language":"en"}).json()["id"]
    url = BASE + "/campaign-posts"
    params = brief(plan_id=plan_id, edition="en", channel="linkedin", destination="/issuers")
    assert desk.post(url, json=params).status_code == 409
    assert desk.put(BASE + "/plans/" + plan_id, json={**plan, "approve":True}).status_code == 200
    post = desk.post(url, json=params).json()
    from urllib.parse import parse_qs, urlsplit
    landing = urlsplit(post["link"])
    assert landing.path == "/issuers"
    assert parse_qs(landing.query)["lang"] == ["en"] and parse_qs(landing.query)["utm_source"] == ["linkedin"]
    path = url + "/" + post["id"] + "/suggest"
    suggestion = desk.post(path, json={"brief":"Keep it short", "version":post["version"]})
    assert suggestion.status_code == 200
    assert suggestion.json()["headline"] == "Who stands behind a ticker?"
    assert desk.get(url).json()["items"][0] == post
    class WrongEdition:
        def complete_json(self, *args, **kwargs):
            return {"headline": "Tiker ortida qaysi korxona turibdi?",
                    "body": "Emitentlar katalogini oching va o‘zingiz bilgan kompaniyani toping."}
    monkeypatch.setattr(campaign_post_routes, "get_classifier_client", lambda: WrongEdition())
    assert desk.post(path, json={"version":post["version"]}).status_code == 503
    monkeypatch.setattr(campaign_post_routes, "get_classifier_client", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert desk.post(path, json={"brief":"Keep it short", "version":post["version"]}).status_code == 503
    assert desk.get(url).json()["items"][0] == post


def test_feature_campaigns_are_private_and_destinations_belong_to_the_site():
    client = TestClient(api.app)
    url = BASE + "/campaign-posts"
    assert client.get(url).status_code == 401
    assert client.post(url, json=brief()).status_code == 401


def test_feature_campaign_rejects_external_or_unsupported_destinations(desk):
    assert desk.post(BASE + "/campaign-posts", json=brief(destination="https://example.org")).status_code == 422
