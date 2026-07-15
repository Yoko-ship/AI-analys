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
from datetime import date
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
                # Validate the source's period fields instead of trusting them:
                # openinfo has published quarter values like 7 or 10, which used
                # to create corrupt periods ("2025Q7") that then won every
                # lexicographic "latest period" comparison.
                try:
                    year_num = int(year)
                except (TypeError, ValueError):
                    year_num = 0
                try:
                    quarter_num = int(quarter or 0)
                except (TypeError, ValueError):
                    quarter_num = -1
                if not (2000 <= year_num <= date.today().year + 1) or quarter_num not in (0, 1, 2, 3, 4):
                    logger.warning(
                        "financial_indicators org=%s: dropping record with invalid period year=%r quarter=%r",
                        org, year, quarter,
                    )
                    continue
                period = str(year_num)
                if quarter_num:
                    period += f"Q{quarter_num}"
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


class NsbuDerivedIndicatorsCollector:
    """Ratios derived from filed NSBU statements, for issuers openinfo's
    ``/reports/financial_indicators/`` cannot serve.

    The endpoint 400s server-side for some orgs (e.g. Toshkentdonmahsulotlari,
    ALSKOM, Temiryo'l-sug'urta: "local variable 'long_term_bank_loans'
    referenced before assignment"), leaving their ROE/ROA/P-B blank on the
    market board even though their quarterly reports publish a full balance.
    For catalog orgs with NO financial_indicators facts on file, compute the
    same fields from the latest parseable NSBU Excel and land them under the
    same dataset, so ``get_all_ratios`` serves them with no read-side changes.

    Registered after FinancialIndicatorsCollector: ``run_all`` lands each
    collector's facts before the next runs, so "no facts on file" already
    accounts for this run's endpoint results.
    """

    name = "nsbu_derived_indicators"
    dataset = "financial_indicators"

    def collect(self, orgs: list[str], session: Any) -> list[dict[str, Any]]:
        conn = rc.get_catalog_conn()
        try:
            covered = {
                str(r["entity_id"])
                for r in conn.execute(
                    "SELECT DISTINCT entity_id FROM facts "
                    "WHERE dataset='financial_indicators' AND value_num IS NOT NULL"
                ).fetchall()
            }
            org_tickers: dict[str, list[str]] = {}
            for r in conn.execute(
                "SELECT ticker, org_id FROM catalog_companies "
                "WHERE org_id IS NOT NULL AND org_id != ''"
            ).fetchall():
                org_tickers.setdefault(str(r["org_id"]), []).append(r["ticker"])
        finally:
            conn.close()

        facts: list[dict[str, Any]] = []
        for org in orgs:
            if org in covered:
                continue
            for ticker in org_tickers.get(str(org), []):
                # Prefer the newest annual (full-year flows → honest ROE/margin);
                # fall back to the newest report of any period type.
                latest = rc._latest_excel_report(ticker, "NSBU")
                if not latest:
                    continue
                candidates = [latest]
                if latest.get("quarter"):
                    cconn = rc.get_catalog_conn()
                    annual = cconn.execute(
                        "SELECT year, quarter FROM catalog_reports "
                        "WHERE ticker=? AND report_form='NSBU' AND quarter=0 "
                        "AND excel_url IS NOT NULL AND year IS NOT NULL "
                        "ORDER BY year DESC LIMIT 1",
                        (ticker,),
                    ).fetchone()
                    cconn.close()
                    if annual:
                        candidates.insert(0, {"year": annual["year"], "quarter": 0})
                ratios: dict[str, Any] = {}
                report: dict[str, int] | None = None
                for cand in candidates:
                    try:
                        data = rc.fetch_report_excel_data(ticker, "NSBU", cand["year"], cand["quarter"])
                        if not data.get("ok"):
                            continue
                        computed = rc.compute_financial_ratios(data.get("income"), data.get("balance"))
                    except Exception:  # noqa: BLE001 — best-effort per issuer
                        logger.exception("nsbu_derived %s (%s) failed", ticker, org)
                        continue
                    if any(v is not None for v in (computed.get("metrics") or {}).values()):
                        ratios, report = computed, cand
                        break
                if not report:
                    continue
                metrics = ratios.get("metrics") or {}
                vals = ratios.get("source_values") or {}
                period = str(report["year"]) + (f"Q{report['quarter']}" if report.get("quarter") else "")
                row_fields = {
                    "roe": (metrics.get("ROE"), "%"),
                    "roa": (metrics.get("ROA"), "%"),
                    "net_profit_margin": (metrics.get("net_margin"), "x"),
                    "debt_to_equity": (metrics.get("debt_to_equity"), "x"),
                    # NSBU sums are thousands of UZS — same unit contract as the
                    # indicators endpoint's absolutes.
                    "total_assets": (vals.get("total_assets"), "UZS"),
                    "total_equity": (vals.get("equity"), "UZS"),
                    "total_liabilities": (vals.get("total_liabilities"), "UZS"),
                    "net_profit": (vals.get("net_income"), "UZS"),
                }
                emitted = 0
                for field, (value, unit) in row_fields.items():
                    if value is None:
                        continue
                    facts.append({
                        "entity_id": str(org), "dataset": self.dataset, "field": field,
                        "period": period, "value": value, "unit": unit,
                        "source": self.name,
                        "source_url": f"nsbu-excel:{ticker}:{period}",
                    })
                    emitted += 1
                if emitted:
                    logger.info("nsbu_derived %s (org %s) %s: %d fields", ticker, org, period, emitted)
                    break  # issuer covered via one ticker; siblings join by org
        return facts


register(NsbuDerivedIndicatorsCollector())


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
