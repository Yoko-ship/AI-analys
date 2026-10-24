from __future__ import annotations

import meetings


class _Response:
    status_code = 200
    text = """
    <main>
      <div><h1>Extraordinary shareholders meeting</h1><span>Example issuer</span></div>
      <div><span class="font-medium">Publication date:</span><span>2026-09-11</span></div>
      <div class="prose">
        <p>Meeting notice body.</p>
        <h2>Organization information</h2>
        <div><div><p>Address:</p><p>Tashkent</p></div></div>
      </div>
      <a href="/announce/to_pdf/21349">PDF</a>
    </main>
    """

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, **_kwargs):
        assert url == "https://openinfo.uz/ru/announce/21349"
        return _Response()


def test_announcement_detail_returns_safe_structured_content() -> None:
    item = meetings.announcement_detail(21349, "ru", session=_Session())

    assert item["title"] == "Extraordinary shareholders meeting"
    assert item["organization"] == "Example issuer"
    assert item["metadata"] == [{"label": "Publication date", "value": "2026-09-11"}]
    assert {"kind": "paragraph", "text": "Meeting notice body."} in item["content"]
    assert {"kind": "heading", "text": "Organization information"} in item["content"]
    assert item["organization_details"] == [{"label": "Address", "value": "Tashkent"}]
    assert item["pdf_url"] == "https://openinfo.uz/announce/to_pdf/21349"
    assert item["source_url"] == "https://openinfo.uz/ru/announce/21349"


def test_source_announcement_is_cached_by_notice_and_language(monkeypatch) -> None:
    """Serve the source-language notice; repeated readers share its short cache."""
    import openinfo_http
    calls = []
    now = [1000.0]
    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            return _Response()
    monkeypatch.setattr(openinfo_http, "shared_session", lambda: Session())
    monkeypatch.setattr(meetings, "_detail_cache", {})
    monkeypatch.setattr(meetings.time, "time", lambda: now[0])
    first = meetings.announcement_detail(21349, "ru")
    second = meetings.announcement_detail(21349, "ru")
    assert len(calls) == 1
    assert first == second
    assert first["title"] == "Extraordinary shareholders meeting"
    assert first["content"][0]["text"] == "Meeting notice body."
    assert first["metadata"][0]["value"] == "2026-09-11"
    assert first["organization_details"][0]["value"] == "Tashkent"
    meetings.announcement_detail(21349, "uz")
    assert calls[-1] == "https://openinfo.uz/uz/announce/21349"
    meetings.announcement_detail(21350, "ru")
    assert calls[-1] == "https://openinfo.uz/ru/announce/21350"
    assert len(calls) == 3
    now[0] += meetings.DETAIL_TTL_SECONDS + 1
    meetings.announcement_detail(21349, "ru")
    assert len(calls) == 4
