"""Versioned migrations and the revision-keyed cache (ТЗ §10.1/§10.9).

The project changed its schema with CREATE TABLE IF NOT EXISTS and hand-written
ALTER TABLE guarded by PRAGMA. Nothing recorded what had been applied, so no
deployment could say which shape it was in and no deploy could fail on a
database behind the code.
"""
from __future__ import annotations

import sqlite3

import cache_layer
import migrations


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE catalog_financials (ticker TEXT)")
    return conn


class TestMigrations:
    def test_a_fresh_database_needs_every_migration(self):
        conn = _db()
        assert migrations.current_version(conn) == 0
        assert len(migrations.pending(conn, migrations.MIGRATIONS[:2])) == 2

    def test_applying_records_what_ran(self):
        conn = _db()
        result = migrations.upgrade(conn, migrations.MIGRATIONS[:2])
        assert result["ok"] is True and len(result["applied"]) == 2
        assert migrations.current_version(conn) == 2
        rows = list(conn.execute("SELECT version, name, duration_ms FROM schema_migrations"))
        assert [r[0] for r in rows] == [1, 2]
        assert all(r[2] is not None for r in rows)

    def test_running_twice_changes_nothing(self):
        conn = _db()
        migrations.upgrade(conn, migrations.MIGRATIONS[:2])
        second = migrations.upgrade(conn, migrations.MIGRATIONS[:2])
        assert second["applied"] == []
        assert migrations.current_version(conn) == 2

    def test_add_column_is_idempotent_by_inspection(self):
        conn = _db()
        step = migrations.add_column("catalog_financials", "report_id", "INTEGER")
        step(conn)
        step(conn)                                   # must not raise
        cols = {r[1] for r in conn.execute("PRAGMA table_info(catalog_financials)")}
        assert "report_id" in cols

    def test_a_failure_stops_the_run_and_keeps_what_applied(self):
        """Applying the rest out of order would leave a shape nobody can name."""
        def boom(_conn):
            raise RuntimeError("column type not supported")

        register = (
            migrations.MIGRATIONS[0],
            migrations.Migration(99, "broken", boom),
            migrations.Migration(100, "later", migrations.run_sql("SELECT 1")),
        )
        conn = _db()
        result = migrations.upgrade(conn, register)
        assert result["ok"] is False and result["failed"] == 99
        assert migrations.current_version(conn) == 1
        assert 100 not in migrations.applied(conn)

    def test_status_says_whether_the_database_is_ready(self):
        conn = _db()
        before = migrations.status(conn, migrations.MIGRATIONS[:2])
        assert before["ready"] is False and len(before["pending"]) == 2
        migrations.upgrade(conn, migrations.MIGRATIONS[:2])
        after = migrations.status(conn, migrations.MIGRATIONS[:2])
        assert after["ready"] is True and after["pending"] == []

    def test_versions_are_unique_and_ordered(self):
        versions = [m.version for m in migrations.MIGRATIONS]
        assert versions == sorted(versions)
        assert len(set(versions)) == len(versions)


class TestCache:
    def setup_method(self):
        cache_layer.clear()

    def test_the_revision_is_in_the_key(self):
        """A new revision misses rather than needing an invalidation step."""
        a = cache_layer.key("market:multiples", 1487, "months=12")
        b = cache_layer.key("market:multiples", 1488, "months=12")
        assert a != b and "rev=1487" in a

    def test_a_value_round_trips(self):
        cache_layer.set("k", {"pe": 8.4})
        assert cache_layer.get("k") == {"pe": 8.4}

    def test_a_miss_is_none_not_an_error(self):
        assert cache_layer.get("never-written") is None

    def test_cached_produces_once(self):
        calls = []

        def produce():
            calls.append(1)
            return {"v": len(calls)}

        first = cache_layer.cached("k2", produce)
        second = cache_layer.cached("k2", produce)
        assert first == second == {"v": 1}
        assert len(calls) == 1

    def test_an_expired_entry_is_dropped(self):
        cache_layer.set("k3", "value", ttl=-1)
        assert cache_layer.get("k3") is None

    def test_it_names_its_backend(self):
        assert cache_layer.backend() in ("redis", "memory")
