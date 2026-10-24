"""Reads for terminal screens, reusing the catalogue's publication boundary."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
import logging

import catalogue.filings as filings
import catalogue.organization as organization
from company_catalog import COMPANY_SECTORS
from securities_catalog import get_securities_map
from server.company.financials import financial_series
from server.terminal import analytics, cbu
import dividends
import company_imports

logger = logging.getLogger(__name__)


def universe():
    """One row per issuer with a listed stock; never count preferred twice."""
    approved = company_imports.approved_metadata_map()
    securities = get_securities_map()
    stocks = {t for t, row in securities.items() if str(row.get("type") or "stock").lower() != "bond"}
    kinds = organization.filing_org_types(stocks)
    result = []
    for company in filings.list_companies_with_stats():
        tickers = company.get("tickers") or [company["ticker"]]
        if not set(tickers) & stocks:
            continue
        ticker = company["ticker"]
        reviewed = [approved[t] for t in tickers if t in approved]
        if reviewed and not any(bool(r.get("catalog_visible", 1)) for r in reviewed):
            continue
        imported = approved.get(ticker) or {}
        company = {**company, "company_name": imported.get("company_name") or company.get("company_name")}
        sector = imported.get("sector") or COMPANY_SECTORS.get(ticker, "other")
        kind = organization.resolve_kind(org_type=next((kinds[t] for t in tickers if kinds.get(t)), None),
                                         name=company.get("company_name"), sector=sector)
        if kind == "financial" and any("micro" in str(kinds.get(t, "")) for t in tickers):
            continue
        result.append({**company, "name": company.get("company_name") or ticker, "sector": sector, "kind": kind})
    return result


def market_context():
    """Use the same checked share classes and capitalisation as the market."""
    import catalogue.market_store as market
    import public_contract
    import fundamentals
    securities, listings = get_securities_map(), market.get_all_listings()
    quotes = market.get_all_quotes()
    from server.market.dates import _iso_trade_date
    classes = []
    for ticker, security in securities.items():
        if str(security.get("type") or "stock").lower() == "bond":
            continue
        row = {**security, **(listings.get(ticker) or {}), "ticker": ticker}
        quote = quotes.get(str(row.get("isin") or "").upper()) or {}
        quote_day, row_day = _iso_trade_date(quote.get("trade_date")), _iso_trade_date(row.get("last_trade_date"))
        if quote_day and (not row_day or quote_day >= row_day) and analytics.number(quote.get("close_price")) is not None:
            row.update(last_price=quote["close_price"], last_trade_date=quote_day,
                       market_cap=quote.get('market_cap'), market_cap_source='openinfo_quote')
            if analytics.number(quote.get('shares_outstanding')) is not None and quote['shares_outstanding']>0:
                row['shares_outstanding']=quote['shares_outstanding']
        checked = public_contract.market_class_input(row)
        row["market_cap"] = checked["market_cap"] if checked["usable_for_issuer_cap"] else None
        row['market_input']=checked
        classes.append(row)
    return {c["ticker"]: {"market_cap": fundamentals.market_cap_issuer(group).get("value") if fundamentals.share_count_consistency(group)['consistent'] else None,
                           "excluded_classes":fundamentals.market_cap_issuer(group).get('excluded_classes',[]),
                           "price": c.get("last_price") if c['market_input']['price_age_days'] is not None and 0<=c['market_input']['price_age_days']<=c['market_input']['max_price_age_days'] else None,
                           "market_date": c.get("last_trade_date")}
            for group in fundamentals.group_by_issuer(classes).values() for c in group}


BANK_FIELDS = {
    'main': ('assets_share_pct', 'loans_share_pct', 'equity_share_pct', 'deposits_share_pct'),
    'structure': ('household_loans_bn', 'company_loans_bn', 'household_deposits_bn', 'company_deposits_bn'),
}


def bank_metrics(bank):
    return {'cbu_' + field: analytics.number((bank.get(kind) or {}).get(field))
            for kind, fields in BANK_FIELDS.items() for field in fields}


async def screener(form="NSBU", scope="separate", year=None):
    """Share simultaneous identical reads, without retaining completed results.

    SQLite batches serialize across requests as well as across issuers. The
    state belongs to the running loop, so tests/app restarts cannot inherit a
    task or lock from a closed loop. Each consumer gets its own result object.
    """
    loop = asyncio.get_running_loop()
    state = getattr(loop, '_terminal_screener_reads', None)
    if state is None:
        state = {'lock': asyncio.Lock(), 'pending': {}}
        loop._terminal_screener_reads = state
    key = (form, scope, str(year) if year is not None else None)
    task = state['pending'].get(key)
    if task is None:
        async def build():
            try:
                async with state['lock']:
                    return await _screener_batch(form, scope, year)
            finally:
                state['pending'].pop(key, None)
        task = asyncio.create_task(build())
        state['pending'][key] = task
        # A disconnected sole waiter must not leave an unobserved exception.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return deepcopy(await asyncio.shield(task))


async def _screener_batch(form, scope, year):
    from catalogue.read_batch import scope as read_scope
    with read_scope():
        return await _screener(form, scope, year)


async def _screener(form="NSBU", scope="separate", year=None):
    loop = asyncio.get_running_loop()
    companies, market, central = await asyncio.gather(loop.run_in_executor(None, universe), loop.run_in_executor(None, market_context), loop.run_in_executor(None, cbu.context))
    # SQLite issuer reads contend across executor threads: the 65-issuer
    # production probe took 1.33s serialized versus 4.19s with six readers.
    semaphore = asyncio.Semaphore(1)

    async def load(company):
        ticker = company["ticker"]
        async with semaphore:
            try:
                data = await financial_series(ticker, "annual", form, scope if form == "MSFO" else None)
            except Exception:
                logger.exception("Terminal history unavailable for %s", ticker)
                return {**company, **analytics.snapshot({}, kind=company["kind"], year=year),
                        "standard": form, "scope": scope, "issues": [{"code": "SOURCE_UNAVAILABLE"}], "years": []}
        context = market.get(ticker) or {}
        latest = max((p for p in data.get("periods", []) if len(str(p)) == 4), default=None)
        cap = context.get("market_cap") if year is None or str(year) == latest else None
        row = analytics.snapshot(data, kind=company["kind"], year=year, market_cap=cap)
        if row.get("pb") is not None and row["pb"] > 10:
            from server.terminal import journal
            journal.emit("pb_high", ticker=ticker, standard=form, period=row["period"],
                         message="Проверить число акций: P/B > 10", details={"pb": row["pb"]},
                         dedupe_key=f"{ticker}:{form}:{scope}:{row['period']}:{context.get('market_date')}:{row['pb']}")
        bank = central["banks"].get(ticker, {}) if company["kind"] == "bank" else {}
        payments = await loop.run_in_executor(None, dividends.read_snapshot, ticker)
        dividend = analytics.dividend(payments, context.get("price")) if year is None else {"dy": None}
        return {**company, **row, **context, "dy": dividend["dy"], "dividend": dividend,
                "cbu": bank, **bank_metrics(bank), "npl": (bank.get("npl") or {}).get("npl_pct"), "years": data.get("periods", []),
                "profit_history": analytics.values(data, "net_profit")}

    rows = await asyncio.gather(*(load(c) for c in companies))
    return {"ok": True, "rows": rows, "years": sorted({p for r in rows for p in r["years"] if len(str(p)) == 4}, reverse=True),
            "standard": form, "scope": scope, "deposit_rate": (central.get("deposit") or {}).get("value"),
            "deposit": central.get("deposit"), "sector_series": central.get("sector_series", {}),
            "as_of": datetime.now(timezone.utc).isoformat()}


async def issuer(ticker, form="NSBU", scope="separate"):
    loop = asyncio.get_running_loop()
    annual, quarterly, kind, index = await asyncio.gather(
        financial_series(ticker, "annual", form, scope if form == "MSFO" else None),
        financial_series(ticker, "quarterly", form, scope if form == "MSFO" else None),
        loop.run_in_executor(None, partial(organization.organization_kind, ticker)),
        loop.run_in_executor(None, partial(filings.get_company_index, ticker)))
    from financial_analysis.sector_templates import resolve_template
    template = resolve_template(index or {}, {"fund": "investment_fund", "industry": "non_financial"}.get(kind, kind))
    from server.currency import history
    central, fx, market, payments = await asyncio.gather(loop.run_in_executor(None, cbu.context), loop.run_in_executor(None, history.cached_usd), loop.run_in_executor(None, market_context), loop.run_in_executor(None, dividends.read_snapshot, ticker))
    context = market.get(ticker) or {}
    snap = {**analytics.snapshot(annual, kind=kind, market_cap=context.get("market_cap")), **context}
    payment = analytics.dividend(payments, context.get("price"))
    snap["dy"] = payment["dy"]
    bank_history=await loop.run_in_executor(None,cbu.monthly_bank_history,ticker) if kind=='bank' and central['banks'].get(ticker) else []
    growth = []
    if snap["period"]:
        for field in ("net_profit", "total_equity", "total_assets"):
            for years in (3, 5):
                growth.append({"field": field, **analytics.growth(analytics.values(annual, field), snap["period"], years, inflation=central.get("inflation"), fx=fx)})
    return {"ok": True, "ticker": ticker, "snapshot": snap, "growth": growth,
            "quarters": analytics.quarters(quarterly), "template": template, "deposit": central.get("deposit"), "dividend":payment,
            "cbu": central["banks"].get(ticker, {}), "cbu_history":bank_history, "sector": central.get("sector", {}), "sector_series":central.get("sector_series", {}),
            "macro_sources": {"inflation": cbu.INFLATION_URL, "fx": "https://cbu.uz/ru/arkhiv-kursov-valyut/"}}


async def reconciliation(ticker, scope="separate"):
    left, right = await asyncio.gather(financial_series(ticker, "annual", "NSBU"),
                                        financial_series(ticker, "annual", "MSFO", scope))
    return {"ok": True, "ticker": ticker, **analytics.reconcile(left, right)}
