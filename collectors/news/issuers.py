"""News issuers operations with explicit dependencies."""
from __future__ import annotations
import reports_catalog as rc

from typing import Any
import collectors.news.delivery as collectors_news_delivery
import collectors.news.settings as collectors_news_settings

import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage


_prod_issuers: list[dict[str, Any]] | None = None


def issuers_from_prod() -> list[dict[str, Any]]:
    """The issuer catalog (ticker, name, openinfo org_id) read from prod, cached per process.

    A scheduled run has an empty database of its own — a Railway volume mounts to one service
    only — so without this the classifier would fall back to the static ticker list and
    openinfo filings could not be attributed to a ticker at all.
    """
    global _prod_issuers
    if _prod_issuers is not None:
        return _prod_issuers
    body = collectors_news_delivery._prod_request("GET", "/api/admin/catalog/issuers")
    _prod_issuers = (body or {}).get("issuers") or []
    if _prod_issuers:
        collectors_news_settings.logger.info("issuer catalog from prod: %d ticker(s), %d with an openinfo org_id",
                    len(_prod_issuers), sum(1 for i in _prod_issuers if i.get("org_id")))
    return _prod_issuers


def build_universe() -> dict[str, str]:
    """ticker → company name, for constraining the classifier's ticker tags.

    Local catalog first, then prod, then the static list — so a container with no database of
    its own still classifies against the real universe rather than a stale snapshot.
    """
    universe: dict[str, str] = {}
    try:
        conn = catalogue_storage.get_catalog_conn()
        for r in conn.execute("SELECT ticker, company_name FROM catalog_companies").fetchall():
            if r["ticker"]:
                universe[r["ticker"].upper()] = r["company_name"] or r["ticker"]
        conn.close()
    except Exception:  # noqa: BLE001 — fall back below
        collectors_news_settings.logger.exception("catalog universe query failed; trying prod")
    if not universe:
        universe = {str(r["ticker"]).upper(): (r.get("company_name") or r["ticker"])
                    for r in issuers_from_prod() if r.get("ticker")}
        if universe:
            collectors_news_settings.logger.info("issuer universe: %d ticker(s) from prod (no local catalog)", len(universe))
    if not universe:
        collectors_news_settings.logger.warning("no catalog locally or in prod — falling back to the static ticker list")
        universe = {t.upper(): n for t, n in catalogue_settings._TICKER_TO_NAME.items()}
    return universe


def _openinfo_ticker_map() -> dict[str, list[str]]:
    """openinfo organization id → our ticker(s). Several tickers can share one issuer
    (ordinary + preferred, e.g. UZNG/UZNGP), and a fact concerns all of its share classes."""
    mapping: dict[str, list[str]] = {}
    rows: list[Any] = []
    try:
        conn = catalogue_storage.get_catalog_conn()
        rows = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id <> ''"
        ).fetchall()
        conn.close()
    except Exception:  # noqa: BLE001 — fall back to prod below
        collectors_news_settings.logger.exception("could not read local catalog org ids; trying prod")
    if not rows:
        # A scheduled container has no catalog of its own; without this openinfo — the most
        # valuable source — would be skipped entirely on every scheduled run.
        rows = [r for r in issuers_from_prod() if r.get("org_id") and r.get("ticker")]
    for r in rows:
        mapping.setdefault(str(r["org_id"]).strip(), []).append(r["ticker"])
    return mapping
