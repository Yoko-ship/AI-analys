"""Catalogue schema bootstrap and compatibility migrations."""
from __future__ import annotations
import sqlite3

import dbx


def _init_schema(conn: sqlite3.Connection) -> None:

    conn.executescript("""

        CREATE TABLE IF NOT EXISTS catalog_companies (

            ticker          TEXT PRIMARY KEY,

            company_name    TEXT NOT NULL,

            org_id          TEXT,

            last_synced_at  TEXT,

            sync_error      TEXT

        );



        -- Admin-reviewed imports from the exchange/OpenInfo discovery path.

        -- ``catalog_companies`` remains the operational ticker -> org map used

        -- by the collectors; this companion table records whether a discovered

        -- security has been reviewed for the public product and preserves the

        -- source snapshot plus any explicit correction the reviewer made.

        CREATE TABLE IF NOT EXISTS catalog_company_imports (

            ticker          TEXT PRIMARY KEY,

            company_name    TEXT NOT NULL,

            org_id          TEXT,

            isin            TEXT,

            security_type   TEXT,

            share_type      TEXT,

            sector          TEXT NOT NULL DEFAULT 'other',

            logo_url        TEXT,

            resolved_by     TEXT,

            status          TEXT NOT NULL DEFAULT 'pending',

            catalog_visible INTEGER NOT NULL DEFAULT 1,

            source_payload  TEXT,

            review_note     TEXT,

            reviewed_by     TEXT,

            reviewed_at     TEXT,

            sync_status     TEXT,

            sync_error      TEXT,

            discovered_at   TEXT NOT NULL DEFAULT (datetime('now')),

            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))

        );

        CREATE INDEX IF NOT EXISTS idx_company_import_status

            ON catalog_company_imports(status, updated_at);



        CREATE TABLE IF NOT EXISTS catalog_company_import_events (

            id          INTEGER PRIMARY KEY AUTOINCREMENT,

            ticker      TEXT NOT NULL,

            action      TEXT NOT NULL,

            actor       TEXT,

            detail      TEXT,

            created_at  TEXT NOT NULL DEFAULT (datetime('now'))

        );

        CREATE INDEX IF NOT EXISTS idx_company_import_event_ticker

            ON catalog_company_import_events(ticker, created_at);



        -- What the catalog knows about itself. One row so far: when the last

        -- FULL sweep finished. That cannot be derived from the company stamps —

        -- the hourly pass refreshes a handful, so the newest is always minutes

        -- old, and the oldest belongs to a ticker the sweep skips on purpose.

        CREATE TABLE IF NOT EXISTS catalog_state (

            key        TEXT PRIMARY KEY,

            value      TEXT,

            updated_at TEXT

        );



        CREATE TABLE IF NOT EXISTS catalog_reports (

            id                  INTEGER PRIMARY KEY AUTOINCREMENT,

            ticker              TEXT NOT NULL,

            report_form         TEXT NOT NULL,

            period_type         TEXT NOT NULL,

            year                INTEGER,

            quarter             INTEGER NOT NULL DEFAULT 0,

            title               TEXT,

            published_at        TEXT,

            pdf_url             TEXT,

            excel_url           TEXT,

            excel_url_form1     TEXT,

            openinfo_report_id  TEXT,

            object_id           TEXT,

            synced_at           TEXT NOT NULL DEFAULT (datetime('now')),

            UNIQUE(ticker, report_form, period_type, year, quarter)

        );



        CREATE INDEX IF NOT EXISTS idx_cat_ticker ON catalog_reports(ticker);

        CREATE INDEX IF NOT EXISTS idx_cat_year   ON catalog_reports(year);



        CREATE TABLE IF NOT EXISTS catalog_new_reports (

            id          INTEGER PRIMARY KEY AUTOINCREMENT,

            ticker      TEXT NOT NULL,

            report_form TEXT NOT NULL,

            period_type TEXT NOT NULL,

            year        INTEGER,

            quarter     INTEGER NOT NULL DEFAULT 0,

            title       TEXT,

            detected_at TEXT NOT NULL DEFAULT (datetime('now'))

        );

        CREATE INDEX IF NOT EXISTS idx_cnr_ticker   ON catalog_new_reports(ticker);

        CREATE INDEX IF NOT EXISTS idx_cnr_detected ON catalog_new_reports(detected_at);



        CREATE TABLE IF NOT EXISTS catalog_ratios (

            ticker         TEXT NOT NULL,

            form           TEXT NOT NULL,

            year           INTEGER NOT NULL,

            quarter        INTEGER NOT NULL DEFAULT 0,

            roa            REAL,

            roe            REAL,

            net_margin     REAL,

            debt_ratio     REAL,

            debt_to_equity REAL,

            updated_at     TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (ticker, form, year, quarter)

        );



        CREATE TABLE IF NOT EXISTS catalog_financials (

            ticker            TEXT NOT NULL,

            form              TEXT NOT NULL DEFAULT 'NSBU',

            year              INTEGER NOT NULL,

            quarter           INTEGER NOT NULL DEFAULT 0,

            revenue           REAL,

            gross_profit      REAL,

            cash              REAL,

            total_liabilities REAL,

            net_income        REAL,

            operating_income  REAL,

            operating_expenses REAL,

            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (ticker, form, year, quarter)

        );

        CREATE INDEX IF NOT EXISTS idx_cat_fin_ticker ON catalog_financials(ticker);



        CREATE TABLE IF NOT EXISTS catalog_trade_stats (

            isin              TEXT PRIMARY KEY,

            trade_date        TEXT,

            total_value       REAL,

            total_qty         REAL,

            trade_count       INTEGER,

            avg_price         REAL,

            largest_qty       REAL,

            largest_value     REAL,

            largest_pct_value REAL,

            largest_pct_qty   REAL,

            open_price        REAL,

            high_price        REAL,

            low_price         REAL,

            close_price       REAL,

            -- Negotiated (пакетные) deals of the day, kept OUT of every session

            -- number above: their price never stood in the order book, so it

            -- may not move a candle or a turnover column (HMKB 14.08.2026 —

            -- 2,2 млрд бумаг по 55,00 при рынке 95,5–99,99).

            block_count       INTEGER,

            block_qty         REAL,

            block_value       REAL,

            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))

        );



        -- The exchange's own session quote per security (uzse.uz/isu_infos):

        -- the official close, the previous close it is measured against (which

        -- the exchange CARRIES FORWARD through sessions with no trades, so no

        -- feed of executions can reproduce it) and the session's own totals.

        -- This is what makes the board's change % the exchange's change %, for

        -- every listed security rather than the 78 the /stocks mirror carries.

        CREATE TABLE IF NOT EXISTS catalog_quotes (

            isin               TEXT PRIMARY KEY,

            ticker             TEXT,

            name               TEXT,

            market             TEXT,

            share_type         TEXT,

            trade_date         TEXT,

            close_price        REAL,

            prev_close         REAL,

            prev_close_date    TEXT,

            change_value       REAL,

            change_percent     REAL,

            open_price         REAL,

            high_price         REAL,

            low_price          REAL,

            quantity           REAL,

            turnover           REAL,

            shares_outstanding REAL,

            market_cap         REAL,

            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))

        );



        -- One row per security per SESSION — the exchange's settled daily record.

        --

        -- catalog_quotes above keeps only the latest session, so a series existed

        -- nowhere we could reach: drawing a sparkline meant one live request to

        -- openinfo per ticker, which is why lists of securities had no chart on

        -- them at all. The data was never missing, only discarded — uzse.uz's

        -- quote page publishes its last ~21 settled sessions in a table the

        -- collector already parses and threw away after reading one row from it.

        --

        -- Carried-forward sessions belong here: the exchange repeats a close at

        -- zero quantity when nothing traded, and a flat line IS what the security

        -- did that day. Dropping them would compress calendar time and make a

        -- quiet month look like an active week.

        --

        -- The session-DETAIL columns (open/high/low, the trade count and the

        -- largest deal) exist so a period can be summarised the way a session

        -- is: «за месяц» has an opening price, a high, a low, an average deal

        -- and a biggest deal exactly as one day does, and none of it could be

        -- answered while the table held closes alone. They are nullable and

        -- filled by whichever source can: the day statistics for the sessions

        -- the collector has seen, openinfo's conclusions archive for OHLC

        -- before that, and the date-filtered trade feed for the rest.

        CREATE TABLE IF NOT EXISTS catalog_quote_history (

            isin         TEXT NOT NULL,

            trade_date   TEXT NOT NULL,

            close_price  REAL,

            change_value REAL,

            quantity     REAL,

            turnover     REAL,

            open_price   REAL,

            high_price   REAL,

            low_price    REAL,

            trade_count  REAL,

            largest_value REAL,

            largest_qty  REAL,

            updated_at   TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (isin, trade_date)

        );

        CREATE INDEX IF NOT EXISTS idx_quote_history_isin

            ON catalog_quote_history (isin, trade_date);



        -- One row per security per HOUR of a session, rolled up from the

        -- executions log on the uzse.uz quote page ("Время | Цена | ... "). The

        -- exchange publishes that log only while the page still shows the

        -- session — there is no archive of it — so the hourly series exists

        -- exactly as long as the collector keeps storing it here. This is what

        -- the 1Д/1Н chart draws; daily closes stay in catalog_quote_history.

        CREATE TABLE IF NOT EXISTS catalog_intraday_history (

            isin        TEXT NOT NULL,

            trade_date  TEXT NOT NULL,

            hour        INTEGER NOT NULL,

            open_price  REAL,

            high_price  REAL,

            low_price   REAL,

            close_price REAL,

            quantity    REAL,

            turnover    REAL,

            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (isin, trade_date, hour)

        );



        -- Exchange-listing registry for issuers that are listed on RFB Tashkent

        -- (openinfo info_rfb.isin_codes) but absent from the live uzse-stock feed

        -- because they have not traded recently. Carries the last-known trade

        -- (from /iuzse/conclusions/) plus shares outstanding so these securities

        -- can still appear on the market board / company page, tagged inactive.

        CREATE TABLE IF NOT EXISTS catalog_listings (

            ticker             TEXT PRIMARY KEY,

            isin               TEXT,

            name               TEXT,

            share_type         TEXT,

            listing_date       TEXT,

            shares_outstanding REAL,

            nominal            REAL,

            reference_price    REAL,

            last_price         REAL,

            last_trade_date    TEXT,

            open_price         REAL,

            high_price         REAL,

            low_price          REAL,

            volume             REAL,

            market_cap         REAL,

            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))

        );



        -- openinfo's dividend calendar, mapped onto our tickers (see dividends.py).

        -- The source publishes one market-wide calendar keyed by organization_id

        -- and carries our ticker on barely half its rows, so the mapping is done

        -- once at snapshot time and stored — a company page then reads an indexed

        -- table instead of asking openinfo to resolve "UNVB" as a company name,

        -- which is what used to answer «Дивиденды не объявлялись» for every issuer.

        -- One row per (security, filing): ordinary and preferred lines each get a

        -- copy, because the filing declares both amounts and the page shows the

        -- column that matches the security.

        CREATE TABLE IF NOT EXISTS catalog_dividends (

            ticker            TEXT NOT NULL,

            filing_id         TEXT NOT NULL,

            org_id            TEXT,

            organization      TEXT,

            decision_date     TEXT,

            pub_date          TEXT,

            ordinary_amount   REAL,

            ordinary_percent  REAL,

            ordinary_start    TEXT,

            ordinary_end      TEXT,

            preferred_amount  REAL,

            preferred_percent REAL,

            preferred_start   TEXT,

            preferred_end     TEXT,

            link              TEXT,

            matched_by        TEXT,

            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (ticker, filing_id)

        );

        CREATE INDEX IF NOT EXISTS idx_cat_div_ticker ON catalog_dividends(ticker);



        -- openinfo's shareholder-meeting announcement calendar (see meetings.py).

        -- A rolling window of notices, keyed by the MEETING date — the one feed

        -- that announces a corporate event before it happens. One row per

        -- announcement; ticker is filled where the issuer is a security we list

        -- and stays NULL otherwise, because the market calendar shows every

        -- issuer that filed a notice.

        CREATE TABLE IF NOT EXISTS catalog_meetings (

            announcement_id TEXT PRIMARY KEY,

            org_id          TEXT,

            organization    TEXT,

            ticker          TEXT,

            title           TEXT,

            meeting_date    TEXT,

            pub_date        TEXT,

            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))

        );

        CREATE INDEX IF NOT EXISTS idx_cat_meet_date ON catalog_meetings(meeting_date);



        -- Generic, forward-compatible fact store (scalable-pipeline design).

        -- Any source (adapter) can land any (entity, dataset, field, period) value

        -- without a schema change, so new datasets/fields published in the future

        -- flow in automatically. entity_id is the openinfo org_id (issuer).

        CREATE TABLE IF NOT EXISTS facts (

            entity_id   TEXT NOT NULL,

            dataset     TEXT NOT NULL,

            field       TEXT NOT NULL,

            period      TEXT NOT NULL DEFAULT '',

            value_num   REAL,

            value_text  TEXT,

            unit        TEXT,

            source      TEXT NOT NULL,

            source_url  TEXT,

            fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),

            PRIMARY KEY (entity_id, dataset, field, period, source)

        );

        CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id, dataset);



        -- §3.11 editorial-news store. We keep only headline + our own LLM-authored

        -- summary + link + metadata — never the source's full article body — which

        -- keeps aggregation inside Uzbek copyright's news-of-the-day / press-review

        -- allowances (see NEWS_MODULE.md). Populated by the news collector (push) /

        -- the search agent; read by GET /api/news/feed and the risk-profile info dim.

        CREATE TABLE IF NOT EXISTS news (

            id              INTEGER PRIMARY KEY AUTOINCREMENT,

            url             TEXT NOT NULL UNIQUE,

            source          TEXT NOT NULL,

            source_id       TEXT,

            lang            TEXT,

            title           TEXT NOT NULL,

            snippet         TEXT,

            summary_ru      TEXT,

            image_url       TEXT,

            published_at    TEXT,

            collected_at    TEXT NOT NULL DEFAULT (datetime('now')),

            coverage_weight REAL NOT NULL DEFAULT 0.5

        );

        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);

        CREATE INDEX IF NOT EXISTS idx_news_source    ON news(source_id);



        -- Per-item NLP output (one row per news item). Every value is a statistical/

        -- analytical signal, not a diagnosis (TZ §3.11): 'direction' is a model

        -- estimate the UI must present with a disclaimer.

        CREATE TABLE IF NOT EXISTS news_nlp (

            news_id         INTEGER PRIMARY KEY REFERENCES news(id) ON DELETE CASCADE,

            relevant        INTEGER NOT NULL DEFAULT 0,

            relevance_score REAL,

            type            TEXT,

            tone            TEXT,

            tone_score      REAL,

            impact          TEXT,

            direction       TEXT,

            sectors_json    TEXT,

            reason          TEXT,

            model           TEXT,

            classified_at   TEXT NOT NULL DEFAULT (datetime('now'))

        );



        -- News ↔ issuer links (a news item may touch several tickers).

        CREATE TABLE IF NOT EXISTS news_entities (

            news_id  INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,

            ticker   TEXT NOT NULL,

            PRIMARY KEY (news_id, ticker)

        );

        CREATE INDEX IF NOT EXISTS idx_news_ent_ticker ON news_entities(ticker);



        -- One row per collector invocation. Token counts measure the news job

        -- exactly; the before/after percentage is the account's own rolling

        -- Codex limit reading, not an estimate derived from tokens.

        CREATE TABLE IF NOT EXISTS news_usage_runs (

            id                    INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id                TEXT NOT NULL UNIQUE,

            mode                  TEXT NOT NULL,

            started_at            TEXT NOT NULL,

            finished_at           TEXT NOT NULL,

            model                 TEXT,

            calls                 INTEGER NOT NULL DEFAULT 0,

            prompt_tokens         INTEGER NOT NULL DEFAULT 0,

            completion_tokens     INTEGER NOT NULL DEFAULT 0,

            cached_input_tokens   INTEGER NOT NULL DEFAULT 0,

            total_tokens          INTEGER NOT NULL DEFAULT 0,

            subscription_tokens   INTEGER NOT NULL DEFAULT 0,

            codex_before_pct      REAL,

            codex_after_pct       REAL,

            codex_delta_pct       REAL,

            codex_resets_at       INTEGER,

            fetched               INTEGER,

            classified            INTEGER,

            relevant              INTEGER,

            pushed                INTEGER,

            status                TEXT NOT NULL DEFAULT 'completed'

        );

        CREATE INDEX IF NOT EXISTS idx_news_usage_finished

            ON news_usage_runs(finished_at);

    """)

    # Columns added after the table shipped (CREATE IF NOT EXISTS won't touch

    # an existing table) — idempotent per-column migration.

    have_imports = set(dbx.columns(conn, "catalog_company_imports"))

    if "catalog_visible" not in have_imports:

        conn.execute(

            "ALTER TABLE catalog_company_imports ADD COLUMN catalog_visible INTEGER NOT NULL DEFAULT 1"

        )

    have = set(dbx.columns(conn, "catalog_trade_stats"))

    for col in ("open_price", "high_price", "low_price", "close_price"):

        if col not in have:

            conn.execute(f"ALTER TABLE catalog_trade_stats ADD COLUMN {col} REAL")

    have_imports = set(dbx.columns(conn, "catalog_company_imports"))

    if "catalog_visible" not in have_imports:

        conn.execute(

            "ALTER TABLE catalog_company_imports "

            "ADD COLUMN catalog_visible INTEGER NOT NULL DEFAULT 1"

        )

    have_hist = set(dbx.columns(conn, "catalog_quote_history"))

    for col in ("open_price", "high_price", "low_price", "trade_count",

                "largest_value", "largest_qty"):

        if col not in have_hist:

            conn.execute(f"ALTER TABLE catalog_quote_history ADD COLUMN {col} REAL")

    # The dividend calendar's bond line (coupon payouts). Shipped after the

    # table: the market «Календарь» offers the same Простые/Привилегированные/

    # Облигации split openinfo's own table has, and the bond columns were the

    # one line normalize_row used to drop.

    have_div = set(dbx.columns(conn, "catalog_dividends"))

    for col, typ in (("bond_amount", "REAL"), ("bond_percent", "REAL"),

                     ("bond_start", "TEXT"), ("bond_end", "TEXT")):

        if col not in have_div:

            conn.execute(f"ALTER TABLE catalog_dividends ADD COLUMN {col} {typ}")

    have_news = set(dbx.columns(conn, "news"))

    if "image_url" not in have_news:

        conn.execute("ALTER TABLE news ADD COLUMN image_url TEXT")

    # The site is served in three languages but every summary we stored was Russian, so an

    # English or Uzbek reader got a Russian feed. The classifier writes all three in the one

    # call it already makes (see news_classifier._SYSTEM) — there is no cheaper source:

    # verified 2026-07-29 against real Chrome, its on-device translator has no Uzbek at all

    # (ru->uz, uz->ru and en->uz all report "unavailable"), so the browser can never serve

    # the Uzbek feed. Nullable: rows collected before this exist and are backfilled by

    # `news_collector.py --backfill-translations`.

    for col in ("summary_en", "summary_uz"):

        if col not in have_news:

            conn.execute(f"ALTER TABLE news ADD COLUMN {col} TEXT")

    # The story page's long read: OUR OWN multi-paragraph account of what the source

    # published, in the three UI languages. It exists because a feed teaser is one sentence

    # while the article behind it is five paragraphs, and a reader who opened the story got

    # the sentence. This is still not the source's text — the article is read once, in

    # memory, to write our own summary, and is never stored (see NEWS_MODULE.md's legal

    # invariant). Nullable: rows collected before it exist, and sources with no article page

    # (the rating agencies, openinfo filings) never get one.

    for col in ("detail_ru", "detail_en", "detail_uz"):

        if col not in have_news:

            conn.execute(f"ALTER TABLE news ADD COLUMN {col} TEXT")

    # Per-field period provenance (JSON {field: period}). A financials row is

    # labelled with ONE period, but a few fields can only be sourced from a

    # different one (bank revenue exists in openinfo's indicators and nowhere in

    # the NSBU form). Recording which period each such field came from is what

    # keeps the row honest instead of passing a full-year figure off as a quarter.

    have_fin = set(dbx.columns(conn, "catalog_financials"))

    if "field_periods" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN field_periods TEXT")

    # ТЗ Дополнение 1 §Б.4: a published figure names the report it was read from.

    # Until this column was filled, "where did this revenue come from?" had no

    # answer — nobody could say which filing, which form or which period, or

    # whether the number was parsed at all rather than taken off the wrong field.

    # That is the gap the whole FIN group of defects grew out of.

    if "report_id" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN report_id INTEGER")

    # The comparative period the same filing prints beside its own figures (NSBU

    # form 2's value1/value2, "за соответствующий период прошлого года" — the

    # reporting period is value3/value4, see openinfo_reconcile.pl_value), as

    # JSON with its own period label. It rides on the row it was filed with

    # rather than becoming a period of its own — the comparative is P&L only, and

    # a row with no balance sheet would be ranked as a period and divide ratios

    # by nothing.

    if "prior_period" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN prior_period TEXT")

    # ТЗ мультипликаторов (2026-08-10). Three additions that let the market tab

    # compute what it used to borrow from the indicator feed:

    #   noninterest_income — «е. Итого беспроцентных доходов» (banks): the second

    #     half of the net-margin denominator, interest + non-interest income;

    #   org_type — jsc/bank/insurance/microfinance, the FORM the figures were

    #     read from. P/S is not shown for banks and insurers, margin carries the

    #     bank footnote — the display rules need the form, not a sector guess;

    #   balance_period — JSON {equity_start, equity_end, assets_start,

    #     assets_end} in thousands, from the SAME filing: P/B's denominator and

    #     the averaged base ROE/ROA divide by.

    if "noninterest_income" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN noninterest_income REAL")

    if "org_type" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN org_type TEXT")

    if "balance_period" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN balance_period TEXT")

    # The quarterly Баланс sub-tab shows the same three lines as the annual one —

    # Активы, Обязательства, Капитал (customer, 2026-08-16) — but the cache never

    # kept the two balance totals the parse already extracts. Nullable: history

    # fills from the quarterly re-backfill, and a row pushed with a filed balance

    # block falls back to balance_period's assets_end/equity_end at read time.

    if "total_assets" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN total_assets REAL")

    if "total_equity" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN total_equity REAL")

    if "operating_expenses" not in have_fin:

        conn.execute("ALTER TABLE catalog_financials ADD COLUMN operating_expenses REAL")

    # The current section of the balance — «Итого по разделу II» of the asset

    # side, «Текущие обязательства, всего» and «Товарно-материальные запасы».

    # The indicator feed publishes liquidity, asset turnover and ROCE for barely

    # half the board (56, 56 and 64 of 95 on 2026-08-17) while every one of those

    # issuers files the lines they are computed from, so the columns were empty

    # for the rest. These three make them derivable.

    for column in ("current_assets", "current_liabilities", "inventories"):

        if column not in have_fin:

            conn.execute(f"ALTER TABLE catalog_financials ADD COLUMN {column} REAL")

    for column in ("interest_income", "interest_expense"):

        if column not in have_fin:

            conn.execute(f"ALTER TABLE catalog_financials ADD COLUMN {column} REAL")

    # «Номинальная стоимость» of the security, as the exchange's own card states

    # it (`parval`). Every listed line has one and no page showed it.

    if "nominal" not in set(dbx.columns(conn, "catalog_listings")):

        conn.execute("ALTER TABLE catalog_listings ADD COLUMN nominal REAL")

    conn.commit()
