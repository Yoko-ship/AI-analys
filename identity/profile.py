"""Profile persistence and behavior behind an explicit database boundary."""
from __future__ import annotations
from typing import Any
import identity.clock as identity_clock
import identity.research as identity_research
import identity.settings as identity_settings
import identity.users as identity_users
import json


class Profile:
    def __init__(self, database, notes, sessions):
        self.database = database
        self.notes = notes
        self.sessions = sessions

    def update_profile(
        self,
        user_id: int,
        full_name: str | None = None,
        avatar_data_url: str | None = None,
        *,
        set_full_name: bool = False,
        set_avatar: bool = False,
    ) -> identity_users.WebUser:
        updates: list[str] = []
        params: list[Any] = []

        if set_full_name:
            normalized_name = (full_name or "").strip()
            if not normalized_name:
                raise ValueError("Full name cannot be empty")
            updates.append("full_name = %s")
            params.append(normalized_name)

        if set_avatar:
            normalized_avatar = identity_users.normalize_avatar_data_url(avatar_data_url)
            updates.append("avatar_data_url = %s")
            params.append(normalized_avatar)

        if not updates:
            with self.database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                    FROM web_users
                    WHERE id = %s
                    """,
                    (user_id,),
                ).fetchone()
            if not row:
                raise ValueError("User not found")
            return identity_users.row_to_user(row)

        params.append(user_id)
        with self.database.connect() as conn:
            row = conn.execute(
                f"""
                UPDATE web_users
                SET {", ".join(updates)}
                WHERE id = %s
                RETURNING id, email, full_name, avatar_data_url, created_at, last_login_at, is_active, email_verified, tier, subscription_until
                """,
                params,
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return identity_users.row_to_user(row)


    def update_preferences(self, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = set(identity_settings.DEFAULT_PROFILE_PREFERENCES)
        clean = {key: value for key, value in (updates or {}).items() if key in allowed and value is not None}
        if clean.get("language") not in (None, "ru", "en", "uz"):
            raise ValueError("Unsupported language")
        if clean.get("theme") not in (None, "light", "dark"):
            raise ValueError("Unsupported theme")
        if "text_scale" in clean:
            clean["text_scale"] = max(80, min(130, int(clean["text_scale"])))
        if "timezone" in clean:
            clean["timezone"] = str(clean["timezone"]).strip()[:80] or "Asia/Tashkent"
        if "default_analysis_period" in clean and clean["default_analysis_period"] not in ("latest", "quarterly", "annual"):
            raise ValueError("Unsupported analysis period")
        if "pattern_alert_types" in clean:
            import pattern_engine
            known = set(pattern_engine.CHART_TYPES) | set(pattern_engine.CANDLE_TYPES)
            types = clean["pattern_alert_types"]
            if not isinstance(types, list) or any(t not in known for t in types):
                raise ValueError("Unsupported pattern type")
            clean["pattern_alert_types"] = sorted(set(types))
        with self.database.connect() as conn:
            row = conn.execute(
                """
                UPDATE web_users
                SET preferences = COALESCE(preferences, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                RETURNING preferences
                """,
                (json.dumps(clean), user_id),
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return {**identity_settings.DEFAULT_PROFILE_PREFERENCES, **dict(row.get("preferences") or {})}


    def get_preferences(self, user_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute("SELECT preferences FROM web_users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise ValueError("User not found")
        return {**identity_settings.DEFAULT_PROFILE_PREFERENCES, **dict(row.get("preferences") or {})}


    def get_profile(self, user_id: int, recent_limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(recent_limit or 50), 100))
        with self.database.connect() as conn:
            user_row = conn.execute(
                """
                SELECT id, email, full_name, avatar_data_url, created_at, last_login_at,
                       is_active, email_verified, tier, subscription_until, preferences, two_factor_enabled,
                       password_changed_at
                FROM web_users
                WHERE id = %s
                """,
                (user_id,),
            ).fetchone()
            if not user_row:
                raise ValueError("User not found")

            stats_row = conn.execute(
                """
                SELECT
                    COUNT(*)::BIGINT AS total_analyses,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')::BIGINT AS analyses_7d,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')::BIGINT AS analyses_30d,
                    COUNT(*) FILTER (WHERE from_cache)::BIGINT AS cached_analyses,
                    COUNT(DISTINCT ticker) FILTER (WHERE ticker IS NOT NULL AND ticker <> '')::BIGINT AS analyzed_companies,
                    AVG(score)::NUMERIC(10, 2) AS avg_score,
                    MAX(score)::NUMERIC(10, 2) AS best_score,
                    MIN(created_at) AS first_analysis_at,
                    MAX(created_at) AS last_analysis_at
                FROM web_analysis_history
                WHERE user_id = %s
                """,
                (user_id,),
            ).fetchone()

            favorites_rows = conn.execute(
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

            top_row = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(company_name, ''), company_input) AS company_label,
                    COUNT(*)::BIGINT AS analysis_count
                FROM web_analysis_history
                WHERE user_id = %s
                GROUP BY 1
                ORDER BY analysis_count DESC, MAX(created_at) DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            recent_rows = conn.execute(
                """
                SELECT
                    id,
                    company_input,
                    company_name,
                    ticker,
                    title,
                    score,
                    grade,
                    verdict,
                    summary_text,
                    from_cache,
                    model,
                    cost,
                    archived,
                    bookmarked,
                    folder,
                    tags,
                    pinned_note,
                    created_at
                FROM web_analysis_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()

        stats = {
            "total_analyses": int(stats_row["total_analyses"] or 0),
            "analyses_7d": int(stats_row["analyses_7d"] or 0),
            "analyses_30d": int(stats_row["analyses_30d"] or 0),
            "cached_analyses": int(stats_row["cached_analyses"] or 0),
            "analyzed_companies": int(stats_row["analyzed_companies"] or 0),
            "avg_score": float(stats_row["avg_score"]) if stats_row["avg_score"] is not None else None,
            "best_score": float(stats_row["best_score"]) if stats_row["best_score"] is not None else None,
            "first_analysis_at": stats_row["first_analysis_at"].isoformat() if stats_row["first_analysis_at"] else None,
            "last_analysis_at": stats_row["last_analysis_at"].isoformat() if stats_row["last_analysis_at"] else None,
            "top_company": top_row["company_label"] if top_row else None,
            "top_company_count": int(top_row["analysis_count"] or 0) if top_row else 0,
        }

        favorites = [
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
            for row in favorites_rows
        ]

        recent_analyses = [identity_research.analysis_row(row) for row in recent_rows]
        preferences = {**identity_settings.DEFAULT_PROFILE_PREFERENCES, **dict(user_row.get("preferences") or {})}
        security = {
            "email_verified": bool(user_row.get("email_verified")),
            "two_factor_enabled": bool(user_row.get("two_factor_enabled")),
            "password_changed_at": user_row["password_changed_at"].isoformat() if user_row.get("password_changed_at") else None,
        }

        return {
            "user": identity_users.row_to_user(user_row).to_public_dict(),
            "stats": stats,
            "favorites": favorites,
            "recent_analyses": recent_analyses,
            "notes": self.notes.list_notes(user_id),
            "preferences": preferences,
            "security": security,
        }


    def export_user_data(self, user_id: int, current_token: str | None = None) -> dict[str, Any]:
        profile = self.get_profile(user_id, recent_limit=100)
        return {
            "exported_at": identity_clock._utcnow().isoformat(),
            **profile,
            "sessions": self.sessions.list_sessions(user_id, current_token),
            "notes": self.notes.list_notes(user_id),
        }


    def delete_account(self, user_id: int, confirmation: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT email FROM web_users WHERE id = %s", (user_id,)).fetchone()
            if not row:
                raise ValueError("User not found")
            if (confirmation or "").strip().lower() != str(row["email"]).strip().lower():
                raise ValueError("Enter your email address to confirm account deletion")
            cursor = conn.execute("DELETE FROM web_users WHERE id = %s", (user_id,))
        return cursor.rowcount > 0
