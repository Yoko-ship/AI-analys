from __future__ import annotations

import asyncio

import analysis_service as subject


def test_regular_analysis_returns_sector_nsbu_contract_before_legacy_llm(monkeypatch):
    monkeypatch.setattr(subject.analysis_cache, "get", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        subject,
        "get_data",
        lambda company: (object(), object(), None, "Resolved Company"),
    )
    monkeypatch.setattr(
        subject,
        "collect_company_data",
        lambda *args, **kwargs: {"ok": True, "security": {"ticker": "SAFE"}},
    )
    expected = {
        "analysis_contract": "sector_nsbu",
        "analysis_status": "available",
        "sector_template_code": "bank",
    }
    monkeypatch.setattr(subject, "_sector_nsbu_result", lambda **kwargs: {**expected, "arguments": kwargs})

    def legacy_must_not_run(*args, **kwargs):
        raise AssertionError("the universal LLM analysis path must not run")

    monkeypatch.setattr(subject, "run_analysis", legacy_must_not_run)

    result = asyncio.run(subject.run_company_analysis("SAFE", language="ru"))

    assert result["analysis_contract"] == "sector_nsbu"
    assert result["analysis_status"] == "available"
    assert result["arguments"]["resolved_name"] == "Resolved Company"
    assert result["arguments"]["company_data"]["security"]["ticker"] == "SAFE"
