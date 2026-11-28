"""Record successful registration inside the caller's account transaction."""
from identity import clock


def complete(conn, user_id):
    # Decide from the locked database row, not an earlier read. Concurrent or
    # repeated completions must preserve the first date. A missing start means
    # legacy history is unknown, even if an old account proves its inbox today.
    conn.execute(
        """
        UPDATE web_users SET registration_completed_at = COALESCE(registration_completed_at, %s)
        WHERE id = %s AND registration_started_at IS NOT NULL
        """,
        (clock._utcnow(), user_id),
    )
