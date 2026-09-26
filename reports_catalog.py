"""Compatibility imports for reports_catalog; implementations have explicit owners."""

from catalogue.codecs import (
    _BALANCE_BASE_KEYS,
    _BALANCE_INSURANCE_KEYS,
    _BALANCE_KEYS,
    _PRIOR_KEYS,
    _balance_total_fallback,
    _decode_balance_period,
    _decode_field_periods,
    _decode_prior_period,
    _encode_balance_period,
    _encode_field_periods,
    _encode_prior_period,
    _financials_num,
    _financials_period,
)

from catalogue.dynamics import (
    build_dynamics_data,
)

from catalogue.evidence import (
    _FINANCIAL_PASSPORT_DERIVED,
    _FINANCIAL_PASSPORT_FIELDS,
    get_financial_value_passport,
)

from catalogue.facts import (
    _cleanup_invalid_fact_periods,
    audit_financials_consistency,
    get_catalog_coverage,
    get_facts,
    purge_premature_annual_facts,
    upsert_facts,
)

from catalogue.fields import (
    BALANCE_MONEY_KEYS,
    FACT_MONEY_FIELDS,
    FACT_PERCENT_FIELDS,
    FACT_SHARE_FIELDS,
    FIN_MONEY_FIELDS,
    NSBU_THOUSANDS_UZS,
    RATIO_MONEY_FIELDS,
    _FIN_CURRENT_FIELDS,
    _FIN_FIELDS,
    _MIN_PLAUSIBLE,
    _RATIO_FIELDS,
)

from catalogue.filings import (
    FULL_SWEEP_KEY,
    _canonical_ticker,
    _cleanup_old_notifications,
    _org_siblings,
    _purge_ticker_data,
    _report_key,
    _upsert_report,
    full_sweep_age_hours,
    get_catalog_stats,
    get_company_index,
    get_company_reports,
    get_new_reports_for_tickers,
    get_recent_filings,
    get_recent_new_reports,
    get_report_urls,
    get_state,
    list_companies_with_stats,
    set_state,
)

from catalogue.financial_store import (
    _FINANCIALS_SEED_PATH,
    _FINANCIAL_KEYS,
    _maybe_seed_financials,
    _seed_lock,
    _seeded,
    bulk_replace_financials,
    bulk_upsert_financials,
    upsert_financials_cache,
    upsert_ratio_cache,
)

from catalogue.history import (
    EXCEL_HARVEST_MAX_BYTES,
    _parse_workbook_uncached,
    harvest_historical_quarters,
    parse_catalogued_report,
    unified_quarterly_records,
)

from catalogue.market_store import (
    INTRADAY_KEEP_DAYS,
    _INTRADAY_COLS,
    _LISTING_COLS,
    _PURGE_TABLES,
    _QUOTE_COLS,
    _QUOTE_HISTORY_COLS,
    _QUOTE_HISTORY_DETAIL_COLS,
    _TRADE_STAT_KEYS,
    bulk_upsert_intraday_history,
    bulk_upsert_listings,
    bulk_upsert_quote_history,
    bulk_upsert_quotes,
    bulk_upsert_trade_stats,
    get_all_listings,
    get_all_quotes,
    get_all_trade_stats,
    get_intraday_history,
    get_quote_history,
    purge_delisted,
    trade_stats_as_history,
)

from catalogue.parsing import (
    _CASH_ACCOUNT_CODES,
    _CURRENT_ASSETS_SECTION_FORMULAS,
    _INSURANCE_EQUITY_FORMULAS,
    _INSURANCE_GROSS_RESERVE_FORMULAS,
    _INSURANCE_NET_RESERVE_FORMULAS,
    _INSURANCE_REINSURER_SHARE_FORMULAS,
    _LABEL_EXCLUSIONS,
    _LABEL_PATTERNS,
    _LIABILITIES_SECTION_FORMULAS,
    _extract_cash,
    _extract_current_assets,
    _extract_formula_total,
    _extract_liabilities_total,
    _extract_metric,
    _gather_rows,
    _row_value,
    _squash,
    _strict_balance_row_value,
    compute_financial_ratios,
    extract_insurance_balance,
)

from catalogue.periods import (
    _PUB_MONTH_QUARTER,
    _QUARTER_END_MONTH,
    _STATED_QUARTER_LABELS,
    _completed_annual_is_recent,
    _effective_annual_year,
    _extract_quarter,
    _extract_year,
    _fact_period_rank,
    _hours_since,
    _is_fresh,
    _is_future_period,
    _is_premature_annual_period,
    _is_premature_annual_year,
    _latest_complete_fiscal_year,
    _now_iso,
    _period_key,
    _period_months,
    _quarter_period_from_publication,
    _stated_quarter,
)

from catalogue.ratios import (
    _RATIOS_CACHE_TTL_SECONDS,
    _company_equity,
    _derived_equity,
    _ratios_cache,
    _ratios_cache_lock,
    _ratios_cached,
    _row_period,
    _ticker_org_map,
    get_all_ratios,
    get_company_ratios_cached,
    get_sector_averages,
    invalidate_ratios_cache,
)

from catalogue.refresh import (
    _PROVENANCE_FIELDS,
    _fin_candidates,
    _latest_excel_report,
    _register_parse,
    _sync_missing_companies,
    backfill_report_links,
    refresh_financials_cache,
    refresh_financials_from_pdf,
)

from catalogue.schema import (
    _init_schema,
)

from catalogue.settings import (
    CATALOG_SYNC_TTL_HOURS,
    FINANCIALS_ANNUAL_FRESH_DAYS,
    FINANCIALS_BATCH,
    FINANCIALS_SYNC_BATCH,
    FINANCIALS_TTL_DAYS,
    _FIN_LOCK,
    _SYNC_LOCK,
    _TICKER_TO_NAME,
    logger,
)

from catalogue.snapshots import (
    _CORRECTION_BALANCE_KEYS,
    _TTM_COMPANION_KEYS,
    _apply_registered_financial_corrections,
    _attach_annual_companion,
    _attach_prior_interim_companion,
    _correction_period,
    _enrich_financials_from_facts,
    _fin_row_fields,
    _financials_enrich_enabled,
    _inherit_financials_by_org,
    _prior_matches,
    get_all_financials,
    get_financials_series,
    get_financials_series_quarterly,
)

from catalogue.sources import (
    _ANNUAL_RECORD_EXCLUSIONS,
    _LEGAL_FORM_TOKENS,
    _ORG_TYPE_CANDIDATES,
    _build_report_document,
    _fetch_main_results,
    _json_get,
    _make_session,
    _nsbu_export_urls,
    _org_search_terms,
    _probe_org_type,
    _unified_pdf_id_map,
    fetch_report_excel_data,
    parse_excel_report_document,
    resolve_company,
)

from catalogue.storage import (
    APP_DATA_DIR,
    _catalog_db_path,
    get_catalog_conn,
)

from catalogue.sync import (
    _DETERMINISTIC_RESOLVERS,
    _sweep_representatives,
    _sync_auditions,
    discover_and_upsert_securities,
    sync_all,
    sync_company,
    sync_recent_filings,
    sync_stale_companies,
)

# Preserve imported constants used by existing catalogue callers.
from collections.abc import Sequence
from company_catalog import COMPANY_CATALOG
from company_catalog import COMPANY_SECTORS
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from db import sqlite_connect
from delisted import DELISTED_ISINS
from delisted import DELISTED_TICKERS
from entity_resolver import ORG_OVERRIDES
from entity_resolver import UNRELIABLE_FINANCIALS
from financial_corrections import correction_periods_for
from financial_corrections import corrections_for
from collectors.openinfo.settings import OPENINFO_API_BASE
from collectors.openinfo.settings import OPENINFO_WEB_BASE
from collectors.openinfo.settings import REQUEST_TIMEOUT
from pathlib import Path
from typing import Any
from typing import Iterable
from urllib.parse import urlencode
import dbx
import json
import logging
import os
import re
import sqlite3
import threading
import time

from catalogue.ratios import _CATALOG_ANALYSIS_VALUE_KEYS
from catalogue.fields import _IFRS_BANK_FIELDS
from catalogue.ratios import _cached_balance
from catalogue.ratios import _cached_catalog_ratio_payload
from catalogue.parsing import _commercial_period_expenses
from catalogue.snapshots import _remember_ifrs_sources
from catalogue.snapshots import _unified_statement_records
from catalogue.ratios import build_cached_catalog_dynamics
from catalogue.ratios import get_all_ratios_cached
from catalogue.ratios import get_cached_catalog_period
from catalogue.history import get_financial_history_coverage
from catalogue.history import repair_statement_links
