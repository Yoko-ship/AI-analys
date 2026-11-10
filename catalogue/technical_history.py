"""Inspect and recover missing ATR history from official, unadjusted daily prices."""
import argparse
from datetime import date, timedelta
import json
from math import isclose

import catalogue.market_store as quotes
from collectors.openinfo import transport
from collectors.openinfo.market_history import fetch_execution_history
import corporate_actions
from formulas import months_before
import securities_catalog as securities
from technical_screener import number, snapshot, stamp


def _snapshot(rows, ticker, isin):
    adjusted, _ = corporate_actions.adjust_history(
        rows, ticker, isin, date_key='trade_date',
        price_fields=('open_price', 'high_price', 'low_price', 'close_price'))
    return snapshot(adjusted)


def _fill_gaps(stored, points, isin, *, source='official'):
    """Only fill unknown fields or add missing sessions; keep known prices intact."""
    combined = {stamp(r['trade_date']): dict(r) for r in stored}
    changed = {}
    candidates = {}
    for point in points:
        day = stamp(point.get('date'))
        if day is None:
            raise ValueError('Invalid archive date')
        row = {'isin': isin, 'trade_date': day.strftime('%Y%m%d'),
               **{f'{key}_price': number(point.get(key), positive=True)
                  for key in ('open', 'high', 'low', 'close')},
               'quantity': number(point.get('trading_volume')),
               'turnover': number(point.get('trading_value'))}
        group = candidates.setdefault(day, [])
        if row not in group:
            group.append(row)
    for day, group in candidates.items():
        current = combined.get(day, {})
        if len(group) > 1:
            # KSCMP's archive has two different 2024-03-17 conclusions.
            # Only use the one corroborated by the stored session; without
            # independent evidence the date remains a gap, not an arbitrary pick.
            fields = ('close_price', 'quantity', 'turnover')
            group = [r for r in group if current.get('close_price') is not None
                     and all(current.get(k) is None or (r.get(k) is not None
                             and isclose(current[k], r[k], rel_tol=1e-6)) for k in fields)]
        if len(group) != 1:
            if day not in combined:
                combined[day] = {'isin': isin, 'trade_date': day.strftime('%Y%m%d')}
                changed[day] = combined[day]
            continue
        row = group[0]
        merged = {**row, **{k: v for k, v in current.items() if v is not None}}
        if any(v is not None and current.get(k) is None for k, v in row.items()):
            combined[day] = merged
            changed[day] = merged
    return list(combined.values()), [dict(r, source=source) for r in changed.values()]


def repair(*, apply=False, months=240):
    """Preview by default. Apply only repairs that yield a valid ATR(14).

    Uses the same paced transport as the collector. No source requests run in
    the screener HTTP request. Raw prices stay raw in storage so corporate
    actions are applied exactly once when the screener reads them.
    """
    if not 1 <= months <= 240:
        raise ValueError('months must be between 1 and 240')
    universe = {t: m for t, m in securities.get_securities_map().items()
                if str(m.get('type') or m.get('security_type') or '').lower() != 'bond'}
    codes = {str(m.get('isin') or '').strip().upper() for m in universe.values()} - {''}
    history = quotes.get_quote_history(sorted(codes), 600)
    results = []
    with transport._make_session() as session:
        for ticker, meta in sorted(universe.items()):
            isin = str(meta.get('isin') or '').strip().upper()
            result = {'ticker': ticker, 'isin': isin}
            results.append(result)
            if not isin:
                result['status'] = 'missing_isin'
                continue
            stored = history.get(isin, [])
            before = _snapshot(stored, ticker, isin)
            result['observations'] = before['observations']
            if before['values']['atr14'] is not None:
                result['status'] = 'available'
                continue
            try:
                start, end = months_before(date.today(), months), date.today()
                payload = transport._json_get(session, '/iuzse/conclusions/', {
                    'isu_cd': isin, 'start_date': start.isoformat(),
                    'end_date': (end + timedelta(days=1)).isoformat()})
                points = payload.get('results') or []
                if points and str(payload.get('ticker') or '').strip().upper() != ticker.upper():
                    result['status'] = 'source_mismatch'
                    continue
                proposed, changes = _fill_gaps(stored, points, isin)
                after = _snapshot(proposed, ticker, isin)
                result.update(archive_sessions=len(points), observations=after['observations'])
                execution_changes = []
                if after['values']['atr14'] is None:
                    executions = fetch_execution_history(session, isin, start, end)
                    proposed, execution_changes = _fill_gaps(proposed, executions, isin, source='executions')
                    after = _snapshot(proposed, ticker, isin)
                    result.update(execution_sessions=len(executions), observations=after['observations'])
                if after['values']['atr14'] is None:
                    result['status'] = after['missing']['atr14']
                    continue
            except Exception as exc:
                result.update(status='source_error', error=type(exc).__name__)
                continue
            result.update(status='recoverable', sessions_to_write=len(changes) + len(execution_changes), atr14=after['values']['atr14'])
            if apply:
                quotes.bulk_upsert_quote_history(changes)
                quotes.bulk_upsert_quote_history(execution_changes)
                actual = quotes.get_quote_history([isin], 600).get(isin, [])
                verified = _snapshot(actual, ticker, isin)
                result.update(status='recovered' if verified['values']['atr14'] is not None else 'verification_failed',
                              atr14=verified['values']['atr14'])
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Fill verified gaps in the configured catalogue')
    parser.add_argument('--months', type=int, default=240)
    args = parser.parse_args()
    results = repair(apply=args.apply, months=args.months)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(r['status'] in {'source_error', 'source_mismatch', 'verification_failed'} for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
