from __future__ import annotations

import codex_usage


def test_parse_main_codex_rate_limit() -> None:
    snapshot = codex_usage._parse_rate_limit({
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {
                    "usedPercent": 26,
                    "windowDurationMins": 10080,
                    "resetsAt": 1788455987,
                },
                "planType": "prolite",
            },
            "codex_bengalfox": {"primary": {"usedPercent": 0}},
        }
    })

    assert snapshot == {
        "limit_id": "codex",
        "used_percent": 26.0,
        "window_minutes": 10080,
        "resets_at": 1788455987,
        "plan_type": "prolite",
    }


def test_parse_legacy_default_rate_limit() -> None:
    snapshot = codex_usage._parse_rate_limit({
        "rateLimits": {"primary": {"usedPercent": 7.5}, "planType": "pro"}
    })

    assert snapshot and snapshot["limit_id"] == "default"
    assert snapshot["used_percent"] == 7.5
