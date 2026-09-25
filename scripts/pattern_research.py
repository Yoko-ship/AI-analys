"""How the detected patterns have actually behaved on UZSE (ТЗ §5.3).

Runs pattern_engine over the full openinfo archive of every listed share and
pools the outcomes per pattern type, split by the site's own liquidity tier
(formulas.data_quality). Read-only: it fetches public history and prints.

    .venv/bin/python scripts/pattern_research.py [--out report.json] [--tickers HMKB,URTS]
                                                 [--stats-out config/pattern_stats.json]

``--stats-out`` writes the liquid-tier table the company chart quotes beside
each pattern («цель в 24 % случаев, случайно — 30 %»). Regenerate it when the
engine or its parameters change; the file carries both.

The line to read is hit rate against chance: a pattern whose target came first
no more often than it does from an ordinary session of the same stock is not a
signal, whatever its name.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import formulas  # noqa: E402
import pattern_engine  # noqa: E402
from listings_collector import _uzse_screener_isins  # noqa: E402
from openinfo_collector import _make_session, fetch_price_history  # noqa: E402


def _pool(rows: list[dict]) -> dict:
    decided = [r for r in rows if r["outcome"] in ("target", "stop")]
    hits = sum(r["outcome"] == "target" for r in decided)
    chances = [r["chance_pct"] for r in decided if r.get("chance_pct") is not None]
    rets = [r["directional_return_pct"] for r in rows]
    return {
        "signals": len(rows), "decided": len(decided),
        "hit_rate_pct": hits / len(decided) * 100 if decided else None,
        "chance_pct": sum(chances) / len(chances) if chances else None,
        "avg_return_pct": sum(rets) / len(rets) if rets else None,
        "securities": len({r["ticker"] for r in rows}),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--stats-out")
    args = ap.parse_args()

    session = _make_session()
    universe = _uzse_screener_isins(session)
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        universe = {t: i for t, i in universe.items() if t in wanted}

    histories: dict[str, tuple[str, list]] = {}
    for ticker, isin in sorted(universe.items()):
        try:
            points = fetch_price_history(isin, session, 240).get("points") or []
        except Exception as exc:  # noqa: BLE001 — one unreadable code is not the run
            print(f"{ticker}: fetch failed ({exc})", file=sys.stderr)
            continue
        histories[ticker] = (formulas.data_quality(formulas.normalize_points(points))["data_tier"], points)
        time.sleep(0.3)

    report = {"model_version": pattern_engine.MODEL_VERSION, "parameters": pattern_engine.DEFAULTS,
              "by_sensitivity": {}, "cycles": []}
    for level in pattern_engine.SENSITIVITY:
        outcomes = []
        for ticker, (tier, points) in histories.items():
            result = pattern_engine.analyse(points, sensitivity=level)
            if result["status"] != "AVAILABLE":
                continue
            for s in result["signals"]:
                if s.get("outcome") in ("target", "stop", "horizon"):
                    outcomes.append({"ticker": ticker, "tier": tier, "type": s["type"], "family": s["family"],
                                     "direction": s["direction"], "outcome": s["outcome"],
                                     "chance_pct": s.get("chance_pct"),
                                     "directional_return_pct": s["directional_return_pct"]})
            if level == "medium" and tier == "full":
                report["cycles"].append({"ticker": ticker, **{k: result["cycle"].get(k) for k in
                                         ("status", "period_sessions", "p_value", "significant")}})
        by_tier = {}
        for tier in ("full", "sparse", "illiquid"):
            rows = [o for o in outcomes if o["tier"] == tier]
            by_tier[tier] = {"all": _pool(rows), **{t: _pool([o for o in rows if o["type"] == t])
                                                    for t in sorted({o["type"] for o in rows})}}
        report["by_sensitivity"][level] = by_tier

    def fmt(v):
        return "—" if v is None else f"{v:6.1f}"

    for level, by_tier in report["by_sensitivity"].items():
        table = by_tier["full"]
        print(f"\n== full tier, sensitivity {level} ==")
        print(f"{'pattern':26} {'sec':>4} {'signals':>8} {'decided':>8} {'hit%':>7} {'chance%':>8} {'edge':>7} {'avg ret%':>9}")
        for kind, st in sorted(table.items(), key=lambda kv: (kv[0] != "all", kv[0])):
            edge = (st["hit_rate_pct"] - st["chance_pct"]) if st["hit_rate_pct"] is not None and st["chance_pct"] is not None else None
            print(f"{kind:26} {st['securities']:>4} {st['signals']:>8} {st['decided']:>8} {fmt(st['hit_rate_pct']):>7} "
                  f"{fmt(st['chance_pct']):>8} {fmt(edge):>7} {fmt(st['avg_return_pct']):>9}")
    cyc = [c for c in report["cycles"] if c["status"] == "AVAILABLE"]
    print(f"\n== cycles: {sum(c['significant'] for c in cyc)} of {len(cyc)} liquid shares significant at 5 % "
          f"(≈{0.05 * len(cyc):.1f} expected by chance alone) ==")
    for c in cyc:
        if c["significant"]:
            print(f"  {c['ticker']:7} period {c['period_sessions']:6.1f} sessions  p={c['p_value']}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    if args.stats_out:
        from datetime import date
        stats = {
            "model_version": pattern_engine.MODEL_VERSION,
            "generated": date.today().isoformat(),
            "universe": "UZSE shares in the full liquidity tier (formulas.data_quality)",
            "parameters": pattern_engine.DEFAULTS,
            "sensitivity": pattern_engine.SENSITIVITY,
            "method": ("Signal at the breakout close, filled at the next session's close with fee and "
                       "slippage; hit = target before stop within the horizon; chance = the same "
                       "target/stop distances from ordinary sessions of the same stock."),
            "by_sensitivity": {
                level: {"securities": by_tier["full"]["all"]["securities"],
                        "types": {k: {f: (round(v, 1) if isinstance(v, float) else v) for f, v in st.items()}
                                  for k, st in by_tier["full"].items()}}
                for level, by_tier in report["by_sensitivity"].items()},
        }
        Path(args.stats_out).write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
