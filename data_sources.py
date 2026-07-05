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


class FinancialIndicatorsCollector:
    """openinfo ``/reports/financial_indicators/`` — structured issuer indicators.

    A cleaner, parse-free source than NSBU Excel: for many issuers it returns
    net_revenue / net_profit / total_assets / total_liabilities / ROE / ROA etc.
    directly. Every key the endpoint returns is stored, so newly-published
    indicators are captured automatically.
    """

    name = "openinfo_financial_indicators"
    dataset = "financial_indicators"

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
                for key, raw in rec.items():
                    if key in self._SKIP or raw is None:
                        continue
                    field, unit = self.FIELD_MAP.get(key, (key, None))
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
    orgs = sorted({r["org_id"] for r in recs if r.get("org_id")})
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
