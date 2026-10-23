from fastapi.testclient import TestClient
import pytest
import api
from server.currency import history


def test_archive_rate_is_dated_persisted_and_divided_by_nominal(monkeypatch,tmp_path):
    monkeypatch.setenv("CBU_HISTORY_DB", str(tmp_path/"fx.sqlite3"))
    calls=[]
    def fetch(day):
        calls.append(day)
        return [{"Ccy":"USD","Rate":"120000","Nominal":"10","Date":"30.12.2025"}]
    monkeypatch.setattr(history,"fetch",fetch)
    first=history.rates("2025-12-31")
    assert first["rates"][0]["per_unit"] == 12000
    assert first["rates"][0]["effective_date"] == "2025-12-30"
    assert history.rates("2025-12-31") == first
    assert calls == ["2025-12-31"]


def test_archive_never_substitutes_current_or_future_rate(monkeypatch,tmp_path):
    monkeypatch.setenv("CBU_HISTORY_DB", str(tmp_path/"fx.sqlite3"))
    monkeypatch.setattr(history,"fetch",lambda day:[{"Ccy":"USD","Rate":"13000","Nominal":"1","Date":"01.01.2026"}])
    with pytest.raises(ValueError):history.rates("2025-12-31")


def test_existing_currency_api_accepts_exact_historical_date(monkeypatch):
    monkeypatch.setattr(history,"rates",lambda day:{"ok":True,"as_of":day,"rates":[{"ccy":"USD","per_unit":12000}]})
    response=TestClient(api.app).get("/api/currency/rates?as_of=2025-12-31")
    assert response.json()["as_of"]=="2025-12-31"
    assert TestClient(api.app).get("/api/currency/rates?as_of=garbage").status_code==422
