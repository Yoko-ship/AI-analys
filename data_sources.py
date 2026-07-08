"""Source-adapter registry — the pluggable ingestion layer of the data pipeline.

Each data source is a small ``Collector``: given the discovered issuer orgs it
fetches raw records and normalizes them into generic *facts* (entity, dataset,
field, period, value) landed in the fact store. Adding a new source is one class
+ ``register()`` — the orchestrator, fact store, coverage and API layers are
untouched. A source that starts publishing a *new field* in the future needs no
code change: the collector stores whatever keys the source returns, so the field
simply appears as new fact rows. This is the "if a source gets published later, I
get it too" property from the pipeline design.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import reports_catalog as rc
from entity_resolver import resolve_all
from openinfo_collector import _json_get, _make_session

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, "Collector"] = {}


@runtime_checkable
class Collector(Protocol):
    name: str

    def collect(self, orgs: list[str], session: Any) -> list[dict[str, Any]]:
        """Return a list of fact rows for the given issuer orgs."""
        ...


def register(collector: "Collector") -> "Collector":
    _REGISTRY[collector.name] = collector
    return collector


def registry() -> dict[str, "Collector"]:
    return dict(_REGISTRY)


# Absolute figures that must reconcile before we trust them; ratios are always
# safe to store (they are the source of truth we validate against).
_ABSOLUTE_INDICATOR_FIELDS = {
    "net_revenue", "net_profit", "total_assets", "total_liabilites",
    "total_liabilities", "total_equity",
}


def reconciles_indicators(rec: dict[str, Any], tol: float = 0.6) -> bool:
    """True if an indicator record is internally consistent.

    net_profit is cross-checked against the published ROE (net_profit/equity) and
    ROA (net_profit/assets). This is the automated guard: if the absolute figures
    do not reproduce the ratios the source itself reports, they are untrustworthy
    (e.g. revenue mislabelled as profit) and must not be shipped. When there is no
    ratio to check against, we cannot invalidate, so it passes (fail-open).
    """
    npf = rec.get("net_profit")
    equity = rec.get("total_equity")
    assets = rec.get("total_assets")
    roe = rec.get("return_on_equity")
    roa = rec.get("return_on_assets")
    checks: list[bool] = []
    if npf is not None and equity not in (None, 0) and roe is not None:
        checks.append(abs(npf / equity * 100 - roe) <= tol)
    if npf is not None and assets not in (None, 0) and roa is not None:
        checks.append(abs(npf / assets * 100 - roa) <= tol)
    return all(checks) if checks else True


class FinancialIndicatorsCollector:
    """openinfo ``/reports/financial_indicators/`` — structured issuer indicators.

    A cleaner, parse-free source than NSBU Excel: for many issuers it returns
    net_revenue / net_profit / total_assets / total_liabilities / ROE / ROA etc.
    directly. Every key the endpoint returns is stored, so newly-published
    indicators are captured automatically.
    """

    name = "openinfo_financial_indicators"
    dataset = "financial_indicators"
    dropped = 0  # records whose absolute figures failed reconciliation

    # openinfo key -> (fact field, unit). Unmapped keys are still stored verbatim
    # so future indicators are never dropped.
    FIELD_MAP = {
        "net_revenue": ("net_revenue", "UZS"),
        "net_profit": ("net_profit", "UZS"),
        "total_assets": ("total_assets", "UZS"),
        "total_liabilites": ("total_liabilities", "UZS"),  # openinfo's spelling
        "total_liabilities": ("total_liabilities", "UZS"),
        "total_equity": ("total_equity", "UZS"),
        "return_on_assets": ("roa", "%"),
        "return_on_equity": ("roe", "%"),
        "net_profit_margin": ("net_profit_margin", "x"),
        "debt_to_equity_ratio": ("debt_to_equity", "x"),
        "cost_of_risk": ("cost_of_risk", "%"),
    }
    _SKIP = {"reporting_year", "quarter", "id"}

    def collect(self, orgs: list[str], session: Any) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for org in orgs:
            try:
                data = _json_get(session, "/reports/financial_indicators/", {"organization_id": org})
            except Exception as exc:  # noqa: BLE001 — best-effort per issuer
                logger.debug("financial_indicators %s failed: %s", org, exc)
                continue
            results = data.get("results") if isinstance(data, dict) else data
            src_url = (
                "https://new-api.openinfo.uz/api/v2/reports/financial_indicators/"
                f"?organization_id={org}"
            )
            for rec in results or []:
                year = rec.get("reporting_year")
                quarter = rec.get("quarter")
                period = str(year or "")
                if quarter not in (None, 0, "0", ""):
                    period += f"Q{quarter}"
                # Guard: only trust the absolute figures if they reconcile with the
                # ratios the source reports. Ratios are always kept.
                trust_absolutes = reconciles_indicators(rec)
                if not trust_absolutes:
                    logger.warning(
                        "financial_indicators org=%s %s failed ROE/ROA reconciliation "
                        "— dropping absolute figures", org, period,
                    )
                    self.dropped += 1
                for key, raw in rec.items():
                    if key in self._SKIP or raw is None:
                        continue
                    field, unit = self.FIELD_MAP.get(key, (key, None))
                    if not trust_absolutes and key in _ABSOLUTE_INDICATOR_FIELDS:
                        continue
                    facts.append({
                        "entity_id": org, "dataset": self.dataset, "field": field,
                        "period": period, "value": raw, "unit": unit,
                        "source": self.name, "source_url": src_url,
                    })
        return facts


register(FinancialIndicatorsCollector())


def run_all(collectors: list[str] | None = None, session: Any = None) -> dict[str, Any]:
    """Discover every issuer org, run the registered collectors, land facts.

    Runs on a network that can reach openinfo (the collector host / proxy).
    """
    session = session or _make_session()
    recs = resolve_all(session=session)
    orgs = {r["org_id"] for r in recs if r.get("org_id")}
    # The live-feed resolver misses report-only or awkwardly-named issuers
    # (Octobank 27, Kapitalbank 29, Tenge Bank 815 all resolved to nothing),
    # so their indicators were never collected — leaving their revenue blank and
    # their net-income showing the revenue figure. Union in every org from the
    # synced local catalog, whose ticker->org mapping is authoritative.
    try:
        conn = rc.get_catalog_conn()
        catalog_orgs = {
            str(row["org_id"])
            for row in conn.execute(
                "SELECT DISTINCT org_id FROM catalog_companies "
                "WHERE org_id IS NOT NULL AND org_id != ''"
            ).fetchall()
        }
        conn.close()
        orgs |= catalog_orgs
    except Exception:  # noqa: BLE001 — catalog union is best-effort
        logger.exception("failed to union catalog orgs into fact collection")
    orgs = sorted(orgs)
    result: dict[str, Any] = {}
    for name, collector in registry().items():
        if collectors and name not in collectors:
            continue
        try:
            facts = collector.collect(orgs, session)
            written = rc.upsert_facts(facts)
            result[name] = {"facts": len(facts), "written": written}
            logger.info("collector %s: %d facts", name, written)
        except Exception as exc:  # noqa: BLE001
            logger.exception("collector %s failed", name)
            result[name] = {"error": str(exc)}
    return {"orgs": len(orgs), "collectors": result}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))
