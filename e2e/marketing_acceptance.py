"""Local fixture for marketing-workspace.spec.js. Requires a fresh, disposable analytics DB."""
import json
import os
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Only permit a local disposable analytics DB. Catalogue mutations go in a temporary SQLite file.
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg import connect, sql
from uuid import uuid4
import atexit
dsn = os.environ["MARKETING_QA_PG"]
host = conninfo_to_dict(dsn).get("host", "")
if host not in ("", "localhost", "127.0.0.1") and not host.startswith("/"):
    raise ValueError("Use a local disposable analytics database")
schema = "marketing_qa_" + uuid4().hex
with connect(dsn, autocommit=True) as db:
    db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))


@atexit.register
def cleanup():
    with connect(dsn, autocommit=True) as db:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


tmp = tempfile.TemporaryDirectory()
os.environ.update(CATALOG_DB_PATH=f"{tmp.name}/qa.db", DATABASE_BACKEND="sqlite",
                  DATABASE_URL=make_conninfo(dsn, options=f"-c search_path={schema}"),
                  ANALYTICS_FLUSH_SECONDS="0.3", PYTHON_DOTENV_DISABLED="1")

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from server.news import marketing_routes as routes
from server.auth.access import _admin_panel_gate
import news_store
import web_analytics as analytics

app = FastAPI()
app.include_router(routes.router)
from analytics_api import public_router
app.include_router(routes.workspace.public)
app.include_router(public_router)
app.dependency_overrides[_admin_panel_gate] = lambda: None

now = datetime.now(timezone.utc)
news_store.upsert_news([dict(title="Дивиденд", snippet="100 сумов", published_at=now.isoformat(),
                             source="OpenInfo", url="https://example.test/1", relevant=True,
                             relevance_score=1, impact="high", type="corporate_event")])
story, = routes._stories()
from news_marketing import Pitch
pitch = Pitch(id=story["id"], excerpt="100 сумов", ru=dict(headline="Дивиденд", body="Предложено 100 сумов.", reason="Для акционеров"),
              uz=dict(headline="Dividend", body="100 so‘m taklif qilindi.", reason="Aksiyadorlar uchun"))
with closing(routes.get_catalog_conn()) as conn, conn:
    conn.execute("INSERT INTO news_marketing VALUES(1,?,?)", (routes._revision([story]), json.dumps(routes.verified_pitches([pitch],[story]))))

    conn.execute("INSERT INTO marketing_experiments VALUES(?,?,?,?,?)",
                 ("baseline", "Completed landing test", "/market", "/news", (now-timedelta(days=5)).isoformat()))
analytics.init_db()
with analytics._conn() as conn:
    if conn.execute("SELECT COUNT(*) AS n FROM web_events").fetchone()["n"]:
        raise ValueError("Use a fresh QA database")
    for i in range(5):
        rows = [(0, "s", "/news/1", "news-1-ru")]
        if i < 2: rows.append((1, "s", "/market", None))
        if i == 0: rows.append((60, "return", "/market", None))
        for minute, session, path, tag in rows:
            conn.execute("""INSERT INTO web_events(ts,visitor_id,session_id,event,path,utm_campaign,internal)
                            VALUES(%s,%s,%s,'pageview',%s,%s,%s)""",
                         (now-timedelta(days=1)+timedelta(minutes=minute), f"reader{i}", session, path, tag, i==4))

    for arm in ("a", "b"):
        for i in range(100):
            for minute, path in [(0, "/news")] + ([(1, "/market")] if i < (85 if arm=="a" else 20) else []):
                conn.execute("""INSERT INTO web_events(ts,visitor_id,session_id,event,path,utm_campaign)
                                VALUES(%s,%s,'s','pageview',%s,%s)""", (now-timedelta(days=3)+timedelta(minutes=minute),
                             f"test-{arm}-{i}", path, f"exp-baseline-{arm}" if minute == 0 else None))

dist = Path(__file__).resolve().parents[1] / "web/dist"
app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
@app.get("/{path:path}")
def shell(path: str):
    return FileResponse(dist / "index.html")
