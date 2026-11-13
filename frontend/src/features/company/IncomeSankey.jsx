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

const LABEL_WIDTH = 208;
const TOTAL_LABEL_WIDTH = 168;
const LABEL_HEIGHT = 64;
const LABEL_GAP = 12;
const BRANCH_OFFSET = 42;

function layout({totals, bridges}) {
  const margin = TOTAL_LABEL_WIDTH / 2 + LABEL_GAP;
  const stepWidth = Math.max(280, (680 - 2 * margin) / bridges.length);
  const width = 2 * margin + stepWidth * bridges.length;
  const volume = Math.max(1, ...bridges.map((lines, i) =>
    Math.max(0, totals[i].value) - Math.min(0, totals[i + 1].value) +
    lines.reduce((sum, line) => sum + Math.max(0, line.value), 0)));
  const band = value => 114 * Math.abs(value) / volume;
  const branchHeight = line => Math.max(LABEL_HEIGHT, band(line.value)) + LABEL_GAP;
  const gainsHeight = Math.max(0, ...bridges.map(lines => lines
    .filter(line => line.value > 0).reduce((sum, line) => sum + branchHeight(line), 0)));
  const center = 152 + gainsHeight;
  const nodes = totals.map((line, i) => ({
    ...line, key: line.id, x: margin + i * stepWidth, y: center - band(line.value) / 2,
    h: band(line.value), labelX: margin + i * stepWidth - TOTAL_LABEL_WIDTH / 2,
    labelY: center - 64 - LABEL_HEIGHT, labelWidth: TOTAL_LABEL_WIDTH, align: 'center',
    color: colorOf(line, i === 0),
  }));
  const links = [];
  const addLink = (key, a, b, node) => {
    if (node.h > 0) links.push({key, node, path: ribbon(a.x + 5, a.y, b.x - 5, b.y, node.h)});
  };
  let bottom = center + 68;
  bridges.forEach((lines, i) => {
    const start = nodes[i], end = nodes[i + 1], junction = (start.x + end.x) / 2;
    const gains = lines.filter(line => line.value > 0);
    const expenses = lines.filter(line => line.value < 0);
    const inputs = band(Math.max(0, start.value)) + band(Math.min(0, end.value)) +
      gains.reduce((sum, line) => sum + band(line.value), 0);
    let inY = center - inputs / 2, outY = inY;
    addLink(`start-${i}`, start, {x: junction + 5, y: start.value >= 0 ? inY : outY}, start);
    if (start.value >= 0) inY += start.h;
    else outY += start.h;
    addLink(`end-${i}`, {x: junction - 5, y: end.value < 0 ? inY : outY}, end, end);
    if (end.value < 0) inY += end.h;
    else outY += end.h;

    // Route each branch on the side of its endpoint opposite the text.
    // Keeping the ribbons near the junction also clears the centered totals.
    let gainBottom = center - 64 - LABEL_HEIGHT;
    for (const line of gains) {
      const h = band(line.value), key = `${i}-${line.id}`;
      const height = branchHeight(line);
      const mid = gainBottom - (height + LABEL_GAP) / 2;
      const x = junction - BRANCH_OFFSET;
      const node = {...line, key, x, y: mid - h / 2, h, labelX: x - LABEL_GAP - LABEL_WIDTH,
        labelY: mid - LABEL_HEIGHT / 2, labelWidth: LABEL_WIDTH, align: 'right', color: colorOf(line)};
      nodes.push(node);
      addLink(key, node, {x: junction + 5, y: inY}, node);
      gainBottom -= height;
      inY += h;
    }
    let expenseTop = center + 104;
    for (const line of expenses) {
      const h = band(line.value), key = `${i}-${line.id}`;
      const height = branchHeight(line);
      const mid = expenseTop + (height - LABEL_GAP) / 2;
      const x = junction + BRANCH_OFFSET;
      const node = {...line, key, x, y: mid - h / 2, h, labelX: x + LABEL_GAP,
        labelY: mid - LABEL_HEIGHT / 2, labelWidth: LABEL_WIDTH, align: 'left', color: colorOf(line)};
      nodes.push(node);
      addLink(key, {x: junction - 5, y: outY}, node, node);
      expenseTop += height;
      outY += h;
      bottom = Math.max(bottom, expenseTop);
    }
  });
  const left = Math.min(0, ...nodes.map(node => node.labelX - LABEL_GAP));
  const right = Math.max(width, ...nodes.map(node => node.labelX + node.labelWidth + LABEL_GAP));
  return {nodes, links, left, width: right - left, height: bottom};
}

export function IncomeSankey({rows, details, columns, format, lang, t, showDifference = false}) {
  const heading = React.useId(), note = React.useId();
  const [selected, setSelected] = React.useState('');
  const [inspection, setInspection] = React.useState(null);
  const periods = React.useMemo(() => {
    const source = details?.length ? [...rows, ...details] : rows;
    return columns.filter(column => column.basis !== 'as_of').map(column => {
      const flow = incomeFlow(source, column.key);
      if (!flow) return {...column, graph: null};
      const bridges = showDifference ? flow.bridges : flow.bridges.map(lines =>
        lines.filter(line => line.id !== 'difference'));
      return {...column, graph: layout({...flow, bridges})};
    });
  }, [rows, details, columns, showDifference]);
  const graphs = periods.map(period => period.graph).filter(Boolean);
  const active = periods.find(period => period.key === selected) || periods.findLast(period => period.graph) || periods.at(-1);
  const graph = active?.graph;
  const inspected = inspection?.period === active?.key ? inspection?.node : null;
  const title = t('Выручка и расходы', 'Tushum va xarajatlar', 'Revenue & expenses breakdown');
  const showsDifference = chart => chart?.nodes.some(node => node.id === 'difference');
  const hasDifference = showsDifference(graph);
  const hasCharts = graphs.length > 0;
  const empty = <p role="status" className="fc-empty fc-sankey-empty">
    {t('Для схемы не хватает отчётных данных за этот период.', 'Bu davr uchun hisobot ma’lumotlari yetarli emas.', 'Not enough reported figures for this period.')}
  </p>;
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
  const revenue = graph?.nodes.find(node => node.id === 'revenue')?.value;
  const grossMarginApplicable = graph?.nodes.some(node => node.id === 'cost_of_sales') ||
    !graph?.nodes.some(node => ['operating_expenses', 'selling_expense', 'admin_expense', 'other_operating_expense'].includes(node.id));
  const marginLabel = inspected && ({
    gross_profit: t('Валовая маржа', 'Yalpi marja', 'Gross margin'),
    operating_income: t('Операционная маржа', 'Operatsion marja', 'Operating margin'),
    profit_before_tax: t('Маржа до налога', 'Soliqqacha marja', 'Pre-tax margin'),
    net_income: t('Чистая маржа', 'Sof marja', 'Net margin'),
  })[inspected.id];
  const inspect = (event, node, pointer = false) => {
    const bounds = event.currentTarget.closest('.fc-sankey-plot').getBoundingClientRect();
    const target = event.currentTarget.getBoundingClientRect();
    setInspection({node, period: active.key,
      x: (pointer ? event.clientX : target.left + target.width / 2) - bounds.left,
      y: (pointer ? event.clientY : target.top + target.height / 2) - bounds.top});
  };
  const clear = () => setInspection(null);
  const periodLabel = t('Отчётный период', 'Hisobot davri', 'Reporting period');
  return <section className="fc-income-sankey" aria-labelledby={heading}>
    <header className="fc-sankey-header">
      <div><h3 id={heading}>{title}</h3>{hasCharts && <span className={!graph ? 'fc-sankey-hidden' : undefined}>{unit}</span>}</div>
      {active && <div className="fc-sankey-periods">
        <span>{periodLabel}</span>
        <div className="fc-segment" role="group" aria-label={periodLabel}>
          {periods.map(period => <button key={period.key} type="button" aria-pressed={period.key === active.key}
            onClick={() => { clear(); setSelected(period.key); }}>{period.label}</button>)}
        </div>
      </div>}
    </header>
    {hasCharts ? <>
      <p className={`fc-sankey-scroll-hint${graph ? '' : ' fc-sankey-hidden'}`}>{t('Прокрутите схему вправо', 'Sxemani o‘ngga suring', 'Scroll right to see the full diagram')}</p>
      <div className="fc-sankey-plot" style={{
        '--sankey-aspect': Math.min(...graphs.map(chart => chart.width / chart.height)),
        '--sankey-min-height': `${Math.max(...graphs.map(chart => Math.min(chart.width, 940) * chart.height / chart.width))}px`,
      }}>
        {graph ? <div className="fc-sankey-scroll" role="region" tabIndex={0} onScroll={clear}
          onKeyDown={event => { if (event.key === 'Escape') clear(); }}
          aria-label={t('Схема доходов и расходов', 'Daromad va xarajatlar sxemasi', 'Income flow diagram')}>
          <svg role="img" aria-label={`${title} · ${active.label} · ${unit}`} aria-describedby={hasDifference ? note : undefined}
            viewBox={`${graph.left} 0 ${graph.width} ${graph.height}`} style={{'--sankey-width': `${graph.width}px`}}>
            {graph.links.map(({key, node, path}) => <path key={key} d={path}
              className={`fc-sankey-ribbon is-${node.color}${inspected?.key === node.key ? ' is-inspected' : ''}`}
              onPointerEnter={event => inspect(event, node, true)} onPointerLeave={clear}
              onClick={event => inspect(event, node, true)}/>)}
            {graph.nodes.map(node => <g key={node.key} tabIndex={0}
              aria-label={`${label(node)} · ${format(node.value)} ${exactUnit}`}
              className={`fc-sankey-node is-${node.color}`}
              onPointerEnter={event => inspect(event, node, true)} onPointerLeave={clear}
              onFocus={event => inspect(event, node)} onBlur={clear} onClick={event => inspect(event, node, true)}>
              <rect x={node.x - 5} y={node.y} width="10" height={Math.max(2, node.h)} rx="2"/>
              <foreignObject x={node.labelX} y={node.labelY} width={node.labelWidth} height={LABEL_HEIGHT}>
                <div className={`fc-sankey-label align-${node.align}`}>
                  <span>{label(node)}</span>
                  <span className="fc-sankey-amount">{compact.format(node.value / divisor)}</span>
                </div>
              </foreignObject>
            </g>)}
          </svg>
        </div> : empty}
        {inspected && <div className="fc-sankey-tooltip" role="tooltip"
          style={{'--tooltip-x': `${inspection.x}px`, '--tooltip-y': `${inspection.y}px`}}>
          <span>{active.label}</span>
          <strong>{label(inspected)}</strong>
          <strong>{format(inspected.value)} {exactUnit}</strong>
          {marginLabel && revenue > 0 && (inspected.id !== 'gross_profit' || grossMarginApplicable || inspected.value !== revenue)
            && <span>{marginLabel} · {compact.format(inspected.value / revenue * 100)}%</span>}
        </div>}
      </div>
      {graphs.some(showsDifference) && <p id={note} className={`fc-sankey-note${hasDifference ? '' : ' fc-sankey-hidden'}`}>
        {t('Несверенная разница — часть отчётного итога, которую не объясняют доступные строки.',
          'Solishtirilmagan tafovut — mavjud satrlar izohlamaydigan hisobot summasi.',
          'An unreconciled difference is the part of a reported total the available lines do not explain.')}
      </p>}
      <details className={`fc-sankey-amounts${graph ? '' : ' fc-sankey-hidden'}`}>
        <summary>{t('Точные значения', 'Aniq summalar', 'View exact amounts')} <small>· {exactUnit}</small></summary>
        {graph && <dl>{graph.nodes.map(node => <div key={node.key}><dt>{label(node)}</dt><dd>{format(node.value)}</dd></div>)}</dl>}
      </details>
    </> : empty}
  </section>;
}
