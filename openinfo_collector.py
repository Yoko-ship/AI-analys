"""Compatibility imports for openinfo_collector; implementations have explicit owners."""

from collectors.openinfo.cache import (
    _EXCEL_CACHE_LOCK,
    _excel_cache_file,
    _get_excel_cache,
    _load_excel_cache,
    _save_excel_cache,
    _set_excel_cache,
)

from collectors.openinfo.cells import (
    _compact_cell,
    _safe_float,
    _safe_report_number,
)

from collectors.openinfo.documents import (
    _build_report_document,
    _probe_document,
    fetch_accounting_bundle,
    fetch_available_periods,
    fetch_report_documents,
    get_company_periods,
)

from collectors.openinfo.issuers import (
    _catalog_name_for_ticker,
    _normalize_key,
    resolve_company,
)

from collectors.openinfo.market import (
    _market_summary,
    _pick_security,
    fetch_dividends,
    fetch_price_history,
    fetch_stock_screener,
)

from collectors.openinfo.pdf import (
    parse_nsbu_pdf_financials,
    preview_pdf_url,
)

from collectors.openinfo.runner import (
    _probe_screener_availability,
    collect_company_data,
    main,
)

from collectors.openinfo.settings import (
    EXCEL_ABSOLUTE_MAX_REPORTS,
    EXCEL_CACHE_PATH,
    EXCEL_CACHE_TTL_SECONDS,
    EXCEL_MAX_ANNUAL_REPORTS,
    EXCEL_MAX_BYTES,
    EXCEL_MAX_QUARTER_REPORTS,
    EXCEL_MAX_REPORTS,
    EXCEL_MAX_TABLE_ROWS_PER_SHEET,
    EXCEL_PARSER_VERSION,
    EXCEL_PARSE_ENABLED,
    OPENINFO_API_BASE,
    OPENINFO_WEB_BASE,
    REQUEST_TIMEOUT,
    logger,
)

from collectors.openinfo.spreadsheets import (
    _bounded_report_limit,
    _select_excel_documents,
    fetch_excel_report_snapshots,
    parse_excel_report_document,
    preview_excel_url,
)

from collectors.openinfo.transport import (
    _fix_mojibake,
    _json_get,
    _make_session,
)

from collectors.openinfo.workbooks import (
    EXCEL_FINANCIAL_KEYWORDS,
    _classify_excel_row,
    _excel_row_label,
    _parse_excel_workbook,
    _row_matches_financial_context,
)


if __name__ == "__main__":
    raise SystemExit(main())

import os
import time
from pathlib import Path
import requests
from openinfo_http import OPENINFO_PROXY
from openinfo_http import VERIFY_SSL

from collectors.openinfo.cache import _EXCEL_CACHE_MEMO
from collectors.openinfo.cache import _shared_excel_cache
