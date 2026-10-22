"""Private transaction ledger with atomic validation and retry-safe writes."""
from uuid import uuid4

from identity.portfolio_math import FIELDS, calculate_ledger, normalize_transaction


class Portfolio:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _lock(conn, user_id):
        # Serialize all writes per owner, including their first transaction.
        if not conn.execute("SELECT id FROM web_users WHERE id=%s FOR UPDATE", (user_id,)).fetchone():
            raise ValueError("ACCOUNT_NOT_FOUND")

    @staticmethod
    def _list(conn, user_id):
        return conn.execute("""SELECT id, sequence, ticker, kind, trade_date, quantity, price, fees, amount,
                            note, version, created_at, updated_at FROM web_portfolio_transactions
                            WHERE user_id=%s AND deleted_at IS NULL
                            ORDER BY trade_date NULLS FIRST, sequence""", (user_id,)).fetchall()

    def list_transactions(self, user_id):
        with self.database.connect() as conn:
            return self._list(conn, user_id)

    def list_portfolio_positions(self, user_id):
        return calculate_ledger(self.list_transactions(user_id))["items"]

    @staticmethod
    def _insert(conn, user_id, key, row):
        return conn.execute("""INSERT INTO web_portfolio_transactions
                            (user_id, id, ticker, kind, trade_date, quantity, price, fees, amount, note)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id, sequence, ticker, kind, trade_date, quantity, price, fees, amount,
                                      note, version, created_at, updated_at""",
                            (user_id, key, *(row[k] for k in FIELDS))).fetchone()

    def add_transaction(self, user_id, key, payload):
        row = normalize_transaction(payload)
        with self.database.connect() as conn:
            self._lock(conn, user_id)
            previous = conn.execute("SELECT * FROM web_portfolio_transactions WHERE user_id=%s AND id=%s",
                                    (user_id, key)).fetchone()
            if previous:
                if previous["deleted_at"] is not None or normalize_transaction(previous) != row:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return next(r for r in self._list(conn, user_id) if r["id"] == key)
            rows = self._list(conn, user_id)
            if len(rows) >= 10000:
                raise ValueError("TRANSACTION_LIMIT")
            calculate_ledger([*rows, {**row, "sequence": max((r["sequence"] for r in rows), default=0) + 1}])
            return self._insert(conn, user_id, key, row)

    def update_transaction(self, user_id, key, payload, *, version):
        row = normalize_transaction(payload)
        with self.database.connect() as conn:
            self._lock(conn, user_id)
            rows = self._list(conn, user_id)
            self._existing(rows, key, version)
            calculate_ledger([{**r, **row} if r["id"] == key else r for r in rows])
            conn.execute("""UPDATE web_portfolio_transactions SET ticker=%s, kind=%s, trade_date=%s,
                         quantity=%s, price=%s, fees=%s, amount=%s, note=%s, version=version+1, updated_at=NOW()
                         WHERE user_id=%s AND id=%s""", (*(row[k] for k in FIELDS), user_id, key))
            return next(r for r in self._list(conn, user_id) if r["id"] == key)

    @staticmethod
    def _existing(rows, key, version):
        old = next((r for r in rows if r["id"] == key), None)
        if old is None:
            raise ValueError("TRANSACTION_NOT_FOUND")
        if old["version"] != version:
            raise ValueError("VERSION_CONFLICT")
        return old

    def delete_transaction(self, user_id, key, *, version):
        with self.database.connect() as conn:
            self._lock(conn, user_id)
            rows = self._list(conn, user_id)
            self._existing(rows, key, version)
            calculate_ledger([r for r in rows if r["id"] != key])
            # Keep the key so a create retry cannot resurrect a deleted record.
            conn.execute("""UPDATE web_portfolio_transactions SET deleted_at=NOW(), updated_at=NOW(), version=version+1
                         WHERE user_id=%s AND id=%s""", (user_id, key))
        return True

    def upsert_portfolio_position(self, user_id, ticker, *, quantity, average_cost, currency="UZS", note=""):
        """Compatibility for older clients: edit only an opening-only holding."""
        if currency != "UZS":
            raise ValueError("Only UZS cost basis is currently supported")
        row = normalize_transaction(dict(ticker=ticker, kind="opening", quantity=quantity, price=average_cost, note=note))
        with self.database.connect() as conn:
            self._lock(conn, user_id)
            rows = [r for r in self._list(conn, user_id) if r["ticker"] == row["ticker"]]
            if any(r["kind"] != "opening" for r in rows):
                raise ValueError("USE_TRANSACTION_HISTORY")
            if rows:
                conn.execute("""UPDATE web_portfolio_transactions SET quantity=%s, price=%s, note=%s,
                             version=version+1, updated_at=NOW() WHERE user_id=%s AND id=%s""",
                             (row["quantity"], row["price"], row["note"], user_id, rows[0]["id"]))
            else:
                self._insert(conn, user_id, str(uuid4()), row)
        return {"ticker": row["ticker"], "quantity": row["quantity"], "average_cost": row["price"],
                "currency": "UZS", "note": row["note"]}

    def delete_portfolio_position(self, user_id, ticker):
        with self.database.connect() as conn:
            self._lock(conn, user_id)
            rows = [r for r in self._list(conn, user_id) if r["ticker"] == ticker.strip().upper()]
            if any(r["kind"] != "opening" for r in rows):
                raise ValueError("USE_TRANSACTION_HISTORY")
            if not rows:
                return False
            conn.execute("""UPDATE web_portfolio_transactions SET deleted_at=NOW(), updated_at=NOW(), version=version+1
                         WHERE user_id=%s AND id=%s""", (user_id, rows[0]["id"]))
        return True
