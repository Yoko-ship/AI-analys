import {formatRatio} from '../../shared/format.jsx';
import {technicalDescription, technicalValue, TECHNICAL_PERCENT, tt} from './technicalColumns.js';

export function technicalCell(row, key, data, lang) {
  const snapshot = data[row.ticker];
  const value = technicalValue(data, row.ticker, key);
  const reason = snapshot?.missing?.[key];
  const missing = reason === 'benchmark_unavailable' ? technicalDescription('beta', lang)
    : reason === 'missing_ohlc' ? tt(lang, 'Нет проверенных цен открытия, максимума или минимума.', 'Tasdiqlangan ochilish, maksimum yoki minimum narxlari yo‘q.', 'Verified open, high or low prices are missing.')
    : tt(lang, 'Недостаточно истории.', 'Tarix yetarli emas.', 'Insufficient history.');
  const title = [technicalDescription(key, lang), snapshot?.as_of,
    snapshot && `${snapshot.observations} ${tt(lang, 'сессий', 'sessiya', 'sessions')}`, value == null && reason !== 'benchmark_unavailable' ? missing : null].filter(Boolean).join(' · ');
  const percent = TECHNICAL_PERCENT.has(key);
  return <td className={`num${percent && value ? value > 0 ? ' technical-value-positive' : ' technical-value-negative' : ''}`} data-technical={key} title={title}>
    {value == null ? '—' : `${formatRatio(value, key === 'dayVolume' ? 0 : 2, lang)}${percent ? '%' : ''}`}
  </td>;
}
