"""Complete, price-eligible daily history from OpenInfo's execution archive."""
from collections import defaultdict
from datetime import datetime
from math import ceil

from collectors.openinfo import transport
from collectors.openinfo.market_fallback import (
    MAX_SESSION_PAGES, MAX_SESSION_RECORDS, TASHKENT, _board_execution, _session_finished,
)
import trade_stats


def fetch_execution_history(session, isin, start, end):
    """Read a bounded, stable archive; never treat a short page as full history.

    T1/NC transfers do not set the order-book price. Tied executions without
    IDs may establish the range but cannot establish a unique open or close.
    Equal-looking executions remain distinct when summing quantity/turnover.
    """
    if not isin:
        raise ValueError('Execution history requires an ISIN')
    params = {'isu_cd': isin, 'start_date': start.isoformat(),
              'end_date': end.isoformat(), 'page_size': 1000}
    first = transport._json_get(session, '/iuzse/trade-results/', {**params, 'page': 1})
    count, pages, size = (int(first[k]) for k in ('count', 'total_pages', 'page_size'))
    if count == 0 and pages == 0 and first.get('results') == []:
        return []
    if (count < 1 or size < 1 or pages != ceil(count / size)
            or count > MAX_SESSION_RECORDS or pages > MAX_SESSION_PAGES):
        raise ValueError('Invalid or oversized execution history')
    grouped = defaultdict(list)
    for page in range(1, pages + 1):
        payload = first if page == 1 else transport._json_get(
            session, '/iuzse/trade-results/', {**params, 'page': page})
        batch = payload['results']
        if (tuple(payload[k] for k in ('count', 'total_pages', 'page_size')) != (count, pages, size)
                or payload['current_page'] != page or payload['has_next'] is not (page < pages)
                or not isinstance(batch, list) or len(batch) != min(size, count - (page - 1) * size)):
            raise ValueError('Incomplete or changing execution history')
        for record in batch:
            if str(record.get('isin_code') or '').strip().upper() != isin:
                raise ValueError('Execution history returned another security')
            moment = datetime.fromisoformat(record['trade_datetime'])
            if moment.tzinfo is not None:
                moment = moment.astimezone(TASHKENT)
            day = moment.date()
            if not start <= day <= end:
                raise ValueError('Execution history returned another date range')
            item = _board_execution(record, day.strftime('%Y%m%d'))
            if item and not trade_stats._is_block(item) and _session_finished(day.isoformat()):
                grouped[day].append((moment.replace(tzinfo=None), item))
    check = transport._json_get(session, '/iuzse/trade-results/', {**params, 'page': 1})
    if any(check.get(k) != first.get(k) for k in
           ('count', 'total_pages', 'page_size', 'current_page', 'has_next', 'results')):
        raise ValueError('Execution history changed during pagination')
    points = []
    for day, trades in sorted(grouped.items()):
        trades.sort(key=lambda pair: pair[0])
        prices = [r['trade_price'] for _, r in trades]
        opens = {r['trade_price'] for moment, r in trades if moment == trades[0][0]}
        closes = {r['trade_price'] for moment, r in trades if moment == trades[-1][0]}
        points.append({'date': day.isoformat(),
                       'open': next(iter(opens)) if len(opens) == 1 else None,
                       'close': next(iter(closes)) if len(closes) == 1 else None,
                       'high': max(prices), 'low': min(prices),
                       'trading_volume': sum(r['trade_quantity'] for _, r in trades),
                       'trading_value': sum(r['trading_value'] for _, r in trades)})
    return points
