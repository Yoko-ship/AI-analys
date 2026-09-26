"""Notifications persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any
import identity.clock as identity_clock


class Notifications:
    def __init__(self, database):
        self.database = database

    def notification_states(self, user_id: int) -> dict[str, dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT notification_id, read_at, dismissed_at FROM web_notification_state WHERE user_id = %s",
                (user_id,),
            ).fetchall()
        return {
            row["notification_id"]: {
                "read": bool(row["read_at"]),
                "dismissed": bool(row["dismissed_at"]),
            }
            for row in rows
        }


    def set_notification_state(self, user_id: int, notification_ids: list[str], *, dismissed: bool = False) -> int:
        ids = [str(value).strip()[:160] for value in notification_ids if str(value).strip()][:200]
        if not ids:
            return 0
        now = identity_clock._utcnow()
        with self.database.connect() as conn:
            for notification_id in ids:
                conn.execute(
                    """
                    INSERT INTO web_notification_state (user_id, notification_id, read_at, dismissed_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, notification_id)
                    DO UPDATE SET read_at = COALESCE(web_notification_state.read_at, EXCLUDED.read_at),
                                  dismissed_at = COALESCE(EXCLUDED.dismissed_at, web_notification_state.dismissed_at)
                    """,
                    (user_id, notification_id, now, now if dismissed else None),
                )
        return len(ids)
