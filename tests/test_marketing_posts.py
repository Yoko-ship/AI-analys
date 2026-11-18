from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
import news_store
from server.auth.access import _admin_panel_gate


def test_daily_marketing_round_trip(monkeypatch, tmp_path):
    from collectors.news import marketing
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "news.db"))
    monkeypatch.setenv("ADMIN_API_SECRET", "test-secret")
    client = TestClient(api.app)
    url = "/api/admin/marketing"
    assert client.get(url).status_code == 401
    monkeypatch.setitem(api.app.dependency_overrides, _admin_panel_gate, lambda: None)
    assert client.get(url).json()["items"] == []
    from catalogue import market_store
    row = dict(isin="ISIN-NGQS", ticker="NGQS", market="STK", trade_date="20261117",
               close_price=47616, prev_close=39680, quantity=27)
    market_store.bulk_upsert_quotes([row])
    quote = "39 680 → 47 616 UZS"
    assert client.get(url + "/candidates").status_code != 200
    headers = {"X-Admin-Secret": "test-secret"}
    calls = []
    def request(method, path, **kwargs):
        response = client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    def generate(stories, usage):
        calls.append(stories)
        return [dict(id=stories[0]["id"], excerpt=quote,
                     ru=dict(reason="Для акционеров важен статус выплаты.", headline="Рост цены закрытия", body="Акции подорожали за торговую сессию."),
                     uz=dict(reason="Aksiyadorlar uchun to‘lov holati muhim.", headline="Dividend taklif qilindi",
                             body="Kengash har bir aksiya uchun 100 so‘m taklif qildi."))]
    monkeypatch.setattr(marketing, "_prod_request", request)
    monkeypatch.setattr(marketing, "generate", generate)
    assert marketing.refresh(None) == 1
    marketing.refresh(None)
    assert len(calls) == 1
    idea, = client.get(url).json()["items"]
    assert idea["excerpt"] == quote
    assert idea["uz"]["text"].startswith("NGQS +20%")
    assert "https://uzstock.uz/uz/market?utm_source=telegram" in idea["uz"]["text"]
    assert "utm_campaign=mover-" in idea["ru"]["text"] and "/uz/market" not in idea["ru"]["text"]
    assert idea["uz"]["reason"] == "Aksiyadorlar uchun to‘lov holati muhim."
    market_store.bulk_upsert_quotes([{**row, "close_price": 39680}])
    assert client.get(url).json()["items"] == []


def test_unmatched_evidence_is_never_offered():
    from server.news.marketing_routes import verified_pitches
    from news_marketing import Pitch
    pitch = Pitch(id=4, excerpt="approved", ru=dict(headline="Решение", body="Решение принято", reason="Для инвесторов"),
                  uz=dict(headline="Qaror", body="Qaror qabul qilindi", reason="Investorlar uchun"))
    assert verified_pitches([pitch], [{"id": 4, "title": "Meeting", "snippet": "proposed"}]) == []


def test_generator_can_decline_all_candidates(monkeypatch):
    from collectors.news import marketing

    class Model:
        def complete_json(self, system, user, **kwargs):
            assert "Uzbek" in system and "Russian" in system
            assert "Only a meeting notice" in user
            assert kwargs["response_schema"]
            return {"items": []}

    monkeypatch.setattr(marketing, "get_classifier_client", lambda: Model())
    assert marketing.generate([{"id": 1, "title": "Only a meeting notice"}], None) == []


def test_collector_and_desk_accept_five_bilingual_stories(monkeypatch):
    from collectors.news import marketing
    from server.news.marketing_routes import Submission

    stories = [{"id": n, "title": f"Сообщение эмитента {n}"} for n in range(1, 7)]

    class Model:
        def complete_json(self, system, user, *, response_schema, **kwargs):
            assert response_schema["properties"]["items"]["maxItems"] == 5
            return {"items": [
                {"id": story["id"], "excerpt": story["title"],
                 "ru": {"headline": story["title"], "body": "Опубликован отчёт.", "reason": "Для акционеров."},
                 "uz": {"headline": "Hisobot", "body": "Hisobot e’lon qilindi.", "reason": "Aksiyadorlar uchun."}}
                for story in stories[:5]
            ]}

    monkeypatch.setattr(marketing, "get_classifier_client", lambda: Model())
    items = marketing.generate(stories, None)
    submission = Submission(revision="a" * 64, items=items)
    assert [p.id for p in submission.items] == [1, 2, 3, 4, 5]
    with pytest.raises(ValidationError, match="at most 5"):
        Submission(revision=submission.revision, items=[*items, {**items[-1], "id": 6}])


def test_mixed_script_word_in_uzbek_edition_is_rejected():
    from server.news.marketing_routes import verified_pitches
    from news_marketing import Pitch

    headline = "CONTACT FINANCE obligatsiya uchun 1 726,03 so‘m daromad hisobлади"
    story = dict(id=6544, title="CONTACT FINANCE: Начисление доходов по ц/б",
                 snippet="Начислено 1 726,03 сум на облигацию.")
    pitch = Pitch(id=6544, excerpt=story["snippet"],
                  ru=dict(headline=story["title"], body=story["snippet"], reason="Для держателей облигаций"),
                  uz=dict(headline=headline, body="Emitent daromad hisobladi.", reason="Obligatsiya egalari uchun"))
    assert verified_pitches([pitch], [story]) == []
    pitch.uz.headline = headline.replace("hisobлади", "hisobladi")
    assert len(verified_pitches([pitch], [story])) == 1

def test_editorial_feedback_survives_batch_and_reaches_generator(monkeypatch, tmp_path):
    from collectors.news import marketing
    from server.news import marketing_routes as routes
    import json
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "feedback.db"))
    monkeypatch.setenv("ADMIN_API_SECRET", "qa-secret")
    monkeypatch.setitem(api.app.dependency_overrides, _admin_panel_gate, lambda: None)
    story = dict(id=12, title="Дивиденд", snippet="100 сумов", published_at="today", url="https://example.test", source="Filing")
    monkeypatch.setattr(routes, "_stories", lambda: [story])
    text = "Дивиденд\nhttps://uzstock.uz/news/12?utm_source=telegram&utm_medium=social&utm_campaign=news-12-ru"
    item = {**story, "source_revision":routes._revision(story), "ru":{"text":text}, "uz":{"text":"UZ"}}
    from contextlib import closing
    with closing(routes.get_catalog_conn()) as conn, conn:
        conn.execute("INSERT INTO news_marketing VALUES(1, ?, ?)", ("old", json.dumps([item])))
    client = TestClient(api.app)
    payload = dict(status="published", text="Редактор добавил сумму.\n" + text, reason="Specific dividend amount", source_revision=item["source_revision"])
    wrong = dict(payload, text=text.replace("/news/12", "/unrelated"))
    assert client.put("/api/admin/marketing/posts/12/ru", json=wrong).status_code == 422
    resp = client.put("/api/admin/marketing/posts/12/ru", json=payload)
    assert resp.status_code == 200
    saved = client.get("/api/admin/marketing").json()["items"][0]
    assert saved["ru"]["decision"]["reason"] == payload["reason"]
    feedback = client.get("/api/admin/marketing/candidates",headers={"X-Admin-Secret":"qa-secret"}).json()["feedback"]
    assert "Редактор добавил сумму." in feedback[0]["editor_copy"]
    class Model:
        def complete_json(self, system, user, **kwargs):
            assert payload["reason"] in user and story["title"] in user
            return {"items":[]}
    monkeypatch.setattr(marketing, "get_classifier_client", lambda: Model())
    assert marketing.generate([story], None, feedback) == []
    monkeypatch.setattr(routes, "_stories", lambda: [])
    assert client.put("/api/admin/marketing/posts/12/ru", json=payload).status_code == 409
    assert client.get("/api/admin/marketing/workspace").json()["history"][0]["status"] == "published"


def test_real_exchange_movers_replace_unrelated_news(monkeypatch, tmp_path):
    from catalogue import market_store
    from server.news import marketing_routes as routes
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "movers.db"))
    monkeypatch.setitem(api.app.dependency_overrides, _admin_panel_gate, lambda: None)
    news_store.upsert_news([dict(title="В Ферганской области построят солнечную станцию на 500 МВт",
        published_at=datetime.now(timezone.utc).isoformat(), url="https://example.test/solar",
        source="News", relevant=True, relevance_score=1, impact="high", type="corporate_event")])
    def quote(ticker, close, prev, quantity, **extra):
        return dict(isin="ISIN-"+ticker, ticker=ticker, name=ticker, market="STK", trade_date="20261117",
                    prev_close=prev, close_price=close, quantity=quantity, turnover=close*quantity) | extra
    rows = [quote("NGQS",47616,39680,27), quote("ORGS",12787.2,10656,1), quote("UZINP",4800,5800,206581),
            quote("SMALL",0.015,0.014,170), quote("OTHER",105,100,50), quote("SIXTH",101,100,1),
            quote("BOND",200,100,5,market="BND"), quote("FLAT",50,50,1), quote("CARRY",500,100,0),
            quote("OLD",200,100,5,trade_date="20261116"), quote("NOBASE",500,None,5)]
    market_store.bulk_upsert_quotes(rows)
    client=TestClient(api.app)
    ideas=client.get("/api/admin/marketing").json()["items"]
    assert [i["ticker"] for i in ideas]==["NGQS","UZINP","ORGS","SMALL","OTHER"]
    assert len({i["id"] for i in ideas})==5
    assert ideas[0]["id"]<0
    for lang in ("ru","uz"):
        assert "NGQS +20%" in ideas[0][lang]["text"] and "UZINP −17,24%" in ideas[1][lang]["text"]
        assert "2026-11-17" in ideas[0][lang]["text"] and "39 680" in ideas[0][lang]["text"]
        assert "0,015" in ideas[3][lang]["text"] and "0,014" in ideas[3][lang]["text"]
    assert "/uz/market?" in ideas[0]["uz"]["text"]
    assert [s["id"] for s in routes.candidates()["stories"]] == [i["id"] for i in ideas]
    market_store.bulk_upsert_quotes([quote("NEW",100,None,1,trade_date="20261118")])
    assert client.get("/api/admin/marketing").json()["items"] == []
    assert routes.candidates()["stories"] == []
