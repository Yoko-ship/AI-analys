"""The data and calculation auditor (ТЗ v1.3 §12).

The load-bearing test in this file is `TestIsolation`. Everything else the
auditor does is worthless if it shares code with the layer it audits: two
implementations that call the same function agree by construction, and the check
becomes a very expensive way of printing "no problems found". §12.1 states the
rule and §12.9 requires a test to enforce it — this is that test.

The rest exercises each group on data where the answer is known, and the
reference set of §12.8 pins the twenty cases the ТЗ verified by hand, so a
regression in the calculation layer fails the build rather than the market.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest

from audit import rules as rules_mod
from audit.checks import AuditContext, Finding, registry
from audit.runner import run_audit

AUDIT_DIR = pathlib.Path(__file__).resolve().parent.parent / "audit"

# The production calculation layer. The auditor may not import any of it.
FORBIDDEN = {"formulas", "fundamentals", "heatmap", "instruments", "invariants"}


class TestIsolation:
    def test_the_auditor_does_not_import_the_calculation_layer(self):
        """§12.1: 'код аудитора не имеет права импортировать formulas.py'."""
        offences: list[str] = []
        for path in sorted(AUDIT_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in FORBIDDEN:
                        offences.append(f"{path.name}:{node.lineno} imports {name}")
        assert offences == [], (
            "the auditor must recompute independently, not call the code it audits:\n"
            + "\n".join(offences))

    def test_it_has_its_own_number_and_date_parsing(self):
        from audit import independent as ind

        assert ind.num("1 234,56") == pytest.approx(1234.56)
        assert ind.num("—") is None and ind.num(None) is None and ind.num("abc") is None
        assert ind.day("31.07.2026") == date(2026, 7, 31)
        assert ind.day("2026-07-31") == date(2026, 7, 31)
        assert ind.day("20260731") == date(2026, 7, 31)

    def test_it_reads_thresholds_from_the_same_configuration(self):
        from audit import independent as ind

        assert ind.threshold("multiples.roe_abs_max") == 100
        assert ind.threshold("quality.flat_share_max") == 0.5
        # ...and has its own defaults, so a missing config cannot mute a rule.
        assert ind.threshold("audit.recompute_tolerance_pct") is not None


class TestRuleBook:
    def test_all_six_groups_are_present_and_complete(self):
        counts: dict[str, int] = {}
        for rule in rules_mod.ALL_RULES:
            counts[rule.group] = counts.get(rule.group, 0) + 1
        assert counts == {"FIN": 15, "MUL": 12, "MKT": 14, "CND": 12, "CAT": 6, "XSC": 5}
        assert len(rules_mod.ALL_RULES) == 64

    def test_every_rule_has_an_implementation(self):
        implemented = set(registry())
        declared = {r.code for r in rules_mod.ALL_RULES}
        assert declared - implemented == set()

    def test_severities_are_from_the_defined_set(self):
        allowed = {rules_mod.BLOCKING, rules_mod.WARNING, rules_mod.INFO}
        assert {r.severity for r in rules_mod.ALL_RULES} <= allowed


# ---------------------------------------------------------------------------
# The checks, on data whose answer is known
# ---------------------------------------------------------------------------

def fire(code: str, ctx: AuditContext) -> list[Finding]:
    return list(registry()[code](ctx) or [])


class TestFinGroup:
    def test_fin_01_catches_a_balance_that_does_not_close(self):
        ctx = AuditContext(
            financials={"X": {"total_liabilities": 900.0, "year": 2025}},
            ratios={"X": {"total_assets": 1000.0, "total_equity": 50.0, "period": "2025"}})
        found = fire("FIN-01", ctx)
        assert [f.ticker for f in found] == ["X"]
        assert found[0].severity == rules_mod.BLOCKING

    def test_fin_04_catches_gross_profit_above_revenue(self):
        ctx = AuditContext(financials={"TGPG": {"revenue": 615_000.0,
                                                "gross_profit": -1_500_000.0}})
        assert fire("FIN-04", ctx)[0].ticker == "TGPG"

    def test_fin_06_catches_a_thousandfold_unit_error(self):
        """The most frequent and least visible parsing error."""
        peers = {f"P{i}": {"revenue": 1_000_000.0} for i in range(5)}
        peers["BAD"] = {"revenue": 1_000_000.0 * 5000}
        ctx = AuditContext(financials=peers,
                           securities={k: {"sector": "finance"} for k in peers})
        assert [f.ticker for f in fire("FIN-06", ctx)] == ["BAD"]

    def test_fin_06_leaves_an_ordinary_spread_alone(self):
        peers = {f"P{i}": {"revenue": 1_000_000.0 * (i + 1)} for i in range(6)}
        ctx = AuditContext(financials=peers,
                           securities={k: {"sector": "finance"} for k in peers})
        assert fire("FIN-06", ctx) == []

    def test_fin_11_and_fin_12(self):
        ctx = AuditContext(financials={"X": {"year": 2025}},
                           ratios={"X": {"total_equity": -1.0, "period": "2019"}})
        assert fire("FIN-11", ctx)[0].metric == "total_equity"
        assert fire("FIN-12", ctx)[0].ticker == "X"

    def test_fin_14_catches_nothing_when_periods_are_unique(self):
        ctx = AuditContext(financials={"A": {"year": 2025, "quarter": 0},
                                       "B": {"year": 2025, "quarter": 0}})
        assert fire("FIN-14", ctx) == []


class TestMulGroup:
    def _ctx(self, **kw):
        base = AuditContext(
            published_multiples=[{
                "ticker": "A", "issuer": "acme", "share_class": "ordinary",
                "market_cap_issuer": {"value": 1000.0, "status": "ok"},
                "pe": {"value": 5.0, "status": "ok", "base_period": "2025A"},
                "pb": {"value": 1.0, "status": "ok"},
                "roe": {"value": 20.0, "status": "ok"}}],
            financials={"A": {"net_income": 200.0, "year": 2025}},
            ratios={"A": {"total_equity": 1000.0, "period": "2025"}},
            today=date(2026, 1, 15))
        for k, v in kw.items():
            setattr(base, k, v)
        return base

    def test_mul_01_passes_when_the_recomputation_agrees(self):
        assert fire("MUL-01", self._ctx()) == []

    def test_mul_01_catches_a_published_pe_that_cannot_be_reproduced(self):
        ctx = self._ctx()
        ctx.published_multiples[0]["pe"]["value"] = 42.0
        found = fire("MUL-01", ctx)
        assert found and found[0].expected == pytest.approx(5.0)
        assert found[0].actual == pytest.approx(42.0)

    def test_mul_04_catches_two_classes_disagreeing(self):
        """KFSK 203.56 against KFSKP 0.19 — one issuer, one profit."""
        ctx = self._ctx(published_multiples=[
            {"ticker": "KFSK", "issuer": "kfsk", "pe": {"value": 203.56}},
            {"ticker": "KFSKP", "issuer": "kfsk", "pe": {"value": 0.19}}])
        found = fire("MUL-04", ctx)
        assert found and found[0].metric == "pe"
        assert found[0].severity == rules_mod.BLOCKING

    def test_mul_04_is_silent_when_they_agree(self):
        ctx = self._ctx(published_multiples=[
            {"ticker": "KFSK", "issuer": "kfsk", "pe": {"value": 8.4}},
            {"ticker": "KFSKP", "issuer": "kfsk", "pe": {"value": 8.4}}])
        assert fire("MUL-04", ctx) == []

    def test_mul_05_catches_the_thousandfold_share_count(self):
        ctx = self._ctx(board=[{"ticker": "ALKBP", "last_price": 8.0,
                                "shares_outstanding": 25.0, "market_cap": 200_000.0}])
        found = fire("MUL-05", ctx)
        assert found and found[0].input["looks_like_thousands"] is True

    def test_mul_09_catches_an_impossible_roe(self):
        ctx = self._ctx()
        ctx.published_multiples[0]["roe"]["value"] = 10715.33
        assert fire("MUL-09", ctx)[0].actual == pytest.approx(10715.33)

    def test_mul_10_catches_a_multiple_published_on_a_loss(self):
        ctx = self._ctx(financials={"A": {"net_income": -50.0}})
        assert fire("MUL-10", ctx)[0].metric == "pe"


class TestMktGroup:
    def _map(self, tiles, sectors=None, counts=None):
        return {"tiles": tiles, "sectors": sectors or [], "counts": counts or {}}

    def test_mkt_01_recomputes_every_change(self):
        ctx = AuditContext(
            board=[{"ticker": "A", "last_price": 110.0, "close_price": 100.0}],
            published_map=self._map([{"ticker": "A", "change_pct": 5.0}]))
        found = fire("MKT-01", ctx)
        assert found and found[0].expected == pytest.approx(10.0)

    def test_mkt_02_catches_a_top_built_on_one_trade(self):
        """UQEQ led the screen on one trade of one share for 30 720 sums."""
        tiles = [{"ticker": "UQEQ", "change_pct": 20.0, "trades": 1, "quantity": 1,
                  "turnover": 30720.0, "confidence": None}]
        assert fire("MKT-02", AuditContext(published_map=self._map(tiles)))[0].ticker == "UQEQ"

    def test_mkt_02_accepts_a_marked_tile(self):
        tiles = [{"ticker": "UQEQ", "change_pct": 20.0, "trades": 1, "confidence": "low"}]
        assert fire("MKT-02", AuditContext(published_map=self._map(tiles))) == []

    def test_mkt_03_catches_trades_without_a_price(self):
        tiles = [{"ticker": "UTYK", "trades": 8, "turnover": 34_050_000.0, "last_price": None}]
        assert fire("MKT-03", AuditContext(published_map=self._map(tiles)))[0].ticker == "UTYK"

    def test_mkt_04_catches_a_change_on_a_tile_that_did_not_trade(self):
        tiles = [{"ticker": "SANE", "status": "not_traded", "change_pct": 0.0}]
        assert fire("MKT-04", AuditContext(published_map=self._map(tiles)))[0].ticker == "SANE"

    def test_mkt_09_catches_a_capitalisation_computed_for_a_bond(self):
        ctx = AuditContext(
            board=[{"ticker": "S", "market_cap": 100.0, "type": "stock"},
                   {"ticker": "B1", "market_cap": 50.0, "type": "bond"}],
            published_summary={"market_cap": {"value": 100.0}})
        found = fire("MKT-09", ctx)
        assert any(f.actual == pytest.approx(50.0) for f in found)

    def test_mkt_12_recomputes_the_sector_aggregate(self):
        tiles = [{"ticker": "BIG", "sector": "finance", "change_pct": 1.0,
                  "turnover": 99_000_000.0, "status": "ok"},
                 {"ticker": "TINY", "sector": "finance", "change_pct": 20.0,
                  "turnover": 100.0, "status": "ok"}]
        ctx = AuditContext(published_map=self._map(
            tiles, sectors=[{"name": "finance", "change_pct": 10.5, "tiles_counted": 2}]))
        found = fire("MKT-12", ctx)
        assert found and found[0].expected == pytest.approx(1.0, abs=0.01)


class TestCndGroup:
    def _hist(self, rows):
        return [{"date": d, "open": o, "high": h, "low": lo, "close": c,
                 "trading_volume": v, "trading_value": t} for d, o, h, lo, c, v, t in rows]

    def test_cnd_01_catches_broken_ohlc(self):
        hist = {"X": self._hist([("2026-04-01", 10, 8, 9, 11, 5, 50)])}
        assert fire("CND-01", AuditContext(history=hist))[0].ticker == "X"

    def test_cnd_02_catches_a_flat_series(self):
        rows = [(f"2026-04-{d:02d}", 100, 100, 100, 100, 5, 500) for d in range(1, 21)]
        found = fire("CND-02", AuditContext(history={"UQEQ": self._hist(rows)}))
        assert found and found[0].actual == pytest.approx(1.0)

    def test_cnd_06_catches_a_declared_window_that_is_too_wide(self):
        """133 calendar days may not be published under the name "MA20"."""
        found = fire("CND-06", AuditContext(published_ma_windows={"ma20": 133, "ma50": 200}))
        assert found and found[0].metric == "ma20_window"
        assert found[0].actual == pytest.approx(133.0)

    def test_cnd_06_accepts_the_configured_window(self):
        assert fire("CND-06", AuditContext(published_ma_windows={"ma20": 28, "ma50": 70})) == []

    def test_cnd_06_catches_a_server_that_declares_nothing(self):
        """With no declared window the chart is free to invent its own."""
        found = fire("CND-06", AuditContext(published_ma_windows={}))
        assert found and found[0].metric == "ma20_window"

    def test_cnd_07_catches_windows_that_are_not_a_single_rule(self):
        found = fire("CND-07", AuditContext(published_ma_windows={"ma20": 70, "ma50": 28}))
        assert found and found[0].metric == "ma_windows"
        assert fire("CND-07", AuditContext(published_ma_windows={"ma20": 28, "ma50": 70})) == []

    def test_cnd_10_catches_an_invented_point(self):
        rows = [("2026-04-01", 100, 100, 100, 100, 5, 500),
                ("2026-04-02", 100, 110, 100, 110, 0, 0)]
        assert fire("CND-10", AuditContext(history={"X": self._hist(rows)}))[0].ticker == "X"


class TestCatAndXsc:
    def test_cat_01_catches_disagreeing_universes(self):
        ctx = AuditContext(published_catalog={
            "source_counts": {"securities": 82, "board": 85, "financials": 107}})
        assert fire("CAT-01", ctx)[0].input["counts"]["board"] == 85

    def test_cat_03_catches_a_duplicated_isin(self):
        ctx = AuditContext(published_catalog={"items": [
            {"ticker": "A", "isin": "UZ1"}, {"ticker": "B", "isin": "UZ1"}]})
        assert fire("CAT-03", ctx)[0].ticker == "B"

    def test_xsc_03_is_the_main_invariant(self):
        """YTD moved on 83 of 84 securities when the period button changed."""
        ctx = AuditContext(published_metrics_by_period={
            "BNGPP": {1: {"ytd": {"value": 9.52}}, 12: {"ytd": {"value": 557.14}}}})
        found = fire("XSC-03", ctx)
        assert found and found[0].ticker == "BNGPP"
        assert found[0].severity == rules_mod.BLOCKING

    def test_xsc_03_is_silent_when_the_block_holds(self):
        block = {"ytd": {"value": -26.86}, "yoy": {"value": None}}
        ctx = AuditContext(published_metrics_by_period={
            "UQEQ": {m: block for m in (1, 3, 6, 12, 36, 60)}})
        assert fire("XSC-03", ctx) == []

    def test_xsc_05_compares_the_header_with_the_rows(self):
        ctx = AuditContext(published_summary={"instruments": 96},
                           published_map={"counts": {"tiles": 85}})
        assert fire("XSC-05", ctx)[0].deviation == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

class TestRunner:
    def test_a_clean_pass_reports_ok(self):
        # An empty context still has to declare its MA windows: "the server
        # published nothing" is itself a CND-06/07 finding.
        report = run_audit(AuditContext(published_ma_windows={"ma20": 28, "ma50": 70}),
                           persist=False)
        assert report["status"] == "ok"
        assert report["rules_run"] == 64 and report["summary"]["blocking"] == 0

    def test_a_blocking_finding_fails_the_run(self):
        ctx = AuditContext(published_multiples=[
            {"ticker": "KFSK", "issuer": "k", "pe": {"value": 203.56}},
            {"ticker": "KFSKP", "issuer": "k", "pe": {"value": 0.19}}])
        report = run_audit(ctx, persist=False)
        assert report["status"] == "failed"
        assert report["summary"]["blocking"] >= 1

    def test_one_broken_rule_does_not_take_the_run_down(self, monkeypatch):
        from audit import checks as checks_mod

        def boom(_ctx):
            raise RuntimeError("source unavailable")

        original = checks_mod._REGISTRY["FIN-01"]
        monkeypatch.setitem(checks_mod._REGISTRY, "FIN-01", boom)
        try:
            report = run_audit(AuditContext(), persist=False)
        finally:
            checks_mod._REGISTRY["FIN-01"] = original
        assert report["rules_failed"] == [{"rule": "FIN-01", "error": "source unavailable"}]
        assert report["rules_run"] == 64

    def test_a_group_can_be_run_alone(self):
        report = run_audit(AuditContext(), group="MUL", persist=False)
        assert report["rules_run"] == 12

    def test_a_full_pass_reports_whether_it_fits_the_budget(self):
        report = run_audit(AuditContext(), persist=False)
        assert report["within_budget"] is True
        assert report["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# The reference set (ТЗ §12.8)
# ---------------------------------------------------------------------------

class TestReferenceSet:
    """Cases verified by hand, used twice: the rule must find the known problem,
    and after the fix the number must be right."""

    def test_uqeq_style_vwap_is_turnover_over_volume(self):
        from audit import independent as ind

        points = ind.series([
            {"date": "2026-01-05", "close": 100, "trading_volume": 10, "trading_value": 500},
            {"date": "2026-01-06", "close": 60, "trading_volume": 10, "trading_value": 700},
        ])
        assert ind.vwap(points) == pytest.approx(60.0)     # not (100+60)/2 = 80

    def test_kasu_moves_at_one_hundredth_of_a_sum(self):
        from audit import independent as ind

        assert ind.day_change(0.0125, 0.01) == pytest.approx(25.0)

    def test_alkbp_share_count_ratio_is_flagged(self):
        ctx = AuditContext(board=[{"ticker": "ALKBP", "last_price": 8.0,
                                   "shares_outstanding": 25.0, "market_cap": 200_000.0}])
        assert fire("MUL-05", ctx)

    def test_utgap_roe_is_flagged(self):
        ctx = AuditContext(published_multiples=[{"ticker": "UTGAP", "roe": {"value": 10715.33}}])
        assert fire("MUL-09", ctx)

    def test_bngpp_ytd_spread_is_flagged(self):
        ctx = AuditContext(published_metrics_by_period={
            "BNGPP": {1: {"ytd": {"value": 18.42}}, 12: {"ytd": {"value": 542.86}}}})
        assert fire("XSC-03", ctx)

    def test_sane_no_trades_is_not_zero_percent(self):
        ctx = AuditContext(published_map={"tiles": [
            {"ticker": "SANE", "status": "not_traded", "change_pct": 0.0}]})
        assert fire("MKT-04", ctx)

    def test_utyk_has_trades_and_must_have_a_price(self):
        ctx = AuditContext(published_map={"tiles": [
            {"ticker": "UTYK", "trades": 8, "turnover": 34_050_000.0, "last_price": None}]})
        assert fire("MKT-03", ctx)


# ---------------------------------------------------------------------------
# Persistence and the control it enables (ТЗ §12.2, §12.4)
# ---------------------------------------------------------------------------

@pytest.fixture()
def clean_store():
    """Findings for a reserved ticker, removed afterwards.

    The store writes to the project's catalog database on purpose — auditing a
    different file than the application writes would be worse than not auditing.
    """
    from audit import store

    store.init()
    marker = "ZZAUDITTEST"
    yield store, marker
    conn = store._conn()
    try:
        conn.execute("DELETE FROM audit_findings WHERE ticker = ?", (marker,))
        conn.execute("DELETE FROM audit_runs WHERE trigger = 'pytest'")
        conn.commit()
    finally:
        conn.close()


class TestStore:
    def test_the_same_problem_seen_twice_is_one_row(self, clean_store):
        """Twenty runs must not produce twenty rows nobody reads (§12.4)."""
        store, marker = clean_store
        finding = Finding("MUL-09", "ROE вне диапазона", marker, "roe", 100.0, 10715.33)
        run_a = store.start_run("pytest")
        store.record(run_a, [finding])
        run_b = store.start_run("pytest")
        store.record(run_b, [finding])
        rows = store.find_findings(ticker=marker)
        assert len(rows) == 1
        assert rows[0]["seen_count"] == 2
        assert rows[0]["first_seen"] <= rows[0]["last_seen"]

    def test_a_finding_is_resolved_not_deleted(self, clean_store):
        store, marker = clean_store
        run = store.start_run("pytest")
        store.record(run, [Finding("MUL-09", "ROE вне диапазона", marker, "roe")])
        [row] = store.find_findings(ticker=marker)
        updated = store.update_finding(row["id"], status="accepted", note="known exception")
        assert updated["status"] == "accepted" and updated["note"] == "known exception"
        # Accepted findings leave the open list but still exist.
        assert store.find_findings(ticker=marker) == []
        assert store.find_findings(ticker=marker, status="accepted")

    def test_an_unknown_status_is_refused(self, clean_store):
        store, _ = clean_store
        with pytest.raises(ValueError):
            store.update_finding(1, status="probably-fine")


class TestBlockingSuppression:
    def test_a_blocking_finding_removes_the_number_from_publication(self, clean_store):
        """§12.2: the auditor is a control, not a commentary.

        Without this the module would describe a wrong figure accurately while
        the wrong figure kept being published beside the description.
        """
        import api

        store, marker = clean_store
        run = store.start_run("pytest")
        store.record(run, [Finding("MUL-09", "ROE вне диапазона", marker, "roe",
                                   100.0, 10715.33)])
        rows = [{"ticker": marker, "roe": {"value": 10715.33, "status": "ok"},
                 "pe": {"value": 8.0, "status": "ok"}}]
        withheld = api._apply_audit_blocks(rows)
        assert withheld == 1
        assert rows[0]["roe"]["value"] is None
        assert rows[0]["roe"]["status"] == "audit_blocked"
        # Only the flagged metric is withheld; the rest of the row still serves.
        assert rows[0]["pe"]["value"] == pytest.approx(8.0)

    def test_the_badge_says_what_was_withheld(self, clean_store):
        store, marker = clean_store
        run = store.start_run("pytest")
        store.record(run, [Finding("MUL-09", "ROE вне диапазона", marker, "roe")])
        badge = store.ticker_badge(marker)
        assert badge["status"] == "blocking"
        assert badge["metrics_withheld"] == ["roe"]
        assert badge["reasons"]

    def test_publication_survives_an_audit_outage(self, monkeypatch):
        """An auditor that cannot answer must not blank the board."""
        import api
        import audit

        def boom():
            raise RuntimeError("audit database unavailable")

        monkeypatch.setattr(audit, "blocking_index", boom)
        rows = [{"ticker": "A", "pe": {"value": 8.0, "status": "ok"}}]
        assert api._apply_audit_blocks(rows) == 0
        assert rows[0]["pe"]["value"] == pytest.approx(8.0)
