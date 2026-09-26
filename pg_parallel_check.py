"""Parallel run: the live SQLite answer against the PostgreSQL copy (ТЗ §11.6).

The service is still serving from SQLite on its volume. The same rows now exist
in PostgreSQL. This asks the one question that decides whether the flag can be
flipped: does the SAME code, reading the SAME data through a different backend,
produce the same answers?

Read-only on both sides. Every difference is either explained by a cause named
in the specification or it blocks the cutover — an unexplained difference means
the port changed something nobody asked it to.

    APP_URL=... ADMIN_SECRET=... DATABASE_URL=... python pg_parallel_check.py
"""
from __future__ import annotations

import json
import os
import sys

import requests

import rollout

BASE = os.environ["APP_URL"].rstrip("/")
TIMEOUT = 120


def live(path: str) -> dict:
    """What the running service returns — still SQLite-backed."""
    resp = requests.get(f"{BASE}{path}", timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# Columns that record WHEN a row was written, not what it says. The live system
# keeps collecting after the snapshot is taken, so these move by definition.
_WRITE_STAMPS = {"updated_at", "synced_at", "fetched_at", "last_synced_at", "loaded_at"}


def _same_date(a, b) -> bool:
    """Is this the same day written two ways?

    `last_trade_date` holds both `31.07.2026` and `2026-07-31` in the same
    column — a pre-existing hygiene problem, not something the migration did.
    Two spellings of one date are not a difference in the data.
    """
    def norm(v):
        text = str(v or "").strip()
        if len(text) == 10 and text[2] == "." and text[5] == ".":
            return f"{text[6:]}-{text[3:5]}-{text[:2]}"
        return text
    return isinstance(a, str) and isinstance(b, str) and norm(a) == norm(b) and norm(a)


def explain(subject: str, before, after) -> str | None:
    """The only differences allowed, each with the cause that produces it.

    A float artefact is the migration doing its job: SQLite cannot represent
    6853225471.87 and stores ...870001, PostgreSQL NUMERIC stores it exactly.
    Anything else has to be looked at.
    """
    def near(a, b) -> bool:
        if isinstance(a, dict) and isinstance(b, dict):
            return set(a) == set(b) and all(near(a[k], b[k]) for k in a)
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(near(x, y) for x, y in zip(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if a == b:
                return True
            scale = max(abs(a), abs(b))
            return scale > 0 and abs(a - b) / scale <= 1e-9
        return a == b

    if near(before, after):
        return "float artefact removed by NUMERIC (ТЗ §10.1)"

    # Drift between two snapshots taken minutes apart is not a backend
    # difference. Only write-stamps and re-spelled dates are forgiven, and only
    # when every OTHER field matches.
    if isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
        moved = [k for k in before if not near(before[k], after[k])]
        if moved and all(k in _WRITE_STAMPS or _same_date(before[k], after[k])
                         for k in moved):
            stamps = [k for k in moved if k in _WRITE_STAMPS]
            dates = [k for k in moved if k not in _WRITE_STAMPS]
            parts = []
            if stamps:
                parts.append(f"write timestamp moved ({', '.join(stamps)})")
            if dates:
                parts.append(f"same date, other spelling ({', '.join(dates)})")
            return "; ".join(parts)
    return None


def main() -> int:
    os.environ["DATABASE_BACKEND"] = "postgres"
    # Imported AFTER the switch so every module binds to the right backend.
    from catalogue.snapshots import get_all_financials
    from catalogue.ratios import get_all_ratios      # noqa: E402
    from securities_catalog import get_securities_map                   # noqa: E402

    live_fin = live("/api/market/financials")["financials"]
    live_rat = live("/api/market/ratios")["ratios"]
    # /api/securities, not /api/instruments: the latter is the ENRICHED catalog
    # (share_class, is_listed, is_active) and comparing it against the raw map
    # compares two different shapes and calls the difference a regression.
    live_sec = live("/api/securities")["securities"]

    pg_fin, pg_rat, pg_sec = get_all_financials(), get_all_ratios(), get_securities_map()
    # The API scales NSBU thousands at the response boundary; do the same here
    # so the two sides are the same units, not the same numbers by luck.
    from catalogue.fields import FIN_MONEY_FIELDS, NSBU_THOUSANDS_UZS, RATIO_MONEY_FIELDS

    def scale(row, fields):
        return {**row, **{k: row[k] * NSBU_THOUSANDS_UZS
                          for k in fields if isinstance(row.get(k), (int, float))}}

    pg_fin = {t: ({**scale(r, FIN_MONEY_FIELDS),
                   "annual": scale(r["annual"], FIN_MONEY_FIELDS)} if r.get("annual")
                  else scale(r, FIN_MONEY_FIELDS)) for t, r in pg_fin.items()}
    pg_rat = {t: scale(r, RATIO_MONEY_FIELDS) for t, r in pg_rat.items()}

    reports = []
    for name, old, new, keys in (
        ("financials", live_fin, pg_fin, sorted(set(live_fin) | set(pg_fin))),
        ("ratios", live_rat, pg_rat, sorted(set(live_rat) | set(pg_rat))),
        ("securities", live_sec, pg_sec, sorted(set(live_sec) & set(pg_sec))),
    ):
        report = rollout.compare(
            keys,
            lambda t, _o=old: _o.get(t),
            lambda t, _n=new: _n.get(t),
            explain=explain)
        report["dataset"] = name
        report["sqlite_only"] = sorted(set(old) - set(new))[:10]
        report["postgres_only"] = sorted(set(new) - set(old))[:10]
        reports.append(report)
        print(f"{name:12s} {rollout.summarise(report)}")
        if report["unexplained"]:
            for diff in report["unexplained"][:3]:
                print(f"    UNEXPLAINED {diff['subject']}")
                print(f"      sqlite  : {json.dumps(diff['before'], default=str)[:160]}")
                print(f"      postgres: {json.dumps(diff['after'], default=str)[:160]}")

    ready = all(r["ready_to_enable"] for r in reports)
    print("\nREADY TO FLIP:" if ready else "\nBLOCKED:", ready)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
