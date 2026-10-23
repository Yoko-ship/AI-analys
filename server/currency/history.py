"""Official CBU archive. Requested day and effective day are both retained."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import requests
import dbx
from db import APP_DATA_DIR


def fetch(day):
    response=requests.get(f"https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/{day}/",timeout=15)
    response.raise_for_status()
    return response.json()


def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS cbu_archive (day TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    c.commit()


def rates(day):
    requested=date.fromisoformat(day)
    if requested>date.today() or requested.year<2000:
        raise ValueError("Unsupported archive date")
    path=Path(os.getenv("CBU_HISTORY_DB") or APP_DATA_DIR / "cbu_history.sqlite3")
    path.parent.mkdir(parents=True,exist_ok=True)
    c=dbx.connect(str(path))
    try:
        dbx.ensure_schema(c,"cbu-archive-v1",schema)
        stored=c.execute("SELECT payload FROM cbu_archive WHERE day=?",(day,)).fetchone()
        if stored:return json.loads(stored["payload"])
        raw=fetch(day)
        if not isinstance(raw,list):raise ValueError("Invalid CBU archive")
        rows=[]
        for row in raw:
            if row.get("Ccy") not in {"USD","EUR","RUB"}:continue
            effective=datetime.strptime(row["Date"],"%d.%m.%Y").date()
            rate,nominal=float(row["Rate"]),float(row["Nominal"])
            import math
            if effective>requested or not math.isfinite(rate) or not math.isfinite(nominal) or rate<=0 or nominal<=0:
                raise ValueError("Invalid or future CBU rate")
            rows.append({"ccy":row["Ccy"],"rate":rate,"nominal":nominal,"per_unit":rate/nominal,"effective_date":effective.isoformat()})
        if not any(r["ccy"]=="USD" for r in rows):raise ValueError("USD missing from CBU archive")
        payload={"ok":True,"as_of":day,"source":"cbu.uz",
                 "source_url":f"https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/{day}/","rates":rows}
        c.execute("INSERT INTO cbu_archive(day,payload) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET payload=excluded.payload",(day,json.dumps(payload)))
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
