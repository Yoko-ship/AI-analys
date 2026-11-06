"""Investor indicators over verified report facts and compatible filed disclosures.

Report money is thousand UZS. Per-share amounts are UZS and share counts are
individual shares. No share count or ordinary-share entitlement is inferred
from nominal capital, a current exchange listing, or a different filing.
"""
from collections import defaultdict
from copy import deepcopy
import logging

from .sector_numbers import decimal, number, ratio, total

ADDITIONAL = {'P2', 'P7', 'P8'}
VERSION = 'report-investor-metrics-1'
NAMES = {
    'operating_margin': ('Операционная маржа', 'Operatsion marja', 'Operating margin'),
    'book_value': ('Балансовая стоимость капитала', 'Kapitalning balans qiymati', 'Book value of equity'),
    'interest_debt_to_equity': ('Долг / капитал (D/E)', 'Qarz / kapital (D/E)', 'Debt / equity (D/E)'),
    'price_to_book': ('P/BV', 'P/BV', 'P/BV'),
    'eps_basic': ('Базовая прибыль на акцию (EPS)', 'Aksiyaga bazaviy foyda (EPS)', 'Basic earnings per share (EPS)'),
}
MEANINGS = {
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
        docs = source_store.read(issuer['id'], standard='NSBU', scope=report['scope'])
        rows = observations.nsbu([d for d in docs if not d.get('period_end') or d['period_end'] == report['financial_as_of']])
    else:
        docs = publication.snapshots(issuer['ticker'], scope=report['scope'])
        rows = observations.ifrs([d for d in docs if d['period_end'] == report['financial_as_of']])
    observations.check(rows)
    return rows


def _compatible(report, rows, facts):
    """Require an exact context and a source revision matching the report balance."""
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
        keys += [key for key in ('net_income', 'revenue') if key in facts and any(r.get('metric_id') == key for r in group)]
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


def calculate(report, rows):
    facts = _facts(report)
    end, start = report['financial_as_of'], report['financial_as_of'][:4] + '-01-01'
    rows = _compatible(report, rows, facts)
    pick = lambda key, unit='UZS_thousand', flow=False: _pick(rows, key, unit, end, start if flow else None)
    fact = lambda key: {'value': decimal(facts.get(key, {}).get('value')), 'components': [facts[key]] if key in facts else []}
    result = []

    def emit(code, value, formula, parts, unit='ratio', reason='INPUTS_MISSING', **extra):
        result.append({
            'metric': code, 'metric_code': code, 'method_id': f'{VERSION}:{code}',
            **dict(zip(('name_ru', 'name_uz', 'name_en'), NAMES[code])),
            **dict(zip(('meaning_ru', 'meaning_uz', 'meaning_en'), MEANINGS[code])),
            'value': number(value), 'raw_result': str(value) if value is not None else None,
            'unit': unit, 'formula': formula, 'period': report['period'], 'period_end': end,
            'accounting_standard': report['standard'].upper(), 'scope': report['scope'],
            'origin': 'calculated', 'verification_status': 'verified' if value is not None else 'unavailable',
            'calculation_status': 'verified' if value is not None else 'missing_or_invalid_components',
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

    common, shares = pick('common_equity'), pick('ordinary_shares', 'shares')
    bvps = ratio(common['value'] * 1000 if common['value'] is not None and common['value'] > 0 else None, shares['value'])
    instrument = report.get('instrument') or {}
    price, quoted = decimal(instrument.get('last_price')), instrument.get('market_as_of')
    usable = (instrument.get('instrument_type') == 'ordinary_share' and quoted and quoted >= end
              and (instrument.get('freshness') or {}).get('status') in {'fresh', 'aging'}
              and price is not None and price > 0)
    emit('price_to_book', ratio(price, bvps) if usable else None,
         'ordinary_share_price / (common_equity × 1000 / ordinary_shares)',
         [{'value': price, 'components': [instrument]}, {'value': bvps, 'components': common['components'] + shares['components']}],
         reason='BOOK_OR_QUOTE_INPUTS_MISSING', market_as_of=quoted)

    disclosed = pick('eps_basic', 'UZS_per_share', True)
    if disclosed['value'] is not None:
        emit('eps_basic', disclosed['value'], 'disclosed basic earnings per share', [disclosed], 'UZS_per_share', origin='reported')
    else:
        profit, weighted = pick('profit_ordinary', flow=True), pick('weighted_average_shares', 'shares', True)
        value = ratio(profit['value'] * 1000 if profit['value'] is not None else None, weighted['value'])
        # A conflicting/blocked disclosed EPS must not be bypassed by recomputing it.
        if disclosed['components']:
            value = None
        emit('eps_basic', value, 'profit_ordinary × 1000 / weighted_average_shares',
             [profit, weighted], 'UZS_per_share', reason='EPS_INPUTS_MISSING')
    return result


def project(report):
    """Change only the public indicator selection, retaining statutory evidence."""
    if report.get('status') not in {'available', 'stale'}:
        report['ratios'], report['additional_ratios'] = [], []
        return report
    if (report.get('issuer') or {}).get('organization_type') != 'non_financial':
        return report
    try:
        rows = _load(report)
    except Exception:
        logging.getLogger(__name__).warning('Optional investor disclosures unavailable for %s', report['issuer']['ticker'], exc_info=True)
        rows = []
    metrics = calculate(report, rows)
    report['additional_ratios'] = [r for r in report['ratios'] if r['metric_code'] in ADDITIONAL]
    report['ratios'] = metrics + [r for r in report['ratios'] if r['metric_code'] not in ADDITIONAL]
    report['ratio_policy_version'] = VERSION
    return report
