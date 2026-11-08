import { fileURLToPath } from 'node:url';

const landingLogos = { HMKB: '/logos/HMKB_MARK.png', GRBK: '/logos/GRBK.png', UZTL: '/logos/UZTL_MARK.svg' };

export const landingStocks = [
  { ticker: 'HMKB', name: 'Хамкорбанк', last_price: 118, close_price: 116, sector: 'finance', volume: 900000 },
  { ticker: 'GRBK', name: 'Гарант банк', last_price: 4315, close_price: 4006, sector: 'finance', volume: 800000 },
  { ticker: 'UZMT', name: 'Узметкомбинат', last_price: 51200, close_price: 53000, sector: 'manufacturing', volume: 700000 },
  { ticker: 'UZTL', name: 'Узбектелеком', last_price: 22298, close_price: 22149, sector: 'telecom', volume: 600000 },
  { ticker: 'MIQE', isin: 'UZ7007440009', name: 'Minora qurish ekspeditsiyasi', last_price: null, close_price: null, sector: 'other', volume: null },
].map(stock => ({ ...stock, type: 'stock', last_trade_date: '2026-11-06', quantity: 100, trade_count: 2 }));

export async function setupLanding(page, { theme = 'dark', language = 'ru', width = 1440 } = {}) {
  await page.setViewportSize({ width, height: 1000 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(({ theme, language }) => {
    if (!localStorage.getItem('uz_stock_analyzer_theme')) localStorage.setItem('uz_stock_analyzer_theme', theme);
    if (!localStorage.getItem('uz_stock_analyzer_language')) localStorage.setItem('uz_stock_analyzer_language', language);
    localStorage.setItem('uz_track_internal', '1');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  }, { theme, language });
  await page.route('**/logos/**', route => route.fulfill({
    path: fileURLToPath(new URL(`..${new URL(route.request().url()).pathname}`, import.meta.url)),
  }));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const payload = path === '/api/market/stocks' ? { stocks: [...landingStocks, { ticker: 'BOND', type: 'bond', last_price: 1000000 }] }
      : path === '/api/companies' ? { companies: landingStocks.map(s => ({ ...s, company_name: s.name })) }
      : path === '/api/securities' ? { securities: Object.fromEntries(landingStocks.map(s => [s.ticker, { ...s, logo_url: landingLogos[s.ticker] }])) }
      : path === '/api/market/trade-stats' ? { trade_date: '20261106', stats: { UZ7007440009: { trade_date: '20261106', total_value: 240100, total_qty: 100, trade_count: 4, avg_price: 2401 } } }
      : path === '/api/news/feed' ? { items: [{ id: 6570, lang: 'ru', title: 'Компании опубликовали годовые результаты', title_ru: 'Компании опубликовали годовые результаты', title_en: 'Companies publish annual results', title_uz: 'Kompaniyalar yillik natijalarni e’lon qildi', published_at: '2026-11-06T10:00:00Z', source: 'OpenInfo' }] }
      : { items: [], stats: {}, series: {}, changes: {} };
    return route.fulfill({ json: { ok: true, ...payload } });
  });
}
