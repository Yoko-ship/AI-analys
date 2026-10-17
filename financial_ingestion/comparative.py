"""Fill a missing annual year from the next year's filing (ТЗ T-04, data rule 3).

docs/catalog-terminal/02-data.md, R-D4. When an issuer filed no usable annual
for year N, its annual for N+1 still prints year N beside every line:
form 2 «за соответствующий период прошлого года» (value1/value2) and form 1
«на начало года», which is N's year-end. Those figures are the issuer's own,
so the year is shown from them, with the source named. Nothing is drawn where
no later filing states the year.

Rules:

* **A real filing always wins.** Comparative years live in their own table,
  and the reader uses one only where no usable filed row exists. No writer of
  catalog_financials has to know about them, and a filing published later
  replaces the comparative without anyone deleting anything.
* **Banks are left out.** The bank form prints a single value column and has
  no comparative (memory: bank-form-has-no-comparative).
* **An unfilled opening balance is a gap.** A nought «на начало» is a blank
  cell, not a company with nothing on its balance sheet.
* The same usability rule as every loader (catalogue.fields.usable_filing).
"""
from __future__ import annotations

import json
import logging

import dbx

import catalogue.fields as catalogue_fields
import catalogue.periods as catalogue_periods
import catalogue.storage as catalogue_storage

log = logging.getLogger(__name__)

FORM = "NSBU"
FIRST_YEAR = 2015
_INCOME = ("revenue", "gross_profit", "net_income", "operating_income")


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_comparative_years (
        ticker TEXT NOT NULL, form TEXT NOT NULL, year INTEGER NOT NULL,
        values_json TEXT NOT NULL, source_year INTEGER NOT NULL,
        source_object_id INTEGER, source_org_type TEXT, source_pub_date TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (ticker, form, year))""")
    c.commit()


def _connect():
    c = catalogue_storage.get_catalog_conn()
    dbx.ensure_schema(c, "catalog-comparative-years-v1", _schema)
    return c


def comparative_values(metrics: dict) -> dict | None:
    """Year N's figures as printed in the N+1 filing, or None when it states none."""
    if not metrics or metrics.get("org_type") in ("bank", "microfinance"):
        return None
    prior = metrics.get("prior") or {}
    balance = metrics.get("balance") or {}
    values = {key: prior.get(key) for key in _INCOME}
    assets = balance.get("assets_start") or None
    equity = balance.get("equity_start") if assets is not None else None
    values["total_assets"] = assets
    values["total_equity"] = equity
    values["total_liabilities"] = (assets - equity) if assets is not None and equity is not None else None
    values, problem = catalogue_fields.usable_filing(values)
    if problem is not None and problem["code"] != "no_balance":
        return None
    if not any(values.get(key) is not None for key in catalogue_fields.FILING_MONEY_KEYS):
        return None
    return values


def _usable_years(aliases: list[str]) -> set[int]:
    c = catalogue_storage.get_catalog_conn()
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM catalog_financials WHERE form=? AND quarter=0 AND ticker IN ("
            + ",".join("?" for _ in aliases) + ")", (FORM, *aliases))]
    finally:
        c.close()
    years = set()
    for row in rows:
        _, problem = catalogue_fields.usable_filing(row)
        if problem is None or problem["code"] == "no_balance":
            years.add(int(row["year"]))
    return years


def missing_years(aliases: list[str], last_fy: int | None = None) -> list[int]:
    """Annual years with no usable filing whose following year has one."""
    last_fy = last_fy or catalogue_periods._latest_complete_fiscal_year()
    have = _usable_years(aliases)
    return [year for year in range(FIRST_YEAR, last_fy)
            if year not in have and year + 1 in have]


def _annual_detail(org_id: str, year: int):
    """The openinfo annual whose fiscal year is `year`, newest filing first."""
    import openinfo_reconcile as oi

    for cand in oi.list_candidates_by_org(org_id):
        if cand["period_type"] != "annual":
            continue
        detail = oi.fetch_detail(cand)
        fiscal, _ = oi.period_year_quarter(detail.get("reporting_year"), "annual",
                                           pub_date=cand.get("pub_date"))
        if fiscal == year:
            return cand, detail
    return None, None


def store(aliases: list[str], year: int, values: dict, source: dict) -> None:
    c = _connect()
    try:
        with c:
            for ticker in aliases:
                c.execute(
                    "INSERT INTO catalog_comparative_years "
                    "(ticker, form, year, values_json, source_year, source_object_id, source_org_type, "
                    "source_pub_date, updated_at) VALUES (?,?,?,?,?,?,?,?,datetime('now')) "
                    "ON CONFLICT(ticker, form, year) DO UPDATE SET values_json=excluded.values_json, "
                    "source_year=excluded.source_year, source_object_id=excluded.source_object_id, "
                    "source_org_type=excluded.source_org_type, source_pub_date=excluded.source_pub_date, "
                    "updated_at=datetime('now')",
                    (ticker, FORM, year, json.dumps(values), source["year"], source.get("object_id"),
                     source.get("org_type"), source.get("pub_date")))
    finally:
        c.close()


def comparative_years(ticker: str, form: str = FORM) -> dict[str, dict]:
    """{year: {values…, "source": {...}}} for the reader, in thousands of UZS."""
    c = _connect()
    try:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM catalog_comparative_years WHERE ticker=? AND form=?", (ticker.upper(), form))]
    finally:
        c.close()
    out = {}
    for row in rows:
        values = json.loads(row["values_json"])
        values["source"] = {"kind": "comparative", "year": row["source_year"],
                            "object_id": row["source_object_id"], "org_type": row["source_org_type"],
                            "pub_date": row["source_pub_date"]}
        out[str(row["year"])] = values
    return out


def source_url(source: dict) -> str | None:
    if not source.get("object_id") or not source.get("org_type"):
        return None
    return f"https://openinfo.uz/reports/{source['org_type']}/annual/{source['object_id']}"


def backfill_issuer(org_id: str, aliases: list[str], journal=None) -> list[int]:
    """Fill every missing annual of one issuer that a later filing states."""
    filled = []
    if not org_id or str(org_id).startswith("ticker:"):
        return filled
    for year in missing_years(aliases):
        try:
            cand, detail = _annual_detail(str(org_id), year + 1)
            if not detail:
                continue
            import openinfo_reconcile as oi

            values = comparative_values(oi.extract_metrics(detail))
            if values is None:
                continue
            source = {"year": year + 1, "object_id": cand["object_id"],
                      "org_type": cand["org_type"], "pub_date": cand.get("pub_date")}
            store(aliases, year, values, source)
            filled.append(year)
            if journal:
                journal("year_backfill", ticker=aliases[0], standard=FORM, period=str(year),
                        message=f"{year} from the prior-year column of the {year + 1} annual",
                        source_url=source_url(source), details=source)
        except Exception as exc:  # noqa: BLE001 — one issuer's source never stops the sweep
            log.warning("comparative backfill %s %s: %s", aliases[0], year, exc)
    return filled
