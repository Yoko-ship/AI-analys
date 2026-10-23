"""Explicit, loopback-only demo sessions for local development."""
import os

from fastapi import HTTPException
from psycopg.conninfo import conninfo_to_dict

from identity.users import row_to_user

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def issue_demo_session(request, store):
    user_id = os.getenv("LOCAL_DEMO_USER_ID", "")
    if (os.getenv("APP_ENV") != "local" or not user_id.isdecimal()
            or not request.client or request.client.host not in LOOPBACK_HOSTS
            or request.url.hostname not in LOOPBACK_HOSTS
            or request.headers.get("sec-fetch-site") == "cross-site"
            or request.headers.get("origin", str(request.base_url).rstrip("/")) != str(request.base_url).rstrip("/")):
        raise HTTPException(status_code=404)
    # A local UI must never issue sessions against an attached production DB.
    if conninfo_to_dict(store.database.database_url).get("host") not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=404)
    with store.database.connect() as conn:
        row = conn.execute("SELECT * FROM web_users WHERE id=%s AND is_active=TRUE", (int(user_id),)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        user = row_to_user(row)
        public = user.to_public_dict()
        if public['is_admin'] or public['admin_role']:
            raise HTTPException(status_code=404)
        token = store.sessions._issue_session(conn, user.id, "Local demo", request.client.host)
    return {"ok": True, "user": public, "token": token, "token_type": "bearer"}
