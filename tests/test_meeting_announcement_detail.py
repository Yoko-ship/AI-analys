from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient

import api
import meetings


ANNOUNCEMENT_HTML = """
<html><body><main>
  <div>
    <div>
      <h1>Внеочередное общее собрание акционеров</h1>
      <div><span>"Sinov kompaniyasi" AJ</span></div>
    </div>
    <div class="grid">
      <div><span class="font-medium">Дата публикации:</span><span>20.08.2026 09:00</span></div>
      <div><span class="font-medium">Адрес:</span><span>Ташкент, ул. Тестовая, 1</span></div>
    </div>
    <a href="/ru/announce/to_pdf/21211/">Скачать PDF</a>
    <div class="prose"><div>
      <p><strong>Акционерам общества</strong></p>
      <p>Полный текст <em>объявления</em> на странице.</p>
      <ul><li>Первый вопрос повестки дня.</li></ul>
    </div></div>
    <div>
      <h3>Информация об организации</h3>
      <div class="grid">
        <div><p class="font-medium">ИНН:</p><p>200000001</p></div>
        <div><p class="font-medium">Короткое название:</p><p>SINOV AJ</p></div>
      </div>
    </div>
  </div>
</main></body></html>
"""


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_announcement_detail_parses_safe_structured_content() -> None:
    session = FakeSession(FakeResponse(ANNOUNCEMENT_HTML))

    item = meetings.announcement_detail(21211, "ru", session=session)

    assert session.calls[0][0] == "https://openinfo.uz/ru/announce/21211"
    assert item["title"] == "Внеочередное общее собрание акционеров"
    assert item["organization"] == '"Sinov kompaniyasi" AJ'
    assert item["metadata"] == [
        {"label": "Дата публикации", "value": "20.08.2026 09:00"},
        {"label": "Адрес", "value": "Ташкент, ул. Тестовая, 1"},
    ]
    assert item["content"] == [
        {"kind": "heading", "text": "Акционерам общества"},
        {"kind": "paragraph", "text": "Полный текст объявления на странице."},
        {"kind": "list_item", "text": "Первый вопрос повестки дня."},
    ]
    assert item["organization_details"] == [
        {"label": "ИНН", "value": "200000001"},
        {"label": "Короткое название", "value": "SINOV AJ"},
    ]
    assert item["pdf_url"] == "https://openinfo.uz/ru/announce/to_pdf/21211/"
    assert item["source_url"] == "https://openinfo.uz/ru/announce/21211"


def test_announcement_detail_maps_a_source_404() -> None:
    session = FakeSession(FakeResponse("not found", 404))

    with pytest.raises(meetings.AnnouncementNotFound):
        meetings.announcement_detail(999999, "ru", session=session)


def test_announcement_detail_rejects_a_non_announcement_page() -> None:
    session = FakeSession(FakeResponse("<html><body>maintenance</body></html>"))

    with pytest.raises(meetings.AnnouncementSourceError, match="content is missing"):
        meetings.announcement_detail(21211, "ru", session=session)


def test_announcement_detail_rejects_an_external_pdf_link() -> None:
    html = ANNOUNCEMENT_HTML.replace(
        "/ru/announce/to_pdf/21211/",
        "https://example.com/announce/to_pdf/21211/",
    )

    item = meetings.announcement_detail(21211, "ru", session=FakeSession(FakeResponse(html)))

    assert item["pdf_url"] == ""


def test_announcement_api_returns_the_parsed_item(monkeypatch) -> None:
    item = meetings._announcement_page(ANNOUNCEMENT_HTML, "21211", "ru")
    monkeypatch.setattr(meetings, "announcement_detail", lambda announcement_id, language: item)

    response = TestClient(api.app).get("/api/news/calendar/announcements/21211?language=ru")

    assert response.status_code == 200
    assert response.json()["item"]["title"] == "Внеочередное общее собрание акционеров"


@pytest.mark.parametrize("language", ["de", "RU-ru"])
def test_announcement_detail_rejects_unsupported_languages(language: str) -> None:
    with pytest.raises(ValueError, match="language"):
        meetings.announcement_detail(21211, language, session=FakeSession(FakeResponse("")))
