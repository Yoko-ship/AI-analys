"""Reviewed separate NSBU annual PDF statements, identified by Openinfo issuer ID."""
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from .registry import metric
from .share_disclosures import filing_key


@lru_cache(maxsize=1)
def reports():
    path = Path(__file__).with_name('reviewed_nsbu_annuals.json')
    records = json.loads(path.read_text(encoding='utf-8'))
    for r in records:
        if r['currency'] != 'UZS' or r['unit_scale'] != 1000:
            raise ValueError(f"Unsupported reviewed NSBU statement unit in {r['url']}")
    return records


def selected(issuer_id, scope='separate', documents=None):
    matches = [r for r in reports() if r['issuer_id'] == str(issuer_id) and r['scope'] == scope]
    if not matches:
        return []
    if documents is None:
        from . import source_store
        documents = source_store.read(issuer_id, standard='NSBU', scope=scope)
    # A later validated native annual filing supersedes the reviewed PDF. A
    # quarterly workbook can contain the same December closing date.
    later_annuals = {}
    for doc in documents:
        if doc.get('quality') != 'valid':
            continue
        if any((key := filing_key(f.get('source_url'))) and key[1] == 'annual' for f in doc['source_forms']):
            end = doc['period_end']
            later_annuals[end] = max(later_annuals.get(end, ''), doc.get('published_at') or '')
    return [r for r in matches if later_annuals.get(r['period_end'], '') <= r['published_at']]


def cells(report):
    """Preserve the PDF's label, page and amount alongside its statutory mapping."""
    for page in report['pages']:
        form = page['form']
        stock = form == 'F1'
        for code, label, raw in page['rows']:
            # Form 2 represents expenses as deductions. These PDF income
            # statements print expenses as positive amounts.
            expense = report['expenses_printed_positive'] and form == 'F2' and code in {'020', '050', '060', '070', '170', '250'}
            yield dict(source_form=form, source_code=code, metric_id=metric(form, code), raw_label=label,
                       kind='stock' if stock else 'flow', value=str(-raw if expense else raw),
                       quality='valid', raw_value=str(raw), unit='UZS_thousand', unit_scale=report['unit_scale'],
                       currency=report['currency'], standard='NSBU', scope=report['scope'], issuer_id=report['issuer_id'],
                       period_start=report['period_end'] if stock else report['period_start'],
                       period_end=report['period_end'], role='PRIMARY', page=page['page'],
                       published_at=report['published_at'], source_version=report['sha256'],
                       source_url=report['url'], audit_status='audited',
                       normalization='expense deducted from income' if expense else 'reported in thousand UZS')


def merge_rows(native, reviewed, annual):
    supplements = [cell for report in reviewed for cell in cells(report)]
    def identity(row):
        return row['source_form'], row.get('source_code'), row.get('period_start'), row['period_end']
    if annual:
        keys = {identity(row) for row in supplements}
        return [row for row in native if identity(row) not in keys] + supplements
    # A directly filed quarterly result must retain its own precision and source.
    keys = {identity(row) for row in native if row.get('role') != 'COMPARATIVE'}
    return native + [row for row in supplements if identity(row) not in keys]


def history(report):
    values = {c['metric_id']:int(c['value']) for c in cells(report)}
    expenses = ('selling_expense','admin_expense','other_operating_expense')
    if all(field in values for field in expenses):
        values['operating_expenses'] = sum(values[field] for field in expenses)
    if 'inventory' in values:
        values['inventories'] = values['inventory']
    return values


def add_history_ratios(reports, ticker, template, series):
    from . import ratios
    observations = [cell for report in reports for cell in cells(report)]
    selected_ratios = {'roe': ('roe', 1, '%'), 'roa': ('roa', 1, '%'),
                       'liabilities_to_assets': ('debt_ratio', 100, '%'),
                       'liabilities_to_equity': ('debt_to_equity', 1, 'ratio')}
    for report in reports:
        end = report['period_end']
        for ratio in ratios.calculate(observations, ticker=ticker, template=template, end=end, basis='annual', enriched=True):
            if ratio['metric_id'] not in selected_ratios or ratio['value'] is None:
                continue
            for cell in ratio['components']:
                name = 'net_profit' if cell['metric_id'] == 'net_income' else cell['metric_id']
                displayed = series.get(name, {}).get('values', {}).get(cell['period_end'][:4])
                if displayed is None or Decimal(str(displayed)) != Decimal(cell['value']) * 1000:
                    break
            else:
                name, factor, unit = selected_ratios[ratio['metric_id']]
                entry = series.setdefault(name, {'unit':unit, 'money':False, 'values':{}})
                entry['values'][end[:4]] = float(Decimal(ratio['value']) * factor)
                entry['derived'] = True


def passport(report, field, source_field):
    if source_field == 'operating_expenses' and source_field in history(report):
        return dict(status='DERIVED', period=report['period_end'][:4], field=field, standard='NSBU',
                    formula='selling_expense + admin_expense + other_operating_expense (signed)',
                    inputs=['selling_expense','admin_expense','other_operating_expense'],
                    source={'pdf_url': report['url']}, components=[c for c in cells(report) if c['metric_id'] in
                    ('selling_expense', 'admin_expense', 'other_operating_expense')])
    metric_id = 'inventory' if source_field == 'inventories' else source_field
    cell = next((c for c in cells(report) if c['metric_id'] == metric_id), None)
    if not cell:
        return None
    return dict(status='SOURCED', period=report['period_end'][:4], field=field, standard='NSBU',
                source_field=metric_id, value=int(cell['value']),
                source={**cell, 'pdf_url':report['url'],'report_form':'NSBU','period_type':'annual',
                        'period_year':int(report['period_end'][:4]), 'state':'published',
                        'source_published_at':report['published_at'], 'file_hash':report['sha256'],
                        'normalized_value':int(cell['value'])*1000})
