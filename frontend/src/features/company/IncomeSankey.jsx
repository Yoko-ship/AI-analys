import React from 'react';
import { incomeFlow } from './incomeFlow.js';
import './incomeSankey.css';

const TOTAL_LABELS = {
  revenue: ['Выручка', 'Tushum', 'Revenue'],
  gross_profit: ['Валовая прибыль', 'Yalpi foyda', 'Gross profit'],
  operating_income: ['Операционная прибыль', 'Operatsion foyda', 'Operating profit'],
  profit_before_tax: ['Прибыль до налога', 'Soliqdan oldingi foyda', 'Profit before tax'],
  net_income: ['Чистая прибыль', 'Sof foyda', 'Net income'],
  interest_income: ['Процентные доходы', 'Foiz daromadlari', 'Interest income'],
  net_interest_before_ecl: ['Чистый процентный доход', 'Sof foiz daromadi', 'Net interest income'],
  net_interest_after_ecl: ['Доход после кредитных потерь', 'Kredit zararlaridan keyingi daromad', 'After credit losses'],
  income_before_opex: ['До операционных расходов', 'Operatsion xarajatlargacha', 'Before operating expenses'],
  net_insurance_revenue: ['Чистая страховая выручка', 'Sof sug‘urta tushumi', 'Net insurance revenue'],
  insurance_revenue: ['Страховая выручка', 'Sug‘urta tushumi', 'Insurance revenue'],
  insurance_service_result: ['Результат страховых услуг', 'Sug‘urta xizmatlari natijasi', 'Insurance service result'],
  investment_income: ['Инвестиционный доход', 'Investitsiya daromadi', 'Investment income'],
};

const LOSS_LABELS = {
  net_income: ['Чистый убыток', 'Sof zarar', 'Net loss'],
  gross_profit: ['Валовый убыток', 'Yalpi zarar', 'Gross loss'],
  operating_income: ['Операционный убыток', 'Operatsion zarar', 'Operating loss'],
  profit_before_tax: ['Убыток до налога', 'Soliqdan oldingi zarar', 'Loss before tax'],
};

const LINE_LABELS = {
  cost_of_sales: ['Себестоимость продаж', 'Sotish tannarxi', 'Cost of sales'],
  selling_expense: ['Расходы на сбыт', 'Sotish xarajatlari', 'Selling expenses'],
  admin_expense: ['Административные расходы', 'Ma’muriy xarajatlar', 'Administrative expenses'],
  other_operating_expense: ['Прочие операционные расходы', 'Boshqa operatsion xarajatlar', 'Other operating expenses'],
  operating_expenses: ['Операционные расходы', 'Operatsion xarajatlar', 'Operating expenses'],
  other_operating_income: ['Прочие операционные доходы', 'Boshqa operatsion daromadlar', 'Other operating income'],
  finance_income: ['Финансовые доходы', 'Moliyaviy daromadlar', 'Finance income'],
  finance_cost: ['Финансовые расходы', 'Moliyaviy xarajatlar', 'Finance costs'],
  fx_expense: ['Расходы от курсовых разниц', 'Kurs tafovutlari xarajatlari', 'Foreign exchange expenses'],
  lease_expense: ['Расходы по аренде', 'Ijara xarajatlari', 'Lease expenses'],
  other_finance_cost: ['Прочие финансовые расходы', 'Boshqa moliyaviy xarajatlar', 'Other finance costs'],
  interest_expense: ['Процентные расходы', 'Foiz xarajatlari', 'Interest expenses'],
  income_tax: ['Налог на прибыль', 'Foyda solig‘i', 'Income tax'],
  credit_loss_expense: ['Кредитные потери', 'Kredit zararlari', 'Credit losses'],
  noninterest_income: ['Непроцентные доходы', 'Foizsiz daromadlar', 'Non-interest income'],
  noninterest_expense: ['Непроцентные расходы', 'Foizsiz xarajatlar', 'Non-interest expenses'],
  insurance_cost: ['Расходы на страхование', 'Sug‘urta xarajatlari', 'Insurance costs'],
  insurance_service_expense: ['Расходы по страховым услугам', 'Sug‘urta xizmatlari xarajatlari', 'Insurance service expenses'],
  insurance_finance_expense: ['Финансовые расходы по страхованию', 'Sug‘urta moliyaviy xarajatlari', 'Insurance finance expenses'],
  reinsurance_result: ['Результат перестрахования', 'Qayta sug‘urtalash natijasi', 'Reinsurance result'],
  fee_income: ['Комиссионные доходы', 'Komissiya daromadlari', 'Fee income'],
  fee_expense: ['Комиссионные расходы', 'Komissiya xarajatlari', 'Fee expenses'],
  net_fee_income: ['Чистые комиссионные доходы', 'Sof komissiya daromadi', 'Net fee income'],
  fx_income: ['Доходы от валютных операций', 'Valyuta operatsiyalari daromadi', 'Foreign exchange income'],
  fx_gain_loss: ['Курсовые разницы', 'Kurs tafovutlari', 'Foreign exchange result'],
  extraordinary_profit: ['Чрезвычайные доходы и расходы', 'Favqulodda daromad va xarajatlar', 'Extraordinary result'],
  share_of_profit_associates: ['Доля в прибыли ассоциированных компаний', 'Assotsiatsiyalangan korxonalar foydasidagi ulush', 'Share of associates’ profit'],
  other_profit_payments: ['Прочие платежи из прибыли', 'Foydadan boshqa to‘lovlar', 'Other profit payments'],
  profit_adjustment: ['Корректировка прибыли', 'Foyda tuzatmasi', 'Profit adjustment'],
  tax_adjustment: ['Корректировка налога', 'Soliq tuzatmasi', 'Tax adjustment'],
  noncredit_impairment: ['Прочее обесценение', 'Boshqa qadrsizlanish', 'Other impairment'],
  trading_income: ['Доход от торговых операций', 'Savdo operatsiyalari daromadi', 'Trading income'],
  fair_value_gain_loss: ['Переоценка', 'Qayta baholash', 'Fair value changes'],
  fund_expenses: ['Расходы фонда', 'Fond xarajatlari', 'Fund expenses'],
  difference: ['Несверенная разница', 'Solishtirilmagan tafovut', 'Unreconciled difference'],
};

const colorOf = (line, opening) => line.id === 'difference' ? 'difference' :
  line.value < 0 ? 'expense' : opening ? 'revenue' : 'profit';

function ribbon(x1, y1, x2, y2, height) {
  const middle = (x1 + x2) / 2;
  return `M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}
    v${height} C${middle},${y2 + height} ${middle},${y1 + height} ${x1},${y1 + height} Z`;
}

function layout({totals, bridges}) {
  const step = 236;
  const left = 32;
  const lastX = left + step * (totals.length - 1);
  const width = Math.max(680, lastX + 48);
  const stepWidth = (width - left - 48) / bridges.length;
  const volume = Math.max(1, ...bridges.map((lines, i) =>
    Math.max(0, totals[i].value) - Math.min(0, totals[i + 1].value) +
    lines.reduce((sum, line) => sum + Math.max(0, line.value), 0)));
  const band = value => 114 * Math.abs(value) / volume;
  const heightWithLabel = line => Math.max(42, band(line.value) + 34);
  const gainsHeight = Math.max(0, ...bridges.map(lines => lines
    .filter(line => line.value > 0).reduce((sum, line) => sum + heightWithLabel(line), 0)));
  const center = 122 + gainsHeight;
  const nodes = totals.map((line, i) => ({
    ...line, key: line.id, x: left + i * stepWidth, y: center - band(line.value) / 2,
    h: band(line.value), labelY: center - 78, align: i === totals.length - 1 ? 'end' : 'start',
    color: colorOf(line, i === 0),
  }));
  const links = [];
  const addLink = (key, a, b, h, color) => {
    if (h > 0) links.push({key, color, path: ribbon(a.x + 5, a.y, b.x - 5, b.y, h)});
  };
  let bottom = center + 68;
  bridges.forEach((lines, i) => {
    const start = nodes[i], end = nodes[i + 1], junction = (start.x + end.x) / 2;
    const gains = lines.filter(line => line.value > 0);
    const expenses = lines.filter(line => line.value < 0);
    const inputs = band(Math.max(0, start.value)) + band(Math.min(0, end.value)) +
      gains.reduce((sum, line) => sum + band(line.value), 0);
    let inY = center - inputs / 2, outY = inY;
    addLink(`start-${i}`, start, {x: junction + 5, y: start.value >= 0 ? inY : outY}, start.h, start.color);
    if (start.value >= 0) inY += start.h;
    else outY += start.h;
    addLink(`end-${i}`, {x: junction - 5, y: end.value < 0 ? inY : outY}, end, end.h, end.color);
    if (end.value < 0) inY += end.h;
    else outY += end.h;

    let gainY = center - 91;
    for (const line of gains) {
      const h = band(line.value), key = `${i}-${line.id}`;
      const node = {...line, key, x: start.x + 18, y: gainY - h, h, labelY: gainY - h - 21, align: 'start', color: colorOf(line)};
      nodes.push(node);
      addLink(key, node, {x: junction + 5, y: inY}, h, node.color);
      gainY -= heightWithLabel(line);
      inY += h;
    }
    let expenseY = center + 108;
    for (const line of expenses) {
      const h = band(line.value), key = `${i}-${line.id}`;
      const node = {...line, key, x: end.x - 18, y: expenseY, h, labelY: expenseY - 21, align: 'end', color: colorOf(line)};
      nodes.push(node);
      addLink(key, {x: junction - 5, y: outY}, node, h, node.color);
      expenseY += heightWithLabel(line);
      outY += h;
      bottom = Math.max(bottom, node.y + h + 12);
    }
  });
  return {nodes, links, width, height: bottom};
}

export function IncomeSankey({rows, details, columns, format, lang, t}) {
  const heading = React.useId(), note = React.useId();
  const [selected, setSelected] = React.useState('');
  const periods = React.useMemo(() => {
    const source = details?.length ? [...rows, ...details] : rows;
    return columns.filter(column => column.basis !== 'as_of').map(column =>
      ({...column, flow: incomeFlow(source, column.key)}));
  }, [rows, details, columns]);
  const active = periods.find(period => period.key === selected) || periods.findLast(period => period.flow) || periods.at(-1);
  const graph = active?.flow && layout(active.flow);
  const title = t('Выручка и расходы', 'Tushum va xarajatlar', 'Revenue & expenses breakdown');
  const hasDifference = graph?.nodes.some(node => node.id === 'difference');
  const exactUnit = t('тыс. UZS', 'ming UZS', 'thousand UZS');
  const label = node => {
    const labels = (node.value < 0 && LOSS_LABELS[node.id]) || TOTAL_LABELS[node.id] || LINE_LABELS[node.id];
    return labels ? t(...labels) : node.label;
  };
  const maximum = graph ? Math.max(...graph.nodes.map(node => Math.abs(node.value))) : 0;
  const [divisor, unit] = maximum >= 1e6 ? [1e6, t('млрд UZS', 'mlrd UZS', 'billion UZS')] :
    maximum >= 1e3 ? [1e3, t('млн UZS', 'mln UZS', 'million UZS')] : [1, exactUnit];
  const compact = new Intl.NumberFormat({ru: 'ru-RU', uz: 'uz-UZ', en: 'en-US'}[lang] || 'ru-RU',
    {minimumFractionDigits: 2, maximumFractionDigits: 2});
  return <section className="fc-income-sankey" aria-labelledby={heading}>
    <header className="fc-sankey-header">
      <div><h3 id={heading}>{title}</h3>{graph && <span>{unit}</span>}</div>
      {active && <label>
        {t('Отчётный период', 'Hisobot davri', 'Reporting period')}
        <select value={active.key} onChange={event => setSelected(event.target.value)}>
          {[...periods].reverse().map(period => <option key={period.key} value={period.key}>{period.label}</option>)}
        </select>
      </label>}
    </header>
    {graph ? <>
      <p className="fc-sankey-scroll-hint">{t('Прокрутите схему вправо', 'Sxemani o‘ngga suring', 'Scroll right to see the full diagram')}</p>
      <div className="fc-sankey-scroll" role="region" tabIndex={0}
        aria-label={t('Схема доходов и расходов', 'Daromad va xarajatlar sxemasi', 'Income flow diagram')}>
        <svg role="img" aria-label={`${title} · ${active.label} · ${unit}`} aria-describedby={hasDifference ? note : undefined}
          viewBox={`0 0 ${graph.width} ${graph.height}`} style={{'--sankey-width': `${graph.width}px`}}>
          {graph.links.map(link => <path key={link.key} d={link.path} className={`fc-sankey-ribbon is-${link.color}`}/>)}
          {graph.nodes.map(node => <g key={node.key} className={`fc-sankey-node is-${node.color}`}>
            <title>{label(node)} · {format(node.value)} {exactUnit}</title>
            <rect x={node.x - 5} y={node.y} width="10" height={Math.max(2, node.h)} rx="2"/>
            <text x={node.x} y={node.labelY} textAnchor={node.align}>
              <tspan>{label(node)}</tspan>
              <tspan className="fc-sankey-amount" x={node.x} dy="16">{compact.format(node.value / divisor)}</tspan>
            </text>
          </g>)}
        </svg>
      </div>
      {hasDifference && <p id={note} className="fc-sankey-note">
        {t('Несверенная разница — часть отчётного итога, которую не объясняют доступные строки.',
          'Solishtirilmagan tafovut — mavjud satrlar izohlamaydigan hisobot summasi.',
          'An unreconciled difference is the part of a reported total the available lines do not explain.')}
      </p>}
      <details className="fc-sankey-amounts">
        <summary>{t('Точные значения', 'Aniq summalar', 'View exact amounts')} <small>· {exactUnit}</small></summary>
        <dl>{graph.nodes.map(node => <div key={node.key}><dt>{label(node)}</dt><dd>{format(node.value)}</dd></div>)}</dl>
      </details>
    </> : <p role="status" className="fc-empty">
      {t('Для схемы не хватает отчётных данных за этот период.', 'Bu davr uchun hisobot ma’lumotlari yetarli emas.', 'Not enough reported figures for this period.')}
    </p>}
  </section>;
}
