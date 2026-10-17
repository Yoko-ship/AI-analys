# 04 — Journal, admin «Терминал», alerts

ТЗ tasks: T-13, T-14, T-15. This is the foundation: build it first (see
README, Order).

## R-L1 One event journal (T-13) — PARTIAL

- **Intent:** every event is written to one journal on the server. Users
  appear only as an internal id (no name, email or token). The journal is
  append-only. Retention: data and error events 12 months, user actions
  90 days.
- **Record fields:** time (UTC+5), event, level, ticker, standard, period,
  function, user id or «гость», response ms, error_id, human text, source
  document link.
- **Already there:** several narrow logs, each with its own schema:
  - `web_events` (`web_analytics.py:76-117`) for site visits. It is
    buffered and drops events on overflow, which is fine for analytics but
    not for a journal.
  - `web_admin_audit_log` (`web_analytics.py:121-144`) for admin actions.
  - `control_audit` (`admin_control/store.py:69-90`), already immutable via
    triggers.
  - `ingest_events` (`financial_ingestion/store.py:78`) and
    `catalog_company_import_events` (`catalogue/schema.py:86`).
  - 500 errors get an `error_id`, but only in the process log
    (`server/hardening.py:115-129`).
- **Gap:** no single journal; nothing persists errors; no retention.
- **Approach:** one new `terminal_events` table with the fields above and
  the **same append-only trigger pattern as `control_audit`**. Add a single
  `emit_event()` helper with a fixed event catalogue (below) that rejects
  unknown event names. It writes in a batch, without dropping events,
  following the Postgres round-trip lessons. Do not fold `web_events` into
  it: visits stay analytics. Retention is a daily purge by level class,
  which is the only permitted delete.

Event catalogue (from the ТЗ):

| Event | Level | Emitted by |
|---|---|---|
| cmd_run | Инфо | terminal (client beacon) |
| cmd_unknown | Инфо | terminal |
| screen_error | Критично | terminal on API error / 500, plus server 500 handler |
| screen_slow | Внимание | timing middleware, > 3 s |
| ai_limit | Инфо | `server/auth/limits.py` when a quota is hit |
| export | Инфо | terminal |
| load_ok / load_empty / load_duplicate | Инфо / Критично / Внимание | loaders (02 R-D1, R-D2) |
| value_quarantine | Критично | 02 R-D3 |
| year_backfill | Инфо | 02 R-D4 |
| restatement | Внимание | 02 R-D7 |
| ai_published / ai_blocked | Инфо / Внимание | AI publication path, publication holds |
| verdict_conflict | Критично | 03 R-A1 validator |
| ins_retention_jump / ins_reserves_missing / pb_high | Внимание / Критично / Внимание | 03 R-A8 |
| load_format_changed | Критично | CBU loaders (05) |
| formula_changed | Инфо | ADM template edits (03 R-A9); added by us, implied by the ТЗ |

T-13 acceptance: each event is reproduced once and visible in the admin.
Write a test per event.

## R-L2 Timing and error capture — PARTIAL

- **Already there:** the 500 handler with `error_id`; an in-memory trace
  buffer (`obs.py`, 512 entries) used only by two endpoints.
- **Gap:** no timing middleware.
- **Approach:** one ASGI middleware that measures every terminal-facing
  request and emits `screen_slow` / `screen_error`. The browser beacon
  covers what the server cannot see (render time, network failures).

## R-L3 Admin «Терминал» section (T-14) — PARTIAL

- **Intent:** 4 screens built only from the journal, so the PM can answer
  "what is broken today" without developers:
  1. A **coverage matrix**: issuers × 2020–2025 and quarters from 2022.
     Green = loaded, yellow = from the prior-year column, red = gap or
     quarantine. Clicking a cell opens its journal entries.
  2. **Errors**: Критично + Внимание, filtered by date, issuer and event,
     with an Excel export.
  3. **Usage**: top functions and issuers over 7/30 days, and the share of
     unknown commands.
  4. **Summary** with norms/alarms: annual coverage ≥ 95%, 0 new
     quarantined values, published AI analyses not falling, 0 verdict
     conflicts, < 1% screen errors per hour, < 5% slow screens (alarm at
     10%).
- **Already there:** the admin shell with tabs
  (`frontend/src/admin/adminModel.js:97-135`); «top tickers by views»
  (`EngagementSection.jsx:63`); `/api/coverage` per-ticker dataset flags
  (`server/catalog/routes.py:207`); NSBU load checkpoints per ticker × year
  × quarter (`financial_ingestion/nsbu_history.py:54-58`, no API); the
  `admin_control` collections `coverage` and `incidents`, which have **no
  frontend**.
- **Approach:** add one «Терминал» tab to the existing admin shell. The
  matrix reads checkpoints + journal; build its API on the existing
  `admin_control` coverage/incidents adapters rather than beside them.

## R-L4 Alerts (T-15) — MISSING

- **Intent:** a summary for the past 24 h every morning at 09:00 (email or
  Telegram); each new Критично event is sent immediately, at most once per
  hour per identical error. Acceptance: the digest arrives at 09:00 three
  days running.
- **Already there:** `email_delivery.py` (security mails only); `bot.py`
  (a user-facing Telegram bot). There is no admin channel.
- **Approach:** a small notifier that sends Telegram through the existing
  bot token to an admin chat id from settings, with email as the fallback.
  The throttle is keyed on (event, ticker, error_id) and stored in the DB,
  so it survives restarts. The digest runs from the production scheduler
  (prod is the VPS deployed by CI) at 09:00 Asia/Tashkent.
