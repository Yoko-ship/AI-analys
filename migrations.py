"""migrations.py — versioned, ordered, recorded schema changes (ТЗ §10.1/§10.10).

The project has been changing its schema with ``CREATE TABLE IF NOT EXISTS`` and
a hand-written ``ALTER TABLE`` guarded by ``PRAGMA table_info``. That works right
up until it doesn't: nothing records what has been applied, so nobody can say
which shape a given deployment is in, a change cannot be ordered against another,
and there is no way to fail a deploy whose database is behind the code.

This is the smallest thing that fixes that and stays honest about the stack we
are actually on. Each migration has a version, a name and a forward step; the
applied ones are recorded in ``schema_migrations`` with when and how long they
took; running twice is a no-op. ТЗ names Alembic because it names PostgreSQL —
the guarantees asked for are ordering, idempotence and a record, and those are
what this provides on the database the project runs on today.

Migrations must be additive. A column is added, never dropped; a table is
created, never renamed in place. Deployment is not atomic — the old code runs
against the new schema for the length of a rollout — so a destructive step turns
a routine deploy into an outage.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

Step = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Step


def _columns(conn: Any, table: str) -> set[str]:
    """Portable column list — PRAGMA would tie migrations to SQLite."""
    import dbx

    try:
        return set(dbx.columns(conn, table))
    except Exception as exc:  # an ABSENT TABLE has no columns; anything else is a fault
        if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
            return set()
        raise


def add_column(table: str, column: str, ddl: str) -> Step:
    """An additive column, applied only when it is absent.

    Idempotent by inspection rather than by catching an error, so a genuine
    failure is still a failure.
    """
    def step(conn: sqlite3.Connection) -> None:
        if column not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return step


def columns(table: str, *cols: tuple[str, str]) -> Step:
    """Several additive columns on one table, each applied only when absent."""
    steps = [add_column(table, name, ddl) for name, ddl in cols]

    def step(conn: sqlite3.Connection) -> None:
        for one in steps:
            one(conn)
    return step


def run_sql(*statements: str) -> Step:
    def step(conn: sqlite3.Connection) -> None:
        for statement in statements:
            conn.execute(statement)
    return step


# ---------------------------------------------------------------------------
# The register. Append only; never renumber, never edit an applied migration —
# a deployment that already ran version 3 will not run it again, so changing it
# means two environments hold different shapes under the same version number.
# ---------------------------------------------------------------------------

MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "financials: field_periods",
              add_column("catalog_financials", "field_periods", "TEXT")),
    Migration(2, "financials: report_id — every figure names its filing",
              add_column("catalog_financials", "report_id", "INTEGER")),
    Migration(3, "audit: rule/run/finding registry",
              run_sql(
                  "CREATE INDEX IF NOT EXISTS ix_findings_rule "
                  "ON audit_findings (rule_code, status)")),
    Migration(4, "provenance: report state index",
              run_sql(
                  "CREATE INDEX IF NOT EXISTS ix_reports_org "
                  "ON source_reports (org_id, period_year DESC)")),
    Migration(5, "bonds: reference lookup by isin",
              run_sql(
                  "CREATE INDEX IF NOT EXISTS ix_bond_reference_isin "
                  "ON bond_reference (isin)")),
    # The issuer files what a coupon PAYS and when payment opens; it does not
    # file the accrual period the payment covers. The original NOT NULL demanded
    # two dates that no source states, which would have meant inventing them.
    # The table has never held a row — nothing wrote to it before the terms
    # loader — so it is rebuilt rather than migrated in place.
    Migration(6, "bonds: coupon periods are nullable — only the payment is filed",
              run_sql(
                  "DROP TABLE IF EXISTS bond_coupons",
                  """CREATE TABLE bond_coupons (
                       ticker      TEXT NOT NULL REFERENCES bond_reference(ticker),
                       coupon_no   INTEGER NOT NULL,
                       period_from TEXT, period_to TEXT,
                       pay_date    TEXT NOT NULL,
                       amount      REAL,
                       is_paid     INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (ticker, coupon_no)
                     )""")),
    # ТЗ мультипликаторов (внешний аудит 2026-08-10): the market tab computes
    # its own denominators from the filings. balance_period carries the filed
    # equity/assets at start and end of the period (JSON, thousands);
    # noninterest_income completes a bank's total income; org_type records
    # which NSBU form the row was read from, because the display rules differ
    # by form (no P/S for banks and insurers, the bank margin footnote).
    Migration(7, "financials: filed balance, bank total income, form type",
              columns("catalog_financials",
                      ("noninterest_income", "REAL"),
                      ("org_type", "TEXT"),
                      ("balance_period", "TEXT"))),
    # ГЦБ primary market (cbu.uz fiscal-agent page) + the key rate history —
    # the base curve of the UZS market and the anchor of every bond spread.
    # CREATE IF NOT EXISTS: a fresh database already gets both from the
    # provenance schema initializer; this applies them to deployed ones.
    Migration(8, "bonds: gov auction results + key rate history",
              run_sql(
                  """CREATE TABLE IF NOT EXISTS gov_bond_auctions (
                       sec_id          TEXT NOT NULL,
                       auction_date    TEXT NOT NULL,
                       isin            TEXT,
                       term_days       INTEGER,
                       maturity_date   TEXT,
                       income_type     TEXT,
                       announced_volume REAL,
                       dealers         INTEGER,
                       placed_qty      REAL,
                       placed_value    REAL,
                       wavg_rate       REAL,
                       min_rate        REAL,
                       max_rate        REAL,
                       source_url      TEXT,
                       synced_at       TEXT,
                       PRIMARY KEY (sec_id, auction_date)
                     )""",
                  "CREATE INDEX IF NOT EXISTS ix_gov_auctions_date "
                  "ON gov_bond_auctions (auction_date DESC)",
                  """CREATE TABLE IF NOT EXISTS gov_key_rate (
                       effective_from TEXT PRIMARY KEY,
                       rate           REAL NOT NULL,
                       source_url     TEXT,
                       synced_at      TEXT
                     )""")),
    # HMKB 14.08.2026: a negotiated 2,2-млрд-бумаг deal at 55,00 (board T1)
    # was summed into the session's turnover, quantity, low and VWAP, while
    # the exchange's own bulletin excludes it. Day statistics now aggregate
    # price-eligible executions only; the day's negotiated deals are carried
    # beside the session in their own columns.
    Migration(9, "trade stats: negotiated deals apart from the session",
              columns("catalog_trade_stats",
                      ("block_count", "INTEGER"),
                      ("block_qty", "REAL"),
                      ("block_value", "REAL"))),
    # openinfo's indicator feed publishes a liquidity ratio and an asset turnover
    # for 56 of the 95 issuers on the board and ROCE for 64, so three of the four
    # «Коэффициенты» columns were blank for the rest — while every one of them
    # files the balance lines those ratios are built from. Parsed and stored, the
    # coefficients become derivable wherever the feed is silent.
    Migration(10, "financials: the balance's current section",
              columns("catalog_financials",
                      ("current_assets", "REAL"),
                      ("current_liabilities", "REAL"),
                      ("inventories", "REAL"))),
    # «Номинальная стоимость» of every listed security. The exchange states it as
    # `parval` on the same security card the share count comes from — for shares
    # (AGBA 1 168 sums) as well as for bonds, where only the bond contour was
    # reading it. No page showed it for a share.
    Migration(11, "listings: the security's par value",
              columns("catalog_listings", ("nominal", "REAL"))),
)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          applied_at TEXT NOT NULL DEFAULT (datetime('now')),
          duration_ms INTEGER
        )
        """
    )


def applied(conn: sqlite3.Connection) -> set[int]:
    _ensure_table(conn)
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def pending(conn: sqlite3.Connection,
            register: Sequence[Migration] = MIGRATIONS) -> list[Migration]:
    done = applied(conn)
    return [m for m in sorted(register, key=lambda m: m.version) if m.version not in done]


def upgrade(conn: sqlite3.Connection,
            register: Sequence[Migration] = MIGRATIONS) -> dict[str, Any]:
    """Apply every pending migration in order, recording each one.

    A migration that raises stops the run: applying the rest out of order would
    leave a shape nobody can name. What has already been applied stays applied
    and recorded, so a retry resumes rather than restarts.
    """
    _ensure_table(conn)
    ran: list[str] = []
    for migration in pending(conn, register):
        started = time.time()
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, duration_ms) VALUES (?,?,?)",
                (migration.version, migration.name,
                 int((time.time() - started) * 1000)))
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.exception("migration %d (%s) failed", migration.version, migration.name)
            return {"ok": False, "applied": ran, "failed": migration.version,
                    "error": str(exc)}
        ran.append(f"{migration.version}:{migration.name}")
        logger.info("migration %d applied: %s", migration.version, migration.name)
    return {"ok": True, "applied": ran, "current_version": current_version(conn)}


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def status(conn: sqlite3.Connection,
           register: Sequence[Migration] = MIGRATIONS) -> dict[str, Any]:
    """What shape is this database in? (ТЗ §10.4: /ready must be able to say.)"""
    waiting = pending(conn, register)
    return {
        "current_version": current_version(conn),
        "latest_version": max((m.version for m in register), default=0),
        "pending": [{"version": m.version, "name": m.name} for m in waiting],
        # §10.4.6: a 503 while the database is behind the code is the honest
        # answer — serving from a shape the code does not expect is not.
        "ready": not waiting,
    }
