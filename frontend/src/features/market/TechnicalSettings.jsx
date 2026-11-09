import {TermInfo} from '../../shared/TermInfo.jsx';
import {TECHNICAL_DEFAULTS, tt} from './technicalColumns.js';
import './technical.css';

export function TechnicalSettings({lang, cols, visibleCols, toggleCol, setVisibleCols}) {
  return <div className="technical-settings" data-testid="technical-settings">
    <p>{tt(lang, 'Дневные сессии · цены с учётом дроблений. Последняя цена уже есть в таблице.', 'Kunlik sessiyalar · splitga tuzatilgan narxlar. Oxirgi narx jadvalda bor.', 'Daily sessions · split-adjusted prices. Last price is already in the table.')}</p>
    <div className="technical-actions">
      <button type="button" onClick={() => setVisibleCols(previous => new Set([...previous, ...TECHNICAL_DEFAULTS]))}>{tt(lang, 'Показать Technical', 'Technical ko‘rsatish', 'Show Technical')}</button>
    </div>
    {[['last', tt(lang, 'Цена, UZS', 'Narx, UZS', 'Price, UZS')], ...cols].map(([key, label]) => <div key={key} className="technical-setting-row">
      <label><input type="checkbox" checked={key === 'last' || visibleCols.has(key)} disabled={key === 'last'} onChange={() => toggleCol(key)} aria-label={label} /><span>{label}</span><TermInfo termId={key} lang={lang} label={label} /></label>
    </div>)}
    <p>{tt(lang, 'ATR и Beta — необязательные. Beta пока недоступна: нет проверенной истории индекса.', 'ATR va Beta ixtiyoriy. Beta hozircha mavjud emas: tasdiqlangan indeks tarixi yo‘q.', 'ATR and Beta are optional. Beta is unavailable without verified index history.')}</p>
  </div>;
}

export function TechnicalStatus({lang, status, asOf, retry}) {
  return <div className="technical-status" data-testid="technical-status" role={status === 'error' ? 'alert' : 'status'}>
    <span>{status === 'loading' ? tt(lang, 'Загрузка Technical…', 'Technical yuklanmoqda…', 'Loading Technical…')
      : status === 'error' ? tt(lang, 'Не удалось загрузить Technical.', 'Technical yuklanmadi.', 'Could not load Technical.')
      : `${tt(lang, 'Technical · рынок на', 'Technical · bozor sanasi', 'Technical · market as of')} ${asOf || '—'} · ${tt(lang, 'Даты отдельных бумаг — в подсказках. Нет данных — «—».', 'Alohida aksiya sanalari izohlarda. Ma’lumot yo‘q — «—».', 'Per-security dates are in tooltips. Missing data: “—”.')}`}</span>
    {status === 'error' && <button type="button" onClick={retry}>{tt(lang, 'Повторить Technical', 'Technical qayta urinish', 'Retry Technical')}</button>}
  </div>;
}
