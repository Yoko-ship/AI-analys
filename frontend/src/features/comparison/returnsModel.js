import {MAX_COMPANIES} from './model.js';

const MONTH = /^20\d{2}-(0[1-9]|1[0-2])$/;
export const RETURN_LIMIT = MAX_COMPANIES;

export function readReturns(search) {
  const p = new URLSearchParams(search);
  return {
    tickers: [...new Set((p.get('companies') ?? 'HMKB,IPKY,SQBN').split(',').map(t => t.trim().toUpperCase()).filter(t => /^[A-Z0-9]{2,16}$/.test(t)))].slice(0, RETURN_LIMIT),
    from: MONTH.test(p.get('from')) ? p.get('from') : '',
    to: MONTH.test(p.get('to')) ? p.get('to') : '',
    frequency: p.get('frequency') === 'annual' ? 'annual' : 'monthly',
    layout: p.get('layout') === 'relative' ? 'relative' : 'heatmap',
  };
}

export function returnsQuery(state) {
  return '?' + new URLSearchParams({view:'returns',companies:state.tickers.join(','),from:state.from,to:state.to,frequency:state.frequency,layout:state.layout});
}

export function shiftMonth(month, delta) {
  const date = new Date(`${month}-01T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + delta);
  return date.toISOString().slice(0,7);
}

export function normalizeHistory(points, asOf = '2099-12-31') {
  const dates = new Map();
  for (const p of Array.isArray(points) ? points : []) {
    let date = String(p.date || '');
    if (/^\d{8}$/.test(date)) date = `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`;
    if (!/^20\d{2}-\d{2}-\d{2}$/.test(date) || date > asOf) continue;
    const parsed = new Date(date + 'T00:00:00Z');
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0,10) !== date) continue;
    if (!p.ambiguous && (typeof p.close !== 'number' || !Number.isFinite(p.close) || p.close <= 0)) continue;
    // Preserve an unknown price at the disputed date: dropping it would let an
    // older quote silently become the baseline or endpoint. Repeated identical
    // quotes are harmless; conflicts remain unknown regardless of input order.
    const ambiguous=p.ambiguous || (dates.has(date) && dates.get(date).close !== p.close);
    dates.set(date, ambiguous ? {date,close:null,ambiguous:true} : {date,close:p.close});
  }
  return [...dates.values()].sort((a,b) => a.date.localeCompare(b.date));
}

// Prices already include recorded split/bonus adjustments in the history API.
// A missing month has no return. A later trade may use an older close, but its
// actual baseline date and stale flag travel with the value all the way to UI.
function calculate(points, from, to, asOf) {
  const start = from + '-01';
  const endExclusive = shiftMonth(to,1) + '-01';
  const base = points.findLast(p => p.date < start) || null;
  const end = points.findLast(p => p.date >= start && p.date < endExclusive && p.date <= asOf) || null;
  const status = start > asOf ? 'future' : !end ? 'no_trades' : base?.ambiguous || end.ambiguous ? 'ambiguous' : !base ? 'no_base' : 'available';
  const value = status === 'available' ? (end.close/base.close - 1)*100 : null;
  return {value:Number.isFinite(value) ? value : null,status,base,end,
    stale:Boolean(base && base.date.slice(0,7) < shiftMonth(from,-1)),
    staleEnd:Boolean(end && end.date.slice(0,7) < (to < asOf.slice(0,7) ? to : asOf.slice(0,7))),
    partial:asOf < endExclusive && asOf >= start,from,to};
}

export function periodReturn(points, from, to, asOf) {
  return calculate(normalizeHistory(points,asOf),from,to,asOf);
}

export function buildReturns(points, from, to, asOf) {
  const history = normalizeHistory(points,asOf);
  const months = {}, years = {};
  if (!MONTH.test(from) || !MONTH.test(to) || from > to) return {months,years,total:null};
  for (let month = from, count = 0; month <= to && count < 240; month = shiftMonth(month,1), count++) {
    months[month] = calculate(history,month,month,asOf);
  }
  for (const year of [...new Set(Object.keys(months).map(m => m.slice(0,4)))]) {
    const start = from > year+'-01' ? from : year+'-01';
    const end = to < year+'-12' ? to : year+'-12';
    years[year] = calculate(history,start,end,asOf);
    years[year].partial ||= start !== year+'-01' || end !== year+'-12';
  }
  const total = calculate(history,from,to,asOf);
  // The selected interval and a one-year row have identical semantics.
  if (from.slice(0,4) === to.slice(0,4)) total.partial = years[from.slice(0,4)]?.partial || total.partial;
  return {months,years,total};
}

export function rankReturns(rows) {
  return [...rows].sort((a,b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
}
