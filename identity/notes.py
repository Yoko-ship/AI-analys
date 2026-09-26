"""Notes persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any
import identity.clock as identity_clock
import json


class Notes:
    def __init__(self, database):
        self.database = database

    def list_notes(self, user_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, analysis_id, title, body, pinned, tags, created_at, updated_at
                FROM web_saved_notes WHERE user_id = %s
                ORDER BY pinned DESC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [{
            "id": int(row["id"]),
            "analysis_id": int(row["analysis_id"]) if row.get("analysis_id") else None,
            "title": row["title"],
            "body": row["body"],
            "pinned": bool(row["pinned"]),
            "tags": list(row.get("tags") or []),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        } for row in rows]


    def save_note(self, user_id: int, note_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()[:160]
        body = str(payload.get("body") or "").strip()[:8000]
        if not title and not body:
            raise ValueError("Note cannot be empty")
        tags = [str(tag).strip()[:40] for tag in (payload.get("tags") or []) if str(tag).strip()][:12]
        analysis_id = payload.get("analysis_id")
        with self.database.connect() as conn:
            if analysis_id:
                linked = conn.execute(
                    "SELECT id FROM web_analysis_history WHERE id = %s AND user_id = %s",
                    (analysis_id, user_id),
                ).fetchone()
                if not linked:
                    raise ValueError("Analysis not found")
            if note_id:
                row = conn.execute(
                    """
                    UPDATE web_saved_notes
                    SET analysis_id = %s, title = %s, body = %s, pinned = %s,
                        tags = %s::jsonb, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    RETURNING id
                    """,
                    (analysis_id, title, body, bool(payload.get("pinned")), json.dumps(tags), identity_clock._utcnow(), note_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    INSERT INTO web_saved_notes (user_id, analysis_id, title, body, pinned, tags)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id
                    """,
                    (user_id, analysis_id, title, body, bool(payload.get("pinned")), json.dumps(tags)),
                ).fetchone()
        if not row:
            raise ValueError("Note not found")
        return next(note for note in self.list_notes(user_id) if note["id"] == int(row["id"]))


    def delete_note(self, user_id: int, note_id: int) -> bool:
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM web_saved_notes WHERE id = %s AND user_id = %s", (note_id, user_id))
        return cursor.rowcount > 0
