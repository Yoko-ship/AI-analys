import { num } from '../../lib/format.js';
import { comparisonText, translatedLabel } from './copy.js';

export const MAX_COMPANIES = 4;
export const SAVED_KEY = 'uzstock_comparisons_v1'; // Public localStorage name. gitleaks:allow
const DEFAULT_TICKERS = ['HMKB', 'IPKY', 'SQBN'];

export const METRICS = [
  { key: 'interest_income', group: 'income', type: 'amount', family: 'bank', label: ['Процентные доходы', 'Foizli daromadlar', 'Interest income'] },
  { key: 'revenue', group: 'income', type: 'amount', family: 'corporate', label: ['Выручка', 'Tushum', 'Revenue'] },
  { key: 'net_profit', group: 'income', type: 'amount', label: ['Чистая прибыль', 'Sof foyda', 'Net profit'], change: 'net_profit_yoy' },
  { key: 'assets', group: 'balance', type: 'amount', label: ['Активы', 'Aktivlar', 'Total assets'] },
  { key: 'equity', group: 'balance', type: 'amount', label: ['Собственный капитал', 'O‘z kapitali', 'Total equity'] },
  { key: 'loan_book', group: 'balance', type: 'amount', family: 'bank', label: ['Кредитный портфель', 'Kredit portfeli', 'Loan portfolio'] },
  { key: 'customer_funds', group: 'balance', type: 'amount', family: 'bank', label: ['Средства клиентов', 'Mijozlar mablag‘lari', 'Customer funds'] },
  { key: 'roe', group: 'ratios', type: 'percent', label: ['Рентабельность капитала · ROE', 'Kapital rentabelligi · ROE', 'Return on equity · ROE'] },
  { key: 'roa', group: 'ratios', type: 'percent', label: ['Рентабельность активов · ROA', 'Aktivlar rentabelligi · ROA', 'Return on assets · ROA'] },
  { key: 'cost_income', group: 'ratios', type: 'percent', family: 'bank', label: ['Расходы / доходы · CIR', 'Xarajatlar / daromadlar · CIR', 'Cost / income · CIR'] },
  { key: 'pe', group: 'ratios', type: 'multiple', label: ['Цена / прибыль · P/E', 'Narx / foyda · P/E', 'Price / earnings · P/E'] },
  { key: 'pb', group: 'ratios', type: 'multiple', label: ['Цена / капитал · P/B', 'Narx / kapital · P/B', 'Price / book · P/B'] },
  { key: 'price', group: 'market', type: 'price', label: ['Цена акции', 'Aksiya narxi', 'Share price'] },
  { key: 'market_cap', group: 'market', type: 'amount', label: ['Капитализация', 'Kapitallashuv', 'Market capitalization'] },
  { key: 'turnover', group: 'market', type: 'amount', label: ['Оборот за сессию', 'Sessiya aylanmasi', 'Session turnover'] },
];

export function readComparison(search = '') {
  const params = new URLSearchParams(search);
  const tickers = params.has('companies') ? params.get('companies').split(',') : DEFAULT_TICKERS;
  const period = params.get('period') || '';
  return {
    tickers: [...new Set(tickers.map(t => t.trim().toUpperCase()).filter(t => /^[A-Z0-9]{2,16}$/.test(t)))].slice(0, MAX_COMPANIES),
    period: /^20\d{2}(Q[1-4])?$/.test(period) ? period : 'latest',
    standard: params.get('standard') === 'IFRS' ? 'IFRS' : 'NSBU',
    scope: params.get('scope') === 'consolidated' ? 'consolidated' : 'separate',
    unit: params.get('unit') === 'million' ? 'million' : 'billion',
  };
}

export function comparisonQuery(state) {
  return '?' + new URLSearchParams({companies:state.tickers.join(','),period:state.period,standard:state.standard,scope:state.scope,unit:state.unit}).toString();
}

export function apiQuery(state) {
  return '?' + new URLSearchParams({tickers:state.tickers.join(','),period:state.period,standard:state.standard,scope:state.scope}).toString();
}

export function periodLabel(period, language) {
  if (!period || period === 'latest') return comparisonText(language, 'latest');
  const year = period.slice(0,4);
  if (!period.includes('Q')) return year + (language==='en' ? ' · FY' : language==='uz' ? ' · yillik' : ' · годовой');
  const months = Number(period.slice(-1))*3;
  return language==='en' ? months + 'M ' + year : language==='uz' ? year + ', ' + months + ' oy' : months + ' месяцев ' + year;
}

export function comparisonMatches(data, state) {
  return Boolean(data?.ok && data.standard===state.standard && data.scope===state.scope
    && (state.period==='latest' || data.period===state.period)
    && Array.isArray(data.companies) && data.companies.map(c=>c.ticker).join(',')===state.tickers.join(','));
}

export function comparisonValue(ticker,key,state,data) {
  if (!comparisonMatches(data,state)) return {value:null,status:'unavailable',change:null};
  const cell=data.companies.find(c=>c.ticker===ticker)?.metrics?.[key];
  return { ...cell, value:Number.isFinite(cell?.value)?cell.value:null, status:cell?.status||'unavailable', change:Number.isFinite(cell?.change)?cell.change:null };
}

export function formatComparisonValue(value,metric,state,language) {
  if (!Number.isFinite(value)) return '—';
  const display=metric.type==='amount'?value/(state.unit==='million'?1e6:1e9):value;
  return num(display,language,metric.type==='amount'?3:2)+(metric.type==='percent'?'%':metric.type==='multiple'?'×':'');
}

export function comparisonCsv(state,language,data) {
  if (!comparisonMatches(data,state)) return '';
  const rows=[
    [comparisonText(language,'reported')],
    [comparisonText(language,'period'),data.period||''],
    [comparisonText(language,'standard'),data.standard],
    [comparisonText(language,'scope'),comparisonText(language,data.scope)],
    [comparisonText(language,'unit'),comparisonText(language,state.unit)],
    [comparisonText(language,'tableNote')],[],
    [comparisonText(language,'metric'),...state.tickers],
    ...METRICS.map(metric=>[translatedLabel(metric.label,language),...state.tickers.map(ticker=>{
      const {value}=comparisonValue(ticker,metric.key,state,data);
      return value===null?'':formatComparisonValue(value,metric,state,language);
    })]),[],['Ticker','Metric','Status','Source','Period','Market date','Valuation basis'],
    ...data.companies.flatMap(c=>Object.entries(c.metrics||{}).map(([key,cell])=>[
      c.ticker,key,cell.status||'',cell.source?.url||'',cell.period||'',cell.as_of||c.market_as_of||'',cell.base_period||'',
    ])),
  ];
  return '\uFEFF'+rows.map(row=>row.map(value=>{
    const text=String(value);return /[",\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;
  }).join(',')).join('\r\n');
}

export function readSavedComparisons() {
  try {
    const raw=JSON.parse(localStorage.getItem(SAVED_KEY)||'[]');
    return Array.isArray(raw)?raw.filter(item=>typeof item?.id==='string'&&typeof item.name==='string'&&typeof item.query==='string')
      .slice(0,10).map(item=>({id:item.id,name:item.name.slice(0,80),query:comparisonQuery(readComparison(item.query))})):[];
  }catch{return [];}
}
