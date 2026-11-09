import {termFor} from '../../lib/glossary.js';

export const TECHNICAL_KEYS = ['sma20', 'sma50', 'sma200', 'high52w', 'low52w', 'rsi14', 'dayChange', 'changeOpen', 'gap', 'dayVolume', 'atr14', 'beta'];
export const TECHNICAL_DEFAULTS = TECHNICAL_KEYS.filter(key => !['atr14', 'beta'].includes(key));
export const TECHNICAL_PERCENT = new Set(['sma20', 'sma50', 'sma200', 'high52w', 'low52w', 'dayChange', 'changeOpen', 'gap']);
export const isTechnical = key => TECHNICAL_KEYS.includes(key);
export const tt = (lang, ru, uz, en) => lang === 'en' ? en : lang === 'uz' ? uz : ru;

export function technicalColumns(lang) {
  return [
    ['sma20', 'SMA20, %'], ['sma50', 'SMA50, %'], ['sma200', 'SMA200, %'],
    ['high52w', '52W High, %'], ['low52w', '52W Low, %'], ['rsi14', 'RSI (14)'],
    ['dayChange', tt(lang, 'Изм. за сессию, %', 'Sessiya o‘zgarishi, %', 'Session change, %')],
    ['changeOpen', tt(lang, 'От открытия, %', 'Ochilishdan, %', 'Change from open, %')],
    ['gap', 'Gap, %'], ['dayVolume', tt(lang, 'Объём, шт.', 'Hajm, dona', 'Volume, shares')],
    ['atr14', 'ATR (14), UZS'], ['beta', 'Beta'],
  ];
}
export function technicalDescription(key, lang) {
  return termFor(key, lang)?.def || '';
}
export function technicalValue(data, ticker, key) {
  const value = data?.[ticker]?.values?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
