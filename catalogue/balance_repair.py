"""Reconcile retained balances against their exact filing, with an audit backup.

Only superseded algebraic corrections can be reverted automatically. A manual
review remains authoritative. Unavailable, wrong-period and unbalanced filings
are reported without changing the stored financial data.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlparse

import data_quality as dq
from catalogue import codecs, filings, parsing, periods, ratios, sources, storage

BALANCE_FIELDS = ('total_assets', 'total_equity', 'total_liabilities')
ALGEBRAIC_REASON = 'Автоматическая подсказка по формуле:'


def verified_balance(ticker, form, year, quarter):
    urls = filings.get_report_urls(ticker, form, year, quarter) or {}
    source_url = urls.get('excel_url_form1') or urls.get('excel_url')
    if not source_url:
        raise ValueError('No linked balance workbook')
    workbook = sources.fetch_report_excel_data(ticker, form, year, quarter)
    if not workbook.get('ok') or not workbook.get('balance'):
        raise ValueError('Balance workbook unavailable')
    conflict = periods.header_period_conflict(workbook['balance'], year, quarter, urls.get('published_at'))
    if conflict:
        raise ValueError('Balance workbook belongs to a different reporting period')
    values = parsing.compute_filing_values(workbook.get('income'), workbook['balance'])['source_values']
    # A derived equity makes an identity check tautological. Verification must
    # use the explicitly filed totals, including the separate bank form.
    if parse_qs(urlparse(source_url).query).get('org_type') == ['bank']:
        from sector_report_service import map_special_lines
        snapshot = {'current_values': {}, 'opening_values': {}, 'previous_values': {},
                    'quality': {'data_quality': []}}
        map_special_lines(snapshot, {'balance': workbook['balance']}, 'bank')
        values.update({f: snapshot['current_values'].get(f) for f in BALANCE_FIELDS})
        values['balance'] = {name + suffix: snapshot[target].get(field)
                             for name, field in (('assets', 'total_assets'), ('equity', 'total_equity'))
                             for suffix, target in (('_end', 'current_values'), ('_start', 'opening_values'))}
    else:
        insurance = values.get('gross_insurance_reserves') is not None or values.get('net_insurance_reserves') is not None
        filed = parsing._filed_return_balance(workbook['balance'], insurance)
        values['total_assets'], values['total_equity'] = filed.get('assets_end'), filed.get('equity_end')
        if not insurance:
            from financial_analysis.sector_inputs import FORM1, source_line_pairs
            from financial_analysis.sector_numbers import number
            code = next(code for code, field in FORM1.items() if field == 'total_liabilities')
            row = source_line_pairs(workbook['balance'], 'form1').get(code) or {}
            values['total_liabilities'] = number(row.get('raw_current'))
    totals = [values.get(field) for field in BALANCE_FIELDS]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in totals):
        raise ValueError('Filing balance is incomplete')
    assets, equity, liabilities = totals
    if assets <= 0 or abs(assets - equity - liabilities) > max(1.0, abs(assets) * 0.0005):
        raise ValueError('Filing balance does not reconcile')
    return {**{f: values[f] for f in BALANCE_FIELDS}, 'balance': values.get('balance'), 'source_url': source_url}


def _candidates(tickers):
    conn = storage.get_catalog_conn()
    try:
        dq._ensure_schema(conn)
        corrections = [dict(r) for r in conn.execute(
            "SELECT * FROM data_corrections WHERE dataset='financials' AND form='NSBU' AND status='approved'").fetchall()]
        rows = [dict(r) for r in conn.execute("SELECT * FROM catalog_financials WHERE form='NSBU'").fetchall()]
    finally:
        conn.close()
    auto_keys = {(r['ticker'], r['year'], r['quarter']) for r in corrections
                 if r['field'] in BALANCE_FIELDS and r['reason'].startswith(ALGEBRAIC_REASON)}
    selected_tickers = {t.upper() for t in tickers or ()}
    eligible = [r for r in rows if (r['ticker'] in selected_tickers if selected_tickers else
                r.get('org_type') == 'insurance' or (r['ticker'], r['year'], r['quarter']) in auto_keys)]
    selected = {}
    for ticker in {r['ticker'] for r in eligible}:
        own = [r for r in eligible if r['ticker'] == ticker]
        latest = max(own, key=lambda r: (r['year'], r['quarter'] or 5))
        selected[(ticker, latest['year'], latest['quarter'])] = latest
        annual = [r for r in rows if r['ticker'] == ticker and r['quarter'] == 0 and r['year'] <= latest['year']]
        if annual:
            last = max(annual, key=lambda r: r['year'])
            selected[(ticker, last['year'], last['quarter'])] = last
    for row in eligible:
        key = row['ticker'], row['year'], row['quarter']
        if key in auto_keys:
            selected[key] = row
    return [selected[k] for k in sorted(selected)], corrections


def _apply(row, source, corrections, backup_dir, *, restore=False):
    backup_dir.mkdir(parents=True, exist_ok=True)
    record = {'original': row, 'source': source, 'corrections': corrections, 'created_at': dq._now()}
    path = backup_dir / f"{row['ticker']}-{row['year']}Q{row['quarter']}-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    conn = storage.get_catalog_conn()
    try:
        with conn:
            params = [source[f] for f in BALANCE_FIELDS]
            balance = codecs._encode_balance_period(source['balance'])
            field_periods = codecs._decode_field_periods(row.get('field_periods')) or {}
            for field in BALANCE_FIELDS:
                field_periods.pop(field, None)
                if restore and field in source.get('field_periods', {}):
                    field_periods[field] = source['field_periods'][field]
            params += [balance, codecs._encode_field_periods(field_periods), row['ticker'], row['form'], row['year'], row['quarter']]
            conditions = []
            for field in (*BALANCE_FIELDS, 'balance_period'):
                # dbx translates SQLite's null-safe IS into PostgreSQL's
                # IS NOT DISTINCT FROM, preserving parameter type inference.
                conditions.append(f'{field} IS ?')
                params.append(row.get(field))
            cursor = conn.execute(
                "UPDATE catalog_financials SET total_assets=?, total_equity=?, total_liabilities=?, "
                "balance_period=?, field_periods=?, updated_at=datetime('now') "
                "WHERE ticker=? AND form=? AND year=? AND quarter=? AND " + ' AND '.join(conditions), params)
            if cursor.rowcount != 1:
                raise ValueError('Stored balance changed during verification; retry required')
            for correction in corrections:
                if restore:
                    restored = conn.execute(
                        "UPDATE data_corrections SET status='approved', reviewed_by=?, reviewed_at=?, review_note=? "
                        "WHERE id=? AND status='reverted' AND reviewed_by='verified-filing-reconciliation'",
                        (correction.get('reviewed_by'), correction.get('reviewed_at'),
                         correction.get('review_note'), correction['id']))
                    if restored.rowcount != 1:
                        raise ValueError('Correction changed after reconciliation; manual review required')
                    continue
                conn.execute("UPDATE data_corrections SET status='reverted', reviewed_by=?, reviewed_at=?, review_note=? "
                             "WHERE id=? AND status='approved'",
                             ('verified-filing-reconciliation', dq._now(),
                              'Superseded algebraic proposal; reconciled against exact official filing: ' + source['source_url'],
                              correction['id']))
    finally:
        conn.close()
    ratios.invalidate_ratios_cache()


def repair(*, tickers=None, apply=False, backup_dir=None):
    if backup_dir is None:
        from db import APP_DATA_DIR
        backup_dir = APP_DATA_DIR / 'balance-repair-backups'
    rows, approved = _candidates(tickers)
    result = {'changed': 0, 'plans': [], 'skipped': []}
    for row in rows:
        key = {k: row[k] for k in ('ticker', 'form', 'year', 'quarter')}
        try:
            source = verified_balance(**key)
            stale = [c for c in approved if all(c[k] == key[k] for k in key)
                     and c['field'] in BALANCE_FIELDS and c['reason'].startswith(ALGEBRAIC_REASON)
                     and not math.isclose(float(c['value_thousands_uzs']), source[c['field']], rel_tol=1e-12, abs_tol=0.01)]
            changed = any(row.get(f) != source[f] for f in BALANCE_FIELDS)
            changed |= codecs._decode_balance_period(row.get('balance_period')) != source['balance']
            if not changed and not stale:
                continue
            plan = {**key, 'before': {f: row.get(f) for f in BALANCE_FIELDS},
                    'after': {f: source[f] for f in BALANCE_FIELDS},
                    'revert_correction_ids': [c['id'] for c in stale], 'source_url': source['source_url']}
            result['plans'].append(plan)
            if apply:
                _apply(row, source, stale, Path(backup_dir))
                result['changed'] += 1
        except Exception as exc:
            # Avoid leaking connection details from unexpected infrastructure errors.
            reason = str(exc) if type(exc) is ValueError else type(exc).__name__
            result['skipped'].append({**key, 'reason': reason})
    return result


def rollback_unverified(*, backup_dir=None, apply=False):
    """Undo only this utility's unchanged writes that fail explicit-source proof."""
    if backup_dir is None:
        from db import APP_DATA_DIR
        backup_dir = APP_DATA_DIR / 'balance-repair-backups'
    backup_dir = Path(backup_dir)
    result = {'restored': 0, 'plans': [], 'skipped': []}
    for path in sorted(backup_dir.glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        original, written = record['original'], record['source']
        key = {k: original[k] for k in ('ticker', 'form', 'year', 'quarter')}
        try:
            verified_balance(**key)
            continue
        except ValueError as exc:
            # Missing evidence is not contradictory evidence: only a complete,
            # explicitly filed balance that fails its identity warrants undo.
            if str(exc) != 'Filing balance does not reconcile':
                continue
        except Exception:
            continue
        conn = storage.get_catalog_conn()
        try:
            current = conn.execute('SELECT * FROM catalog_financials WHERE ticker=? AND form=? AND year=? AND quarter=?',
                                   tuple(key.values())).fetchone()
        finally:
            conn.close()
        if not current or any(current[f] != written[f] for f in BALANCE_FIELDS):
            continue
        if codecs._decode_balance_period(current['balance_period']) != codecs._decode_balance_period(written['balance']):
            continue
        result['plans'].append({**key, 'backup': path.name})
        if apply:
            restored = {f: original[f] for f in BALANCE_FIELDS}
            restored.update(balance=codecs._decode_balance_period(original['balance_period']),
                            source_url=written['source_url'], rollback_of=path.name,
                            field_periods=codecs._decode_field_periods(original.get('field_periods')))
            try:
                _apply(dict(current), restored, record['corrections'], backup_dir/'rollbacks', restore=True)
                result['restored'] += 1
            except Exception as exc:
                result['skipped'].append({**key, 'reason': type(exc).__name__})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--tickers', nargs='+')
    parser.add_argument('--rollback-unverified', action='store_true')
    args = parser.parse_args()
    result = rollback_unverified(apply=args.apply) if args.rollback_unverified else repair(tickers=args.tickers, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
