"""One batch read for the administrator's technical screener."""
import corporate_actions
import catalogue.market_store as quotes
import securities_catalog as securities
from technical_screener import snapshot, stamp


def load():
    universe = {ticker: meta for ticker, meta in securities.get_securities_map().items()
                if str(meta.get('type') or meta.get('security_type') or '').lower() != 'bond'}
    codes = sorted({str(meta.get('isin') or '').upper() for meta in universe.values()} - {''})
    history = quotes.get_quote_history(codes, 600)
    as_of = max((day for rows in history.values() for row in rows
                 if (day := stamp(row.get('trade_date'))) is not None), default=None)
    technical = {}
    for ticker, meta in universe.items():
        isin = str(meta.get('isin') or '').upper()
        rows, _ = corporate_actions.adjust_history(
            history.get(isin, []), ticker, isin, date_key='trade_date',
            price_fields=('close_price', 'open_price', 'high_price', 'low_price'))
        technical[ticker] = snapshot(rows, as_of)
    return {'ok': True, 'as_of': as_of.isoformat() if as_of else None, 'technical': technical}
