"""Read-only application adapter for the financial-column terminal."""
from datetime import date
from decimal import Decimal
import re

from catalogue.storage import get_catalog_conn
from catalogue.organization import organization_kind
from financial_ingestion import publication
from . import capital_returns, derived, matrix, observations, periods, ratios, source_store


def _latest_separate_end(ticker):
    from catalogue import filings
    from issuer_financials import period_end
    dates = []
    today = date.today().isoformat()
    for report in filings.get_company_reports(ticker):
        if (report.get('report_form') != 'NSBU' or report.get('scope') not in {None, 'separate'}
                or source_store.CONSOLIDATED_TITLE.search(report.get('title') or '')
                or not any(report.get(k) for k in ('excel_url', 'excel_url_form1', 'pdf_url'))):
            continue
        quarter = report.get('quarter')
        period = str(report.get('year')) + (f'Q{quarter}' if quarter else '')
        end = period_end(period)
        if end and end < today:
            dates.append(end)
    return max(dates, default=None)


def _check_filing_rows(source_rows, ticker, form, selected_period=None):
    import data_quality
    held = data_quality.held_public_periods(ticker, form)
    for row in source_rows:
        end = row['period_end']
        period = end[:4] if end.endswith('-12-31') else end[:4] + 'Q' + str(int(end[5:7]) // 3)
        if selected_period == period + 'Q4' and row.get('role') == 'PRIMARY':
            period = selected_period
        if period in held:
            row.update(value=None, quality='blocked', reason='UNDER_REVIEW')
    return observations.check(source_rows)


def history_gross_margins(ticker, issuer_id, template, series, periods):
    """Use the same signed Form 2 inputs as the statement for each history column."""
    from issuer_financials import period_end

    revenue = series.get('net_revenue', {}).get('values', {})
    gross = series.get('gross_profit', {}).get('values', {})
    available = [p for p in periods if revenue.get(p) is not None and gross.get(p) is not None]
    if not available or not issuer_id or template in capital_returns.FINANCIAL:
        return {}
    source = observations.nsbu(source_store.read(issuer_id, standard='NSBU', scope='separate'))
    _check_filing_rows(source, ticker, 'NSBU')
    inputs = [r for r in source if r['source_form'] == 'F2' and
              r['metric_id'] in {'gross_profit', 'revenue', 'cost_of_sales', 'operating_expenses'}]
    if not inputs:
        return {}
    values = {}
    for period in available:
        end = period_end(period)
        if not end:
            continue
        basis = 'quarter' if 'Q' in period else 'annual'
        calculated = ratios.calculate(inputs, ticker=ticker, template=template, end=end, basis=basis, enriched=True)
        margin = next(r for r in calculated if r['metric_id'] == 'gross_margin')
        if margin['value'] is None:
            continue
        # A restatement or a conflicting historical feed can put a different
        # amount in the public table. Only label a ratio of its visible inputs.
        parts = margin['components'][:2]
        displayed = (gross[period], revenue[period])
        if all(abs(Decimal(part['value']) * 1000 - Decimal(str(amount))) <= Decimal('0.01')
               for part, amount in zip(parts, displayed)):
            values[period] = float(margin['value'])
    return values


def _filing_roce_cell(docs, ticker, template, end, period=None):
    rows = observations.nsbu(docs)
    _check_filing_rows(rows, ticker, 'NSBU', period)
    basis = 'annual' if end.endswith('-12-31') and not (period or '').endswith('Q4') else 'ytd'
    return capital_returns.roce(rows, template=template, end=end, basis=basis)


def filing_roce(company, end, scope, requested_period=None):
    """The screener uses the same filed YTD/FY result as the ratio table."""
    latest = end is None
    ticker = company['ticker']
    template = organization_kind(ticker, name=company.get('name'))
    docs = source_store.read(company['org_id'], standard='NSBU', scope=scope, period_end=end, latest=True)
    if not end:
        imported = docs[0]['period_end'] if docs else ''
        indexed = _latest_separate_end(ticker) if scope == 'separate' else None
        end = max(imported, indexed or '') or None
        if end != imported:
            docs = []
    if not end:
        return None, {'value': None, 'reason_code': 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'
                      if template in capital_returns.FINANCIAL else 'ROCE_INPUTS_MISSING', 'unit': 'percent'}
    period = requested_period or (end[:4] if end.endswith('-12-31') else f'{end[:4]}Q{int(end[5:7]) // 3}')
    if end.endswith('-12-31'):
        from catalogue.filings import get_report_urls
        year = int(end[:4])
        fourth = get_report_urls(ticker, 'NSBU', year, 4)
        if fourth or period.endswith('Q4'):
            annual = get_report_urls(ticker, 'NSBU', year, 0)
            if latest and fourth and not annual and scope == 'separate':
                period = f'{year}Q4'
            urls = fourth if period.endswith('Q4') else annual
            docs = source_store.read_filing_version(company['org_id'], scope, end, urls or {})
    cell = _filing_roce_cell(docs, ticker, template, end, period)
    metric = {'value': float(cell['value']) if cell['value'] is not None else None, 'raw_result': cell['value'],
              'unit': cell['unit'], 'reason_code': cell['reason'], 'quality': cell['quality'], 'basis': cell['basis'],
              'balance_basis': cell['balance_basis'], 'formula': cell['formula']}
    if latest and cell['reason'] in {'ROCE_INPUTS_MISSING', 'NON_POSITIVE_CAPITAL_EMPLOYED'}:
        dates = source_store.prior_dates(company['org_id'], standard='NSBU', scope=scope, end=end)
        for stamp in sorted(dates, reverse=True):
            previous = source_store.read(company['org_id'], standard='NSBU', scope=scope, period_end=stamp)
            prior = _filing_roce_cell(previous, ticker, template, stamp)
            if prior['value'] is not None:
                metric['last_verified'] = {k: prior[k] for k in ('period_start', 'period_end', 'basis', 'unit', 'quality', 'balance_basis')}
                metric['last_verified'].update(value=float(prior['value']), raw_result=prior['value'],
                                              source_url=prior['components'][0]['source_url'])
                break
    return period, metric


def _reconciled_form2(rows):
    """Independently tie the primary income statement to its pretax and after-tax results."""
    fields = ('operating_income', 'finance_income', 'finance_cost', 'ordinary_profit', 'extraordinary_profit',
              'profit_before_tax', 'income_tax', 'other_profit_payments', 'net_income')
    amounts = {}
    for field in fields:
        cell = matrix.choose([r for r in rows if r.get('metric_id') == field and r['unit'] == 'UZS_thousand'])
        if cell.get('value') is None or cell['quality'] not in {'valid', 'warn'}:
            return False
        amounts[field] = Decimal(cell['value'])
    return (any(amounts.values())
            and amounts['operating_income'] + amounts['finance_income'] + amounts['finance_cost'] == amounts['ordinary_profit']
            and amounts['ordinary_profit'] + amounts['extraordinary_profit'] == amounts['profit_before_tax']
            and amounts['profit_before_tax'] + amounts['income_tax'] + amounts['other_profit_payments'] == amounts['net_income'])


def filing_ebit(company, report):
    """Read matched Form 2 lines when only balance-sheet checks block the analysis card."""
    from catalogue.filings import get_report_urls
    from issuer_financials import period_end, period_key

    blocks = {q.get('code') for q in report.get('data_quality', []) if q.get('severity') == 'blocking'}
    if (report.get('status') != 'quality_blocked' or not blocks
            or blocks - {'CAPITAL_COMPONENTS_MISMATCH', 'BALANCE_IDENTITY_FAILED'}):
        return None
    period = report.get('period')
    end = period_end(period)
    if not end or end != report.get('financial_as_of') or end >= date.today().isoformat():
        return None
    year, quarter = period_key(period)
    ticker = company['ticker']
    indexed = get_report_urls(ticker, 'NSBU', year, quarter if 'Q' in period else 0) or {}
    url = indexed.get('excel_url')
    published = indexed.get('published_at')
    if not url or not published or not any(s.get('publication_date') == published for s in report.get('sources', [])):
        return None
    scope = report['scope']
    docs = source_store.read(company['org_id'], standard='NSBU', scope=scope, period_end=end)
    rows = observations.nsbu([d for d in docs if d.get('published_at') == published and d.get('scope') == scope
                              and d.get('period_end') == end and d.get('currency') == 'UZS' and d.get('unit_scale')
                              and str(d.get('issuer_id')) == str(company['org_id'])])
    _check_filing_rows(rows, ticker, 'NSBU')
    primary = [r for r in rows if r['source_form'] == 'F2' and r.get('source_url') == url
               and r['role'] == 'PRIMARY' and r['kind'] == 'flow']
    if 'BALANCE_IDENTITY_FAILED' in blocks and not _reconciled_form2(primary):
        return None
    template = organization_kind(ticker, name=company.get('name'))
    cell = matrix.choose([r for r in derived.enrich(primary, template=template) if r.get('metric_id') == 'ebit'])
    if cell['value'] is None:
        return None
    return {'value': float(cell['value']), 'raw_result': cell['value'], 'unit': cell['unit'],
            'calculation_status': 'verified', 'formula': cell['formula'], 'source_url': url}


def load(ticker, *, form='NSBU', scope=None, freq='annual', view='full', statement='all',
         include_sources=True, include_ratios=True):
    ticker, form = ticker.upper().strip(), form.upper()
    form = 'MSFO' if form == 'IFRS' else form
    if form not in {'NSBU', 'MSFO'} or scope not in {None, 'separate', 'consolidated', 'unknown'}:
        raise ValueError('Unknown accounting context')
    if freq not in {'annual', 'quarter', 'interim'}:
        raise ValueError('Unknown frequency')
    if view not in {'full', 'template', 'overview', 'investor'}:
        raise ValueError('Unknown financial view')
    if view == 'investor' and form != 'MSFO':
        raise ValueError('Investor view requires IFRS')
    if statement not in {'all', 'income', 'balance'}:
        raise ValueError('Unknown financial statement')
    include_ratios = include_ratios and statement == 'all' and view != 'overview'
    c = get_catalog_conn()
    try:
        row = c.execute('SELECT company_name,org_id FROM catalog_companies WHERE ticker=?', (ticker,)).fetchone()
        issuer = dict(row) if row else {}
        issuer_id = str(issuer.get('org_id') or f'ticker:{ticker}')
        published = [dict(r) for r in c.execute(
            "SELECT field,period,value_num,unit,source,source_url FROM facts WHERE entity_id=? "
            "AND dataset='financial_indicators' AND source='openinfo_financial_indicators' AND value_num IS NOT NULL",
            (issuer_id,))] if form == 'NSBU' and include_ratios else []
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
                  'previous_version': d.get('previous_version'), 'documents': d['source_forms']} for d in docs] if include_sources else []
        filed = []
        if scope == 'separate' and template in {'financial', 'microfinance', 'leasing'}:
            from . import microfinance
            filed = microfinance.filed_documents(ticker, issuer_id)
            for document, version, source in filed:
                source_rows.extend(microfinance.filed_rows(document, version, source))
                if include_sources:
                    forms.append(microfinance.original_form(document, version, source))
        from . import reviewed_annual
        audits = reviewed_annual.selected(issuer_id, scope, docs)
        if audits:
            source_rows = reviewed_annual.merge_rows(source_rows, audits, annual=freq == 'annual')
            if include_sources:
                for audit in audits:
                    forms.append({'period_end':audit['period_end'], 'source_version':audit['sha256'],
                                  'source_url':audit['url'], 'documents':[{'form':'NSBU', 'page':p['page'],
                                  'text':'\n'.join(f'{label}: {raw}' for _,label,raw in p['rows'])} for p in audit['pages']]})
        issues = {issue for d in docs for issue in d['source_coverage']['issues']}
        if audits:
            issues.add('PARTIAL_SOURCE_IMPORT')
        if any(not microfinance.has_all_lines(document) for document, _, _ in filed):
            issues.add('INCOMPLETE_STRUCTURED_FORM')
        coverage = {'complete': bool(docs or filed) and not issues and all(d['source_coverage']['complete'] for d in docs),
                    'notes': 'not_applicable', 'issues': sorted(issues)}
        available_scopes = ['separate']
    else:
        available_scopes = publication.scopes(ticker)
        scope = scope or (available_scopes[0] if available_scopes else 'separate')
        snapshots = publication.snapshots(ticker, scope=scope) if scope != 'unknown' else []
        source_rows = observations.ifrs(snapshots, canonical_metrics=view != 'full')
        if view == 'investor':
            from .investor_sources import audited_fund
            source_rows.extend(audited_fund(ticker, issuer_id, scope, imported=source_rows))
            if source_rows and scope not in available_scopes:
                available_scopes = [*available_scopes, scope]
        if snapshots:
            latest = max(snapshots, key=lambda s:s['period_end'])
            shareholders = [{**owner, 'standard': form, 'source_version': latest['id'],
                             'source_url': latest['payload'].get('source', {}).get('pdf_url')}
                            for owner in latest['payload'].get('shareholders') or []]
        forms = [{'period_end': s['period_end'], 'source_version': s['id'],
                  'documents': s['payload'].get('source_forms', []),
                  'source_url': s['payload'].get('source', {}).get('pdf_url')} for s in snapshots] if include_sources else []
        covers = [s['payload'].get('source_coverage') or {'complete': False, 'notes': 'missing', 'issues': ['LEGACY_PARTIAL_IMPORT']} for s in snapshots]
        coverage = {'complete': bool(covers) and all(v['complete'] for v in covers),
                    'notes': 'present' if covers and all(v.get('notes') == 'present' for v in covers) else 'missing',
                    'issues': sorted({issue for v in covers for issue in v['issues']})}
    # No future reporting periods, even if a catalogue placeholder was imported.
    today = date.today().isoformat()
    source_rows = [r for r in source_rows if periods.statement_end(r) < today]
    issues = _check_filing_rows(source_rows, ticker, form)
    source_rows = derived.enrich(source_rows, template=template)
    if view == 'investor':
        from .investor import enrich
        source_rows = enrich(source_rows)
    filed_end = _latest_separate_end(ticker) if form == 'NSBU' and scope == 'separate' and include_ratios and view == 'template' else None
    table = matrix.build(source_rows, mode=freq, recent=view in {'template', 'overview', 'investor'}, filed_end=filed_end,
                         annual_history=view == 'investor', interim_ttm=view == 'investor',
                         recent_ttm=include_ratios and view == 'template' and form == 'NSBU' and template not in capital_returns.FINANCIAL)
    ratio_rows = []
    for column in table['columns'] if include_ratios else []:
        for ratio in ratios.calculate(source_rows, ticker=ticker, template=template,
                                      end=column['end'], basis=column['basis'], enriched=True):
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
    if view == 'investor':
        from .investor import project
        from .investor_ratios import calculate
        payload['ratios'] = calculate(source_rows, ratio_rows, table['columns'], template) if include_ratios else []
        return project(payload, source_rows)
    if view in {'template', 'overview'}:
        from .presentation import income_flow_details, project
        payload = project(payload)
        if view == 'template' and statement != 'balance':
            payload['income_flow_rows'] = income_flow_details(table['rows'], payload['rows'])
        if view == 'overview':
            payload = {**payload, 'rows': payload['overview_rows'], 'ratios': [], 'published_ratios': [], 'shareholders': []}
    from .presentation import select_statement
    return select_statement(payload, statement)
