"""Explain a displayed financial value using its source and calculation evidence."""
from __future__ import annotations
from typing import Any

import catalogue.codecs as catalogue_codecs
import catalogue.filings as catalogue_filings
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import re


_FINANCIAL_PASSPORT_FIELDS = {

    "interest_income": "interest_income",

    "interest_expense": "interest_expense",

    "net_revenue": "revenue",

    "gross_profit": "gross_profit",

    "operating_income": "operating_income",

    "operating_expenses": "operating_expenses",

    "net_profit": "net_income",

    "cash": "cash",

    "total_assets": "total_assets",

    "total_liabilities": "total_liabilities",

    "total_equity": "total_equity",

    "current_assets": "current_assets",

    "current_liabilities": "current_liabilities",

    "inventories": "inventories",

}


_FINANCIAL_PASSPORT_DERIVED = {

    "net_margin": {

        "formula": "net_profit / net_revenue * 100",

        "inputs": ("net_profit", "net_revenue"),

    },

    "roe": {

        "formula": "net_profit / average_equity * 100",

        "inputs": ("net_profit", "total_equity"),

    },

    "roa": {

        "formula": "net_profit / average_assets * 100",

        "inputs": ("net_profit", "total_assets"),

    },

    "debt_ratio": {

        "formula": "total_liabilities / total_assets * 100",

        "inputs": ("total_liabilities", "total_assets"),

    },

    "debt_to_equity": {

        "formula": "total_liabilities / total_equity",

        "inputs": ("total_liabilities", "total_equity"),

    },

}


def get_financial_value_passport(ticker: str, period: str, field: str,

                                 form: str = "NSBU") -> dict[str, Any]:

    """Return the evidence available for one value in the financial table.



    A display value and its origin are intentionally separate concepts.  The

    historical cache contains values written before report-level provenance was

    introduced; those values remain visible for continuity, but this function

    labels them ``NO_SOURCE_PASSPORT`` rather than inventing a filing link.

    """

    ticker = str(ticker or "").strip().upper()

    period = str(period or "").strip().upper()

    field = str(field or "").strip()

    form = str(form or "NSBU").strip().upper()

    if not ticker:

        return {"status": "NO_DATA", "reason": "ticker is required"}

    if not re.fullmatch(r"\d{4}(?:Q[1-4])?", period):

        return {"status": "NO_DATA", "reason": "invalid financial period"}



    if field in _FINANCIAL_PASSPORT_DERIVED:

        definition = _FINANCIAL_PASSPORT_DERIVED[field]

        return {

            "status": "DERIVED",

            "period": period,

            "field": field,

            "standard": form,

            "formula": definition["formula"],

            "inputs": list(definition["inputs"]),

            "reason": "This value is calculated by the platform; open its input values for filing sources.",

        }



    source_field = _FINANCIAL_PASSPORT_FIELDS.get(field)

    if not source_field:

        return {

            "status": "NO_SOURCE_PASSPORT",

            "period": period,

            "field": field,

            "standard": form,

            "reason": "No filing-level passport is defined for this indicator.",

        }



    if form == "MSFO":

        from financial_ingestion.publication import passport

        published = passport(ticker, period, field)

        if published is not None:

            return published



    year = int(period[:4])

    quarter = int(period[-1]) if len(period) == 6 else 0

    conn = catalogue_storage.get_catalog_conn()

    try:

        siblings = catalogue_filings._org_siblings(conn, ticker) or [ticker]

        placeholders = ",".join("?" * len(siblings))

        # The normal series reader lets the requested class replace a sibling

        # where both contain the issuer's filing.  This query applies exactly

        # the same preference, then takes the newest cache write as a tiebreak.

        # Match the annual reader's explicitly filed cumulative-Q4 fallback.

        # An annual row anywhere in the issuer takes precedence, including one

        # with this particular field missing; do not blend filing perimeters.

        fallback_q4 = form == "NSBU" and quarter == 0 and not conn.execute(

            f"SELECT 1 FROM catalog_financials WHERE ticker IN ({placeholders}) "

            "AND form=? AND year=? AND quarter=0 LIMIT 1", (*siblings, form, year)).fetchone()

        source_quarter = 4 if fallback_q4 else quarter

        rows = conn.execute(

            f"SELECT ticker, {source_field} AS value, field_periods, report_id, updated_at "

            f"FROM catalog_financials WHERE ticker IN ({placeholders}) "

            "AND form=? AND year=? AND quarter=? "

            f"AND {source_field} IS NOT NULL "

            + ("AND EXISTS (SELECT 1 FROM catalog_reports r WHERE r.ticker=catalog_financials.ticker "

               "AND r.report_form=catalog_financials.form AND r.year=catalog_financials.year "

               "AND r.quarter=4) " if fallback_q4 else "") +

            "ORDER BY CASE WHEN ticker=? THEN 1 ELSE 0 END DESC, updated_at DESC",

            (*siblings, form, year, source_quarter, ticker),

        ).fetchall()

    finally:

        conn.close()



    if not rows:

        return {

            "status": "NO_DATA",

            "period": period,

            "field": field,

            "standard": form,

            "reason": "No parsed filing value exists for this period.",

        }



    row = rows[0]

    filed_periods = catalogue_codecs._decode_field_periods(row["field_periods"]) or {}

    stated_period = str(filed_periods.get(source_field) or (f"{year}Q4" if fallback_q4 else period))

    report_id = row["report_id"]

    if not report_id:

        return {

            "status": "NO_SOURCE_PASSPORT",

            "period": period,

            "field": field,

            "standard": form,

            "source_field": source_field,

            "value": row["value"],

            "reason": "The value predates report-level provenance and cannot be attributed safely.",

        }



    try:

        import provenance



        report_data = provenance.report(int(report_id))

    except Exception:  # provenance must never make the company page fail

        catalogue_settings.logger.exception("financial passport lookup failed for report %s", report_id)

        report_data = None

    if not report_data:

        return {

            "status": "NO_SOURCE_PASSPORT",

            "period": period,

            "field": field,

            "standard": form,

            "source_field": source_field,

            "value": row["value"],

            "reason": "The linked filing is no longer available in the provenance register.",

        }



    figure = next((item for item in report_data.get("figures", [])

                   if item.get("field") == source_field), None)

    source = {

        "report_id": report_data.get("id"),

        "title": report_data.get("title"),

        "report_form": report_data.get("report_form"),

        "standard": report_data.get("report_form") or form,

        "perimeter": report_data.get("org_id"),

        "period_type": report_data.get("period_type"),

        "period_year": report_data.get("period_year"),

        "period_quarter": report_data.get("period_quarter"),

        "state": report_data.get("state"),

        "state_reason": report_data.get("state_reason"),

        "pdf_url": report_data.get("pdf_url"),

        "excel_url": report_data.get("excel_url"),

        "file_hash": report_data.get("file_hash"),

        # Source publication and collection dates mean different things.  The

        # latter is the moment this platform first registered the document;

        # neither is substituted for the other when one is absent.

        "source_published_at": report_data.get("source_published_at"),

        "received_at": report_data.get("discovered_at"),

        "published_at": report_data.get("published_at"),

        "parsed_at": report_data.get("parsed_at"),

        "extraction_version": report_data.get("extraction_version"),

        "source_ticker": row["ticker"],

        "stated_period": stated_period,

    }

    if figure:

        source["page"] = figure.get("page")

        source["raw_label"] = figure.get("raw_label")

        source["raw_value"] = figure.get("value")

        source["unit_scale"] = figure.get("unit_scale")

        try:

            raw_value = float(figure.get("value"))

            scale = int(figure.get("unit_scale") or 1)

            source["normalized_value"] = raw_value * scale

            source["normalization_formula"] = "raw_value × unit_scale"

            source["sign"] = "negative" if raw_value < 0 else "positive" if raw_value > 0 else "zero"

        except (TypeError, ValueError):

            pass

    return {

        "status": "SOURCED",

        "period": period,

        "field": field,

        "standard": form,

        "source_field": source_field,

        "value": row["value"],

        "source": source,

        "reason": None if figure else "The filing is linked, but this field has no extracted page/label metadata.",

    }
