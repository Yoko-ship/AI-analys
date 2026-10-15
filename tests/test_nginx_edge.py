"""The per-client request limit in front of the app, held to real traffic.

The limit is only useful if it never touches a real visitor and still stops one
address from flooding the single uvicorn worker. Both sides are checked against
recorded page loads of the live site (tests/fixtures/browser_request_bursts.json,
Playwright Chromium with a cold cache, every request to uzstock.uz), run through
a model of nginx's limit_req.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest

import scripts.nginx_edge as edge

_FIXTURE = Path(__file__).parent / "fixtures" / "browser_request_bursts.json"


def _sessions() -> dict[str, list[int]]:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return {s["label"]: s["offsets_ms"] for s in data["sessions"]}


def _admitted(offsets_ms: list[int], rate: float = edge.RATE_PER_SECOND,
              burst: int = edge.BURST) -> int:
    """nginx limit_req with ``nodelay`` (ngx_http_limit_req_lookup): the excess
    drains at ``rate`` per second, a new address starts at zero, each later
    request adds one, and a request that would push it past ``burst`` is refused
    without being counted."""
    excess, last, admitted = 0.0, None, 0
    for t in sorted(offsets_ms):
        current = 0.0 if last is None else max(0.0, excess - rate * (t - last) / 1000.0) + 1.0
        if current > burst:
            continue
        excess, last, admitted = current, t, admitted + 1
    return admitted


class TestTheLimitAgainstRealTraffic:
    @pytest.mark.parametrize("label", ["desktop", "mobile"])
    def test_one_visitor_browsing_fast_is_never_refused(self, label) -> None:
        offsets = _sessions()[label]
        assert _admitted(offsets) == len(offsets)

    def test_three_cold_mobile_loads_behind_one_carrier_nat(self) -> None:
        # Mobile carriers put many subscribers behind one address. Three of them
        # opening the heaviest pages in the same millisecond is the worst case.
        offsets = _sessions()["mobile"] * 3
        assert _admitted(offsets) == len(offsets)

    def test_the_recording_is_a_real_burst(self) -> None:
        # If the fixture ever shrinks to a trickle, the test above proves nothing.
        offsets = sorted(_sessions()["mobile"])
        peak = max(sum(1 for u in offsets if t <= u < t + 1000) for t in offsets)
        assert peak > edge.RATE_PER_SECOND

    def test_a_flood_from_one_address_is_held_to_the_rate(self) -> None:
        flood = [i * 10 for i in range(3000)]  # 100 requests a second for 30 s
        assert _admitted(flood) <= edge.BURST + edge.RATE_PER_SECOND * 30 + 1
        assert _admitted(flood) < len(flood) / 2

    def test_the_model_matches_nginx_on_a_known_case(self) -> None:
        # burst 2, rate 1/s: the first request plus a burst of two pass at once,
        # the fourth is refused, and a second later one more drains through.
        assert _admitted([0, 0, 0, 0], rate=1, burst=2) == 3
        assert _admitted([0, 0, 0, 0, 1000], rate=1, burst=2) == 4


class TestRenderedConfig:
    def test_the_limit_is_keyed_only_when_verified(self) -> None:
        assert "default $binary_remote_addr;" in edge.http_conf(limited=True)
        off = edge.http_conf(limited=False)
        assert "$binary_remote_addr" not in off and 'default "";' in off

    def test_both_states_share_one_zone_and_realip(self) -> None:
        for limited in (True, False):
            conf = edge.http_conf(limited)
            assert f"zone={edge.ZONE}:10m rate={edge.RATE_PER_SECOND}r/s" in conf
            assert "real_ip_recursive on;" in conf
            assert all(f"set_real_ip_from {cidr};" in conf for cidr in edge.TRUSTED_EDGE)

    def test_trusted_edge_holds_no_public_address(self) -> None:
        # A public range here would let anyone on it write their own client address.
        for cidr in edge.TRUSTED_EDGE:
            assert not ipaddress.ip_network(cidr).is_global, cidr

    def test_a_malformed_range_fails_before_nginx_sees_it(self) -> None:
        with pytest.raises(ValueError):
            edge.http_conf(True, trusted=("10.0.0.0/33",))

    def test_the_snippet_applies_the_limit_and_guards_the_probe(self) -> None:
        snippet = edge.server_snippet("abc123")
        assert f"limit_req zone={edge.ZONE} burst={edge.BURST} nodelay;" in snippet
        assert "limit_req_status 429;" in snippet
        assert '$http_x_uzstock_edge_probe != "abc123"' in snippet
        assert "gzip on;" in snippet

    def test_the_probe_token_cannot_break_out_of_the_config(self) -> None:
        with pytest.raises(ValueError):
            edge.server_snippet('x"; return 200 "')

    def test_render_writes_what_ci_runs_in_nginx(self, tmp_path) -> None:
        assert edge.render(str(tmp_path)) == 0
        assert (tmp_path / "uzstock-edge.conf").read_text() == edge.http_conf(limited=True)
        assert "location = /__uzstock/edge-probe" in (tmp_path / "uzstock-monitor.conf").read_text()


class TestProbeVerdict:
    def test_a_resolved_visitor_is_verified(self) -> None:
        assert edge.judge_probe("10.20.0.5 84.54.70.12\n") == ("verified", "10.20.0.5")

    def test_the_proxy_as_client_keeps_the_limit_off(self) -> None:
        # The case the limit must never be keyed on: one bucket for every visitor.
        assert edge.judge_probe("194.93.26.231 194.93.26.231") == ("unresolved", "194.93.26.231")

    @pytest.mark.parametrize("body", [None, "", "garbage", "a b c", "not-an-ip 1.2.3.4"])
    def test_no_usable_answer_is_inconclusive(self, body) -> None:
        assert edge.judge_probe(body)[0] == "inconclusive"

    def test_an_answer_that_skipped_the_proxy_proves_nothing(self) -> None:
        # The host resolving uzstock.uz to itself reaches nginx over loopback.
        assert edge.judge_probe("127.0.0.1 127.0.0.1")[0] == "inconclusive"


class TestProbeStateChanges:
    @pytest.fixture
    def host(self, tmp_path, monkeypatch):
        monkeypatch.setattr(edge, "HTTP_CONF", tmp_path / "edge.conf")
        monkeypatch.setattr(edge, "SERVER_SNIPPET", tmp_path / "snippet.conf")
        monkeypatch.setattr(edge, "STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(edge, "TOKEN_FILE", tmp_path / "token")
        monkeypatch.setattr(edge, "_nginx_test", lambda: (True, ""))
        monkeypatch.setattr(edge.time, "sleep", lambda s: None)
        reloads = []
        monkeypatch.setattr(edge, "_reload", lambda: reloads.append(1))
        return tmp_path, reloads

    def _answer(self, monkeypatch, body):
        monkeypatch.setattr(edge, "_probe_once", lambda token: body)

    def test_verified_switches_the_limit_on(self, host, monkeypatch) -> None:
        tmp, reloads = host
        self._answer(monkeypatch, "10.0.0.2 84.54.70.12")
        assert edge.probe() == 0
        assert "default $binary_remote_addr;" in (tmp / "edge.conf").read_text()
        assert json.loads((tmp / "state.json").read_text())["limited"] is True
        assert reloads == [1]

    def test_unresolved_switches_a_live_limit_off(self, host, monkeypatch) -> None:
        tmp, reloads = host
        (tmp / "state.json").write_text('{"limited": true}')
        self._answer(monkeypatch, "203.0.113.4 203.0.113.4")
        assert edge.probe() == 0
        assert "$binary_remote_addr" not in (tmp / "edge.conf").read_text()
        assert reloads == [1]

    @pytest.mark.parametrize("was", [True, False])
    def test_no_answer_keeps_the_previous_state(self, host, monkeypatch, was) -> None:
        tmp, reloads = host
        (tmp / "state.json").write_text(json.dumps({"limited": was}))
        self._answer(monkeypatch, None)
        assert edge.probe() == 0
        assert json.loads((tmp / "state.json").read_text())["limited"] is was
        assert reloads == []

    def test_a_rejected_config_is_rolled_back(self, host, monkeypatch) -> None:
        tmp, _ = host
        (tmp / "snippet.conf").write_text("gzip on;\n")
        monkeypatch.setattr(edge, "_nginx_test", lambda: (False, "emerg"))
        assert edge.write() == 1
        assert (tmp / "snippet.conf").read_text() == "gzip on;\n"
        assert not (tmp / "edge.conf").exists()

    def test_write_and_probe_share_one_token(self, host, monkeypatch) -> None:
        tmp, _ = host
        seen = []
        monkeypatch.setattr(edge, "_probe_once", lambda token: seen.append(token) or "10.0.0.2 84.54.70.12")
        edge.write()
        edge.probe()
        assert f'!= "{seen[0]}"' in (tmp / "snippet.conf").read_text()
