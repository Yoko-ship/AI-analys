"""Research persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any
import identity.clock as identity_clock
import json


class Research:
    def __init__(self, database):
        self.database = database

    def get_analysis(self, user_id: int, analysis_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM web_analysis_history WHERE id = %s AND user_id = %s",
                (analysis_id, user_id),
            ).fetchone()
        if not row:
            raise ValueError("Analysis not found")
        return analysis_row(row)


    def update_analysis(self, user_id: int, analysis_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "archived", "bookmarked", "folder", "tags", "pinned_note"}
        parts: list[str] = []
        params: list[Any] = []
        for key, value in (updates or {}).items():
            if key not in allowed:
                continue
            if key == "tags":
                tags = [str(tag).strip()[:40] for tag in (value or []) if str(tag).strip()][:12]
                parts.append("tags = %s::jsonb")
                params.append(json.dumps(tags))
            elif key in {"title", "folder", "pinned_note"}:
                limit = 160 if key != "pinned_note" else 4000
                parts.append(f"{key} = %s")
                params.append(str(value or "").strip()[:limit] or None)
            else:
                parts.append(f"{key} = %s")
                params.append(bool(value))
        if not parts:
            return self.get_analysis(user_id, analysis_id)
        params.extend([analysis_id, user_id])
        with self.database.connect() as conn:
            row = conn.execute(
                f"UPDATE web_analysis_history SET {', '.join(parts)} WHERE id = %s AND user_id = %s RETURNING *",
                params,
            ).fetchone()
        if not row:
            raise ValueError("Analysis not found")
        return analysis_row(row)


    def delete_analysis(self, user_id: int, analysis_id: int) -> bool:
        with self.database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM web_analysis_history WHERE id = %s AND user_id = %s",
                (analysis_id, user_id),
            )
        return cursor.rowcount > 0


    def clear_analysis_history(self, user_id: int) -> int:
        with self.database.connect() as conn:
            cursor = conn.execute("DELETE FROM web_analysis_history WHERE user_id = %s", (user_id,))
        return int(cursor.rowcount or 0)


    def record_analysis(self, user_id: int, payload: dict[str, Any], result: dict[str, Any]) -> None:
        company_input = (payload.get("company") or "").strip()
        summary = result.get("summary") or {}
        metrics = result.get("metrics") or {}
        total_score = metrics.get("total_score") or {}
        score = summary.get("score", total_score.get("score"))
        grade = summary.get("grade", total_score.get("grade"))
        verdict = summary.get("verdict") or summary.get("itog") or ""
        summary_text = summary.get("itog") or summary.get("score_summary") or verdict or ""
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO web_analysis_history (
                    user_id,
                    company_input,
                    company_name,
                    ticker,
                    score,
                    grade,
                    verdict,
                    summary_text,
                    from_cache,
                    model,
                    cost,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    company_input,
                    result.get("company_name"),
                    result.get("ticker"),
                    score,
                    grade,
                    verdict,
                    summary_text,
                    bool(result.get("from_cache", False)),
                    result.get("model"),
                    result.get("cost"),
                    identity_clock._utcnow(),
                ),
            )


def analysis_row(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "company_input": row["company_input"],
        "company_name": row.get("company_name"),
        "ticker": row.get("ticker"),
        "title": row.get("title"),
        "score": float(row["score"]) if row.get("score") is not None else None,
        "grade": row.get("grade"),
        "verdict": row.get("verdict"),
        "summary_text": row.get("summary_text"),
        "from_cache": bool(row.get("from_cache")),
        "model": row.get("model"),
        "cost": float(row["cost"]) if row.get("cost") is not None else None,
        "archived": bool(row.get("archived")),
        "bookmarked": bool(row.get("bookmarked")),
        "folder": row.get("folder"),
        "tags": list(row.get("tags") or []),
        "pinned_note": row.get("pinned_note"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
