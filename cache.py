"""
cache.py — кэш результатов анализа на SQLite.

Логика:
  - Ключ кэша: нормализованное имя компании + язык ответа
  - TTL по умолчанию: 7 дней
  - Хранит: raw_analysis, html_report, периоды, стоимость, timestamp
  - Никаких внешних зависимостей — только стандартная библиотека

Использование:
  from cache import AnalysisCache
  cache = AnalysisCache(
  
  # Проверить
  hit = cache.get("UZMET")
  if hit:
      print(hit["company_name"], hit["age_days"])
  
  # Сохранить
  cache.set("UZMET", result_dict)
  
  # Принудительно сбросить
  cache.invalidate("UZMET")
  
  # Все компании в кэше
  entries = cache.list_all()
"""

import sqlite3
import json
import time
import os
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
from db import get_cache_db_path, sqlite_connect

logger = logging.getLogger(__name__)

# TTL в секундах (по умолчанию 7 дней)
DEFAULT_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "7"))
DB_PATH = get_cache_db_path()


def _json_default(value):
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _normalize(company: str) -> str:
    """Нормализует название компании для использования как ключ."""
    s = company.lower().strip()
    s = re.sub(r"\s+", " ", s)      # несколько пробелов → один
    s = re.sub(r"[«»\"']", "", s)   # убираем кавычки
    return s


def _normalize_language(language: str | None) -> str:
    value = (language or "ru").strip().lower()
    return value if value in {"ru", "en", "uz"} else "ru"


def _normalize_cache_mode(mode: str | None = "default") -> str:
    value = (mode or "default").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "default"


def _cache_key(
    company: str,
    language: str | None = "ru",
    mode: str | None = "default",
) -> str:
    base = _normalize(company)
    lang = _normalize_language(language)
    cache_mode = _normalize_cache_mode(mode)
    if lang == "ru" and cache_mode == "default":
        return base
    if cache_mode == "default":
        return f"{base}::{lang}"
    return f"{base}::{lang}::{cache_mode}"


class AnalysisCache:
    def __init__(self, db_path: str = DB_PATH, ttl_days: int = DEFAULT_TTL_DAYS):
        self.db_path  = db_path
        self.ttl_secs = ttl_days * 86400
        self._init_db()

    # ─────────────────────────────────────────────────────
    # ИНИЦИАЛИЗАЦИЯ БД
    # ─────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    cache_key       TEXT PRIMARY KEY,
                    company_name    TEXT NOT NULL,
                    raw_analysis    TEXT NOT NULL,
                    html_report     TEXT NOT NULL,
                    sections_json   TEXT NOT NULL,
                    result_json     TEXT,
                    annual_period   TEXT,
                    quarterly_period TEXT,
                    cost            REAL,
                    created_at      REAL NOT NULL,
                    hit_count       INTEGER DEFAULT 0
                )
            """)
            # Индекс для быстрого поиска по времени (для очистки)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON analysis_cache(created_at)
            """)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(analysis_cache)").fetchall()
            }
            if "result_json" not in columns:
                conn.execute(
                    "ALTER TABLE analysis_cache ADD COLUMN result_json TEXT"
                )
        logger.info(f"Кэш инициализирован: {self.db_path}")

    def _conn(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path)

    # ─────────────────────────────────────────────────────
    # ОСНОВНЫЕ ОПЕРАЦИИ
    # ─────────────────────────────────────────────────────

    def get(
        self,
        company: str,
        language: str | None = "ru",
        mode: str | None = "default",
    ) -> dict | None:
        """
        Возвращает кэшированный результат или None если нет/устарел.
        
        Возвращаемый dict содержит все поля result + доп. поля:
          - from_cache: True
          - cached_at: datetime объект
          - age_days: int — сколько дней назад был сделан анализ
          - age_str: str — "3 дня назад" / "сегодня" / "вчера"
          - expires_in_days: int — через сколько дней истечёт
        """
        cache_mode = _normalize_cache_mode(mode)
        key = _cache_key(company, language, cache_mode)
        now = time.time()

        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_cache WHERE cache_key = ?", (key,)
            ).fetchone()

            if (
                row is None
                and cache_mode == "default"
                and _normalize_language(language) == "ru"
            ):
                # Backward compatibility for very old rows if they ever used the suffixed key.
                legacy_row = conn.execute(
                    "SELECT * FROM analysis_cache WHERE cache_key = ?", (_normalize(company),)
                ).fetchone()
                row = legacy_row

        if row is None:
            return None

        age_secs = now - row["created_at"]
        if age_secs > self.ttl_secs:
            logger.info(f"Кэш устарел для '{company}' ({age_secs/86400:.1f} дн.)")
            return None

        # Увеличиваем счётчик обращений
        with self._conn() as conn:
            conn.execute(
                "UPDATE analysis_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (key,)
            )

        age_days = int(age_secs // 86400)
        expires_in = int((self.ttl_secs - age_secs) // 86400)
        cached_at  = datetime.fromtimestamp(row["created_at"])

        if age_days == 0:
            age_str = "сегодня"
        elif age_days == 1:
            age_str = "вчера"
        else:
            age_str = f"{age_days} дн. назад"

        # Парсим sections обратно из JSON
        try:
            sections = json.loads(row["sections_json"])
        except Exception:
            sections = {}

        result_data = {}
        if "result_json" in row.keys() and row["result_json"]:
            try:
                result_data = json.loads(row["result_json"])
            except Exception:
                result_data = {}

        payload = {
            "company_name":      row["company_name"],
            "raw_analysis":      row["raw_analysis"],
            "html_report":       row["html_report"],
            "sections":          sections,
            "annual_period":     row["annual_period"]   or "",
            "quarterly_period":  row["quarterly_period"] or "",
            "cost":              row["cost"] or 0.0,
            # Мета-поля кэша
            "from_cache":        True,
            "cached_at":         cached_at,
            "age_days":          age_days,
            "age_str":           age_str,
            "expires_in_days":   expires_in,
        }
        payload.update(result_data)
        payload["from_cache"] = True
        payload["source"] = "cache"
        payload["cache_mode"] = cache_mode
        return payload

    def set(
        self,
        company: str,
        result: dict,
        language: str | None = "ru",
        mode: str | None = "default",
    ):
        """
        Сохраняет результат анализа в кэш.
        result — словарь который возвращает run_full_analysis().
        """
        cache_mode = _normalize_cache_mode(mode)
        key = _cache_key(company, language, cache_mode)
        now = time.time()

        sections_json = json.dumps(
            result.get("sections", {}), ensure_ascii=False
        )
        result_json = json.dumps(
            result,
            ensure_ascii=False,
            default=_json_default,
        )

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO analysis_cache
                    (cache_key, company_name, raw_analysis, html_report,
                     sections_json, result_json, annual_period, quarterly_period, cost, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    company_name     = excluded.company_name,
                    raw_analysis     = excluded.raw_analysis,
                    html_report      = excluded.html_report,
                    sections_json    = excluded.sections_json,
                    result_json      = excluded.result_json,
                    annual_period    = excluded.annual_period,
                    quarterly_period = excluded.quarterly_period,
                    cost             = excluded.cost,
                    created_at       = excluded.created_at,
                    hit_count        = 0
            """, (
                key,
                result["company_name"],
                result["raw_analysis"],
                result["html_report"],
                sections_json,
                result_json,
                result.get("annual_period",    ""),
                result.get("quarterly_period", ""),
                result.get("cost", 0.0),
                now,
            ))

        logger.info(f"Кэш сохранён: '{result['company_name']}' (ключ: '{key}', mode: '{cache_mode}')")

    def invalidate(
        self,
        company: str,
        language: str | None = "ru",
        mode: str | None = "default",
    ) -> bool:
        """Удаляет запись из кэша. Возвращает True если запись была."""
        key = _cache_key(company, language, mode)
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_cache WHERE cache_key = ?", (key,)
            )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"Кэш сброшен для '{company}'")
        return deleted

    def list_all(self) -> list[dict]:
        """
        Возвращает все записи кэша (включая устаревшие).
        Отсортировано по дате — свежие первыми.
        """
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT cache_key, company_name, annual_period, quarterly_period,
                       cost, created_at, hit_count
                FROM analysis_cache
                ORDER BY created_at DESC
            """).fetchall()

        result = []
        for row in rows:
            age_secs  = now - row["created_at"]
            age_days  = int(age_secs // 86400)
            is_fresh  = age_secs <= self.ttl_secs
            expires   = max(0, int((self.ttl_secs - age_secs) // 86400))

            if age_days == 0:
                age_str = "сегодня"
            elif age_days == 1:
                age_str = "вчера"
            else:
                age_str = f"{age_days} дн. назад"

            result.append({
                "cache_key":       row["cache_key"],
                "company_name":    row["company_name"],
                "annual_period":   row["annual_period"],
                "quarterly_period":row["quarterly_period"],
                "cost":            row["cost"],
                "cached_at":       datetime.fromtimestamp(row["created_at"]),
                "age_days":        age_days,
                "age_str":         age_str,
                "is_fresh":        is_fresh,
                "expires_in_days": expires,
                "hit_count":       row["hit_count"],
            })

        return result

    def cleanup_expired(self) -> int:
        """Удаляет все устаревшие записи. Возвращает количество удалённых."""
        cutoff = time.time() - self.ttl_secs
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_cache WHERE created_at < ?", (cutoff,)
            )
        count = cursor.rowcount
        if count:
            logger.info(f"Кэш очистка: удалено {count} устаревших записей")
        return count

    def stats(self) -> dict:
        """Статистика кэша."""
        now = time.time()
        cutoff = now - self.ttl_secs
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM analysis_cache"
            ).fetchone()[0]
            fresh = conn.execute(
                "SELECT COUNT(*) FROM analysis_cache WHERE created_at >= ?", (cutoff,)
            ).fetchone()[0]
            total_hits = conn.execute(
                "SELECT COALESCE(SUM(hit_count), 0) FROM analysis_cache"
            ).fetchone()[0]
            total_cost = conn.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM analysis_cache"
            ).fetchone()[0]

        return {
            "total":       total,
            "fresh":       fresh,
            "expired":     total - fresh,
            "total_hits":  total_hits,
            "total_cost":  total_cost,
            "saved_cost":  total_hits * 0.15,  # примерная экономия за хиты
        }


# Глобальный экземпляр (импортируется в bot.py)
cache = AnalysisCache()
