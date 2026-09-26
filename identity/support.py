"""Support persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any


class Support:
    def __init__(self, database):
        self.database = database

    def create_support_request(self, user_id: int, subject: str, message: str) -> dict[str, Any]:
        clean_subject = str(subject or "").strip()[:160]
        clean_message = str(message or "").strip()[:6000]
        if not clean_subject or not clean_message:
            raise ValueError("Subject and message are required")
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO web_support_requests (user_id, subject, message)
                VALUES (%s, %s, %s)
                RETURNING id, status, created_at
                """,
                (user_id, clean_subject, clean_message),
            ).fetchone()
        return {
            "id": int(row["id"]),
            "subject": clean_subject,
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }


    def list_support_requests(self, status: str = "", limit: int = 100) -> dict[str, Any]:
        """Return the feedback inbox for a human administrator.

        Feedback is linked to an account so the team can follow up, but this
        method is only exposed by the human-admin router — regular users can
        never enumerate another person's messages or contact details.
        """
        state = str(status or "").strip().lower()
        if state not in {"", "open", "in_progress", "resolved"}:
            raise ValueError("Unknown feedback status")
        page_size = max(1, min(int(limit or 100), 250))
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.subject, r.message, r.status, r.created_at,
                       u.id AS user_id, u.full_name, u.email
                FROM web_support_requests r
                JOIN web_users u ON u.id = r.user_id
                WHERE (%s = '' OR r.status = %s)
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT %s
                """,
                (state, state, page_size),
            ).fetchall()
        items = []
        for row in rows:
            items.append({
                "id": int(row["id"]),
                "user_id": int(row["user_id"]),
                "full_name": row.get("full_name") or "",
                "email": row.get("email") or "",
                "subject": row.get("subject") or "",
                "message": row.get("message") or "",
                "status": row.get("status") or "open",
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            })
        return {"items": items}


    def update_support_request_status(self, request_id: int, status: str) -> dict[str, Any]:
        state = str(status or "").strip().lower()
        if state not in {"open", "in_progress", "resolved"}:
            raise ValueError("Unknown feedback status")
        with self.database.connect() as conn:
            row = conn.execute(
                """
                UPDATE web_support_requests
                SET status = %s
                WHERE id = %s
                RETURNING id, status
                """,
                (state, int(request_id)),
            ).fetchone()
        if not row:
            raise ValueError("Feedback request not found")
        return {"id": int(row["id"]), "status": row["status"]}
