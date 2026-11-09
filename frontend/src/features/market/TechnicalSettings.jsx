import {TECHNICAL_DEFAULTS, numericBound, technicalDescription, tt} from './technicalColumns.js';
import './technical.css';

export function TechnicalSettings({lang, cols, visibleCols, toggleCol, setVisibleCols, filters, setFilters}) {
  const from = tt(lang, 'от', 'dan', 'min'), to = tt(lang, 'до', 'gacha', 'max');
  return <div className="technical-settings" data-testid="technical-settings">
    <p>{tt(lang, 'Дневные сессии · цены с учётом дроблений. Последняя цена уже есть в таблице.', 'Kunlik sessiyalar · splitga tuzatilgan narxlar. Oxirgi narx jadvalda bor.', 'Daily sessions · split-adjusted prices. Last price is already in the table.')}</p>
    <div className="technical-actions">
      <button type="button" onClick={() => setVisibleCols(previous => new Set([...previous, ...TECHNICAL_DEFAULTS]))}>{tt(lang, 'Показать Technical', 'Technical ko‘rsatish', 'Show Technical')}</button>
      <button type="button" onClick={() => setFilters({})}>{tt(lang, 'Сбросить фильтры', 'Filtrlarni tozalash', 'Reset filters')}</button>
    </div>
    <div className="technical-range-heading"><span>{tt(lang, 'Колонка / фильтр', 'Ustun / filtr', 'Column / filter')}</span><span>{from}</span><span>{to}</span></div>
    {[['last', tt(lang, 'Цена, UZS', 'Narx, UZS', 'Price, UZS')], ...cols].map(([key, label]) => {
      const range = filters[key] || {};
      const min = numericBound(range.min), max = numericBound(range.max);
      const invalid = min != null && max != null && min > max;
      return <div key={key} className="technical-setting-row">
        <label title={technicalDescription(key, lang)}><input type="checkbox" checked={key === 'last' || visibleCols.has(key)} disabled={key === 'last'} onChange={() => toggleCol(key)} aria-label={label} /><span>{label}</span></label>
        {['min', 'max'].map((bound, index) => <input key={bound} type="number" step="any" inputMode="decimal" value={range[bound] ?? ''}
          aria-label={`${label}: ${index ? to : from}`} aria-invalid={invalid || undefined}
          onChange={event => setFilters(previous => ({...previous, [key]:{...previous[key], [bound]:event.target.value}}))} />)}
        {invalid && <span className="technical-range-error" role="alert">{tt(lang, 'Минимум больше максимума', 'Minimum maksimumdan katta', 'Minimum exceeds maximum')}</span>}
      </div>;
    })}
    <p>{tt(lang, 'ATR и Beta — необязательные. Beta пока недоступна: нет проверенной истории индекса. Фильтр исключает бумаги без значения.', 'ATR va Beta ixtiyoriy. Beta hozircha mavjud emas: tasdiqlangan indeks tarixi yo‘q. Filtr qiymati yo‘q aksiyalarni chiqaradi.', 'ATR and Beta are optional. Beta is unavailable without verified index history. Filters exclude missing values.')}</p>
  </div>;
}

export function TechnicalStatus({lang, status, asOf, retry, filtered, clear}) {
  return <div className="technical-status" data-testid="technical-status" role={status === 'error' ? 'alert' : 'status'}>
    <span>{status === 'loading' ? tt(lang, 'Загрузка Technical…', 'Technical yuklanmoqda…', 'Loading Technical…')
      : status === 'error' ? tt(lang, 'Не удалось загрузить Technical.', 'Technical yuklanmadi.', 'Could not load Technical.')
      : `${tt(lang, 'Technical · рынок на', 'Technical · bozor sanasi', 'Technical · market as of')} ${asOf || '—'} · ${tt(lang, 'Даты отдельных бумаг — в подсказках. Нет данных — «—».', 'Alohida aksiya sanalari izohlarda. Ma’lumot yo‘q — «—».', 'Per-security dates are in tooltips. Missing data: “—”.')}`}</span>
    {status === 'error' && <button type="button" onClick={retry}>{tt(lang, 'Повторить Technical', 'Technical qayta urinish', 'Retry Technical')}</button>}
    {filtered && <button type="button" onClick={clear}>{tt(lang, 'Сбросить Technical', 'Technical tozalash', 'Clear Technical')}</button>}
  </div>;
}
