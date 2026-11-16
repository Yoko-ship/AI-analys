import React from 'react';
import {balanceComposition} from './financialBalanceChart.js';
import {StatementChartRows} from './StatementChartRows.jsx';

const COLORS = [
  'var(--chart-primary)', 'var(--muted)',
  'color-mix(in srgb, var(--chart-primary) 68%, var(--panel))',
  'color-mix(in srgb, var(--chart-primary) 60%, var(--text))',
  'color-mix(in srgb, var(--muted) 60%, var(--panel))',
  'color-mix(in srgb, var(--chart-primary) 38%, var(--text))',
  'color-mix(in srgb, var(--chart-primary) 38%, var(--panel))',
  'color-mix(in srgb, var(--muted) 80%, var(--text))',
];
const LABELS = {
  total_liabilities: ['Обязательства', 'Majburiyatlar', 'Liabilities'],
  total_equity: ['Капитал', 'Kapital', 'Equity'],
  share_capital: ['Уставный капитал', 'Ustav kapitali', 'Share capital'],
  share_premium: ['Добавленный капитал', 'Qo‘shilgan kapital', 'Additional capital'],
  reserve_capital: ['Резервный капитал', 'Rezerv kapitali', 'Reserve capital'],
  treasury_shares: ['Выкупленные собственные акции', 'Sotib olingan o‘z aksiyalari', 'Treasury shares'],
  retained_earnings: ['Нераспределенная прибыль (непокрытый убыток)', 'Taqsimlanmagan foyda (qoplanmagan zarar)', 'Retained earnings (uncovered loss)'],
  target_receipts: ['Целевые поступления', 'Maqsadli tushumlar', 'Target receipts'],
  future_expense_reserves: ['Резервы предстоящих расходов и платежей', 'Kelgusi xarajatlar va to‘lovlar rezervlari', 'Reserves for future expenses and payments'],
  unclassified_assets: ['Нераспределённый остаток (состав не подтверждён)', 'Taqsimlanmagan qoldiq (tarkibi tasdiqlanmagan)', 'Unclassified remainder (breakdown unverified)'],
};
const REASONS = {
  missing: ['Недостаточно проверенных данных для Pie chart.', 'Pie chart uchun tekshirilgan ma’lumot yetarli emas.', 'Not enough verified data for a pie chart.'],
  negative: ['В балансе есть отрицательные значения. Pie chart недоступен.', 'Balansda manfiy qiymatlar bor. Pie chart mavjud emas.', 'The balance contains negative values. A pie chart is unavailable.'],
  units: ['Единицы измерения не совпадают.', 'O‘lchov birliklari mos kelmaydi.', 'The measurement units do not match.'],
  zero: ['Итог равен нулю. Доли не определены.', 'Jami nolga teng. Ulushlar aniqlanmagan.', 'The total is zero. Shares are undefined.'],
  inconsistent: ['Составляющие превышают итог баланса.', 'Tarkibiy qismlar balans jamidan oshib ketgan.', 'Components exceed the balance total.'],
  unreconciled: ['Обязательства и капитал не сходятся с итогом активов.', 'Majburiyatlar va kapital aktivlar jamiga mos kelmaydi.', 'Liabilities and equity do not reconcile to total assets.'],
  equity_unreconciled: ['Составляющие капитала не сходятся с итогом раздела.', 'Kapital tarkibi bo‘lim jamiga mos kelmaydi.', 'Equity components do not reconcile to the section total.'],
  deductions: ['Выкупленные акции уменьшают капитал. Pie chart недоступен.', 'Sotib olingan aksiyalar kapitalni kamaytiradi. Pie chart mavjud emas.', 'Treasury shares reduce equity. A pie chart is unavailable.'],
  asset_sections: ['Разделы активов не сходятся с итогом активов.', 'Aktivlar bo‘limlari aktivlar jamiga mos kelmaydi.', 'The asset sections do not reconcile to total assets.'],
  source: ['Не удалось подтвердить единый источник для этих значений.', 'Bu qiymatlar uchun umumiy manba tasdiqlanmadi.', 'A common reporting source could not be verified for these values.'],
  overflow: ['Значения слишком велики для расчёта долей.', 'Qiymatlar ulushlarni hisoblash uchun juda katta.', 'The amounts are too large to calculate shares.'],
};
const unitLabel = (unit, t) => unit === 'UZS_thousand' ? t('тыс. UZS', 'ming UZS', 'thousands UZS') : unit;

function piePath(start, share) {
  const point = angle => `${140 + 112 * Math.cos(angle)},${140 + 112 * Math.sin(angle)}`;
  const middle = start + Math.PI * share;
  const end = start + 2 * Math.PI * share;
  return `M140,140 L${point(start)} A112,112 0 0,1 ${point(middle)} A112,112 0 0,1 ${point(end)} Z`;
}

function PiePanel({id, title, data, period, format, t}) {
  const [selection, setSelection] = React.useState(null);
  const inspected = selection?.period === period.key ? selection.metric : null;
  const setInspected = metric => setSelection({period: period.key, metric});
  const label = row => LABELS[row.metric_id] ? t(...LABELS[row.metric_id]) : row.label;
  const amount = row => row.value == null || !row.unit ? format(row.value) : `${format(row.value)} ${unitLabel(row.unit, t)}`;
  const describe = row => `${label(row)} · ${period.label} · ${amount(row)} · ${format(row.value / data.total * 100)}%`;
  const active = data.rows.find(row => row.metric_id === inspected);
  let angle = -Math.PI / 2;
  return <div className="fc-chart-plot fc-balance-pie" data-balance-chart={id}>
    <h3 className="fc-balance-title">{title}</h3>
    <p className="fc-balance-total">{data.total == null ? '—' : <>{format(data.total)} <small>{unitLabel(data.unit, t)}</small></>}</p>
    {data.reason ? <p className="fc-balance-unavailable" role="status">{t(...REASONS[data.reason])}</p> : <>
      <svg viewBox="0 0 280 280" role="img" aria-label={`${title} · ${period.label} · Pie chart`}>
        {data.rows.map((row, index) => {
          if (!row.value) return null;
          const share = row.value / data.total;
          const path = piePath(angle, share);
          angle += share * Math.PI * 2;
          return <path key={row.metric_id} d={path} fill={COLORS[index % COLORS.length]}
            data-pie-slice={row.metric_id} tabIndex={0} aria-label={describe(row)}
            className={inspected === row.metric_id ? 'is-inspected' : ''}
            onPointerEnter={() => setInspected(row.metric_id)} onFocus={() => setInspected(row.metric_id)}
            onClick={() => setInspected(row.metric_id)}><title>{describe(row)}</title></path>;
        })}
      </svg>
      <p className="fc-balance-reading" role="status">{active ? describe(active) : `${period.label} · ${format(data.total)} ${unitLabel(data.unit, t)}`}</p>
    </>}
    <details className="fc-balance-details">
      <summary aria-label={`${t('Подробнее', 'Batafsil', 'Details')} · ${title}`}>{t('Подробнее', 'Batafsil', 'Details')}</summary>
      <ul className="fc-balance-legend">{data.rows.map((row, index) => <li key={row.metric_id}
        data-balance-value={row.metric_id} style={{'--series-color': COLORS[index % COLORS.length]}}>
        <button type="button" aria-pressed={inspected === row.metric_id} onClick={() => setInspected(row.metric_id)}
          onFocus={() => setInspected(row.metric_id)} disabled={Boolean(data.reason) || row.value === 0}>
          <span>{label(row)}</span><strong>{amount(row)}{!data.reason && <small>{format(row.value / data.total * 100)}%</small>}</strong>
        </button>
      </li>)}</ul>
    </details>
  </div>;
}

export function BalancePieCharts({rows, columns, reportContext, statementContext, renderStatementValue, format, t}) {
  const [selected, setSelected] = React.useState(null);
  const periods = columns.filter(column => column.basis !== 'ttm');
  const period = periods.find(column => column.key === selected) || periods.at(-1);
  if (!period) return <p className="fc-empty" role="status">{t(...REASONS.missing)}</p>;
  const {assets, funding, equity} = balanceComposition(rows, period.key, period.end, reportContext ?? undefined);
  return <section className="fc-balance-pies fc-chart-visuals" aria-label={t('Структура баланса', 'Balans tarkibi', 'Balance composition')}>
    <div className="fc-balance-periods" role="group" aria-label={t('Отчётный период', 'Hisobot davri', 'Reporting period')}>
      {periods.map(column => <button key={column.key} type="button" aria-pressed={column.key === period.key}
        onClick={() => setSelected(column.key)}>{column.label}</button>)}
    </div>
    <div className="fc-balance-panels">
      <PiePanel id="assets" title={t('Активы', 'Aktivlar', 'Assets')} data={assets} period={period} format={format} t={t}/>
      <PiePanel id="funding" title={t('Обязательства и капитал', 'Majburiyatlar va kapital', 'Liabilities and equity')} data={funding} period={period} format={format} t={t}/>
      <PiePanel id="equity" title={t('Источники собственных средств', 'O‘z mablag‘lari manbalari', 'Sources of equity')} data={equity} period={period} format={format} t={t}/>
    </div>
    <details className="fc-balance-details fc-balance-statement-details">
      <summary>{t('Подробнее · Все строки отчёта', 'Batafsil · Hisobotning barcha qatorlari', 'Details · All statement rows')}</summary>
      <StatementChartRows rows={rows} period={period} kind="stock" context={statementContext}
        renderValue={renderStatementValue} t={t}/>
    </details>
  </section>;
}
