import { prepareMarketRows } from '../../lib/marketData.js';
import { sectorOf } from '../../lib/sectors.js';
import { marketRowDay, normalizeMarketDay } from '../../lib/valuation.js';

/** One actively traded share per sector, compared within the same market session. */
export function selectSectorLeaders(market = {}, sectorKeys = []) {
  const { marketRows, marketTradeStats, securitiesMap, companies = [], marketMeta } = market;
  const companyMap = Object.fromEntries(companies.map(company => [company.ticker, company]));
  const rows = prepareMarketRows(marketRows, marketTradeStats)
    .filter(row => row.ticker && row.type !== 'bond' && securitiesMap?.[row.ticker]?.type !== 'bond')
    .map(row => ({
      ticker: row.ticker,
      sector: sectorOf(row.ticker, securitiesMap, companyMap),
      turnover: row.stockVolume,
      trades: row.stockTradeCount || 0,
      // A newer negotiated-only deal leaves the older auction totals intact.
      // Its date must not promote those historic totals into today's ranking.
      tradeDate: row.ts?.trade_count > 0 || row.ts?.total_qty > 0
        ? marketRowDay(row) : normalizeMarketDay(row.last_trade_date),
    }));
  const session = rows.reduce((latest, row) => row.tradeDate > latest ? row.tradeDate : latest,
    normalizeMarketDay(marketMeta?.trade_date) || '');
  if (!session) return [];
  const active = rows.filter(row => row.tradeDate === session && row.turnover > 0)
    .sort((a, b) => b.turnover - a.turnover || b.trades - a.trades || a.ticker.localeCompare(b.ticker, 'en'));
  return sectorKeys.map(sector => active.find(row => row.sector === sector)).filter(Boolean);
}
