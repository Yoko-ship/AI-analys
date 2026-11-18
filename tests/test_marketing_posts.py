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
    now = datetime.now(timezone.utc).isoformat()
    quote = "Совет предложил выплатить 100 сумов на акцию."
    news_store.upsert_news([dict(title="Предложение совета", snippet=quote, relevant=True,
                                 relevance_score=1, impact="high", type="corporate_event",
                                 source="OpenInfo", url="https://openinfo.uz/fact/1", published_at=now)])
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
                     ru=dict(reason="Для акционеров важен статус выплаты.", headline="Дивиденд пока предложен", body=quote),
                     uz=dict(reason="Aksiyadorlar uchun to‘lov holati muhim.", headline="Dividend taklif qilindi",
                             body="Kengash har bir aksiya uchun 100 so‘m taklif qildi."))]
    monkeypatch.setattr(marketing, "_prod_request", request)
    monkeypatch.setattr(marketing, "generate", generate)
    assert marketing.refresh(None) == 1
    marketing.refresh(None)
    assert len(calls) == 1
    idea, = client.get(url).json()["items"]
    assert idea["excerpt"] == quote
    assert idea["uz"]["text"].startswith("Dividend taklif qilindi\n\nKengash")
    assert f"https://uzstock.uz/uz/news/{idea['id']}?utm_source=telegram" in idea["uz"]["text"]
    assert "/uz/news/" not in idea["ru"]["text"]
    assert "utm_campaign=" in idea["ru"]["text"]
    assert idea["url"] == "https://openinfo.uz/fact/1"
    news_store.set_snippets({idea["url"]: "Исправленный текст публикации. Совет отозвал ранее опубликованное предложение."})
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
