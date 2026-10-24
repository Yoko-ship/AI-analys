"""Read-only application adapter for the financial-column terminal."""
from datetime import date
from decimal import Decimal
import re

from catalogue.storage import get_catalog_conn
from catalogue.organization import organization_kind
from financial_ingestion import publication
from . import derived, matrix, observations, ratios, source_store


def load(ticker, *, form='NSBU', scope=None, freq='annual', view='full'):
    ticker, form = ticker.upper().strip(), form.upper()
    form = 'MSFO' if form == 'IFRS' else form
    if form not in {'NSBU', 'MSFO'} or scope not in {None, 'separate', 'consolidated', 'unknown'}:
        raise ValueError('Unknown accounting context')
    if freq not in {'annual', 'quarter', 'interim'}:
        raise ValueError('Unknown frequency')
    if view not in {'full', 'template'}:
        raise ValueError('Unknown financial view')
    c = get_catalog_conn()
    try:
        row = c.execute('SELECT company_name,org_id FROM catalog_companies WHERE ticker=?', (ticker,)).fetchone()
        issuer = dict(row) if row else {}
        issuer_id = str(issuer.get('org_id') or f'ticker:{ticker}')
        published = [dict(r) for r in c.execute(
            "SELECT field,period,value_num,unit,source,source_url FROM facts WHERE entity_id=? "
            "AND dataset='financial_indicators' AND source='openinfo_financial_indicators' AND value_num IS NOT NULL",
            (issuer_id,))] if form == 'NSBU' else []
    finally:
        c.close()
    template = organization_kind(ticker, name=issuer.get('company_name'), sector=issuer.get('sector'))
    if template == 'financial' and re.search(r'lizing|лизинг|leasing', issuer.get('company_name', ''), re.I):
        template = 'leasing'
    shareholders = []
    if form == 'NSBU':
        scope = scope or 'separate'
        docs = source_store.read(issuer_id, standard=form, scope=scope)
        source_rows = observations.nsbu(docs)
        forms = [{'period_end': d['period_end'], 'source_version': d['source_version'],
                  'previous_version': d.get('previous_version'), 'documents': d['source_forms']} for d in docs]
        coverage = {'complete': bool(docs) and all(d['source_coverage']['complete'] for d in docs),
                    'notes': 'not_applicable', 'issues': sorted({issue for d in docs for issue in d['source_coverage']['issues']})}
        available_scopes = ['separate']
    else:
        available_scopes = publication.scopes(ticker)
        scope = scope or (available_scopes[0] if available_scopes else 'separate')
        snapshots = publication.snapshots(ticker, scope=scope) if scope != 'unknown' else []
        source_rows = observations.ifrs(snapshots)
        if snapshots:
            latest = max(snapshots, key=lambda s:s['period_end'])
            shareholders = [{**owner, 'standard': form, 'source_version': latest['id'],
                             'source_url': latest['payload'].get('source', {}).get('pdf_url')}
                            for owner in latest['payload'].get('shareholders') or []]
        forms = [{'period_end': s['period_end'], 'source_version': s['id'],
                  'documents': s['payload'].get('source_forms', []),
                  'source_url': s['payload'].get('source', {}).get('pdf_url')} for s in snapshots]
        covers = [s['payload'].get('source_coverage') or {'complete': False, 'notes': 'missing', 'issues': ['LEGACY_PARTIAL_IMPORT']} for s in snapshots]
        coverage = {'complete': bool(covers) and all(v['complete'] for v in covers),
                    'notes': 'present' if covers and all(v.get('notes') == 'present' for v in covers) else 'missing',
                    'issues': sorted({issue for v in covers for issue in v['issues']})}
    # No future reporting periods, even if a catalogue placeholder was imported.
    today = date.today().isoformat()
    source_rows = [r for r in source_rows if r['period_end'] < today]
    import data_quality
    held = data_quality.held_public_periods(ticker, form)
    for row in source_rows:
        end = row['period_end']
        period = end[:4] if end.endswith('-12-31') else end[:4] + 'Q' + str(int(end[5:7]) // 3)
        if period in held:
            row.update(value=None, quality='blocked', reason='UNDER_REVIEW')
    issues = observations.check(source_rows)
    source_rows = derived.enrich(source_rows)
    table = matrix.build(source_rows, mode=freq)
    ratio_rows = []
    for column in table['columns']:
        for ratio in ratios.calculate(source_rows, ticker=ticker, template=template,
                                      end=column['end'], basis=column['basis']):
            existing = next((r for r in ratio_rows if r['metric_id'] == ratio['metric_id']), None)
            if existing is None:
                existing = {'id': 'ratio:' + ratio['metric_id'], 'metric_id': ratio['metric_id'],
                            'label': ratio['label'], 'unit': ratio['unit'], 'source_form': 'RAT', 'kind': 'ratio', 'cells': {}}
                ratio_rows.append(existing)
            existing['cells'][column['key']] = ratio
    if not source_rows:
        coverage['issues'] = sorted(set(coverage['issues'] + ['NO_IMPORTED_SOURCE_ROWS']))
    payload = {'ok': True, 'ticker': ticker, 'issuer_id': issuer_id, 'issuer_name': issuer.get('company_name', ticker),
            'standard': form, 'scope': scope, 'available_scopes': available_scopes, 'template': template,
            'unit': 'UZS_thousand', 'freq': freq, **table, 'ratios': ratio_rows,
            'published_ratios': [{**r, 'value': str(Decimal(str(r['value_num']))), 'origin': 'OpenInfo_published'} for r in published
                                 if r['field'] in {'roe', 'roa', 'current_ratio', 'quick_ratio', 'debt_ratio', 'debt_to_equity', 'cost_of_risk', 'net_profit_margin', 'asset_turnover', 'roce'}],
            'source_forms': forms, 'coverage': coverage, 'issues': issues,
            'shareholders': shareholders, 'shareholders_status': 'AVAILABLE' if shareholders else 'NOT_DISCLOSED_OR_NOT_VERIFIED'}
    if view == 'template':
        from .presentation import project
        return project(payload)
    return payload
