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


def _apply(row, source, corrections, backup_dir):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--tickers', nargs='+')
    args = parser.parse_args()
    print(json.dumps(repair(tickers=args.tickers, apply=args.apply), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
