"""Convert approved source records into normalized, traceable observations."""
from decimal import Decimal


def nsbu(documents):
    result = []
    for doc in documents:
        end, year = doc['period_end'], int(doc['period_end'][:4])
        scale = Decimal(doc.get('unit_scale') or 1000)
        for row in doc['rows']:
            for side in ('current', 'previous'):
                source = row[side]
                when = end if side == 'current' else f'{year-1}-12-31' if row['kind'] == 'stock' else f'{year-1}{end[4:]}'
                value = str(Decimal(source['value']) * scale / 1000) if source.get('value') is not None and doc['quality'] != 'blocked' else None
                quality = 'blocked' if doc['quality'] == 'blocked' else source['quality']
                result.append({**{k:v for k,v in row.items() if k not in {'current', 'previous'}}, **source, 'value': value, 'quality': quality,
                               'standard': 'NSBU', 'scope': doc['scope'], 'issuer_id': doc['issuer_id'],
                               'period_end': when, 'period_start': when if row['kind'] == 'stock' else when[:4] + '-01-01',
                               'role': 'PRIMARY' if side == 'current' else 'COMPARATIVE',
                               'source_version': doc['source_version'], 'published_at': doc.get('published_at'),
                               'previous_version': doc.get('previous_version'),
                               'accounting_model': 'legacy' if doc.get('template') == 'insurance' else None,
                               'currency': doc.get('currency'), 'unit_scale': doc.get('unit_scale'),
                               'normalization': 'raw × unit_scale / 1000',
                               'reason': 'UNIT_UNRESOLVED' if doc['quality'] == 'blocked' else source.get('reason')})
    return result


def ifrs(snapshots):
    result = []
    for snapshot in snapshots:
        payload, meta = snapshot['payload'], snapshot['payload']['classification']
        source = payload.get('source') or {}
        base = {'issuer_id': str(snapshot['org_id']), 'standard': 'MSFO', 'scope': meta['scope'],
                'period_end': meta['period_end'], 'period_start': meta['period_start'],
                'source_version': snapshot['id'], 'source_url': source.get('pdf_url'),
                'published_at': source.get('source_published_at'), 'role': meta.get('role'),
                'audit_status': meta.get('audit_status', 'unknown'), 'accounting_model': meta.get('accounting_model'),
                'currency': meta.get('currency'), 'unit_scale': meta.get('unit_scale'), 'fx': meta.get('fx')}
        mapped = set()
        for row in payload.get('source_rows') or []:
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
    return result


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
            ('SOURCE_BALANCE_MISMATCH', [('total_assets', 1), ('total_liabilities', -1), ('total_equity', -1)]),
            ('SOURCE_ASSET_SUBTOTAL_MISMATCH', [('total_assets', 1), ('noncurrent_assets', -1), ('current_assets', -1)]),
            ('SOURCE_PASSIVE_TOTAL_MISMATCH', [('total_assets', 1), ('total_equity_liabilities', -1)]),
            ('SOURCE_RESERVE_MISMATCH', [('insurance_reserves_gross', 1), ('reinsurer_share_reserves', -1), ('insurance_reserves_net', -1)]),
            ('SOURCE_INSURANCE_BALANCE_MISMATCH', [('total_assets', 1), ('total_equity', -1), ('insurance_reserves_net', -1), ('nonreserve_liabilities', -1)]),
        ]
        if rows[0].get('standard') == 'NSBU' and any(r.get('source_form') == 'F2' for r in rows):
            rules += [
                ('SOURCE_GROSS_PROFIT_MISMATCH', [('revenue', 1), ('cost_of_sales', 1), ('gross_profit', -1)]),
                ('SOURCE_OPERATING_PROFIT_MISMATCH', [('gross_profit', 1), ('operating_expenses', 1), ('other_operating_income', 1), ('operating_income', -1)]),
                ('SOURCE_NET_PROFIT_MISMATCH', [('profit_before_tax', 1), ('income_tax', 1), ('other_profit_payments', 1), ('net_income', -1)]),
            ]
        for code, terms in rules:
            if not all(len(values.get(field, [])) == 1 for field, _ in terms):
                continue
            parts = [values[field][0] for field, _ in terms]
            difference = sum(Decimal(part['value']) * sign for part, (_, sign) in zip(parts, terms))
            if abs(difference) > 1:  # one display unit, thousands UZS, permits source rounding
                issues.append({'code': code, 'period_end': end, 'scope': scope,
                               'difference': str(difference), 'unit': 'UZS_thousand'})
                for row in parts:
                    row.update(quality='blocked', reason=code)
    return issues
