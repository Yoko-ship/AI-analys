"""Portfolio persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any


class Portfolio:
    def __init__(self, database):
        self.database = database

    def list_portfolio_positions(self, user_id: int) -> list[dict[str, Any]]:
        """Return only explicit holdings, newest edit first.

        Price, valuation and P/L are calculated by the API from the reconciled
        market board.  This storage layer owns just the user's declarations.
        """
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, quantity, average_cost, currency, note, created_at, updated_at
                FROM web_portfolio_positions
                WHERE user_id = %s
                ORDER BY updated_at DESC, ticker ASC
                """,
                (user_id,),
            ).fetchall()
        return [{
            "ticker": row["ticker"],
            "quantity": float(row["quantity"]),
            "average_cost": float(row["average_cost"]),
            "currency": row["currency"],
            "note": row["note"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        } for row in rows]


    def upsert_portfolio_position(self, user_id: int, ticker: str, *, quantity: float,
                                  average_cost: float, currency: str = "UZS",
                                  note: str = "") -> dict[str, Any]:
        ticker = str(ticker or "").strip().upper()
        if not ticker:
            raise ValueError("Ticker is required")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero")
        if average_cost < 0:
            raise ValueError("Average cost cannot be negative")
        currency = str(currency or "UZS").strip().upper()
        if currency != "UZS":
            raise ValueError("Only UZS cost basis is currently supported")
        note = str(note or "").strip()[:1000]
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO web_portfolio_positions
                    (user_id, ticker, quantity, average_cost, currency, note, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, ticker) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    average_cost = EXCLUDED.average_cost,
                    currency = EXCLUDED.currency,
                    note = EXCLUDED.note,
                    updated_at = NOW()
                RETURNING ticker, quantity, average_cost, currency, note, created_at, updated_at
                """,
                (user_id, ticker, quantity, average_cost, currency, note),
            ).fetchone()
        return {
            "ticker": row["ticker"], "quantity": float(row["quantity"]),
            "average_cost": float(row["average_cost"]), "currency": row["currency"],
            "note": row["note"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }


    def delete_portfolio_position(self, user_id: int, ticker: str) -> bool:
        with self.database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM web_portfolio_positions WHERE user_id = %s AND ticker = %s",
                (user_id, str(ticker or "").strip().upper()),
            )
        return cursor.rowcount > 0
