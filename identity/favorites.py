"""Favorites persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any


class Favorites:
    def __init__(self, database):
        self.database = database

    def list_favorites(self, user_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, company_name, created_at, position,
                       price_alert_enabled, price_alert_above, price_alert_below,
                       news_alert_enabled, report_alert_enabled, pattern_alert_enabled
                FROM web_favorite_companies
                WHERE user_id = %s
                ORDER BY position ASC, created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "position": int(row.get("position") or 0),
                "price_alert_enabled": bool(row.get("price_alert_enabled")),
                "price_alert_above": float(row["price_alert_above"]) if row.get("price_alert_above") is not None else None,
                "price_alert_below": float(row["price_alert_below"]) if row.get("price_alert_below") is not None else None,
                "news_alert_enabled": bool(row.get("news_alert_enabled", True)),
                "report_alert_enabled": bool(row.get("report_alert_enabled", True)),
                "pattern_alert_enabled": bool(row.get("pattern_alert_enabled")),
            }
            for row in rows
        ]


    def toggle_favorite(self, user_id: int, ticker: str, company_name: str | None = None) -> dict[str, Any]:
        ticker_value = (ticker or "").strip().upper()
        if not ticker_value:
            raise ValueError("Ticker is required")
        company_value = (company_name or "").strip() or None

        with self.database.connect() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM web_favorite_companies
                WHERE user_id = %s AND ticker = %s
                """,
                (user_id, ticker_value),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    DELETE FROM web_favorite_companies
                    WHERE user_id = %s AND ticker = %s
                    """,
                    (user_id, ticker_value),
                )
                return {"favorited": False, "ticker": ticker_value, "company_name": company_value}

            conn.execute(
                """
                INSERT INTO web_favorite_companies (user_id, ticker, company_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, ticker)
                DO UPDATE SET company_name = COALESCE(EXCLUDED.company_name, web_favorite_companies.company_name)
                """,
                (user_id, ticker_value, company_value),
            )
        return {"favorited": True, "ticker": ticker_value, "company_name": company_value}


    def update_favorite(self, user_id: int, ticker: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "position", "price_alert_enabled", "price_alert_above", "price_alert_below",
            "news_alert_enabled", "report_alert_enabled", "pattern_alert_enabled",
        }
        parts: list[str] = []
        params: list[Any] = []
        for key, value in (updates or {}).items():
            if key not in allowed:
                continue
            parts.append(f"{key} = %s")
            if key == "position":
                params.append(max(0, int(value or 0)))
            elif key in {"price_alert_above", "price_alert_below"}:
                params.append(float(value) if value not in (None, "") else None)
            else:
                params.append(bool(value))
        if not parts:
            raise ValueError("No favorite settings supplied")
        params.extend([(ticker or "").strip().upper(), user_id])
        with self.database.connect() as conn:
            row = conn.execute(
                f"UPDATE web_favorite_companies SET {', '.join(parts)} WHERE ticker = %s AND user_id = %s RETURNING ticker",
                params,
            ).fetchone()
        if not row:
            raise ValueError("Favorite not found")
        return next(item for item in self.list_favorites(user_id) if item["ticker"] == row["ticker"])
