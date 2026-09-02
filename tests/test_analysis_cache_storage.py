import json
import sqlite3

from cache import AnalysisCache


def _result(name="Example"):
    return {
        "company_name": name,
        "raw_analysis": "structured text",
        "html_report": "<html>large rendered report</html>",
        "sections": {"summary": "ok"},
        "annual_period": "2025",
        "quarterly_period": "2026Q1",
        "cost": 0,
    }


def test_web_cache_does_not_store_rendered_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    path = tmp_path / "analysis-cache.db"
    cache = AnalysisCache(str(path))

    cache.set("Example", _result())

    with sqlite3.connect(path) as conn:
        html, result_json = conn.execute(
            "SELECT html_report, result_json FROM analysis_cache"
        ).fetchone()
    assert html == ""
    assert "html_report" not in json.loads(result_json)


def test_telegram_cache_can_opt_in_to_html_export(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    path = tmp_path / "analysis-cache.db"
    cache = AnalysisCache(str(path))

    cache.set("Example", _result(), store_html=True)

    with sqlite3.connect(path) as conn:
        html, result_json = conn.execute(
            "SELECT html_report, result_json FROM analysis_cache"
        ).fetchone()
    assert html == "<html>large rendered report</html>"
    assert "html_report" not in json.loads(result_json)
