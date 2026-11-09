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
  if (key.startsWith('sma')) return tt(lang, 'Отклонение последнего закрытия от среднего за ' + key.slice(3) + ' сессий, %.', 'Oxirgi yopilishning ' + key.slice(3) + ' sessiyalik o‘rtachadan farqi, %.', 'Last close versus the ' + key.slice(3) + '-session simple average, %.');
  const descriptions = {
    high52w: ['Отклонение от максимума за 52 недели, %. Нужна полная история периода.', '52 haftalik maksimumdan farq, %. To‘liq davr tarixi kerak.', 'Distance from the 52-week high, %. Requires full period coverage.'],
    low52w: ['Отклонение от минимума за 52 недели, %. Нужна полная история периода.', '52 haftalik minimumdan farq, %. To‘liq davr tarixi kerak.', 'Distance from the 52-week low, %. Requires full period coverage.'],
    rsi14: ['RSI по Уайлдеру за 14 сессий, от 0 до 100.', '14 sessiyalik Wilder RSI, 0 dan 100 gacha.', 'Wilder RSI over 14 sessions, from 0 to 100.'],
    atr14: ['Средний истинный диапазон по Уайлдеру за 14 сессий, в UZS.', '14 sessiyalik Wilder haqiqiy o‘rtacha diapazoni, UZS.', 'Wilder average true range over 14 sessions, in UZS.'],
    beta: ['Нет проверенной истории рыночного индекса для расчёта Beta.', 'Beta uchun tasdiqlangan bozor indeksi tarixi yo‘q.', 'No verified market-index history is available for Beta.'],
    dayChange: ['Последнее закрытие / предыдущее закрытие − 1, в %.', 'Oxirgi yopilish / oldingi yopilish − 1, %.', 'Last close / previous close − 1, in %.'],
    changeOpen: ['Последнее закрытие / открытие той же сессии − 1, в %.', 'Oxirgi yopilish / shu sessiya ochilishi − 1, %.', 'Last close / same-session open − 1, in %.'],
    gap: ['Открытие / предыдущее закрытие − 1, в %.', 'Ochilish / oldingi yopilish − 1, %.', 'Open / previous close − 1, in %.'],
    dayVolume: ['Количество акций в последней сохранённой сессии.', 'Oxirgi saqlangan sessiyadagi aksiyalar soni.', 'Shares traded in the latest stored session.'],
  };
  return descriptions[key] ? tt(lang, ...descriptions[key]) : '';
}
export function technicalValue(data, ticker, key) {
  const value = data?.[ticker]?.values?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
export function numericBound(value) {
  if (value == null || String(value).trim() === '') return null;
  const number = Number(String(value).trim().replace(',', '.'));
  return Number.isFinite(number) ? number : null;
}
export function hasTechnicalFilters(filters) {
  return Object.values(filters).some(range => numericBound(range.min) != null || numericBound(range.max) != null);
}
export function matchesTechnicalFilters(row, filters, valueOf) {
  return Object.entries(filters).every(([key, range]) => {
    const min = numericBound(range.min), max = numericBound(range.max);
    if (min == null && max == null) return true;
    const value = valueOf(row, key);
    return value != null && Number.isFinite(value) && (min == null || value >= min) && (max == null || value <= max);
  });
}
