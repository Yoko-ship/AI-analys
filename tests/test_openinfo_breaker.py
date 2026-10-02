"""openinfo must not be asked what uzse.uz was asked: on and on after it said no."""
import json
from collections import Counter

import pytest

import openinfo_http as h


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(h, "_paused_until", 0.0)
    monkeypatch.setattr(h, "_block_streak", 0)
    monkeypatch.setattr(h, "_unflushed", Counter())
    monkeypatch.setattr(h, "_JOB", "collector_financials.py --trades-only")
    return tmp_path


def test_repeated_refusals_pause_every_process(state) -> None:
    for _ in range(h.BLOCK_STREAK - 1):
        h._record(403, "https://new-api.openinfo.uz/x")
    assert not h.paused_until()
    h._record(429, "https://new-api.openinfo.uz/x")
    assert h.paused_until()
    # Shared through the data directory: a fresh process reads the same pause.
    h._paused_until = 0.0
    assert (state / h._PAUSE_FILE).exists() and h.paused_until()
    with pytest.raises(h.OpeninfoPaused):
        h.make_session().get("https://new-api.openinfo.uz/api/v2/x")


def test_an_answer_in_between_resets_the_streak(state) -> None:
    for status in (403, 403, 200, 403, 403):
        h._record(status, "https://new-api.openinfo.uz/x")
    assert not h.paused_until()


def test_requests_are_counted_per_day(state) -> None:
    for _ in range(3):
        h._record(200, "https://new-api.openinfo.uz/x")
    h._flush_count()
    h._record(200, "https://new-api.openinfo.uz/x")
    h._flush_count()
    [counter] = state.glob("openinfo-requests-*.json")
    assert json.loads(counter.read_text())["requests"] == 4


def test_the_count_says_which_job_and_endpoint_and_includes_retries(state) -> None:
    h._record(200, "https://new-api.openinfo.uz/api/v2/iuzse/conclusions/?isu_cd=UZ7011340005")
    h._record(200, "https://new-api.openinfo.uz/api/v2/organizations/538/reports/", tries=3)
    h._record(200, "https://openinfo.uz/media/files/a.xlsx")
    h._flush_count()
    [counter] = state.glob("openinfo-requests-*.json")
    data = json.loads(counter.read_text())
    assert data["requests"] == 5
    assert data["by_job"] == {"collector_financials.py --trades-only": 5}
    assert data["by_endpoint"] == {"/iuzse/conclusions/": 1, "/organizations/{id}/reports/": 3,
                                   "openinfo.uz/media/files/{file}": 1}
