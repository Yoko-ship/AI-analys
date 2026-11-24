"""Convert approved source records into normalized, traceable observations."""
from decimal import Decimal


# A source discrepancy above the rounding allowance is always disclosed.
# Up to 0.1% of BOTH the filed and reconciled total is usable with a warning;
# larger discrepancies, zero totals and sign conflicts remain blocked.
RECONCILIATION_RELATIVE_LIMIT = Decimal('0.001')


def _bank_balance_column_issues(rows):
    balance = [r for r in rows if r.get('source_form') == 'BANK_BS']
    issues = {}
    controls = {'total_assets', 'total_liabilities', 'total_equity_liabilities'}
    for side in ('current', 'previous'):
        amounts = [Decimal(r[side]['value']) for r in balance if r[side].get('value') is not None]
        if amounts and not any(amounts) and any(
                r.get('metric_id') == 'total_assets' and r[side].get('value') is not None for r in balance):
            issues[side] = 'EMPTY_BANK_BALANCE_COLUMN'
        elif amounts:
            totals = {r['metric_id']: Decimal(r[side]['value']) for r in balance
                      if r.get('metric_id') in controls and r[side].get('value') is not None}
            if totals.keys() == controls and not any(totals.values()):
                # Some legacy forms populate a few detail lines in the otherwise
                # unused column, including positive loans against zero total assets.
                issues[side] = 'BANK_BALANCE_TOTALS_UNRESOLVED'
    # In some historical forms only the left column contains a balance, and
    # the right column is entirely zero. The layout cannot establish which
    # date the populated column represents.
    if 'current' in issues and 'previous' not in issues:
        issues['previous'] = 'BANK_BALANCE_DATE_UNRESOLVED'
    return issues


def _unreconciled_bank_loan_details(rows):
    """Identify nonpositive detail lines that contradict the same column's positive loan and lease subtotal."""
    groups = {}
    fields = {'loans_and_leases', 'loans_gross', 'leases_gross'}
    for row in rows:
        field = row.get('metric_id')
        if row.get('source_form') != 'BANK_BS' or field not in fields:
            continue
        for side in ('current', 'previous'):
            source = row[side]
            if source.get('quality') == 'valid' and source.get('value') is not None:
                key = (row.get('source_url'), row.get('sheet'), side)
                groups.setdefault(key, {}).setdefault(field, set()).add(Decimal(source['value']))
    conflicts = set()
    for key, amounts in groups.items():
        if any(len(amounts.get(field, ())) != 1 for field in fields):
            continue
        if (min(amounts['loans_and_leases']) > 0 and max(amounts['loans_gross']) <= 0
                and max(amounts['leases_gross']) <= 0):
            conflicts.add(key)
    return conflicts


def nsbu(documents):
    result = []
    for doc in documents:
        end, year = doc['period_end'], int(doc['period_end'][:4])
        scale = Decimal(doc.get('unit_scale') or 1000)
        bank_issues = _bank_balance_column_issues(doc['rows'])
        unreconciled_loan_details = _unreconciled_bank_loan_details(doc['rows'])
        for row in doc['rows']:
            for side in ('current', 'previous'):
                source = row[side]
                when = end if side == 'current' else f'{year-1}-12-31' if row['kind'] == 'stock' else f'{year-1}{end[4:]}'
                value = str(Decimal(source['value']) * scale / 1000) if source.get('value') is not None and doc['quality'] != 'blocked' else None
                quality = 'blocked' if doc['quality'] == 'blocked' else source['quality']
                reason = 'UNIT_UNRESOLVED' if doc['quality'] == 'blocked' else source.get('reason')
                if row['source_form'] == 'BANK_BS' and side in bank_issues and value is not None:
                    value, quality, reason = None, 'blocked', bank_issues[side]
                elif (row['source_form'] == 'BANK_BS' and row.get('metric_id') in {'loans_gross', 'leases_gross'}
                      and (row.get('source_url'), row.get('sheet'), side) in unreconciled_loan_details):
                    value, quality, reason = None, 'blocked', 'UNRECONCILED_LOAN_BREAKDOWN'
                result.append({**{k:v for k,v in row.items() if k not in {'current', 'previous'}}, **source, 'value': value, 'quality': quality,
                               'standard': 'NSBU', 'scope': doc['scope'], 'issuer_id': doc['issuer_id'],
                               'period_end': when, 'period_start': when if row['kind'] == 'stock' else when[:4] + '-01-01',
                               'role': 'PRIMARY' if side == 'current' else 'COMPARATIVE',
                               'source_version': doc['source_version'], 'published_at': doc.get('published_at'),
                               'previous_version': doc.get('previous_version'),
                               'accounting_model': 'legacy' if doc.get('template') == 'insurance' else None,
                               'currency': doc.get('currency'), 'unit_scale': doc.get('unit_scale'),
                               'normalization': 'raw × unit_scale / 1000',
                               'reason': reason})
    return result


def _reconciled_income_rows(payload):
    """Expose the approved statement evidence used to reconcile net income."""
    meta = payload['classification']
    end = meta['period_end']
    reported = {r.get('metric_id') for r in payload.get('source_rows') or []
                if r.get('source_form') == 'PL' and r.get('period_end') == end
                and r.get('period_start') == meta['period_start']}
    reconciliation = payload.get('income_reconciliation') or {}
    for name, metric in (('pretax', 'profit_before_tax'), ('tax', 'income_tax')):
        item = reconciliation.get(name)
        if metric in reported or not item or item.get('column_year') != int(end[:4]):
            continue
        yield {**item, 'metric_id': metric, 'source_form': 'PL', 'source_code': None,
               'origin': 'income_reconciliation', 'kind': 'flow', 'unit': 'UZS_thousand',
               'currency': meta['currency'], 'unit_scale': meta['unit_scale'],
               'period_start': meta['period_start'], 'period_end': end, 'quality': 'valid'}


_LEGACY_BALANCE_METRICS = {
    'due_from_banks': 'bank_balances',
    'inventories': 'inventory',
    'investment_securities': 'debt_equity_investments',
    'issued_debt': 'debt_securities_issued',
    'other_borrowed_funds': 'borrowings',
    'other_borrowings': 'borrowings',
    'prepaid_income_tax': 'current_tax_assets',
}


# Some reviewed imports used a different metric name for the same signed line.
# Require both the old identifier and an exact caption in the statement registry.
_REVIEWED_IFRS_NAMES = {
    'lease_liabilities_long': {'lease_liabilities_noncurrent'},
    'lease_liabilities_short': {'lease_liabilities_current'},
    'noncurrent_lease_liabilities': {'lease_liabilities_noncurrent'},
    'net_fx_gains': {'fx_gain_loss'},
    'long_term_borrowings': {'borrowings_long'},
    'short_term_borrowings': {'borrowings_short'},
    'deferred_tax_asset': {'deferred_tax_assets'},
    'deferred_tax_liabilities': {'deferred_tax_liability'},
    'receivables': {'trade_receivables', 'trade_other_receivables'},
    'payables': {'trade_payables', 'trade_other_payables'},
    'reinsurers_share_reserves': {'reinsurer_share_reserves'},
    'admin_expenses': {'admin_expense'},
    'selling_expenses': {'selling_expense'},
    'other_operating_expenses': {'other_operating_expense'},
    'finance_costs': {'finance_cost'},
    'other_comprehensive_income': {'oci'},
    'total_comprehensive_income': {'comprehensive_income'},
    'acquisition_costs': {'acquisition_expense'},
    'acquisition_expenses': {'acquisition_expense'},
    'interest_income_effective_rate': {'interest_eir'},
    'personnel_expenses': {'staff_costs'},
    'ppe_intangibles_purchases': {'capex'},
    'purchase_ppe_intangibles': {'capex'},
    'capex_ppe_intangibles': {'capex'},
    'purchase_ppe_and_intangibles': {'capex'},
}


def canonical_ifrs_metric(row):
    """Keep the reviewed source while resolving exact labels for display and ratios."""
    if row.get('standard') != 'MSFO':
        return row
    metric_id = row.get('metric_id')
    form = row.get('source_form')
    if form == 'BS' and metric_id in _LEGACY_BALANCE_METRICS:
        return {**row, 'metric_id': _LEGACY_BALANCE_METRICS[metric_id], 'source_metric_id': metric_id}
    if not metric_id or metric_id in _REVIEWED_IFRS_NAMES:
        from .ifrs import metric
        resolved = metric(row.get('raw_label') or '', form)
        if resolved and not metric_id:
            return {**row, 'metric_id': resolved}
        if metric_id and resolved in _REVIEWED_IFRS_NAMES[metric_id]:
            return {**row, 'metric_id': resolved, 'source_metric_id': metric_id}
    return row


def ifrs(snapshots, *, canonical_metrics=True):
    from financial_ingestion.investor_eps import published_rows
    result = []
    for snapshot in snapshots:
        payload, meta = snapshot['payload'], snapshot['payload']['classification']
        source = payload.get('source') or {}
        base = {'issuer_id': str(snapshot['org_id']), 'standard': 'MSFO', 'scope': meta['scope'],
                'period_end': meta['period_end'], 'period_start': meta['period_start'],
                'source_version': snapshot['id'], 'source_url': source.get('pdf_url'),
                'published_at': source.get('source_published_at'), 'received_at': source.get('received_at'),
                'role': meta.get('role'),
                'audit_status': meta.get('audit_status', 'unknown'), 'accounting_model': meta.get('accounting_model'),
                'currency': meta.get('currency'), 'unit_scale': meta.get('unit_scale'), 'fx': meta.get('fx')}
        mapped = set()
        for row in [*(payload.get('source_rows') or []), *published_rows(snapshot), *_reconciled_income_rows(payload)]:
            quality, reason = row['quality'], row.get('reason')
            value = None
            if row.get('raw_value') is not None and row.get('unit_scale'):
                factor = Decimal(1)
                if row.get('currency') not in {'UZS', 'shares'}:
                    fx = meta.get('fx') or {}
                    if fx.get('currency') == row['currency'] and fx.get('as_of') == row['period_end']:
                        factor = Decimal(str(fx['rate']))
                    else:
                        quality, reason = 'blocked', 'FX_EVIDENCE_MISSING'
                divisor = 1 if row.get('unit') in {'shares', 'UZS_per_share'} else 1000
                if quality != 'blocked':
                    value = str(Decimal(row['raw_value']) * Decimal(row['unit_scale']) * factor / divisor)
            result.append({**base, **row, 'value': value, 'quality': quality, 'reason': reason,
                           'normalization': 'raw × source scale × verified currency rate / display scale'})
            if row.get('metric_id'):
                mapped.add(row['metric_id'])
        # Older reviewed snapshots remain useful. Their limited coverage is
        # explicit and they never masquerade as a complete original form.
        for metric_id, figure in payload.get('figures', {}).items():
            if metric_id in mapped:
                continue
            value = payload.get('normalized_uzs', {}).get(metric_id)
            if value is None:
                continue
            kind = 'stock' if metric_id in {'cash', 'total_assets', 'total_equity', 'total_liabilities'} else 'flow'
            result.append({**base, **figure, 'metric_id': metric_id, 'kind': kind,
                           'source_form': 'BS' if kind == 'stock' else 'PL', 'source_code': None,
                           'unit': 'UZS_thousand', 'value': str(Decimal(value) / 1000), 'quality': 'valid',
                           'period_start': meta['period_end'] if kind == 'stock' else meta['period_start'],
                           'normalization': 'approved normalized UZS / 1000'})
    return [canonical_ifrs_metric(row) for row in result] if canonical_metrics else result


def check(observations):
    """Flag source arithmetic; never repair a source total by subtraction."""
    issues = []
    groups = {}
    for row in observations:
        key = (row.get('source_version'), row['period_end'], row.get('scope'), row.get('period_start'))
        groups.setdefault(key, []).append(row)
    for (_, end, scope, _), rows in groups.items():
        values = {}
        for row in rows:
            if row.get('metric_id') and row.get('value') is not None and row.get('quality') in {'valid', 'warn'}:
                values.setdefault(row['metric_id'], []).append(row)
        rules = [
            ('SOURCE_BALANCE_MISMATCH', 'total_assets', [('total_assets', 1), ('total_liabilities', -1), ('total_equity', -1)]),
            ('SOURCE_ASSET_SUBTOTAL_MISMATCH', 'total_assets', [('total_assets', 1), ('noncurrent_assets', -1), ('current_assets', -1)]),
            ('SOURCE_PASSIVE_TOTAL_MISMATCH', 'total_assets', [('total_assets', 1), ('total_equity_liabilities', -1)]),
            ('SOURCE_RESERVE_MISMATCH', 'insurance_reserves_net', [('insurance_reserves_gross', 1), ('reinsurer_share_reserves', -1), ('insurance_reserves_net', -1)]),
            ('SOURCE_INSURANCE_BALANCE_MISMATCH', 'total_assets', [('total_assets', 1), ('total_equity', -1), ('insurance_reserves_net', -1), ('nonreserve_liabilities', -1)]),
        ]
        if rows[0].get('standard') == 'NSBU' and any(r.get('source_form') == 'F2' for r in rows):
            rules += [
                ('SOURCE_GROSS_PROFIT_MISMATCH', 'gross_profit', [('revenue', 1), ('cost_of_sales', 1), ('gross_profit', -1)]),
                ('SOURCE_OPERATING_PROFIT_MISMATCH', 'operating_income', [('gross_profit', 1), ('operating_expenses', 1), ('other_operating_income', 1), ('operating_income', -1)]),
                ('SOURCE_NET_PROFIT_MISMATCH', 'net_income', [('profit_before_tax', 1), ('income_tax', 1), ('other_profit_payments', 1), ('net_income', -1)]),
            ]
        for code, total_field, terms in rules:
            if not all(len(values.get(field, [])) == 1 for field, _ in terms):
                continue
            parts = [values[field][0] for field, _ in terms]
            difference = sum(Decimal(part['value']) * sign for part, (_, sign) in zip(parts, terms))
            if abs(difference) > 1:  # one display unit, thousands UZS, permits source rounding
                reported = Decimal(values[total_field][0]['value'])
                total_sign = dict(terms)[total_field]
                reconciled = reported - difference / total_sign
                limit = min(abs(reported), abs(reconciled)) * RECONCILIATION_RELATIVE_LIMIT
                severity = 'warn' if abs(difference) <= limit else 'blocked'
                issue = {'code': code, 'period_end': end, 'scope': scope,
                         'difference': str(difference), 'unit': 'UZS_thousand',
                         'severity': severity, 'metric_id': total_field,
                         'reported_total': str(reported), 'reconciled_total': str(reconciled),
                         'source_version': parts[0].get('source_version')}
                issues.append(issue)
                for row in parts:
                    row.setdefault('reconciliation_issues', []).append(issue)
                    # A later minor mismatch must never erase a blocking one.
                    if row['quality'] != 'blocked':
                        row.update(quality=severity, reason=code)
    return issues
