"""Daily technical snapshots. Missing sessions/prices are never forward-filled."""
from datetime import date, timedelta
from math import isfinite

KEYS = ('sma20', 'sma50', 'sma200', 'high52w', 'low52w', 'rsi14',
        'dayChange', 'changeOpen', 'gap', 'dayVolume', 'atr14', 'beta')


def number(value, *, positive=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) and (result > 0 if positive else result >= 0) else None


def stamp(value):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def normalize(rows):
    dated = {}
    for raw in rows:
        day = stamp(raw.get('trade_date'))
        if day is None:
            continue
        row = {'date': day, **{key: number(raw.get(key + '_price'), positive=True)
                              for key in ('close', 'open', 'high', 'low')},
               'quantity': number(raw.get('quantity'))}
        # Conflicting duplicate sessions are not two observations or an arbitrary
        # winner. Withhold their prices; the store normally enforces uniqueness.
        if day in dated and dated[day] != row:
            row = dict.fromkeys(row)
            row['date'] = day
        dated[day] = row
    return [dated[day] for day in sorted(dated)]


def pct(value, base):
    return (value / base - 1) * 100 if value is not None and base is not None and base > 0 else None


def wilder_rsi(rows):
    gains, losses, gain, loss = [], [], None, None
    for previous, current in zip(rows, rows[1:]):
        if previous['close'] is None or current['close'] is None:
            gains, losses, gain, loss = [], [], None, None
            continue
        delta = current['close'] - previous['close']
        up, down = max(delta, 0), max(-delta, 0)
        if gain is None:
            gains.append(up)
            losses.append(down)
            if len(gains) == 14:
                gain, loss = sum(gains) / 14, sum(losses) / 14
        else:
            gain, loss = (gain * 13 + up) / 14, (loss * 13 + down) / 14
    if gain is None:
        return None
    return (50 if gain == 0 else 100) if loss == 0 else 100 - 100 / (1 + gain / loss)


def valid_range(row):
    return (all(row[k] is not None for k in ('low', 'high', 'close'))
            and row['low'] <= row['close'] <= row['high']
            and (row['open'] is None or row['low'] <= row['open'] <= row['high']))


def wilder_atr(rows):
    ranges, running = [], None
    for i, row in enumerate(rows):
        previous = rows[i - 1]['close'] if i else row['close']
        if not valid_range(row) or previous is None:
            ranges, running = [], None
            continue
        tr = max(row['high'] - row['low'], abs(row['high'] - previous), abs(row['low'] - previous))
        if running is None:
            ranges.append(tr)
            if len(ranges) == 14:
                running = sum(ranges) / 14
        else:
            running = (running * 13 + tr) / 14
    return running


def snapshot(rows, market_as_of=None):
    rows = normalize(rows)
    values = dict.fromkeys(KEYS)
    missing = dict.fromkeys(KEYS, 'insufficient_history')
    missing['beta'] = 'benchmark_unavailable'
    result = {'as_of': rows[-1]['date'].isoformat() if rows else None,
              'observations': len(rows), 'values': values, 'missing': missing}
    if not rows:
        return result
    latest = rows[-1]
    close = latest['close']
    for size in (20, 50, 200):
        window = rows[-size:]
        if len(window) == size and all(row['close'] is not None for row in window):
            values[f'sma{size}'] = pct(close, sum(row['close'] for row in window) / size)
    values['rsi14'] = wilder_rsi(rows)
    values['atr14'] = wilder_atr(rows)
    if values['atr14'] is None and len(rows) >= 14:
        missing['atr14'] = 'missing_ohlc'
    values['dayVolume'] = latest['quantity']
    values['changeOpen'] = pct(close, latest['open'])
    missing['changeOpen'] = missing['gap'] = 'missing_ohlc'
    if len(rows) >= 2:
        values['dayChange'] = pct(close, rows[-2]['close'])
        values['gap'] = pct(latest['open'], rows[-2]['close'])
    cutoff = (market_as_of or latest['date']) - timedelta(weeks=52)
    window = [row for row in rows if row['date'] >= cutoff]
    # Do not label a newly collected month as a full 52-week range.
    if rows[0]['date'] <= cutoff and window:
        for key, field, extreme in [('high52w', 'high', max), ('low52w', 'low', min)]:
            if all(valid_range(row) for row in window):
                values[key] = pct(close, extreme(row[field] for row in window))
            else:
                missing[key] = 'missing_ohlc'
    result['missing'] = {key: missing[key] for key, value in values.items() if value is None}
    return result
