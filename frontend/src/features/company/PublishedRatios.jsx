import React from 'react';
import { words } from '../../shared/TerminalTables.jsx';
import { finLabel } from '../../shared/financialLabels.jsx';
import { RatioInfo } from '../../shared/RatioInfo.jsx';
import { safeHref } from '../../lib/safeHref.js';
import { safeNumber } from '../../lib/numbers.js';

const FULL_NAMES = {
  roe: ['Рентабельность капитала (ROE)', 'Kapital rentabelligi (ROE)', 'Return on equity (ROE)'],
  roa: ['Рентабельность активов (ROA)', 'Aktivlar rentabelligi (ROA)', 'Return on assets (ROA)'],
  roce: ['Рентабельность задействованного капитала (ROCE)', 'Jalb qilingan kapital rentabelligi (ROCE)', 'Return on capital employed (ROCE)'],
  cost_of_risk: ['Стоимость риска', 'Risk qiymati', 'Cost of risk'],
};
const LABEL_ALIASES = { net_profit_margin: 'net_margin', asset_turnover: 'total_asset_turnover' };

function ratioName(field, lang) {
  if (FULL_NAMES[field]) return words(lang, ...FULL_NAMES[field]);
  const key = LABEL_ALIASES[field] || field;
  const name = finLabel(key, lang);
  return name === key ? words(lang, 'Другой показатель', 'Boshqa ko‘rsatkich', 'Other indicator') : name;
}

export function PublishedRatios({ ratios, lang, format, query, onClearSearch }) {
  const titleId = React.useId();
  const t = (...labels) => words(lang, ...labels);
  // OpenInfo has one observation per indicator and period. Keep the published
  // values and units; these are separate from UZStock's calculated ratios.
  const periods = [...new Set(ratios.map(row => String(row.period)))].sort().reverse();
  const fields = [...new Set(ratios.map(row => row.field))];
  const rows = fields.map(field => ({
    field, name: ratioName(field, lang),
    cells: new Map(ratios.filter(row => row.field === field).map(row => [String(row.period), row])),
  })).filter(row => `${row.name} ${row.field}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <section className="fc-published">
    <h3 id={titleId}>{t('Коэффициенты из отчётов компании', 'Kompaniya hisobotlaridagi koeffitsiyentlar', 'Ratios reported by the company')}</h3>
    <p className="fc-published-note">{t('Данные компании из OpenInfo. Нажмите на значение, чтобы открыть отчёт. Прочерк означает, что данных нет.', 'Kompaniyaning OpenInfo ma’lumotlari. Hisobotni ochish uchun qiymatni bosing. Chiziqcha — ma’lumot yo‘q.', 'Company figures from OpenInfo. Select a value to open the report. A dash means no data is available.')}</p>
    {rows.length ? <>
      <div className="fc-published-scroll" role="region" aria-labelledby={titleId} tabIndex={0}>
        <table className="fc-published-table" aria-labelledby={titleId} data-own-export>
          <thead><tr><th scope="col">{t('Показатель', 'Ko‘rsatkich', 'Metric')}</th>{periods.map(period => <th scope="col" key={period}>{period}</th>)}</tr></thead>
          <tbody>{rows.map(row => <tr key={row.field}>
            <th scope="row">{row.name}<RatioInfo metric={row.field} label={row.name} lang={lang}/></th>
            {periods.map(period => {
              const observation = row.cells.get(period), value = safeNumber(observation?.value);
              const unit = observation?.unit;
              const suffix = ['%', 'percent'].includes(unit) ? ' %' : ['ratio', 'times'].includes(unit) ? ' ×' : unit ? ` ${unit}` : '';
              const text = value == null ? '—' : `${format(value)}${suffix}`;
              const href = value == null ? undefined : safeHref(observation?.source_url);
              return <td key={period}>{href ? <a href={href} target="_blank" rel="noreferrer"
                aria-label={`${t('Открыть отчёт', 'Hisobotni ochish', 'Open report')}: ${row.name}, ${period} — ${text}`}>{text}</a> : text}</td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
      {periods.length > 1 && <p className="fc-published-hint">{t('Прокрутите таблицу вправо, чтобы увидеть предыдущие годы.', 'Oldingi yillarni ko‘rish uchun jadvalni o‘ngga suring.', 'Scroll right to see earlier years.')}</p>}
    </> : <div className="fc-empty" role="status"><p>{t('Показатели не найдены', 'Ko‘rsatkichlar topilmadi', 'No indicators found')}</p>
      <button type="button" onClick={onClearSearch}>{t('Сбросить поиск', 'Qidiruvni tozalash', 'Clear search')}</button>
    </div>}
  </section>;
}
