import sqlite3

import pytest


def test_repeated_run_keeps_gaps_source_versions_and_alerts_idempotent(tmp_path):
    from collectors.financials import coverage

    db = sqlite3.connect(tmp_path / "coverage.sqlite")
    native = {
        "JASM": {
            "filing:NSBU:separate": {
                "eps_basic": {
                    "status": "earlier",
                    "period": "2021-09-30",
                    "value": 454.76,
                },
                "price_to_book": {"status": "gap", "missing_inputs": ["quote"]},
            }
        }
    }
    versions = {"JASM": [["2021-09-30", "source-version-1"]]}

    def check():
        return coverage.save(db, versions, native, native)

    first = check()
    writes = db.total_changes
    assert first["alerts"] and first["changes"]
    assert check() == {"changes": 0, "alerts": []}
    assert db.total_changes == writes
    versions["JASM"][0][1] = "corrected-source"
    changed = check()
    assert changed == {"changes": 1, "alerts": []}
    assert coverage.save(db, versions, native, {})["alerts"]
    assert coverage.save(db, versions, native, {}) == {"changes": 0, "alerts": []}
    assert check()["alerts"]  # issue resolved


def test_metric_period_zero_conflict_and_sector_applicability():
    from collectors.financials import coverage

    row = {
        "ticker": "JASM",
        "period": "2026Q3",
        "status": "available",
        "metrics": {
            "eps_basic": {
                "value": None,
                "missing_inputs": ["weighted_average_shares"],
                "last_verified": {"value": 0, "period_end": "2021-09-30"},
            },
            "price_to_book": {"value": None, "reason_code": "SOURCE_CONFLICT"},
            "roce": {"value": None, "quality": "not_applicable"},
        },
    }
    metrics = coverage.filing_cells(row)
    assert metrics["eps_basic"]["status"] == "earlier"
    assert metrics["eps_basic"]["value"] == 0
    assert metrics["eps_basic"]["period"] == "2021-09-30"
    assert metrics["eps_basic"]["missing_inputs"] == ["weighted_average_shares"]
    assert metrics["price_to_book"]["reason"] == "SOURCE_CONFLICT"
    assert metrics["roce"]["status"] == "inapplicable"
    assert metrics["book_value_per_share"]["status"] == "gap"


def test_partial_pagination_fails_instead_of_reporting_removed_issuers():
    from collectors.financials import coverage

    def page(path, **params):
        return {"total": 2, "rows": [{"ticker": "A"}] if not params["offset"] else []}

    with pytest.raises(ValueError, match="incomplete"):
        list(coverage.filing_rows(page, "separate"))


def test_statement_earlier_value_keeps_the_document_and_never_borrows_another_basis():
    from collectors.financials.coverage_columns import statement_cells

    payload = {
        "display_template": "general",
        "standard": "NSBU",
        "columns": [
            {"key": "2024", "end": "2024-12-31", "basis": "annual"},
            {"key": "2025", "end": "2025-12-31", "basis": "annual"},
            {"key": "asof", "end": "2026-09-30", "basis": "as_of"},
        ],
        "rows": [],
        "published_ratios": [],
        "coverage": {},
        "issues": [],
        "ratios": [
            {
                "id": "ratio:roa",
                "metric_id": "roa",
                "unit": "percent",
                "cells": {
                    "2024": {
                        "value": "0",
                        "source_url": "openinfo:2024",
                        "source_version": "v1",
                    },
                    "2025": {"quality": "missing", "reason": "MISSING_OPENING_BALANCE"},
                    "asof": {"value": "23"},
                },
            }
        ],
    }
    result = statement_cells(payload)
    ratio = result["annual/ratio:roa"]
    assert (
        ratio["status"],
        ratio["period"],
        ratio["source_version"],
        ratio["value"],
    ) == ("earlier", "2024-12-31", "v1", "0")
    assert result["annual/ratio:roce"]["status"] == "gap"


def test_unchanged_statements_still_check_public_and_changed_evidence_recomputes_first():
    from collectors.financials.coverage import verify_statement

    calls = []

    def native():
        calls.append("local")
        return {"income": {"value": 1}}

    def public():
        calls.append("public")
        return {"income": {"value": 1}}

    first = verify_statement(native, public, None)
    assert calls == ["local", "public"]
    calls.clear()
    assert verify_statement(native, public, first) == first
    assert calls == ["public"]
    calls.clear()
    # A previous public value that changed without a registry revision (e.g. a correction).
    verify_statement(native, public, (first[0], {}))
    assert calls == ["public", "local", "public"]


def test_other_standard_for_same_year_is_not_labeled_as_an_earlier_period():
    from collectors.financials.coverage import cell

    r = cell(
        {
            "other_filing": {
                "period": "2025",
                "value": 0,
                "scope": "consolidated",
                "standard": "ifrs",
            }
        },
        "2025",
    )
    assert r["status"] == r["basis"] == "other_filing"
    assert r["scope"] == "consolidated"


def test_daily_collector_two_complete_runs_with_identical_evidence(
    tmp_path, monkeypatch
):
    import json

    from requests import Response

    import db
    import securities_catalog
    from collectors.financials import coverage
    from financial_columns import service as columns
    from server.terminal import service

    monkeypatch.setattr(db, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        service,
        "universe",
        lambda **kw: [{"ticker": "TGBK", "org_id": "815", "kind": "bank"}],
    )
    monkeypatch.setattr(
        coverage, "evidence", lambda companies: {"TGBK": [["form", "2026-09-30", "v1"]]}
    )
    monkeypatch.setattr(
        securities_catalog, "get_securities_map", lambda: {"TGBK": {"type": "stock"}}
    )

    def annual(form, scope):
        return {
            "ok": True,
            "scope": scope,
            "standard": form,
            "rows": [{"ticker": "TGBK", "period": "2025", "kind": "bank"}],
        }

    async def local_annual(**kw):
        return annual(**kw)

    def filing(**kw):
        return {
            "total": 1,
            "rows": [
                {
                    "ticker": "TGBK",
                    "period": "2026Q3",
                    "status": "available",
                    "metrics": {"book_value_per_share": {"value": 6062.674225413403}},
                }
            ],
        }

    def statement(ticker, **kw):
        return {
            "ok": True,
            "display_template": "bank",
            "ticker": ticker,
            "standard": kw["form"],
            "scope": kw["scope"],
            "freq": kw["freq"],
            "columns": [],
            "rows": [],
            "ratios": [],
        }

    count = {"local": 0, "public": 0}

    def local_statement(ticker, **kw):
        count["local"] += 1
        return statement(ticker, **kw)

    def fetch(session, url, *, params, timeout):
        count["public"] += 1
        if url.endswith("screener"):
            value = annual(**params)
        elif url.endswith("filing-metrics"):
            value = filing(**params)
        else:
            value = statement("TGBK", **params)
        response = Response()
        response.status_code = 200
        response._content = json.dumps(value).encode()
        return response

    monkeypatch.setattr(service, "screener", local_annual)
    monkeypatch.setattr(service, "filing_metrics", filing)
    monkeypatch.setattr(columns, "load", local_statement)
    monkeypatch.setattr(coverage.requests.Session, "get", fetch)
    first = coverage.run()
    assert first["changes"] == 1 and first["alerts"] > 0
    assert count == {"local": 9, "public": 14}
    path = tmp_path / "metric-coverage.sqlite3"
    first_bytes = path.read_bytes()
    assert coverage.run() == {"issuers": 1, "changes": 0, "alerts": 0}
    assert count == {"local": 9, "public": 28}
    assert path.read_bytes() == first_bytes


def test_public_fetch_retries_timeouts_and_rate_limits_with_requested_delays():
    from types import SimpleNamespace

    import requests

    from collectors.financials.coverage import public_get

    errors = [requests.ReadTimeout(), requests.Response(), requests.Response()]
    errors[1].status_code = 429
    errors[1].headers["Retry-After"] = "7"
    errors[2].status_code = 200
    errors[2]._content = b'{"total": 0}'

    def get(*args, **kwargs):
        item = errors.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    delays = []
    assert public_get(
        SimpleNamespace(get=get), "filing-metrics", {}, sleep=delays.append
    ) == {"total": 0}
    assert delays == [1, 7]


def test_missing_statement_inputs_and_conflict_link_are_retained():
    from collectors.financials.coverage_columns import statement_cells

    data = {
        "display_template": "general",
        "standard": "NSBU",
        "columns": [{"key": "2025", "end": "2025-12-31", "basis": "annual"}],
        "rows": [],
        "ratios": [
            {
                "id": "ratio:roa",
                "metric_id": "roa",
                "cells": {
                    "2025": {
                        "quality": "blocked",
                        "reason": "CONFLICTING_SOURCE_VALUES",
                        "components": [
                            {
                                "metric_id": "total_assets",
                                "quality": "blocked",
                                "source_version": "sha",
                                "source_url": "openinfo:2025",
                                "period_end": "2025-12-31",
                            }
                        ],
                    }
                },
            }
        ],
    }
    metric = statement_cells(data)["annual/ratio:roa"]
    assert "total_assets" in metric["missing_inputs"]
    assert metric["sources"][0][:2] == ["sha", "openinfo:2025"]
