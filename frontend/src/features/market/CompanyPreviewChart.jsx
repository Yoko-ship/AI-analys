import React from 'react';
import { isoDay, ohlcBar, priceFormatFor } from '../../charts/lwCore.js';
import { safeNumber, formatCompactNumber } from '../../lib/numberFormat.js';

// A static SVG keeps a small hover chart quick to open and does not capture
// wheel gestures from the market table. Missing OHLC stays a close-only tick.
export function CompanyPreviewChart({ points, ticker, lang, t }) {
  const byDate = new Map();
  for (const point of points || []) {
    const date = isoDay(point.date), close = safeNumber(point.close);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || !(close > 0)) continue;
    byDate.set(date, { date, close, open: safeNumber(point.open), high: safeNumber(point.high),
      low: safeNumber(point.low), turnover: safeNumber(point.value) });
  }
  const data = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  if (!data.length) return <div className="company-preview-empty" role="status">{t('Нет истории торгов за 6 месяцев', '6 oylik savdo tarixi yo‘q', 'No trading history for the last 6 months')}</div>;
  const bars = data.map(p => ({ ...ohlcBar(p, p.date), turnover: p.turnover }));
  const low = Math.min(...bars.map(p => p.low)), high = Math.max(...bars.map(p => p.high));
  const padding = (high - low) * 0.12 || high * 0.03;
  const min = Math.max(0, low - padding), max = high + padding;
  const left = 10, right = 394, top = 12, bottom = 156, volumeBottom = 199;
  const step = (right - left) / bars.length, width = Math.max(1, Math.min(5, step * 0.66));
  const x = i => left + step * (i + 0.5);
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);
  const maxTurnover = Math.max(0, ...bars.map(p => p.turnover || 0));
  const price = priceFormatFor(data.at(-1).close, lang).formatter;
  const month = date => new Intl.DateTimeFormat(lang === 'en' ? 'en' : lang === 'uz' ? 'uz' : 'ru',
    { month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`));
  const months = data.flatMap((p, i) => !i || p.date.slice(0, 7) !== data[i - 1].date.slice(0, 7) ? [{ i, date: p.date }] : []);
  const last = bars.at(-1);
  return <figure className="company-preview-figure"><svg className="company-preview-chart" viewBox="0 0 472 222" role="img"
    aria-label={`${t('График цены', 'Narx grafigi', 'Price chart')} ${ticker}: ${data[0].date} — ${data.at(-1).date}`}>
    <title>{ticker} · {t('Дневные цены и оборот в UZS', 'Kunlik narxlar va UZS aylanmasi', 'Daily prices and turnover in UZS')}</title>
    {[0, 1, 2, 3].map(i => {
      const value = min + (max - min) * i / 3;
      return <g key={i} className="company-preview-grid"><line x1={left} x2={right} y1={y(value)} y2={y(value)} />
        <text x={right + 8} y={y(value) + 3}>{price(value)}</text></g>;
    })}
    {months.map(({ i, date }) => <g key={date} className="company-preview-grid">
      <line x1={x(i)} x2={x(i)} y1={top} y2={volumeBottom} />
      <text x={Math.max(20, x(i))} y="216" textAnchor="middle">{month(date)}</text>
    </g>)}
    {bars.map((bar, i) => <g key={bar.time} data-candle={bar.time}
      className={bar.close >= bar.open ? 'company-preview-up' : 'company-preview-down'}>
      <line x1={x(i)} x2={x(i)} y1={y(bar.high)} y2={y(bar.low)} stroke="currentColor" />
      <rect x={x(i) - width / 2} y={Math.min(y(bar.open), y(bar.close))} width={width}
        height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} fill="currentColor" />
      {bar.turnover > 0 && <rect x={x(i) - width / 2} y={volumeBottom - bar.turnover / maxTurnover * 27}
        width={width} height={bar.turnover / maxTurnover * 27} fill="currentColor" opacity="0.5" />}
    </g>)}
    <text className="company-preview-axis" x="10" y="173">{t('Оборот', 'Aylanma', 'Turnover')} · UZS{maxTurnover > 0 ? ` · ${formatCompactNumber(maxTurnover, lang)}` : ''}</text>
    <line className="company-preview-last-line" x1={left} x2={right} y1={y(last.close)} y2={y(last.close)} />
    <rect className="company-preview-price-tag" x={right + 3} y={y(last.close) - 9} width="73" height="18" rx="3" />
    <text className="company-preview-price-text" x={right + 7} y={y(last.close) + 3}>{price(last.close)}</text>
  </svg><figcaption>{t('История', 'Tarix', 'History')}: <time>{data[0].date}</time> — <time>{data.at(-1).date}</time></figcaption></figure>;
}
