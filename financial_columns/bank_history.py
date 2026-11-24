"""Expose the statutory bank balance lines and their calculation evidence on issuer pages."""
from collections import defaultdict
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from issuer_financials import period_end
from . import derived, matrix, observations, ratios, source_store

LINES = {'demand_deposits', 'savings_deposits', 'term_deposits', 'loans_gross'}
FIELDS = LINES | {'customer_funds', 'loans_to_deposits'}


def cells(ticker, issuer_id, kind, periods):
    import data_quality
    if not issuer_id or not periods or kind not in {'bank', 'microfinance', 'financial'}:
        return {}
    held = data_quality.held_public_periods(ticker, 'NSBU')
    periods = [p for p in periods if p not in held and not (p.endswith('Q4') and p[:4] in held)]
    if not periods:
        return {}
    documents = source_store.read(issuer_id, standard='NSBU', scope='separate')
    wanted = {period_end(p) for p in periods}
    source = []
    for doc in documents:
        balance = [r for r in doc['rows'] if r['source_form'] == 'BANK_BS']
        for row in observations.nsbu([{**doc, 'rows': balance}]):
            if row['period_end'] in wanted and row['metric_id'] in FIELDS:
                source.append({**row, 'statement_period_end': doc['period_end']})
    observations.check(source)
    dated = defaultdict(list)
    for row in derived.enrich(source):
        dated[row['period_end']].append(row)
    result = {}
    for period in periods:
        end = period_end(period)
        rows = dated.get(end)
        if not rows:
            continue
        by_metric = defaultdict(list)
        for row in rows:
            by_metric[row['metric_id']].append(row)
        selected = {key: matrix.choose(items) for key, items in by_metric.items()}
        if kind == 'bank':
            calculated = ratios.calculate(rows, ticker=ticker, template=kind, end=end, basis='as_of', enriched=True)
            selected['loans_to_deposits'] = next(r for r in calculated if r['metric_id'] == 'loans_to_deposits')
        result[period] = {key: c for key, c in selected.items()
                          if c.get('quality') in {'valid','warn'} and c.get('value') is not None}
    return result


def series(history):
    result = {}
    for period, fields in history.items():
        for key, cell in fields.items():
            money = key != 'loans_to_deposits'
            entry = result.setdefault(key, {'money': money, 'unit': 'UZS' if money else 'ratio',
                                            'derived': key not in LINES, 'values': {}})
            value = Decimal(cell['value']) * (1000 if money else 1)
            entry['values'][period] = int(value) if value == value.to_integral_value() else float(value)
    return result


def passport(ticker, period, field):
    from catalogue import filings
    from catalogue.organization import organization_kind
    issuer = filings.get_company_index(ticker) or {}
    kind = organization_kind(ticker, name=issuer.get('company_name'), sector=issuer.get('sector'))
    cell = cells(ticker, issuer.get('org_id'), kind, [period]).get(period, {}).get(field)
    base = {'period': period, 'field': field, 'standard': 'NSBU'}
    if not cell:
        return {**base, 'status': 'NO_DATA'}
    parts = cell.get('components') or [cell]
    original = parts[0]
    filing_end = original['statement_period_end']
    quarterly = parse_qs(urlsplit(original['source_url']).query).get('report_type') == ['quarter']
    source = {'excel_url': original['source_url'], 'scope': 'separate', 'standard': 'NSBU',
              'title': 'BANK_BS', 'perimeter': original['scope'], 'source_ticker': ticker,
              'period_year': int(filing_end[:4]), 'period_quarter': int(filing_end[5:7]) // 3 if quarterly else 0,
              'raw_label': original['raw_label'], 'raw_value': original.get('raw_value'), 'role': original.get('role'),
              'stated_period': original['period_end'], 'state': original['quality'], 'currency': original['currency'],
              'unit_scale': original['unit_scale'],
              'period_end': original['period_end'], 'source_published_at': original.get('published_at'),
              'normalized_value': str(Decimal(original['value']) * 1000),
              'normalization_formula': 'raw × source scale (UZS)',
              'source_version': original['source_version'], 'sheet': original['sheet'], 'row': original['row']}
    if field in LINES:
        return {**base, 'status': 'SOURCED', 'source': source}
    return {**base, 'status': 'DERIVED', 'formula': cell['formula'], 'source': source,
            'inputs': [part['metric_id'] for part in parts]}
