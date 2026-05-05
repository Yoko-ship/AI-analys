"""
users.py - user storage and access checks for the bot.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from db import get_users_db_path, sqlite_connect

logger = logging.getLogger(__name__)

DB_PATH = get_users_db_path()

FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "3"))
ADMIN_TELEGRAM_IDS = {
    int(raw.strip())
    for raw in os.getenv("ADMIN_TELEGRAM_ID", "").split(",")
    if raw.strip().isdigit()
}

TIER_FREE = "free"
TIER_PRO = "pro"
TIER_ADMIN = "admin"


@dataclass
class User:
    user_id: int
    username: Optional[str]
    first_name: str
    last_name: Optional[str]
    tier: str
    is_banned: bool
    joined_at: datetime
    last_active_at: datetime
    total_analyses: int
    analyses_today: int
    subscription_until: Optional[datetime]
    language_code: Optional[str]
    notes: Optional[str]

    @property
    def full_name(self) -> str:
        parts = [self.first_name]
        if self.last_name:
            parts.append(self.last_name)
        return " ".join(parts)

    @property
    def display(self) -> str:
        name = self.full_name
        if self.username:
            name += f" (@{self.username})"
        return name

    @property
    def is_pro(self) -> bool:
        if self.tier == TIER_ADMIN:
            return True
        if self.tier == TIER_PRO and self.subscription_until:
            return datetime.now() < self.subscription_until
        return False

    @property
    def is_admin(self) -> bool:
        return self.tier == TIER_ADMIN

    @property
    def sub_status(self) -> str:
        if self.is_banned:
            return "🚫 Заблокирован"
        if self.tier == TIER_ADMIN:
            return "👑 Администратор"
        if self.is_pro:
            until = self.subscription_until.strftime("%d.%m.%Y")
            return f"⭐ PRO до {until}"
        return "🆓 Бесплатный"


class UserDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        logger.info("База пользователей: %s", db_path)

    def _conn(self):
        return sqlite_connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id            INTEGER PRIMARY KEY,
                    username           TEXT,
                    first_name         TEXT NOT NULL DEFAULT '',
                    last_name          TEXT,
                    tier               TEXT NOT NULL DEFAULT 'free',
                    is_banned          INTEGER NOT NULL DEFAULT 0,
                    joined_at          REAL NOT NULL,
                    last_active_at     REAL NOT NULL,
                    total_analyses     INTEGER NOT NULL DEFAULT 0,
                    subscription_until REAL,
                    language_code      TEXT,
                    notes              TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL,
                    company_name TEXT NOT NULL,
                    cost         REAL DEFAULT 0,
                    from_cache   INTEGER DEFAULT 0,
                    created_at   REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_log_user
                ON analysis_log(user_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_log_company
                ON analysis_log(company_name)
                """
            )

    def _sync_admin_tier(self, user_id: int) -> None:
        if user_id not in ADMIN_TELEGRAM_IDS:
            return
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE users
                SET tier=?, subscription_until=NULL
                WHERE user_id=? AND tier!=?
                """,
                (TIER_ADMIN, user_id, TIER_ADMIN),
            )

    def upsert(self, tg_user) -> User:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (user_id, username, first_name, last_name,
                     tier, is_banned, joined_at, last_active_at,
                     total_analyses, language_code)
                VALUES (?, ?, ?, ?, 'free', 0, ?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username       = excluded.username,
                    first_name     = excluded.first_name,
                    last_name      = excluded.last_name,
                    last_active_at = excluded.last_active_at,
                    language_code  = excluded.language_code
                """,
                (
                    tg_user.id,
                    tg_user.username,
                    tg_user.first_name or "",
                    tg_user.last_name,
                    now,
                    now,
                    tg_user.language_code,
                ),
            )
        self._sync_admin_tier(tg_user.id)
        return self.get(tg_user.id)

    def _analyses_today(self, user_id: int) -> int:
        today_start = datetime.combine(date.today(), datetime.min.time()).timestamp()
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT COUNT(*)
                FROM analysis_log
                WHERE user_id=? AND created_at>=?
                """,
                (user_id, today_start),
            ).fetchone()[0]

    def _row_to_user(self, row, analyses_today: int) -> User:
        return User(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            tier=row["tier"],
            is_banned=bool(row["is_banned"]),
            joined_at=datetime.fromtimestamp(row["joined_at"]),
            last_active_at=datetime.fromtimestamp(row["last_active_at"]),
            total_analyses=row["total_analyses"],
            analyses_today=analyses_today,
            subscription_until=(
                datetime.fromtimestamp(row["subscription_until"])
                if row["subscription_until"]
                else None
            ),
            language_code=row["language_code"],
            notes=row["notes"],
        )

    def get(self, user_id: int) -> Optional[User]:
        self._sync_admin_tier(user_id)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_user(row, self._analyses_today(user_id))

    def can_analyze(self, user_id: int) -> tuple[bool, str]:
        user = self.get(user_id)
        if not user:
            return True, ""

        if user.is_banned:
            return False, "🚫 Ваш аккаунт заблокирован. Обратитесь к администратору."

        if user.is_pro:
            return True, ""

        if FREE_DAILY_LIMIT > 0 and user.analyses_today >= FREE_DAILY_LIMIT:
            return False, (
                "⛔ *Дневной лимит исчерпан*\n\n"
                f"Сегодня ты использовал все {FREE_DAILY_LIMIT} новых анализа.\n\n"
                "♾️ *Кэш бесплатен всегда* — повторный просмотр уже открытых компаний не расходует лимит.\n"
                "Попробуй снова после обновления лимита завтра."
            )

        return True, ""

    def can_use_cache(self, user_id: int) -> bool:
        user = self.get(user_id)
        if not user:
            return True
        return not user.is_banned

    def record_analysis(
        self, user_id: int, company_name: str, cost: float = 0.0, from_cache: bool = False
    ):
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO analysis_log (user_id, company_name, cost, from_cache, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, company_name, cost, int(from_cache), now),
            )
            if not from_cache:
                conn.execute(
                    """
                    UPDATE users
                    SET total_analyses = total_analyses + 1, last_active_at = ?
                    WHERE user_id = ?
                    """,
                    (now, user_id),
                )
            else:
                conn.execute(
                    "UPDATE users SET last_active_at = ? WHERE user_id = ?",
                    (now, user_id),
                )

    def touch(self, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_active_at=? WHERE user_id=?",
                (time.time(), user_id),
            )

    def set_tier(self, user_id: int, tier: str, days: Optional[int] = None) -> bool:
        if tier not in (TIER_FREE, TIER_PRO, TIER_ADMIN):
            raise ValueError(f"Неизвестный тариф: {tier}")

        subscription_until = None
        if tier == TIER_PRO and days:
            subscription_until = time.time() + days * 86400

        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET tier=?, subscription_until=?
                WHERE user_id=?
                """,
                (tier, subscription_until, user_id),
            )
        return cursor.rowcount > 0

    def ban(self, user_id: int, banned: bool = True) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE users SET is_banned=? WHERE user_id=?",
                (int(banned), user_id),
            )
        return cursor.rowcount > 0

    def set_notes(self, user_id: int, notes: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET notes=? WHERE user_id=?",
                (notes, user_id),
            )

    def list_all(self, limit: int = 100, offset: int = 0) -> list[User]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM users
                ORDER BY joined_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_user(row, self._analyses_today(row["user_id"])) for row in rows]

    def stats(self) -> dict:
        today_start = datetime.combine(date.today(), datetime.min.time()).timestamp()
        week_start = today_start - 7 * 86400

        with self._conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            new_today = conn.execute(
                "SELECT COUNT(*) FROM users WHERE joined_at >= ?",
                (today_start,),
            ).fetchone()[0]
            active_week = conn.execute(
                "SELECT COUNT(*) FROM users WHERE last_active_at >= ?",
                (week_start,),
            ).fetchone()[0]
            pro_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE tier='pro'",
            ).fetchone()[0]
            admin_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE tier='admin'",
            ).fetchone()[0]
            banned_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_banned=1",
            ).fetchone()[0]
            analyses_today = conn.execute(
                "SELECT COUNT(*) FROM analysis_log WHERE created_at >= ?",
                (today_start,),
            ).fetchone()[0]
            analyses_total = conn.execute(
                "SELECT COUNT(*) FROM analysis_log",
            ).fetchone()[0]
            cost_total = conn.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM analysis_log WHERE from_cache=0",
            ).fetchone()[0]
            cost_saved = conn.execute(
                "SELECT COUNT(*) * 0.15 FROM analysis_log WHERE from_cache=1",
            ).fetchone()[0]
            top_companies = conn.execute(
                """
                SELECT company_name, COUNT(*) as cnt
                FROM analysis_log
                GROUP BY company_name
                ORDER BY cnt DESC
                LIMIT 5
                """
            ).fetchall()

        return {
            "total_users": total_users,
            "new_today": new_today,
            "active_week": active_week,
            "pro_users": pro_users,
            "admin_users": admin_users,
            "banned_users": banned_users,
            "analyses_today": analyses_today,
            "analyses_total": analyses_total,
            "cost_total": round(cost_total, 3),
            "cost_saved": round(cost_saved, 3),
            "top_companies": [(row["company_name"], row["cnt"]) for row in top_companies],
        }

    def user_history(self, user_id: int, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT company_name, cost, from_cache, created_at
                FROM analysis_log
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            {
                "company": row["company_name"],
                "cost": row["cost"],
                "from_cache": bool(row["from_cache"]),
                "date": datetime.fromtimestamp(row["created_at"]),
            }
            for row in rows
        ]


user_db = UserDB()
