"""Compatibility imports for collector_financials; implementations have explicit owners."""
from dotenv import load_dotenv
import os
load_dotenv()
os.environ.setdefault("FINANCIALS_ENRICH_ON_READ", "1")

from collectors.financials.backfill import (
    backfill_company_quarter_history,
    backfill_current_section,
    backfill_financials,
    backfill_quarter_history,
    backfill_quarterly_financials,
)

from collectors.financials.cli import (
    main,
)

from collectors.financials.delivery import (
    _post,
    _stamp_step,
    push_heartbeat,
)

from collectors.financials.filings import (
    collect_and_push_facts,
    push_financials_aliases,
    reconcile_and_push,
    refresh_dividends,
    refresh_meetings,
    register_catalog,
    watch_filings_and_push,
)

from collectors.financials.history import (
    _history_universe,
    backfill_quote_history,
)

from collectors.financials.instruments import (
    _board_bonds,
    push_bank_fx,
    push_bond_reference,
    push_gov_auctions,
)

from collectors.financials.market import (
    SKIP_QUOTES,
    audit_board,
    board_securities,
    push_listings,
    push_quotes,
    quotes_from_archive,
)

from collectors.financials.refresh import (
    collect_rows,
    push,
    refresh_local,
)

from collectors.financials.retry import (
    RETRY_ATTEMPTS,
    RETRY_WAIT_SECONDS,
    _wait_and_retry,
)

from collectors.financials.settings import (
    DEFAULT_URL,
    KEYS,
    log,
)

from collectors.financials.trading import (
    backfill_day_stats,
    backfill_intraday,
    push_trade_stats,
)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())

import os
import sys
import time
import requests

from collectors.financials.backfill import _bank_history_remote_attempt
from collectors.financials.instruments import _filed_terms_for
from collectors.financials.backfill import backfill_bank_financials
