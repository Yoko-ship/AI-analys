"""Compare exact cached filing periods without network or language-model calls.

Amounts leave this boundary in UZS. NSBU running totals remain cumulative YTD;
IFRS is read only from published snapshots of the explicitly selected scope.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import logging
import re

import catalogue.filings as filings
import catalogue.organization as organization
import catalogue.ratios as catalog_ratios
import catalogue.snapshots as snapshots
import catalogue.market_store as market_store
from financial_ingestion import publication
from financial_analysis import profitability
from reporting import store as report_store
from securities_catalog import get_securities_map
import fundamentals
import public_contract

logger = logging.getLogger(__name__)
MAX_COMPANIES = 4
FIELDS = {
    'interest_income': 'interest_income', 'revenue': 'revenue', 'net_profit': 'net_income',
    'assets': 'total_assets', 'equity': 'total_equity', 'loan_book': 'loan_portfolio',
    'customer_funds': 'customer_funds',
}
METRICS = [*FIELDS, 'roe', 'roa', 'cost_income', 'pe', 'pb', 'price', 'market_cap', 'turnover']
PERIOD_RE = re.compile(r'^(20\d{2})(?:Q([1-4]))?$')
TICKER_RE = re.compile(r'^[A-Z0-9]{2,16}$')


class UnknownCompany(ValueError):
    pass


def normalize(tickers, period='latest', standard='NSBU', scope='separate'):
    tokens = tickers.split(',') if isinstance(tickers, str) else list(tickers)
    if len(tokens) > MAX_COMPANIES:
        raise ValueError('Choose at most four companies')
    wanted = list(dict.fromkeys(str(t).strip().upper() for t in tokens if str(t).strip()))
    if any(not TICKER_RE.fullmatch(t) for t in wanted):
        raise ValueError('Invalid ticker')
    if period != 'latest' and not PERIOD_RE.fullmatch(period):
        raise ValueError('Invalid reporting period')
    if standard not in {'NSBU', 'IFRS'} or scope not in {'separate', 'consolidated'}:
        raise ValueError('Invalid accounting standard or scope')
    return wanted


def period_order(period):
    return int(period[:4]), int(period[-1]) if 'Q' in period else 5


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
        return float(parsed) if parsed.is_finite() else None
    except (ValueError, TypeError, ArithmeticError):
        return None


def money(value):
    parsed = number(value)
    return float(Decimal(str(parsed)) * 1000) if parsed is not None else None


def universe():
    securities = get_securities_map()
    stocks = {t: s for t, s in securities.items() if str(s.get('type') or 'stock').lower() != 'bond'}
    forms = organization.filing_org_types(stocks)
    companies = []
    for ticker, security in stocks.items():
        name = security.get('company_name') or security.get('name') or ticker
        kind = organization.resolve_kind(org_type=forms.get(ticker), name=name, sector=security.get('sector'))
        companies.append({'ticker': ticker, 'name': name, 'kind': kind,
                          'family': 'bank' if kind == organization.BANK else 'corporate',
                          'share_type': 'preferred' if security.get('is_preferred') else 'ordinary',
                          'isin': security.get('isin'), 'logo': security.get('logo_url'), 'sector': security.get('sector')})
    return stocks, sorted(companies, key=lambda c: c['ticker'])


def _series(ticker, standard, scope):
    if standard == 'NSBU':
        if scope != 'separate':
            return {}, []
        return {**(snapshots.get_financials_series(ticker, 'NSBU') or {}),
                **(snapshots.get_financials_series_quarterly(ticker, 'NSBU') or {})}, []
    published = publication.snapshots(ticker, scope=scope)
    rows = {}
    for row in published:
        payload = row.get('payload') or {}
        meta = payload.get('classification') or {}
        if meta.get('scope') != scope:
            continue
        period = publication.period_key(meta)
        if PERIOD_RE.fullmatch(str(period or '')):
            rows[period] = {field: float(Decimal(str(value)) / 1000)
                            for field, value in (payload.get('normalized_uzs') or {}).items()
                            if number(value) is not None}
    return rows, published


def options(tickers=(), standard='NSBU', scope='separate'):
    wanted = normalize(tickers, standard=standard, scope=scope)
    securities, companies = universe()
    if any(t not in securities for t in wanted):
        raise UnknownCompany('Unknown company')
    available = []
    for ticker in wanted:
        series, _ = _series(ticker, standard, scope)
        available.append({p for p, row in series.items() if PERIOD_RE.fullmatch(p)
                          and catalog_ratios.catalog_period_problem(row) is None})
    periods = sorted(set().union(*available) if available else set(), key=period_order, reverse=True)
    return {'ok': True, 'companies': companies, 'periods': periods,
            'standard': standard, 'scope': scope, 'max_companies': MAX_COMPANIES}


def market_rows(securities):
    listings, quotes = market_store.get_all_listings(), market_store.get_all_quotes()
    rows = {}
    from server.market.dates import _iso_trade_date
    for ticker, security in securities.items():
        row = {**security, **(listings.get(ticker) or {}), 'ticker': ticker}
        quote = quotes.get(str(row.get('isin') or '').upper()) or {}
        quote_day = _iso_trade_date(quote.get('trade_date'))
        row_day = _iso_trade_date(row.get('last_trade_date'))
        if quote_day and (not row_day or quote_day >= row_day) and number(quote.get('close_price')) is not None:
            row.update(last_price=quote['close_price'], last_trade_date=quote_day, market_cap=None)
        row['last_trade_date'] = _iso_trade_date(row.get('last_trade_date'))
        rows[ticker] = row
    return rows


def _source(ticker, period, standard, scope, published):
    if standard == 'NSBU' and scope != 'separate':
        return None
    if standard == 'IFRS':
        row = next((r for r in published if publication.period_key((r.get('payload') or {}).get('classification') or {}) == period), None)
        if row:
            source = (row.get('payload') or {}).get('source') or {}
            return {'snapshot_id': row.get('id'), 'url': source.get('pdf_url') or source.get('url'),
                    'publication_date': source.get('published_at') or source.get('publication_date'),
                    'received_at': row.get('created_at'), 'period': period, 'scope': scope}
        return None
    reports = filings.get_company_reports(ticker) or []
    candidates = [r for r in reports if r.get('report_form') == 'NSBU'
                  and str(r.get('year')) == period[:4]
                  and int(r.get('quarter') or 0) == (int(period[-1]) if 'Q' in period else 0)]
    row = max(candidates, key=lambda r: str(r.get('published_at') or ''), default=None)
    return {'document_id': row.get('report_id'), 'url': row.get('pdf_url') or row.get('excel_url'),
            'publication_date': row.get('published_at'), 'period': period, 'scope': scope} if row else None


def _statement(ticker, period, standard, scope, series):
    if period not in series:
        return {}, 'missing_period'
    if standard == 'NSBU':
        payload = catalog_ratios.get_cached_catalog_period(ticker, 'NSBU', int(period[:4]), int(period[-1]) if 'Q' in period else 0)
        return (dict(payload.get('all_values') or {}), None) if payload.get('has_data') else ({}, (payload.get('unavailable') or {}).get('code', 'unavailable'))
    row = series[period]
    problem = catalog_ratios.catalog_period_problem(row)
    return ({}, problem['code']) if problem else (dict(row), None)


def _extra_facts(ticker, period, standard, scope):
    """Read verified numeric lines already published; never generate a report."""
    try:
        index = filings.get_company_index(ticker) or {}
        report = report_store.latest_publication(str(index.get('org_id') or ticker), 'ru', standard.lower())
    except Exception:
        logger.exception('comparison: optional published facts unavailable for %s', ticker)
        return {}
    if not report or report.get('period') != period or report.get('scope') != scope or report.get('status') not in {'available', 'stale'}:
        return {}
    return {fact.get('metric_code'): fact for fact in report.get('verified_facts') or []
            if fact.get('verification_status') == 'verified' and fact.get('period') == period
            and fact.get('consolidation_scope') == scope and str(fact.get('accounting_standard') or '').upper() == standard
            and fact.get('unit') in {'thousand UZS', 'UZS'} and fact.get('source_url')}


def compare(tickers, period='latest', standard='NSBU', scope='separate'):
    wanted = normalize(tickers, period, standard, scope)
    if not wanted:
        raise ValueError('Choose at least one company')
    securities, all_companies = universe()
    if any(t not in securities for t in wanted):
        raise UnknownCompany('Unknown company')
    by_ticker = {c['ticker']: c for c in all_companies}
    loaded = {t: _series(t, standard, scope) for t in wanted}
    if period == 'latest':
        available = [{p for p, row in series.items() if PERIOD_RE.fullmatch(p)
                      and catalog_ratios.catalog_period_problem(row) is None} for series, _ in loaded.values()]
        shared = set.intersection(*available) if available else set()
        period = max(shared or set().union(*available), key=period_order, default=None)
    market = market_rows(securities)
    classes = []
    for ticker, row in market.items():
        checked = public_contract.market_class_input(row)
        classes.append({**row, 'market_cap': checked['market_cap'] if checked['usable_for_issuer_cap'] else None, 'market_input': checked})
    groups = fundamentals.group_by_issuer(classes)
    class_groups = {c['ticker']: members for members in groups.values() for c in members}
    trades = market_store.get_all_trade_stats()
    columns = []
    for ticker in wanted:
        company = by_ticker[ticker]
        series, published = loaded[ticker]
        current, problem = _statement(ticker, period, standard, scope, series) if period else ({}, 'missing_period')
        previous_period = str(int(period[:4]) - 1) + period[4:] if period else None
        opening_period = str(int(period[:4]) - 1) if period else None
        previous, _ = _statement(ticker, previous_period, standard, scope, series) if previous_period else ({}, None)
        opening, _ = _statement(ticker, opening_period, standard, scope, series) if opening_period else ({}, None)
        source = _source(ticker, period, standard, scope, published) if period else None
        months = int(period[-1]) * 3 if period and 'Q' in period else 12
        extra = _extra_facts(ticker, period, standard, scope) if current else {}
        cells = {}
        for key, field in FIELDS.items():
            applicable = not ((key in {'interest_income', 'loan_book', 'customer_funds'} and company['family'] != 'bank')
                              or (key == 'revenue' and company['kind'] in {'bank', 'fund'}))
            value = current.get(field)
            if value is None and standard == 'IFRS' and company['family'] == 'bank':
                alias = {'loan_book': 'loans_to_customers', 'customer_funds': 'customer_deposits'}.get(key)
                value = current.get(alias) if alias else None
            # In the NSBU bank form the cache's revenue field is interest income.
            if key == 'interest_income' and standard == 'NSBU' and company['family'] == 'bank':
                value = current.get('interest_income', current.get('revenue'))
            cell_source = source
            if value is None and field in extra:
                fact = extra[field]
                value = number(fact.get('value'))
                if fact['unit'] == 'UZS' and value is not None:
                    value /= 1000
                cell_source = {'url': fact['source_url'], 'document_id': fact.get('source_document_id'), 'publication_date': fact.get('source_published_at'), 'period': period, 'scope': scope}
            cells[key] = {'value': money(value) if applicable else None,
                          'status': 'not_applicable' if not applicable else 'reported' if number(value) is not None else 'unavailable',
                          'period': period, 'unit': 'UZS', 'source': cell_source, 'change': None, 'reason': problem}
        cur_profit, prior_profit = number(current.get('net_income')), number(previous.get('net_income'))
        if cur_profit is not None and prior_profit not in (None, 0):
            cells['net_profit']['change'] = (cur_profit - prior_profit) / abs(prior_profit) * 100
        for key, result in profitability.returns(current, opening, months=months).items():
            cells[key] = {**result, 'status': 'derived' if result['value'] is not None else 'unavailable',
                          'period': period, 'unit': '%', 'source': source, 'change': None}
        from server.catalog.analysis import kind_metrics
        payload = {'all_values': current, 'metrics': {}, 'period_months': months}
        cir = kind_metrics(company['kind'], payload).get('cost_to_income') if company['family'] == 'bank' else None
        cells['cost_income'] = {'value': cir, 'status': 'derived' if cir is not None else 'unavailable' if company['family'] == 'bank' else 'not_applicable',
                                'period': period, 'unit': '%', 'source': source, 'change': None,
                                'formula': 'abs(operating_expenses) / gross_profit * 100'}
        def financial_row(values, label):
            return {**{k: money(v) for k, v in values.items() if number(v) is not None},
                    'balance': {'equity_end': money(values.get('total_equity')),
                                'assets_end': money(values.get('total_assets'))},
                    'year': int(label[:4]), 'quarter': int(label[-1]) if 'Q' in label else 0,
                    'org_type': 'bank' if company['family'] == 'bank' else company['kind']}
        fin = financial_row(current, period) if current and period else None
        if fin and 'Q' in period:
            fin['annual'] = financial_row(opening, opening_period) if opening else None
            fin['prior'] = financial_row(previous, previous_period) if previous else None
        multiples = fundamentals.issuer_multiples(class_groups.get(ticker, []), fin, {})
        for key in ['pe', 'pb', 'market_cap']:
            result = multiples.get('market_cap_issuer' if key == 'market_cap' else key) or {}
            cells[key] = {**result, 'value': number(result.get('value')), 'status': result.get('status') or 'unavailable',
                          'period': period, 'unit': 'UZS' if key == 'market_cap' else 'x', 'source': source,
                          'change': None, 'formula': 'sum(class_price * class_shares)' if key == 'market_cap' else 'issuer_market_cap / ' + ('TTM_net_income' if key == 'pe' else 'ending_equity')}
        row = market.get(ticker) or {}
        trade = trades.get(str(row.get('isin') or '').upper()) or {}
        market_source = {'url': row.get('source_url') or 'https://uzse.uz', 'isin': row.get('isin'), 'as_of': row.get('last_trade_date')}
        cells['market_cap']['source'] = market_source
        for key, value in [('price', number(row.get('last_price'))), ('turnover', number(trade.get('total_value')))]:
            cells[key] = {'value': value, 'status': 'reported' if value is not None else 'unavailable',
                          'unit': 'UZS', 'period': None, 'as_of': trade.get('trade_date') if key == 'turnover' else row.get('last_trade_date'),
                          'source': market_source, 'change': None}
        columns.append({**company, 'status': 'available' if current else 'unavailable', 'reason': problem,
                        'period': period, 'metrics': cells, 'source': source, 'market_as_of': row.get('last_trade_date'),
                        'market_inputs': [c.get('market_input') for c in class_groups.get(ticker, [])]})
    return {'ok': True, 'version': 'company-comparison-1', 'standard': standard, 'scope': scope,
            'currency': 'UZS', 'period': period, 'period_basis': 'cumulative_ytd' if period and 'Q' in period else 'annual',
            'generated_at': datetime.now(timezone.utc).isoformat(), 'companies': columns}
