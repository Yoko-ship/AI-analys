"""Dated, separate NSBU statements from Openinfo's microfinance quarterly form."""

from decimal import Decimal
import json
import re

from issuer_financials import period_end

import dbx
from catalogue.storage import get_catalog_conn
from financial_columns.share_disclosures import filing_key
from financial_ingestion.microfinance import lending_facts
from .nsbu import cell
from .registry import mapping

# The two balance columns are component and total amounts at the same date.
DETAIL_CODES = set("050 051 060 061 070 071 100 101 311 312 331 332".split())
BS_METRICS = mapping("""
    010:cash 020:bank_balances 030:interest_receivables 040:factoring_receivables 050:loans_gross
    051:loan_allowance 052:loans_net 060:leases_gross 061:lease_allowance 062:leases_net
    070:investments_gross 071:investment_allowance 072:investments_net 080:ppe 090:intangibles
    100:other_property 101:other_property_allowance 102:other_property_net 110:other_assets
    120:total_assets 210:borrowings 220:lease_liabilities 230:debt_securities_issued
    240:interest_payables 250:taxes_payable 260:deferred_income 270:other_liabilities
    280:total_liabilities 310:share_capital 311:ordinary_share_capital 312:preferred_share_capital
    320:additional_capital 330:reserve_capital 331:general_reserves 332:other_reserves
    340:retained_earnings 350:current_year_profit 360:total_equity 370:total_equity_liabilities
""")
PL_METRICS = {
    "180": "interest_income",
    "270": "interest_expense",
    "310": "net_interest_before_ecl",
    "320": "credit_loss_provisions",
    "330": "net_interest_after_ecl",
    "470": "noninterest_income",
    "550": "noninterest_expense",
    "600": "income_before_operating_expenses",
    "780": "operating_expenses",
    "900": "profit_before_tax",
    "1000": "income_tax",
    "1200": "net_income",
}


# Control totals printed on the statutory form. Values are filed in thousands of UZS.
INCOME_TOTALS = {
    "180": "110 120 130 140 150 160 170",
    "270": "210 220 230 240 250 260",
    "330": "310 -320",
    "470": "410 420 430 440 450 460",
    "550": "510 520 530 540",
    "780": "710 720 730 740 750 760 770",
    "1100": "900 -1000",
    "1200": "1100 1110",
}


def has_all_lines(doc):
    income_codes = set(PL_METRICS) | set(INCOME_TOTALS) | {"800", "1110"}
    for terms in INCOME_TOTALS.values():
        income_codes.update(term.lstrip("-") for term in terms.split())
    return set(BS_METRICS) <= doc["forms"]["MFI_BS"].keys() and income_codes <= doc["forms"]["MFI_PL"].keys()


def income_disagreements(lines):
    values = {code: cell(line.get("value"))["value"] for code, line in lines.items()}
    conflicts = set()
    for code, formula in INCOME_TOTALS.items():
        terms = formula.split()
        if values.get(code) is None or any(values.get(term.lstrip("-")) is None for term in terms):
            continue
        total = sum(Decimal(values[term.lstrip("-")]) * (-1 if term.startswith("-") else 1) for term in terms)
        if abs(Decimal(values[code]) - total) > 1:
            conflicts.add(code)
    return conflicts


def filed_rows(document, version, source):
    end, forms = document["period_end"], document["forms"]
    details = {
        key: [{"tnum": code, **r} for code, r in forms[form].items()]
        for key, form in [
            ("quarter_balance_sheet_report", "MFI_BS"),
            ("quarter_financial_results_report", "MFI_PL"),
        ]
    }
    lending = lending_facts({"org_type": "microfinance", **details})
    balance = forms["MFI_BS"]
    capital = cell(balance.get("310", {}).get("value2"))["value"]
    shares = [cell(balance.get(code, {}).get("value1"))["value"] for code in ("311", "312")]
    missing_split = (
        capital is not None
        and Decimal(capital) > 0
        and all(v is not None and Decimal(v) == 0 for v in shares)
    )
    conflicts = income_disagreements(forms["MFI_PL"])
    for form, lines in forms.items():
        stock = form == "MFI_BS"
        for code, line in lines.items():
            column = ("value1" if code in DETAIL_CODES else "value2") if stock else "value"
            reading = cell(line.get(column))
            if stock:
                other = cell(line.get("value2" if column == "value1" else "value1"))
                if other["value"] is not None and Decimal(other["value"]) != 0:
                    reading.update(value=None, quality="blocked", reason="SOURCE_COLUMN_UNRESOLVED")
                if missing_split and code in {"311", "312"}:
                    reading.update(value=None, quality="blocked", reason="UNDISCLOSED_CAPITAL_BREAKDOWN")
            elif code in conflicts:
                reading.update(quality="warn", reason="FILED_SUBTOTAL_MISMATCH")
                if Decimal(reading["value"]) == 0:
                    reading.update(value=None, quality="blocked")
            if not stock and code == "600":
                verified = lending.get("values", {}).get("net_revenue_before_operating_expenses")
                if verified is None:
                    reading.update(value=None, quality="blocked", reason="UNRECONCILED_INCOME_SUBTOTAL")
                elif lending.get("derived", {}).get("net_revenue_before_operating_expenses"):
                    reading.update(
                        value=str(verified),
                        quality="valid",
                        formula=lending["derived"]["net_revenue_before_operating_expenses"],
                        origin="UZStock_calculated",
                    )
            if reading["value"] is not None:
                reading["value"] = format(Decimal(reading["value"]).normalize(), "f")
            yield {
                **reading,
                "source_form": form,
                "source_code": code,
                "raw_label": line["title"],
                "source_column": column,
                "source_line_id": line["id"],
                "source_version": version,
                "source_url": source["source_url"],
                "published_at": source["pub_date"],
                "source_ticker_period": source["source_period"],
                "metric_id": (BS_METRICS if stock else PL_METRICS).get(code) or form.lower() + "_" + code,
                "standard": "NSBU",
                "scope": "separate",
                "issuer_id": document["issuer_id"],
                "role": "PRIMARY",
                "kind": "stock" if stock else "flow",
                "accounting_model": "microfinance",
                "period_end": end,
                "period_start": end if stock else end[:4] + "-01-01",
                "unit": "UZS_thousand",
                "currency": "UZS",
                "unit_scale": "1000",
            }


def filed_documents(ticker, issuer_id):
    from catalogue import filings

    conn = get_catalog_conn()
    try:
        if "catalog_microfinance_forms" not in dbx.tables(conn):
            return []
        aliases = filings._org_siblings(conn, ticker) or [ticker]
        placeholders = ",".join("?" for _ in aliases)
        saved = conn.execute(
            f"SELECT DISTINCT year,quarter,source_json FROM catalog_structured_quarters WHERE ticker IN ({placeholders})",
            aliases,
        ).fetchall()
        if not saved:
            return []
        active = {}
        for report in filings.get_company_reports(ticker):
            if report.get("report_form") == "NSBU" and report.get("quarter"):
                active.setdefault((report["year"], report["quarter"]), report)
        result = {}
        for row in saved:
            source = json.loads(row["source_json"])
            version = source.get("statement_version")
            report = active.get((row["year"], row["quarter"]), {})
            key = filing_key(report.get("excel_url") or report.get("excel_url_form1"))
            if (
                not version
                or version in result
                or not key
                or key[:2] != ("microfinance", "quarter")
                or source.get("org_id") != issuer_id
                or source.get("pub_date") != report.get("published_at")
                or source.get("source_url") != "https://openinfo.uz/reports/microfinance/quarter/" + key[2]
            ):
                continue
            record = conn.execute(
                "SELECT payload_json FROM catalog_microfinance_forms WHERE version=?", (version,)
            ).fetchone()
            if record:
                doc = json.loads(record["payload_json"])
                period = f"{row['year']}Q{row['quarter']}"
                if (
                    doc["report_id"] == key[2]
                    and doc["issuer_id"] == issuer_id
                    and source.get("source_period") == period
                    and doc["period_end"] == period_end(period)
                ):
                    result[version] = (doc, version, source)
        return list(result.values())
    finally:
        conn.close()


def observations(ticker, issuer_id):
    return [
        row
        for doc, version, source in filed_documents(ticker, issuer_id)
        for row in filed_rows(doc, version, source)
    ]


def original_form(doc, version, source):
    documents = []
    for form, lines in doc["forms"].items():
        columns = ("title", "value1", "value2") if form == "MFI_BS" else ("title", "value")
        documents.append(
            {
                "form": form,
                "source_rows": [
                    {"row": code, "cells": [line.get(col) for col in columns]}
                    for code, line in sorted(lines.items())
                ],
            }
        )
    return {
        "period_end": doc["period_end"],
        "source_url": source["source_url"],
        "source_version": version,
        "documents": documents,
    }


def quarter_cells(ticker, issuer_id, periods):
    """Keep cumulative income in its filing period until both quarter inputs are available."""
    from collections import defaultdict
    from data_quality import held_public_periods
    from . import matrix
    from .periods import calculate

    if not issuer_id or not periods:
        return {}
    held = held_public_periods(ticker, "NSBU")
    grouped = defaultdict(list)
    for row in observations(ticker, str(issuer_id)):
        period = row["source_ticker_period"]
        if period in held or (period.endswith("Q4") and period[:4] in held):
            continue
        key = row["source_form"].lower() + "_" + row["source_code"]
        grouped[key].append(row)
    history = {}
    for period in periods:
        if not re.fullmatch(r"\d{4}Q[1-4]", period):
            continue
        end = period_end(period)
        for field, rows in grouped.items():
            if rows[0]["kind"] == "stock":
                selected = matrix.choose([r for r in rows if r["period_end"] == end])
            else:
                selected = calculate(rows, end, "quarter")
            if selected.get("value") is not None and selected["quality"] == "valid":
                history.setdefault(period, {})[field] = selected
    return history


def series(history):
    result = {}
    for period, lines in history.items():
        for field, row in lines.items():
            entry = result.setdefault(
                field,
                {
                    "filed_label": row["raw_label"],
                    "unit": "UZS",
                    "money": True,
                    "statement_section": "balance" if row["kind"] == "stock" else "income",
                    "values": {},
                },
            )
            amount = Decimal(row["value"]) * Decimal(row["unit_scale"])
            entry["values"][period] = int(amount) if amount == amount.to_integral_value() else float(amount)
    return result


def passport(ticker, period, field):
    from catalogue import filings

    issuer = filings.get_company_index(ticker) or {}
    row = quarter_cells(ticker, issuer.get("org_id"), [period]).get(period, {}).get(field)
    base = {"field": field, "period": period, "standard": "NSBU"}
    if not row:
        return {**base, "status": "NO_DATA"}
    parts = row.get("components") or [row]
    links = [
        {
            "url": p["source_url"],
            "period": p["source_ticker_period"],
            "code": p["source_code"],
            "raw_value": p.get("raw_value"),
            "unit": p["unit"],
        }
        for p in parts
    ]
    formulas = [p["formula"] for p in parts if p.get("origin") == "UZStock_calculated" and p.get("formula")]
    if len(parts) > 1:
        formulas.append(row["formula"])
    return {
        **base,
        "status": "DERIVED" if formulas else "SOURCED",
        "filed_label": row["raw_label"],
        "filing_links": links,
        "formula": " · ".join(dict.fromkeys(formulas)),
    }
