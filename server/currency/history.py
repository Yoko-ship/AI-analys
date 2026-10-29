"""Official CBU archive. Requested day and effective day are both retained."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import math
import time
import json
import os
from pathlib import Path
import requests
import dbx
from db import APP_DATA_DIR


# Shared across requests: even concurrent chart visitors use at most four workers.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cbu-history")


def _today():
    return datetime.now(ZoneInfo("Asia/Tashkent")).date()


def fetch(day):
    response=requests.get(f"https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/{day}/",timeout=15)
    response.raise_for_status()
    return response.json()


def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS cbu_archive (day TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    c.commit()


def rates(day, *, fetch_missing=True):
    requested=date.fromisoformat(day)
    if requested>_today() or requested.year<2000:
        raise ValueError("Unsupported archive date")
    path=Path(os.getenv("CBU_HISTORY_DB") or APP_DATA_DIR / "cbu_history.sqlite3")
    path.parent.mkdir(parents=True,exist_ok=True)
    c=dbx.connect(str(path))
    try:
        dbx.ensure_schema(c,"cbu-archive-v1",schema)
        stored=c.execute("SELECT payload FROM cbu_archive WHERE day=?",(day,)).fetchone()
        if stored:
            cached = json.loads(stored["payload"])
            fetched_at = cached.pop("_fetched_at", 0)
            final = cached.pop("_final", True)
            if (requested < _today() and final) or (requested == _today() and time.time() - fetched_at < 1800):
                return cached
        if not fetch_missing:
            raise LookupError("No cached CBU observation")
        raw=fetch(day)
        if not isinstance(raw,list):raise ValueError("Invalid CBU archive")
        rows=[]
        for row in raw:
            if row.get("Ccy") not in {"USD","EUR","RUB"}:continue
            effective=datetime.strptime(row["Date"],"%d.%m.%Y").date()
            rate,nominal=float(row["Rate"]),float(row["Nominal"])
            if effective>requested or not math.isfinite(rate) or not math.isfinite(nominal) or rate<=0 or nominal<=0:
                raise ValueError("Invalid or future CBU rate")
            rows.append({"ccy":row["Ccy"],"rate":rate,"nominal":nominal,"per_unit":rate/nominal,"effective_date":effective.isoformat()})
        if not any(r["ccy"]=="USD" for r in rows):raise ValueError("USD missing from CBU archive")
        payload={"ok":True,"as_of":day,"source":"cbu.uz",
                 "source_url":f"https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/{day}/","rates":rows}
        c.execute("INSERT INTO cbu_archive(day,payload) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET payload=excluded.payload",(day,json.dumps({**payload, "_fetched_at": time.time(), "_final": requested < _today()})))
        c.commit()
        return payload
    finally:c.close()


def cached_usd():
    """Read year-end observations without network work in a screener request."""
    path=Path(os.getenv('CBU_HISTORY_DB') or APP_DATA_DIR/'cbu_history.sqlite3')
    path.parent.mkdir(parents=True,exist_ok=True)
    c=dbx.connect(str(path))
    try:
        dbx.ensure_schema(c,'cbu-archive-v1',schema)
        rows=c.execute("SELECT day,payload FROM cbu_archive WHERE day LIKE '%-12-31'").fetchall()
        return {row['day'][:4]:rate['per_unit'] for row in rows
                for rate in json.loads(row['payload'])['rates'] if rate['ccy']=='USD'}
    finally:c.close()



def series(ccy, days=30, end=None):
    """Daily as-of observations, including explicit holes when the archive fails.

    A cold six-month request gets a 30s work budget. Completed snapshots remain
    cached; retrying fills remaining holes without refetching historical days.
    """
    last = date.fromisoformat(end) if end else _today()
    if ccy not in {"USD", "EUR", "RUB"} or days not in {7, 30, 180}:
        raise ValueError("Unsupported currency or history period")
    first = last - timedelta(days=days)
    if last > _today() or first.year < 2000:
        raise ValueError("Unsupported archive date")
    deadline = time.monotonic() + 30

    def observation(day):
        point = {"date": day, "value": None, "effective_date": None}
        expired = time.monotonic() >= deadline
        try:
            snapshot = rates(day, fetch_missing=False) if expired else rates(day)
            row = next((r for r in snapshot["rates"] if r["ccy"] == ccy), None)
            if row and math.isfinite(row["per_unit"]) and row["per_unit"] > 0:
                point.update(value=row["per_unit"], effective_date=row["effective_date"])
        except LookupError:
            if expired:
                point["pending"] = True
        except Exception:
            # An unavailable observation must never become a zero or a made-up carry.
            pass
        return point

    dates = [(first + timedelta(days=i)).isoformat() for i in range(days + 1)]
    # Fetch boundaries and recent dates first; cached days remain usable even
    # after the network budget expires. Restore calendar order for the chart.
    priority = [dates[0], *reversed(dates[1:])]
    points = sorted(_pool.map(observation, priority), key=lambda p: p["date"])
    pending = sum(p.pop("pending", False) for p in points)
    valid = [p for p in points if p["value"] is not None]
    if not valid:
        raise RuntimeError("CBU history unavailable")
    start_value, end_value = points[0]["value"], points[-1]["value"]
    change = end_value - start_value if start_value is not None and end_value is not None else None
    latest = valid[-1]
    return {"ok": True, "ccy": ccy, "days": days, "start": first.isoformat(),
            "end": last.isoformat(), "source": "cbu.uz",
            "source_url": "https://cbu.uz/ru/arkhiv-kursov-valyut/",
            "points": points, "missing_days": len(points) - len(valid), "pending_days": pending,
            "summary": {"latest": latest["value"], "latest_date": latest["date"],
                        "latest_effective_date": latest["effective_date"],
                        "change": change, "change_pct": change / start_value * 100 if change is not None else None,
                        "min": min(p["value"] for p in valid), "max": max(p["value"] for p in valid)}}
