"""Investor indicators over verified report facts and compatible filed disclosures.

Report money is thousand UZS. Per-share amounts are UZS and share counts are
individual shares. Independently reviewed share disclosures may supply dated
counts and rights, never another standard's profit or equity. Current exchange
counts and nominal capital do not establish historical share entitlement.
"""
from collections import defaultdict
from datetime import date, timedelta

import corporate_actions
from copy import deepcopy
import logging

from financial_columns.nsbu import ebit as nsbu_ebit, ebit_line
from .sector_numbers import decimal, number, ratio, total

ADDITIONAL = {'P2', 'P7', 'P8'}
VERSION = 'report-investor-metrics-9'
HISTORICAL_METRICS = {'book_value_per_share', 'price_to_book', 'eps_basic', 'ebit'}
SHARE_METRICS = {'price_to_book', 'book_value_per_share', 'eps_basic', 'eps_closing_estimate'}
NAMES = {
    'ebit': ('EBIT', 'EBIT', 'EBIT'),
    'book_value_per_share': ('Балансовая стоимость акции (BVPS)', 'Aksiyaning balans qiymati (BVPS)', 'Book value per ordinary share (BVPS)'),
    'eps_closing_estimate': ('Приблизительная EPS по числу акций на конец периода', 'Davr oxiridagi aksiyalar bo‘yicha taxminiy EPS', 'Estimated EPS using closing shares'),
    'operating_margin': ('Операционная маржа', 'Operatsion marja', 'Operating margin'),
    'book_value': ('Балансовая стоимость капитала', 'Kapitalning balans qiymati', 'Book value of equity'),
    'interest_debt_to_equity': ('Долг / капитал (D/E)', 'Qarz / kapital (D/E)', 'Debt / equity (D/E)'),
    'price_to_book': ('P/BV', 'P/BV', 'P/BV'),
    'eps_basic': ('Базовая прибыль на акцию (EPS)', 'Aksiyaga bazaviy foyda (EPS)', 'Basic earnings per share (EPS)'),
}
MEANINGS = {
    'ebit': ('Прибыль до налога плюс признанные процентные расходы за тот же период.', 'Soliqqacha foyda va shu davrda tan olingan foiz xarajatlari yig‘indisi.', 'Profit before tax plus recognised interest expense for the same period.'),
    'book_value_per_share': ('Капитал обычных акционеров материнской компании на одну обычную акцию в обращении.', 'Bosh kompaniya oddiy aksiyadorlari kapitalining bitta muomaladagi oddiy aksiyaga to‘g‘ri keladigan qismi.', 'Parent ordinary shareholders’ equity per outstanding ordinary share at the balance sheet date.'),
    'eps_closing_estimate': ('Прибыль обычных акционеров делится на количество акций на конец периода.', 'Oddiy aksiyadorlar foydasi davr oxiridagi aksiyalar soniga bo‘linadi.', 'Ordinary shareholders’ profit divided by closing ordinary shares.'),
    'operating_margin': ('Операционная прибыль / выручка за тот же период. Прибыль до налога не подставляется.',
                        'Bir davrdagi operatsion foyda / tushum. Soliqqacha foyda bilan almashtirilmaydi.',
                        'Operating profit / revenue for the same period. Pre-tax profit is not substituted.'),
    'book_value': ('Собственный капитал на отчётную дату, тыс. UZS; весь капитал, включая неконтролирующие доли при консолидации.',
                   'Hisobot sanasidagi jami o‘z kapitali, ming UZS; konsolidatsiyada nazorat qilinmaydigan ulushlar ham kiradi.',
                   'Total equity at the reporting date, thousand UZS; includes non-controlling interests in consolidated accounts.'),
    'interest_debt_to_equity': ('Процентный долг / собственный капитал. НСБУ: строки 570 + 580 + 730 + 740 + 750 формы 1. МСФО: краткосрочные и долгосрочные заимствования плюс аренда. Отсутствующий компонент не равен нулю.',
                              'Foizli qarz / o‘z kapitali. NSBU: 1-shaklning 570 + 580 + 730 + 740 + 750 satrlari. MHXS: qisqa va uzoq muddatli qarzlar hamda ijara. Yetishmagan qiymat nol emas.',
                              'Interest-bearing debt / total equity. NSBU: Form 1 lines 570 + 580 + 730 + 740 + 750. IFRS: short- and long-term borrowings plus lease liabilities. Missing components are not zero.'),
    'price_to_book': ('Цена обычной акции / баланс на обычную акцию. Используются подтверждённые капитал обычных акционеров и число акций на отчётную дату; дата котировки указана отдельно.',
                      'Oddiy aksiya narxi / oddiy aksiyaning balans qiymati. Hisobot sanasidagi tasdiqlangan kapital va aksiyalar soni; kotirovka sanasi alohida.',
                      'Ordinary share price / ordinary book value per share. Uses verified ordinary equity and shares at the reporting date; the quote date is shown separately.'),
    'eps_basic': ('Опубликованная базовая EPS либо прибыль обычных акционеров / средневзвешенное число обычных акций за тот же период. UZS на акцию, без пересчёта на год.',
                  'E’lon qilingan bazaviy EPS yoki oddiy aksiyadorlar foydasi / shu davrdagi oddiy aksiyalarning o‘rtacha tortilgan soni. UZS/aksiya, yillikka aylantirilmaydi.',
                  'Disclosed basic EPS, or profit attributable to ordinary shareholders / weighted average ordinary shares for the same period. UZS per share, without annualisation.'),
}


def _facts(report):
    return {f['metric_code']: f for f in report.get('verified_facts', [])
            if f.get('verification_status') == 'verified'
            and f.get('period') == report.get('period')
            and f.get('unit_normalized') == 'thousand UZS'}


def _load(report):
    """Read already imported sources only; no ingestion or network on a page view."""
    from financial_columns import observations, source_store
    from financial_ingestion import publication
    issuer = report['issuer']
    if report['standard'].lower() == 'nsbu':
        docs = source_store.read(issuer['id'], standard='NSBU', scope=report['scope'], period_end=report['financial_as_of'])
        rows = observations.nsbu([d for d in docs if not d.get('period_end') or d['period_end'] == report['financial_as_of']])
    else:
        docs = publication.snapshots(issuer['ticker'], scope=report['scope'])
        rows = observations.ifrs([d for d in docs if d['period_end'] == report['financial_as_of']])
    observations.check(rows)
    return rows


def _compatible(report, rows, facts, *, income=False):
    """Match a source revision using the statements needed by the indicator."""
    standard = 'NSBU' if report['standard'].lower() == 'nsbu' else 'MSFO'
    end = report['financial_as_of']
    groups = defaultdict(list)
    for row in rows:
        if (str(row.get('issuer_id')) == str(report['issuer']['id']) and row.get('standard') == standard
                and row.get('scope') == report['scope'] and row.get('period_end') == end
                and row.get('role') != 'COMPARATIVE' and row.get('source_url') and row.get('source_version')):
            groups[row['source_version']].append(row)
    accepted = []
    for group in groups.values():
        # One thousand UZS is the source form's existing rounding tolerance.
        keys = ['total_assets', 'total_equity']
        if income:
            income_keys = [key for key in ('net_income', 'revenue')
                           if key in facts and any(r.get('metric_id') == key for r in group)]
            if income_keys:
                keys = income_keys
        anchors = [_pick(group, key, 'UZS_thousand', end,
                         end[:4] + '-01-01' if key in {'net_income', 'revenue'} else None) for key in keys]
        expected = [decimal(facts.get(key, {}).get('value')) for key in keys]
        if all(a['value'] is not None and e is not None and abs(a['value'] - e) <= 1 for a, e in zip(anchors, expected)):
            accepted.append(group)
    # Independently plausible revisions must not supply halves of one ratio.
    return accepted[0] if len(accepted) == 1 else []


def _pick(rows, key, unit, end, start=None):
    candidates = [r for r in rows if r.get('metric_id') == key and r.get('unit') == unit
                  and r.get('period_end') == end and (start is None or r.get('period_start') == start)]
    values = {decimal(r.get('value')) for r in candidates}
    good = candidates and all(r.get('quality') in {'valid', 'warn'} for r in candidates)
    value = next(iter(values)) if good and len(values) == 1 else None
    return {'value': value, 'components': candidates}


def calculate(report, rows, share_basis=None):
    facts = _facts(report)
    end, start = report['financial_as_of'], report['financial_as_of'][:4] + '-01-01'
    balance_rows = _compatible(report, rows, facts)
    income_rows = _compatible(report, rows, facts, income=True)
    # A failed income check must not discard independently verified balance
    # sheet inputs. EPS still requires the matching income revision as well.
    pick = lambda key, unit='UZS_thousand', flow=False: _pick(
        income_rows if flow else balance_rows, key, unit, end, start if flow else None)
    fact = lambda key: {'value': decimal(facts.get(key, {}).get('value')), 'components': [facts[key]] if key in facts else []}
    basis = share_basis or {}
    basis_ok = (basis.get('verification_status') == 'verified'
                and str(basis.get('issuer_id')) == str(report['issuer']['id'])
                and basis.get('ticker') == report['issuer']['ticker']
                and basis.get('scope') == report['scope'] and basis.get('period_end') == end)
    capital_evidence = []
    if basis_ok and 'closing_share_capital_thousand' in basis:
        capital, treasury = pick('share_capital'), pick('treasury_shares')
        basis_ok = (report['standard'].lower() == 'nsbu'
                    and capital['value'] == decimal(basis['closing_share_capital_thousand'])
                    and treasury['value'] == 0)
        capital_evidence = capital['components'] + treasury['components']
    ordinary_only = basis_ok and basis.get('ordinary_only') is True
    ordinary_at_close = basis_ok and basis.get('ordinary_only_at_end') is True

    def disclosed_count(part, key, *, flow=False):
        # A conflicting/blocked source cell is not a missing source cell.
        if part['components'] or not basis_ok or (flow and basis.get('period_start') != start):
            return part
        value = decimal(basis.get(key))
        if value is None or value <= 0:
            return part
        return {'value': value, 'components': [{**basis, 'metric_id': key, 'value': str(value)}, *capital_evidence]}

    def ordinary_fact(part, key, *, flow=False):
        ordinary_context = ordinary_only and basis.get('period_start') == start if flow else ordinary_only or ordinary_at_close
        if part['components']:
            return part
        group = fact(key)
        parent = group
        if report['scope'] == 'consolidated':
            parent = pick('profit_owners' if flow else 'equity_owners', flow=flow)
            minority = pick('profit_nci' if flow else 'nci', flow=flow)
            if minority['components']:
                derived = group['value'] - minority['value'] if None not in (group['value'], minority['value']) else None
                if parent['components'] and (parent['value'] is None or derived is None or abs(parent['value'] - derived) > 1):
                    derived = None
                    parent = {**parent, 'components': [{**c, 'attribution_conflict': True} for c in parent['components']]}
                parent = {'value': derived, 'components': parent['components'] + group['components'] + minority['components']}
        elif report['scope'] != 'separate':
            return part
        claim = pick('preferred_profit_allocation' if flow else 'preferred_equity_claim', flow=flow)
        if claim['components']:
            amount = claim['value']
            consistent = amount is not None and amount >= 0 and (not ordinary_context or amount == 0)
            return {'value': parent['value'] - amount if consistent and parent['value'] is not None else None,
                    'components': parent['components'] + claim['components']}
        if not ordinary_context:
            return part
        return {'value': parent['value'], 'components': parent['components'] +
                [{**basis, 'metric_id': 'ordinary_only' if ordinary_only else 'ordinary_only_at_end'}]}
    result = []

    def emit(code, value, formula, parts, unit='ratio', reason='INPUTS_MISSING', **extra):
        result.append({
            'metric': code, 'metric_code': code, 'method_id': f'{VERSION}:{code}',
            **dict(zip(('name_ru', 'name_uz', 'name_en'), NAMES[code])),
            **dict(zip(('meaning_ru', 'meaning_uz', 'meaning_en'), MEANINGS[code])),
            'value': number(value), 'raw_result': str(value) if value is not None else None,
            'unit': unit, 'formula': formula, 'period': report['period'], 'period_end': end,
            'accounting_standard': report['standard'].upper(), 'scope': report['scope'],
            'publication_date': (report.get('sources') or [{}])[0].get('publication_date'),
            'period_basis': report.get('period_basis'), 'isin': (report.get('instrument') or {}).get('isin'),
            'origin': 'calculated', 'verification_status': 'verified' if value is not None else 'unavailable',
            'calculation_status': ('verified' if value is not None else 'conflict' if any(
                c.get('quality') == 'blocked' or c.get('attribution_conflict') for p in parts for c in p['components'])
                else 'missing_or_invalid_components'),
            'reason_code': None if value is not None else reason,
            'numerator_value': number(parts[0]['value']) if parts else None,
            'denominator_value': number(parts[1]['value']) if len(parts) > 1 else None,
            'components': [deepcopy(c) for p in parts for c in p['components']],
            **extra,
        })

    operating, revenue, equity = fact('operating_income'), fact('revenue'), fact('total_equity')
    emit('operating_margin', ratio(operating['value'], revenue['value'], True),
         'operating_income / revenue × 100', [operating, revenue], 'percent')
    emit('book_value', equity['value'], 'total_equity = total_assets − total_liabilities', [equity], 'UZS_thousand')
    fields = (['bank_borrowings_long', 'other_borrowings_long', 'bank_borrowings_short',
               'other_borrowings_short', 'current_portion_long_term_debt'] if report['standard'].lower() == 'nsbu'
              else ['borrowings_short', 'borrowings_long', 'lease_liabilities'])
    debt_parts = [pick(k) for k in fields]
    debt = {'value': total(*(p['value'] for p in debt_parts)), 'components': [c for p in debt_parts for c in p['components']]}
    if any(p['value'] is not None and p['value'] < 0 for p in debt_parts):
        debt['value'] = None
    emit('interest_debt_to_equity', ratio(debt['value'], equity['value']),
         f"({' + '.join(fields)}) / total_equity", [debt, equity], reason='DEBT_INPUTS_MISSING')

    if report['standard'].lower() == 'nsbu' and enterprise(report):
        validated = [{**r, 'quality': 'blocked', 'reason': 'CODE_LABEL_MISMATCH'} if not ebit_line(r) else r
                     for r in income_rows if r.get('metric_id') in {'profit_before_tax', 'interest_expense'}]
        pretax, interest = (_pick(validated, field, 'UZS_thousand', end, start)
                            for field in ('profit_before_tax', 'interest_expense'))
        charge = interest['value']
        # The NSBU signed income/expense pair records an expense as negative.
        ebit = nsbu_ebit(pretax['value'], charge)
        emit('ebit', ebit, 'F2/240 + interest expense (F2/180)', [pretax, interest], 'UZS_thousand',
             reason='EBIT_INPUTS_MISSING', period_start=start, numerator_value=None, denominator_value=None,
             addends=[number(pretax['value']), number(-charge) if charge is not None and charge <= 0 else None])

    common = ordinary_fact(pick('common_equity'), 'total_equity')
    shares = disclosed_count(pick('ordinary_shares', 'shares'), 'ordinary_shares')
    bvps = ratio(common['value'] * 1000 if common['value'] is not None else None, shares['value'])
    instrument = report.get('instrument') or {}
    ordinary_issue = instrument.get('instrument_type') in (None, 'ordinary_share')
    emit('book_value_per_share', bvps if ordinary_issue else None, 'common_equity × 1000 / ordinary_shares',
         [common, shares], 'UZS_per_share', missing_inputs=(
             (['common_equity'] if common['value'] is None else []) +
             (['ordinary_shares'] if shares['value'] is None or shares['value'] <= 0 else [])), share_disclosure_url=next(
             (c['source_url'] for c in shares['components'] if c.get('source_url')), None))
    price, quoted = decimal(instrument.get('last_price')), instrument.get('market_as_of')
    market_bvps = bvps
    actions = []
    if quoted and bvps is not None:
        for action in corporate_actions.actions_for(report['issuer']['ticker']):
            if end < action.ex_date <= quoted:
                market_bvps /= decimal(action.ratio)
                actions.append({'source_url': action.source, 'metric_id': action.kind,
                                'effective_date': action.ex_date, 'value': str(action.ratio)})
    valuation_date = instrument.get('valuation_as_of')
    age = (instrument.get('freshness') or {}).get('days_since_trade')
    if not valuation_date and quoted and isinstance(age, int):
        valuation_date = (date.fromisoformat(quoted[:10]) + timedelta(days=age)).isoformat()
    published = max((str(s.get('publication_date') or '')[:10] for s in report.get('sources', [])), default='')
    changed = any(end < action['date'] <= quoted for action in (basis.get('capital_changes', []) if basis_ok and quoted else []))
    usable = (not changed and (not valuation_date or not quoted or quoted <= valuation_date)
              and (not valuation_date or not published or published <= valuation_date)
              and instrument.get('instrument_type') == 'ordinary_share' and quoted and quoted >= end
              and (instrument.get('freshness') or {}).get('status') in {'fresh', 'aging', 'stale'}
              and (instrument.get('currency') or 'UZS') == 'UZS'
              and (not instrument.get('issuer_id') or str(instrument['issuer_id']) == str(report['issuer']['id']))
              and (not instrument.get('ticker') or instrument['ticker'] == report['issuer']['ticker'])
              and (not instrument.get('quote_isin') or instrument['quote_isin'] == instrument.get('isin'))
              and (not basis_ok or not basis.get('isin') or basis['isin'] == instrument.get('isin'))
              and price is not None and price > 0)
    emit('price_to_book', ratio(price, market_bvps) if usable else None,
         'ordinary_share_price / (common_equity × 1000 / ordinary_shares)',
         [{'value': price, 'components': [instrument]}, {'value': market_bvps, 'components': common['components'] + shares['components'] + actions}],
          reason='CAPITAL_CHANGED' if changed else 'BOOK_OR_QUOTE_INPUTS_MISSING', market_as_of=quoted,
          valuation_as_of=valuation_date, price_basis_actions=actions,
          share_disclosure_url=basis.get('source_url') if basis_ok and shares['value'] is not None else None,
          missing_inputs=([key for key, part in [('common_equity',common),('ordinary_shares',shares)]
                           if part['value'] is None or part['value'] <= 0] + ([] if usable else ['usable_quote'])))

    disclosed = pick('eps_basic', 'UZS_per_share', True)
    if disclosed['value'] is not None:
        emit('eps_basic', disclosed['value'], 'disclosed basic earnings per share', [disclosed], 'UZS_per_share',
             origin='reported', period_start=start)
    else:
        profit = ordinary_fact(pick('profit_ordinary', flow=True), 'net_income', flow=True)
        weighted = disclosed_count(pick('weighted_average_shares', 'shares', True), 'weighted_average_shares', flow=True)
        value = ratio(profit['value'] * 1000 if profit['value'] is not None else None, weighted['value'])
        # A conflicting/blocked disclosed EPS must not be bypassed by recomputing it.
        if disclosed['components']:
            value = None
        emit('eps_basic', value, 'profit_ordinary × 1000 / weighted_average_shares',
              [profit, weighted], 'UZS_per_share', reason='EPS_INPUTS_MISSING', period_start=start,
              closing_share_count_verified=basis_ok and shares['value'] is not None,
              missing_inputs=(['reported_eps_conflict'] if disclosed['components'] else
                  (['profit_ordinary'] if profit['value'] is None else []) +
                  (['weighted_average_shares'] if weighted['value'] is None or weighted['value'] <= 0 else [])),
              basis='verified_share_disclosure' if any(c.get('verification_status') == 'verified' and c.get('unit') == 'shares'
                    for p in [profit, weighted] for c in p['components']) else 'filing')
        if (not disclosed['components'] and ordinary_issue and shares['value'] is not None
                and (not weighted['components'] or weighted['value'] is not None and weighted['value'] != shares['value'])):
            estimate = ratio(profit['value'] * 1000 if profit['value'] is not None else None, shares['value'])
            if estimate is not None:
                emit('eps_closing_estimate', estimate, 'profit_ordinary × 1000 / closing_ordinary_shares',
                     [profit, shares], 'UZS_per_share', calculation_status='approximate', origin='estimate')

    if not ordinary_issue:
        for metric in result:
            if metric['metric_code'] in SHARE_METRICS:
                metric.update(value=None, raw_result=None, verification_status='unavailable',
                              calculation_status='not_applicable', reason_code='ORDINARY_SHARES_ONLY', missing_inputs=[])
    return result


def enterprise(report):
    issuer = report.get('issuer') or {}
    from catalogue.organization import uses_credit_metrics
    return (not uses_credit_metrics('financial', issuer.get('name') or '')
            and issuer.get('organization_type') in {'non_financial', 'commodity_exchange'}
            and 'leas' not in str(issuer.get('sector') or '').lower()
            and 'leas' not in str(report.get('sector_template_code') or '').lower())


def _historical_instrument(report, basis, filings, cutoff, *, latest=False):
    """Find the last valuation while this balance sheet was public and current."""
    from bond_quality import day, freshness
    from catalogue.market_store import quote_at
    from issuer_financials import period_end

    instrument = report.get('instrument') or {}
    if instrument.get('instrument_type') != 'ordinary_share':
        return instrument
    isin = instrument.get('isin') or (basis or {}).get('isin')
    if not isin or ((basis or {}).get('isin') and basis['isin'] != isin):
        return instrument
    end = report['financial_as_of']
    published = max((s.get('publication_date') or '' for s in report.get('sources', [])), default='')[:10]
    publication_day = day(published)
    if not publication_day:
        return instrument
    filing_dates = [(period_end(f.get('period')), day(f.get('published_at'))) for f in filings if f.get('period')]
    later = [published_at for closing, published_at in filing_dates if closing and closing > end]
    last_filed = not later and (end, publication_day) in filing_dates
    limit = publication_day
    if later and all(later):
        limit = min(later) - timedelta(days=1)
    elif (latest or last_filed) and cutoff:
        limit = day(cutoff)
    if cutoff:
        limit = min(limit, day(cutoff))
    quote = quote_at(isin, limit.isoformat()) if limit >= publication_day else {}
    if not quote:
        existing = day(instrument.get('market_as_of'))
        if existing and (existing > limit or limit < publication_day):
            return {**instrument, 'last_price': None, 'market_as_of': None}
        return instrument
    traded = day(quote['trade_date'])
    valuation = max(traded, publication_day)
    return {**instrument, 'isin': isin, 'quote_isin': quote['isin'], 'market_as_of': traded.isoformat(),
            'last_price': quote['close_price'], 'freshness': freshness(traded, valuation),
            'valuation_as_of': valuation.isoformat()}


def _metrics_at(issuer, standard, scope, period, stamp, cutoff, filings):
    from catalogue.sources import cached_report_excel_data
    from financial_columns import share_disclosures
    from sector_report_service import sector_report

    old = sector_report(issuer, standard, period, scope, 'ru', persist=False, source_reader=cached_report_excel_data)
    if (old.get('status') not in {'available', 'stale'} or old.get('financial_as_of') != stamp
            or old.get('standard') != standard or old.get('scope') != scope or old.get('period') != period
            or str(old['issuer']['id']) != str(issuer['id']) or old['issuer']['ticker'] != issuer['ticker']):
        return []
    if cutoff and any(str(s.get('publication_date') or '')[:10] > cutoff for s in old.get('sources', [])):
        return []
    basis = share_disclosures.read(issuer['id'], issuer['ticker'], stamp, scope)
    old['instrument'] = _historical_instrument(old, basis, filings, cutoff)
    return [row for row in calculate(old, _load(old), basis) if row['verification_status'] == 'verified'
            and (row['metric_code'] != 'price_to_book' or not cutoff or row['market_as_of'] <= cutoff)]


def _include_history(report, metrics):
    """Keep the current result and the newest independently verified result for each metric."""
    from financial_columns import share_disclosures, source_store
    from financial_ingestion import publication
    from issuer_financials import IssuerNotFoundError, resolve_issuer, period_end, report_rows

    org, ticker = report['issuer']['id'], report['issuer']['ticker']
    end, standard, scope = report['financial_as_of'], report['standard'], report['scope']
    missing = {r['metric_code']: r for r in metrics if r['metric_code'] in HISTORICAL_METRICS
               and r['value'] is None and not r.get('last_verified') and r['calculation_status'] != 'not_applicable'}
    if not missing:
        return
    candidates = defaultdict(set)
    for stamp in share_disclosures.prior_dates(org, ticker, end, scope):
        candidates[stamp].update(('book_value_per_share', 'price_to_book', 'eps_basic'))
    if 'ebit' in missing and standard == 'nsbu':
        for stamp in source_store.prior_dates(org, standard='NSBU', scope=scope, end=end):
            candidates[stamp].add('ebit')
    if standard == 'ifrs':
        from financial_ingestion.investor_eps import published_rows
        for snapshot in publication.snapshots(ticker, scope=scope):
            if str(snapshot.get('org_id')) == str(org) and snapshot.get('period_end') and snapshot['period_end'] < end:
                keys = {r.get('metric_id') for r in [*(snapshot['payload'].get('source_rows') or []), *published_rows(snapshot)]}
                if 'ordinary_shares' in keys:
                    candidates[snapshot['period_end']].update(('price_to_book', 'book_value_per_share'))
                if keys & {'eps_basic', 'weighted_average_shares'}:
                    candidates[snapshot['period_end']].add('eps_basic')
    if not any(missing.keys() & codes for codes in candidates.values()):
        return
    try:
        issuer = resolve_issuer(ticker)
    except IssuerNotFoundError:
        return
    if str(issuer['id']) != str(org) or issuer['ticker'] != ticker:
        return
    cutoff = (report.get('instrument') or {}).get('valuation_as_of') or date.today().isoformat()
    filings = report_rows(issuer, standard) if scope == 'separate' else []
    for stamp in sorted(candidates, reverse=True):
        if not candidates[stamp].intersection(missing):
            continue
        day = date.fromisoformat(stamp)
        if day.month not in (3, 6, 9, 12) or (standard == 'ifrs' and day.month != 12):
            continue
        periods = [str(day.year)] if day.month == 12 else []
        if standard == 'nsbu':
            periods.append(f'{day.year}Q{day.month // 3}')
        for period in periods:
            if period_end(period) != stamp:
                continue
            try:
                historical = _metrics_at(issuer, standard, scope, period, stamp, cutoff, filings)
            except Exception:
                logging.getLogger(__name__).warning('Historical indicators unavailable for %s %s', ticker, period, exc_info=True)
                continue
            for row in historical:
                current = missing.pop(row['metric_code'], None)
                if current is not None:
                    current['last_verified'] = row
            if not missing:
                return


def _with_history(report, rows, basis):
    metrics = calculate(report, rows, basis)
    try:
        book = next(r for r in metrics if r['metric_code'] == 'book_value_per_share')
        market = next(r for r in metrics if r['metric_code'] == 'price_to_book')
        cutoff = (report.get('instrument') or {}).get('valuation_as_of')
        if book['value'] is not None and market['value'] is None and cutoff:
            instrument = _historical_instrument(report, basis, [], cutoff, latest=True)
            if instrument.get('valuation_as_of') and instrument['valuation_as_of'] < cutoff:
                previous = next(r for r in calculate({**report, 'instrument':instrument}, rows, basis)
                                if r['metric_code'] == 'price_to_book')
                if previous['value'] is not None:
                    market['last_verified'] = previous
        _include_history(report, metrics)
        if report['standard'] == 'nsbu' and report.get('status') in {'available', 'stale'}:
            eps = next(r for r in metrics if r['metric_code'] == 'eps_basic')
            if eps['value'] is None and not eps.get('last_verified') and eps['calculation_status'] != 'not_applicable':
                other = _published_ifrs_eps(report)
                if other:
                    eps['other_filing'] = other
    except Exception:
        logging.getLogger(__name__).warning('Optional historical indicators unavailable for %s',
                                            report['issuer']['ticker'], exc_info=True)
    return metrics


def _published_ifrs_eps(report):
    from financial_ingestion import investor_eps, publication
    from issuer_financials import resolve_issuer

    ticker, org = report['issuer']['ticker'], str(report['issuer']['id'])
    cutoff = (report.get('instrument') or {}).get('valuation_as_of') or date.today().isoformat()
    candidates = []
    for scope in ('separate', 'consolidated'):
        for snapshot in publication.snapshots(ticker, scope=scope):
            payload = snapshot['payload']
            source = payload.get('source') or {}
            stamp = snapshot['period_end']
            published = str(source.get('source_published_at') or '')[:10]
            if (str(snapshot['org_id']) != org or stamp > report['financial_as_of'] or not stamp.endswith('-12-31')
                    or not stamp <= published <= cutoff or not source.get('pdf_url')
                    or payload['classification'].get('role') != 'PRIMARY'):
                continue
            if (any(r.get('metric_id') == 'eps_basic' for r in payload.get('source_rows') or [])
                    or investor_eps.published_rows(snapshot)):
                candidates.append((stamp, scope, source['pdf_url']))
    direct = investor_eps.official_eps(org, report['financial_as_of'], cutoff, report['scope'])
    if not candidates:
        return direct
    issuer = resolve_issuer(ticker)
    if str(issuer['id']) != org or issuer['ticker'] != ticker:
        return None
    for stamp, scope, url in sorted(candidates, key=lambda c:(c[0], c[1]==report['scope']), reverse=True):
        if direct and direct['period'] > stamp[:4]:
            return direct
        for row in _metrics_at(issuer, 'ifrs', scope, stamp[:4], stamp, cutoff, []):
            if row['metric_code'] != 'eps_basic':
                continue
            evidence = next((c for c in row['components'] if c.get('source_url')==url and c.get('metric_id')=='eps_basic'), None)
            if evidence:
                if direct and direct['period'] == stamp[:4] and direct['scope'] == scope and direct['value'] != row['value']:
                    return None
                return {'standard':'ifrs', 'scope':scope, 'period':stamp[:4], 'value':row['value'], 'unit':row['unit'],
                        'source_url':url, 'page':evidence.get('page')}
    # An unusable newer statement does not invalidate an independently verified earlier filing.
    if direct and all(stamp[:4] != direct['period'] or scope != direct['scope'] for stamp, scope, _ in candidates):
        return direct
    return None


def project(report):
    """Change only the public indicator selection, retaining statutory evidence."""
    if report.get('status') not in {'available', 'stale'}:
        report['ratios'], report['additional_ratios'] = [], []
        if report.get('status') == 'no_source' and report.get('financial_as_of') and report.get('issuer', {}).get('ticker'):
            metrics = _with_history({**report, 'verified_facts': []}, [], None)
            report['ratios'] = [r for r in metrics if r.get('last_verified')]
        return report
    is_enterprise = enterprise(report)
    if report['issuer'].get('organization_type') == 'investment_fund_ifrs_annual':
        return report
    try:
        rows = _load(report)
    except Exception:
        logging.getLogger(__name__).warning('Optional investor disclosures unavailable for %s', report['issuer']['ticker'], exc_info=True)
        rows = []
    from financial_columns import share_disclosures
    try:
        basis = share_disclosures.read(report['issuer']['id'], report['issuer']['ticker'],
                                       report['financial_as_of'], report['scope'])
    except Exception:
        logging.getLogger(__name__).warning('Share disclosure unavailable for %s', report['issuer']['ticker'], exc_info=True)
        basis = None
    metrics = _with_history(report, rows, basis)
    if not is_enterprise:
        report['ratios'] = [r for r in metrics if r['metric_code'] in SHARE_METRICS] + report['ratios']
        report['ratio_policy_version'] = VERSION
        return report
    report['additional_ratios'] = [r for r in report['ratios'] if r['metric_code'] in ADDITIONAL]
    report['ratios'] = metrics + [r for r in report['ratios'] if r['metric_code'] not in ADDITIONAL]
    report['ratio_policy_version'] = VERSION
    return report
