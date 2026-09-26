"""Initialize the existing PostgreSQL account schema."""
from __future__ import annotations



def initialize(connection_factory) -> None:
    with connection_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_users (
                id              BIGSERIAL PRIMARY KEY,
                email           TEXT NOT NULL UNIQUE,
                full_name       TEXT NOT NULL DEFAULT '',
                avatar_data_url TEXT,
                password_hash   TEXT NOT NULL,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                tier            TEXT NOT NULL DEFAULT 'free',
                subscription_until TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at   TIMESTAMPTZ
            )
            """
        )
        conn.execute(
            """
            ALTER TABLE web_users
            ADD COLUMN IF NOT EXISTS avatar_data_url TEXT
            """
        )
        for statement in (
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS two_factor_secret TEXT",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'free'",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS subscription_until TIMESTAMPTZ",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS failed_login_started TIMESTAMPTZ",
            "ALTER TABLE web_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
        ):
            conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_sessions (
                id           BIGSERIAL PRIMARY KEY,
                user_id      BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                token_hash   TEXT NOT NULL UNIQUE,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at   TIMESTAMPTZ NOT NULL,
                revoked_at   TIMESTAMPTZ
            )
            """
        )
        for statement in (
            "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS user_agent TEXT",
            "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS ip_address TEXT",
            "ALTER TABLE web_sessions ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
        ):
            conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_oauth_accounts (
                id                  BIGSERIAL PRIMARY KEY,
                user_id             BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                provider            TEXT NOT NULL,
                provider_user_id    TEXT NOT NULL,
                provider_email      TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(provider, provider_user_id),
                UNIQUE(user_id, provider)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_analysis_history (
                id              BIGSERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                company_input   TEXT NOT NULL,
                company_name    TEXT,
                ticker          TEXT,
                score           NUMERIC,
                grade           TEXT,
                verdict         TEXT,
                summary_text    TEXT,
                from_cache      BOOLEAN NOT NULL DEFAULT FALSE,
                model           TEXT,
                cost            NUMERIC,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS title TEXT",
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS bookmarked BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS folder TEXT",
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb",
            "ALTER TABLE web_analysis_history ADD COLUMN IF NOT EXISTS pinned_note TEXT",
        ):
            conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_favorite_companies (
                id              BIGSERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                ticker          TEXT NOT NULL,
                company_name    TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, ticker)
            )
            """
        )
        for statement in (
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_above NUMERIC",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS price_alert_below NUMERIC",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS news_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS report_alert_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE web_favorite_companies ADD COLUMN IF NOT EXISTS pattern_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        ):
            conn.execute(statement)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_saved_notes (
                id          BIGSERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                analysis_id BIGINT REFERENCES web_analysis_history(id) ON DELETE SET NULL,
                title       TEXT NOT NULL DEFAULT '',
                body        TEXT NOT NULL DEFAULT '',
                pinned      BOOLEAN NOT NULL DEFAULT FALSE,
                tags        JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_notification_state (
                user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                notification_id TEXT NOT NULL,
                read_at         TIMESTAMPTZ,
                dismissed_at    TIMESTAMPTZ,
                PRIMARY KEY (user_id, notification_id)
            )
            """
        )
        # A portfolio is deliberately separate from a watchlist.  A saved
        # ticker is a research preference; a position has quantities and a
        # user-entered cost basis, so conflating the two would manufacture
        # holdings for every favourite.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_portfolio_positions (
                id              BIGSERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                ticker          TEXT NOT NULL,
                quantity        NUMERIC NOT NULL CHECK (quantity > 0),
                average_cost    NUMERIC NOT NULL CHECK (average_cost >= 0),
                currency        TEXT NOT NULL DEFAULT 'UZS',
                note            TEXT NOT NULL DEFAULT '',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, ticker)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_support_requests (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                subject    TEXT NOT NULL,
                message    TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_sessions_user_id
            ON web_sessions(user_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_sessions_expires_at
            ON web_sessions(expires_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_oauth_accounts_user_id
            ON web_oauth_accounts(user_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_analysis_history_user_created_at
            ON web_analysis_history(user_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_analysis_history_user_company
            ON web_analysis_history(user_id, company_input)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_favorites_user_created_at
            ON web_favorite_companies(user_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_favorites_user_ticker
            ON web_favorite_companies(user_id, ticker)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_saved_notes_user_updated
            ON web_saved_notes(user_id, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_portfolio_positions_user_updated
            ON web_portfolio_positions(user_id, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_support_user_created
            ON web_support_requests(user_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_web_support_status_created
            ON web_support_requests(status, created_at DESC)
            """
        )
        # Only the salted hash of a code is stored.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_email_codes (
                user_id                BIGINT NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
                purpose                TEXT NOT NULL,
                salt                   TEXT NOT NULL,
                code_hash              TEXT NOT NULL,
                attempts               INTEGER NOT NULL DEFAULT 0,
                expires_at             TIMESTAMPTZ NOT NULL,
                sent_at                TIMESTAMPTZ NOT NULL,
                send_count             INTEGER NOT NULL DEFAULT 1,
                window_started_at      TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (user_id, purpose)
            )
            """
        )
