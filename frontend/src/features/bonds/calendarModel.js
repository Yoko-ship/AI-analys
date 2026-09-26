const isoDay = (date) => date.toISOString().slice(0, 10);

export function calendarBounds(data) {
  const from = data.today || isoDay(new Date());
  const last = data.months?.at(-1);
  const to = last ? isoDay(new Date(Date.UTC(last.year, last.month, 0))) : from;
  return { from, to };
}

export function periodPreset(bounds, days) {
  const end = new Date(`${bounds.from}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + days);
  return { from: bounds.from, to: [isoDay(end), bounds.to].sort()[0] };
}

export function validatePeriod({ from, to }, bounds) {
  const isDay = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && isoDay(new Date(value)) === value;
  if (!isDay(from) || !isDay(to)) return "dates";
  if (from > to) return "order";
  if (from < bounds.from || to > bounds.to) return "bounds";
  return null;
}

/** Filter first so partial months, the totals, feed and calendar agree. */
export function paymentPeriod(data, { from, to }) {
  const flows = (data.flows || []).filter((flow) => flow.date >= from && flow.date <= to)
    .sort((a, b) => a.date.localeCompare(b.date));
  const months = [];
  const cursor = new Date(`${from.slice(0, 7)}-01T00:00:00Z`);
  while (isoDay(cursor).slice(0, 7) <= to.slice(0, 7)) {
    months.push({ key: isoDay(cursor).slice(0, 7), year: cursor.getUTCFullYear(),
      month: cursor.getUTCMonth() + 1, coupon: 0, principal: 0, issues: 0 });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  const byMonth = new Map(months.map((month) => [month.key, month]));
  const issues = new Set();
  const monthIssues = new Map();
  let coupon = 0;
  let principal = 0;
  for (const flow of flows) {
    const key = flow.date.slice(0, 7);
    const month = byMonth.get(key);
    coupon += flow.coupon || 0;
    principal += flow.principal || 0;
    month.coupon += flow.coupon || 0;
    month.principal += flow.principal || 0;
    issues.add(flow.ticker);
    if (!monthIssues.has(key)) monthIssues.set(key, new Set());
    monthIssues.get(key).add(flow.ticker);
    month.issues = monthIssues.get(key).size;
  }
  return { flows, months, coupon, principal, issues: issues.size, next: flows[0] };
}
