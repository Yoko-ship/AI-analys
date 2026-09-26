"""Financials cli operations with explicit dependencies."""
from __future__ import annotations
import os

from runtime_preflight import COLLECTOR_REQUIREMENTS
from runtime_preflight import preflight
import argparse
import collectors.financials.backfill as collectors_financials_backfill
import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.filings as collectors_financials_filings
import collectors.financials.history as collectors_financials_history
import collectors.financials.instruments as collectors_financials_instruments
import collectors.financials.market as collectors_financials_market
import collectors.financials.refresh as collectors_financials_refresh
import collectors.financials.settings as collectors_financials_settings
import collectors.financials.trading as collectors_financials_trading


def main() -> int:

    ap = argparse.ArgumentParser()

    ap.add_argument("--push-only", action="store_true", help="skip financials refresh, push current cache")

    ap.add_argument("--no-push", action="store_true", help="refresh locally, do not push")

    ap.add_argument("--no-financials", action="store_true", help="skip the financials step")

    ap.add_argument("--bank-history-only", action="store_true",

                    help="repair bank annual and quarterly history, including previously catalogued gaps")

    ap.add_argument("--bank-history-limit", type=int, default=None,

                    help="banks per history pass (default: 2 daily, all with --bank-history-only)")

    ap.add_argument("--bank-history-ticker", help="limit --bank-history-only to one bank, e.g. BRBN")

    ap.add_argument("--bank-history-due-only", action="store_true",

                    help="with --bank-history-only, respect the seven-day rotation checkpoint")

    ap.add_argument("--no-trades", action="store_true", help="skip the trade-stats step")

    ap.add_argument("--trades-only", action="store_true", help="only fetch+push trade stats")

    ap.add_argument("--no-quotes", action="store_true",

                    help="skip the exchange-quote pass that follows the trade stats")

    ap.add_argument("--no-facts", action="store_true", help="skip the source-adapter fact step")

    ap.add_argument("--facts-only", action="store_true", help="only run+push the source-adapter facts")

    ap.add_argument("--no-listings", action="store_true", help="skip the exchange-listing registry step")

    ap.add_argument("--listings-only", action="store_true", help="only collect+push the listing registry")

    ap.add_argument("--no-gov-auctions", action="store_true",

                    help="skip the ГЦБ auction step (cbu.uz fiscal agent)")

    ap.add_argument("--gov-auctions-only", action="store_true",

                    help="only collect+push ГЦБ auction results and the key rate")

    ap.add_argument("--bank-fx-only", action="store_true",

                    help="only collect+push commercial-bank exchange rates (bankxizmatlari.uz)")

    ap.add_argument("--no-reconcile", action="store_true", help="skip the structured-JSON reconciliation push")

    ap.add_argument("--reconcile-only", action="store_true",

                    help="only reconcile financials against openinfo JSON and push (authoritative)")

    ap.add_argument("--watch-filings", action="store_true",

                    help="reconcile only the issuers that filed recently and push (cheap, hourly)")

    ap.add_argument("--watch-hours", type=int, default=None,

                    help="how far back the filing feed is read (default REPORTS_WATCH_HOURS or 48)")

    ap.add_argument("--backfill-history", type=int, nargs="?", const=12, default=None,

                    metavar="MONTHS",

                    help="one-off: seed the daily-close store from openinfo (default 12 months)")

    ap.add_argument("--backfill-financials", type=int, nargs="?", const=2015, default=None,

                    metavar="FROM_YEAR",

                    help="one-off: parse every historical annual filing into the financials cache")

    ap.add_argument("--backfill-company-financials", metavar="TICKER",

                    help="one-off: parse one issuer's historical annual filings (from 2015)")

    ap.add_argument("--backfill-quarters", type=int, nargs="?", const=2023, default=None,

                    metavar="FROM_YEAR",

                    help="one-off: parse every historical QUARTERLY filing into the financials cache")

    ap.add_argument("--backfill-company-quarterly-financials", metavar="TICKER",

                    help="one-off: re-parse one issuer's catalogued quarterly filings")

    ap.add_argument("--backfill-quarter-history", type=int, nargs="?", const=40, default=None,

                    metavar="PER_TICKER",

                    help="one-off: harvest the quarterly filings that fell out of openinfo's "

                         "ten-quarter window (default 40 workbooks per issuer)")

    ap.add_argument("--backfill-company-quarter-history", metavar="TICKER",

                    help="one-off: harvest and publish one issuer's historical quarterly filings")

    ap.add_argument("--backfill-current-section", type=int, nargs="?", const=2, default=None,

                    metavar="PERIODS",

                    help="one-off: re-parse the newest filings for the balance's current "

                         "section, which the liquidity/quick/turnover ratios need")

    ap.add_argument("--backfill-intraday", type=int, nargs="?", const=30, default=None,

                    metavar="DAYS",

                    help="one-off: bank hourly bars for the last N calendar days from "

                         "the exchange's date-filtered trade feed (default 30)")

    ap.add_argument("--backfill-day-stats", type=int, nargs="?", const=365, default=None,

                    metavar="DAYS",

                    help="one-off: bank per-session day statistics (open/high/low, trade "

                         "count, largest deal) for the last N calendar days, so a PERIOD "

                         "can be summarised the way a session is (default 365)")

    args = ap.parse_args()



    # State is owned by its module.

    collectors_financials_market.SKIP_QUOTES = bool(args.no_quotes)



    # Loudly name any package this pipeline needs but the image does not carry:

    # the per-issuer `except Exception` guards below would otherwise turn a

    # missing dependency into a run that "succeeds" having collected nothing.

    preflight(COLLECTOR_REQUIREMENTS, label="collector")



    if args.bank_history_only:

        if args.no_push:

            ap.error("--bank-history-only publishes repaired data; do not combine it with --no-push")

        try:

            return collectors_financials_backfill.backfill_bank_financials(

                args.bank_history_limit if args.bank_history_limit is not None else 1000,

                force=not args.bank_history_due_only, ticker=args.bank_history_ticker)

        except Exception:

            collectors_financials_settings.log.exception("bank history repair failed")

            return 1



    if args.backfill_financials is not None:

        try:

            return collectors_financials_backfill.backfill_financials(args.backfill_financials)

        except Exception:

            collectors_financials_settings.log.exception("financials backfill failed")

            return 1



    if args.backfill_company_financials:

        try:

            ticker = str(args.backfill_company_financials).strip().upper()

            if not ticker.isalnum():

                raise ValueError("ticker must contain letters and numbers only")

            return collectors_financials_backfill.backfill_financials(2015, tickers={ticker})

        except Exception:

            collectors_financials_settings.log.exception("company financials backfill failed")

            return 1



    if args.backfill_quarters is not None:

        try:

            return collectors_financials_backfill.backfill_quarterly_financials(args.backfill_quarters)

        except Exception:

            collectors_financials_settings.log.exception("quarterly financials backfill failed")

            return 1



    if args.backfill_company_quarterly_financials:

        try:

            ticker = str(args.backfill_company_quarterly_financials).strip().upper()

            if not ticker.isalnum():

                raise ValueError("ticker must contain letters and numbers only")

            return collectors_financials_backfill.backfill_quarterly_financials(2015, tickers={ticker})

        except Exception:

            collectors_financials_settings.log.exception("company quarterly financials backfill failed")

            return 1



    if args.backfill_quarter_history is not None:

        try:

            return collectors_financials_backfill.backfill_quarter_history(args.backfill_quarter_history)

        except Exception:

            collectors_financials_settings.log.exception("quarter-history backfill failed")

            return 1



    if args.backfill_company_quarter_history:

        try:

            return collectors_financials_backfill.backfill_company_quarter_history(args.backfill_company_quarter_history)

        except Exception:

            collectors_financials_settings.log.exception("company quarter-history backfill failed")

            return 1



    if args.backfill_current_section is not None:

        try:

            return collectors_financials_backfill.backfill_current_section(args.backfill_current_section)

        except Exception:

            collectors_financials_settings.log.exception("current-section backfill failed")

            return 1



    if args.backfill_history is not None:

        try:

            return collectors_financials_history.backfill_quote_history(args.backfill_history)

        except Exception:

            collectors_financials_settings.log.exception("history backfill failed")

            return 1



    if args.backfill_intraday is not None:

        try:

            return collectors_financials_trading.backfill_intraday(args.backfill_intraday)

        except Exception:

            collectors_financials_settings.log.exception("intraday backfill failed")

            return 1



    if args.backfill_day_stats is not None:

        try:

            return collectors_financials_trading.backfill_day_stats(args.backfill_day_stats)

        except Exception:

            collectors_financials_settings.log.exception("day-stats backfill failed")

            return 1



    if args.watch_filings:

        status = 0

        try:

            status = collectors_financials_filings.watch_filings_and_push(args.watch_hours)

        except Exception:

            collectors_financials_settings.log.exception("filing watch failed")

            status = 1

        if not args.no_push:

            collectors_financials_delivery.push_heartbeat(status)

        return status



    if args.reconcile_only:

        status = 0

        try:

            status = collectors_financials_filings.reconcile_and_push()

        except Exception:

            collectors_financials_settings.log.exception("reconcile step failed")

            status = 1

        if not args.no_push:

            collectors_financials_delivery.push_heartbeat(status)

        return status



    if args.gov_auctions_only:

        status = 0

        try:

            status = collectors_financials_instruments.push_gov_auctions()

        except Exception:

            collectors_financials_settings.log.exception("gov auctions step failed")

            status = 1

        if not args.no_push:

            collectors_financials_delivery.push_heartbeat(status)

        return status



    if args.bank_fx_only:

        status = 0

        try:

            status = collectors_financials_instruments.push_bank_fx()

        except Exception:

            collectors_financials_settings.log.exception("bank fx step failed")

            status = 1

        if not args.no_push:

            collectors_financials_delivery.push_heartbeat(status)

        return status



    rc_status = 0

    if not (args.no_financials or args.trades_only or args.facts_only or args.listings_only):

        if not args.push_only:

            collectors_financials_refresh.refresh_local()

        rows = collectors_financials_refresh.collect_rows()

        filled = sum(1 for r in rows if all(r[k] is not None for k in ("revenue", "net_income", "cash")))

        collectors_financials_settings.log.info("collected %d companies (%d full non-bank)", len(rows), filled)

        if rows and not args.no_push:

            rc_status = collectors_financials_refresh.push(rows) or rc_status



    if not (args.no_financials or args.no_push or args.trades_only or args.facts_only or args.listings_only):

        try:

            rc_status = collectors_financials_filings.push_financials_aliases() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("financials aliases step failed")

            rc_status = rc_status or 1



    if not (args.no_trades or args.no_push or args.facts_only or args.listings_only):

        try:

            rc_status = collectors_financials_trading.push_trade_stats() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("trade-stats step failed")

            rc_status = rc_status or 1



    if not (args.no_facts or args.no_push or args.trades_only or args.listings_only):

        try:

            rc_status = collectors_financials_filings.collect_and_push_facts() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("facts step failed")

            rc_status = rc_status or 1



    if not (args.no_listings or args.no_push or args.trades_only or args.facts_only):

        try:

            rc_status = collectors_financials_market.push_listings() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("listings step failed")

            rc_status = rc_status or 1



    # The ГЦБ primary market — cheap (two cbu.uz pages), monthly cadence read

    # daily so a new auction lands the morning after it is published.

    if not (args.no_gov_auctions or args.no_push or args.trades_only

            or args.facts_only or args.listings_only):

        try:

            rc_status = collectors_financials_instruments.push_gov_auctions() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("gov auctions step failed")

            rc_status = rc_status or 1



    # Authoritative structured-JSON reconciliation — runs last so it supersedes the

    # legacy Excel/PDF figures and the alias copies for every ticker openinfo can

    # source directly.

    if not (args.no_financials or args.no_push or args.push_only or args.trades_only

            or args.facts_only or args.listings_only):

        try:

            rc_status = collectors_financials_backfill.backfill_bank_financials(

                args.bank_history_limit if args.bank_history_limit is not None

                else int(os.getenv("BANK_HISTORY_BATCH", "2"))) or rc_status

        except Exception:

            collectors_financials_settings.log.exception("bank history step failed")

            rc_status = rc_status or 1



    if not (args.no_reconcile or args.no_push or args.trades_only or args.facts_only or args.listings_only):

        try:

            rc_status = collectors_financials_filings.reconcile_and_push() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("reconcile step failed")

            rc_status = rc_status or 1



    # Every push above writes figures; this is what gives them a filing to point

    # at. Runs last so it links whatever this run produced, and runs on prod

    # because the states belong to prod's registry — the collector's parse moves

    # reports through states in ITS OWN database, which no push ever carries.

    # Until this was wired, prod's registry read 1703 reports and 0 published:

    # every figure on the site was unlinked and the catalog was a queue of

    # everything (ТЗ Дополнение 1 §Б.2).

    if not (args.no_push or args.trades_only or args.facts_only):

        try:

            rc_status = collectors_financials_filings.register_catalog() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("catalog register step failed")

            rc_status = rc_status or 1



    if not (args.no_push or args.trades_only or args.facts_only):

        try:

            rc_status = collectors_financials_filings.refresh_dividends() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("dividend refresh step failed")

            rc_status = rc_status or 1

        try:

            rc_status = collectors_financials_filings.refresh_meetings() or rc_status

        except Exception:

            collectors_financials_settings.log.exception("meetings refresh step failed")

            rc_status = rc_status or 1



    if not args.no_push:

        collectors_financials_delivery.push_heartbeat(rc_status)



    return rc_status
