from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
import asyncio
import migrations
import os
import reports_catalog as catalog_store
import catalogue.market_store as catalogue_market_store
import server.catalog.jobs as catalog_jobs
import server.http as http
import server.market.board as market_board
import server.market.history as market_history
import server.market.patterns as market_patterns
import server.news.jobs as news_jobs
import server.bonds.quality as bond_quality


@asynccontextmanager
async def lifespan(app):
    try:
        await _on_startup(app)
        yield
    finally:
        await _stop_sector_analysis_worker(app)


async def _populate_securities_on_startup() -> None:
    """Warm both market boards and seed the securities table after a deploy.

    The catalog table is otherwise only filled as a side effect of
    ``/api/market/stocks`` (i.e. when the Market view is opened). A fresh data
    volume needs this seed before company pages have cached market metadata.
    Build the stock and bond boards once in the background so both the catalog
    and the short-lived response cache are ready before the first reader arrives.
    The same single-flight cache collapses a visitor racing this warm-up into the
    in-progress build. Errors remain isolated so an unreachable mirror never
    blocks (or crashes) boot.
    """
    kinds = ("stock", "bond")
    results = await asyncio.gather(
        *(market_board._cached_market_board(kind, refresh=True) for kind in kinds),
        return_exceptions=True,
    )
    for kind, result in zip(kinds, results):
        if isinstance(result, Exception):
            http.logger.error("startup market warm-up failed for type=%s: %s", kind, result)
        else:
            http.logger.info("startup market warm-up (%s): %d rows", kind, result.get("count", 0))


async def _on_startup(app) -> None:
    app.state.background_tasks = set()
    market_history._HISTORY_CACHE.clear()
    market_history._HISTORY_LOCKS.clear()
    market_patterns._PATTERN_CACHE.clear()
    # In-process market snapshots belong to this worker lifetime.  Clearing them
    # here also prevents a test/dev app restart from inheriting an old board.
    market_board._reset_market_board_cache()
    # ТЗ §10.10: migrations are applied before deploy, so a process that has just
    # started serves a shape it recognises. Additive and idempotent, so a boot
    # with nothing pending costs one query; a failure leaves /ready answering 503
    # rather than a request answering wrongly.
    try:
        from catalogue.storage import get_catalog_conn

        def _migrate() -> dict[str, Any]:
            conn = get_catalog_conn()
            try:
                return migrations.upgrade(conn)
            finally:
                conn.close()

        result = await asyncio.get_running_loop().run_in_executor(None, _migrate)
        if result.get("applied"):
            http.logger.info("startup migrations applied: %s", ", ".join(result["applied"]))
        elif not result.get("ok"):
            http.logger.error("startup migrations FAILED at version %s: %s",
                         result.get("failed"), result.get("error"))
    except Exception:
        http.logger.exception("startup migrations could not run")
    # The catalog DB lives on a mounted volume, so rows removed from the site
    # survive a redeploy. Purge on boot — idempotent, and it makes deleting a
    # ticker a code change rather than a manual DB step.
    try:
        removed = await asyncio.get_running_loop().run_in_executor(None, catalogue_market_store.purge_delisted)
        if removed:
            http.logger.info("startup purge of delisted securities: %s", removed)
    except Exception:
        http.logger.exception("startup purge of delisted securities failed")
    # The visit record's table lives in the same Postgres as web auth; creating
    # it is additive and idempotent. A missing DATABASE_URL only disables
    # tracking — the site itself must never depend on it.
    try:
        import web_analytics

        await asyncio.get_running_loop().run_in_executor(None, web_analytics.init_db)
    except Exception:
        http.logger.exception("web analytics init failed; tracking is off")
    # Fire-and-forget: seed the catalog without blocking the server from accepting
    # requests. The Market endpoint still refreshes it on demand afterwards.
    _start_task(app, _populate_securities_on_startup(), "market-warmup")
    if catalog_jobs.CATALOG_WATCH:
        _start_task(app, catalog_jobs._catalog_watch_loop(), "catalog-watch")
    if news_jobs.NEWS_CALENDAR_WATCH:
        _start_task(app, news_jobs._news_calendar_watch_loop(), "news-calendar-watch")
    if os.getenv("SECTOR_ANALYSIS_WORKER", "1") == "1":
        _start_task(app, _sector_analysis_loop(), "report-worker")
    if os.getenv("ADMIN_CONTROL_WORKER", "1") == "1":
        _start_task(app, _admin_control_loop(), "admin-control-worker")


def _start_task(app, coroutine, name):
    task = asyncio.create_task(coroutine, name=name)
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)
    return task


async def _admin_control_loop():
    """Compatibility worker; dedicated services can disable it and run the same module."""
    from admin_control import adapters, worker
    loop = asyncio.get_running_loop()
    last_indexed = 0.0
    while True:
        try:
            if loop.time() - last_indexed > 300:
                last_indexed = loop.time()
                try:
                    await loop.run_in_executor(None, adapters.refresh_catalog)
                    await loop.run_in_executor(None, adapters.refresh_analyses)
                except Exception:
                    http.logger.exception("Administrative indexing failed; queued jobs will still run")
            await loop.run_in_executor(None, worker.run_one)
        except asyncio.CancelledError:
            raise
        except Exception:
            http.logger.exception("Administrative control worker failed")
        await asyncio.sleep(2)


async def _sector_analysis_loop():
    from reporting import worker as report_worker
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, report_worker.run_pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            http.logger.exception("sector analysis worker failed")
        await asyncio.sleep(30)


async def _stop_sector_analysis_worker(app):
    tasks = set(getattr(app.state, "background_tasks", ()))
    tasks.update(market_board._MARKET_BOARD_REFRESH_TASKS.values())
    tasks.update(bond_quality._BOND_QUALITY_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    market_board._reset_market_board_cache()
    bond_quality._BOND_QUALITY_TASKS.clear()
    market_history._HISTORY_CACHE.clear()
    market_history._HISTORY_LOCKS.clear()
    market_patterns._PATTERN_CACHE.clear()
