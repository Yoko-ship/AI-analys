const OPERATING_COSTS = ['operating_expenses', 'selling_expense', 'admin_expense', 'other_operating_expense'];
const FINANCE_COSTS = ['finance_cost', 'interest_expense', 'lease_expense', 'fx_expense', 'other_finance_cost'];
const TAX = ['income_tax', 'other_profit_payments', 'profit_adjustment', 'tax_adjustment'];

const BUSINESS = [
  ['revenue'],
  ['gross_profit', 'cost_of_sales'],
  ['operating_income', 'other_operating_income', OPERATING_COSTS],
  ['profit_before_tax', 'finance_income', FINANCE_COSTS, 'extraordinary_profit', 'fx_gain_loss', 'share_of_profit_associates'],
  ['net_income', ...TAX],
];

const INSURER = [
  ['net_insurance_revenue'],
  ['gross_profit', 'insurance_cost'],
  ...BUSINESS.slice(2),
];

const BANK = [
  ['interest_income'],
  ['net_interest_before_ecl', 'interest_expense'],
  ['net_interest_after_ecl', 'credit_loss_expense'],
  ['income_before_opex', ['noninterest_income', 'fee_income', 'fx_income'], ['noninterest_expense', 'fee_expense']],
  ['profit_before_tax', OPERATING_COSTS, 'noncredit_impairment'],
  ['net_income', ...TAX],
];

const IFRS_INSURER = [
  ['insurance_revenue'],
  ['insurance_service_result', 'insurance_service_expense'],
  ['profit_before_tax', 'reinsurance_result', 'investment_income', 'insurance_finance_expense', OPERATING_COSTS],
  ['net_income', ...TAX],
];

const IFRS_BANK = [
  ['interest_income'],
  ['net_interest_before_ecl', 'interest_expense'],
  ['net_interest_after_ecl', 'credit_loss_expense'],
  ['profit_before_tax', ['net_fee_income', 'fee_income', 'fee_expense'], 'trading_income', 'other_operating_income', OPERATING_COSTS],
  ['net_income', ...TAX],
];

const IFRS_FUND = [
  ['investment_income'],
  ['profit_before_tax', 'fair_value_gain_loss', 'fund_expenses', 'finance_income', FINANCE_COSTS],
  ['net_income', ...TAX],
];

const FORMS = {F2: [BUSINESS], INSURANCE_PL: [INSURER], BANK_PL: [BANK], PL: [BUSINESS, IFRS_INSURER, IFRS_BANK, IFRS_FUND]};

const BANK_DEDUCTIONS = new Set([
  'interest_expense', 'credit_loss_expense', 'noninterest_expense', 'fee_expense',
  ...OPERATING_COSTS, 'noncredit_impairment', 'income_tax',
]);

function reconciles(difference, values) {
  return Math.abs(difference) <= Number.EPSILON * 8 * Math.max(1, ...values.map(Math.abs));
}

function adjustmentLines(definition, amounts) {
  if (typeof definition === 'string') return [amounts.get(definition)].filter(Boolean);
  const [total, ...parts] = definition.map(id => amounts.get(id));
  const disclosed = parts.filter(Boolean);
  if (!total) return disclosed;
  // Split a reported total only when its disclosed components reconcile to it.
  const sum = disclosed.reduce((value, part) => value + part.value, 0);
  return disclosed.length && reconciles(total.value - sum, [total.value, sum]) ? disclosed : [total];
}

export function incomeFlow(rows, period) {
  for (const [form, definitions] of Object.entries(FORMS)) {
    const amounts = new Map();
    const conflicts = new Set();
    for (const row of rows) {
      const cell = row.cells?.[period];
      if (row.source_form !== form || row.kind !== 'flow' || row.unit !== 'UZS_thousand' ||
          cell?.value == null || cell.value === '' || !['valid', 'warn'].includes(cell.quality)) continue;
      // Bank forms report expense magnitudes in a single column. F2 uses signed
      // income-minus-expense pairs. Inversion also preserves bank recoveries.
      const value = Number(cell.value) * (form === 'BANK_PL' && BANK_DEDUCTIONS.has(row.metric_id) ? -1 : 1);
      if (!Number.isFinite(value)) continue;
      if (amounts.has(row.metric_id) && amounts.get(row.metric_id).value !== value) conflicts.add(row.metric_id);
      amounts.set(row.metric_id, {id: row.metric_id, label: row.label, value});
    }
    for (const metric of conflicts) amounts.delete(metric);
    const definition = definitions.find(stages => amounts.has(stages[0][0]) && amounts.has('net_income'));
    if (!definition) continue;

    const totals = [amounts.get(definition[0][0])];
    const bridges = [];
    let lines = [];
    for (const [id, ...adjustments] of definition.slice(1)) {
      lines.push(...adjustments.flatMap(item => adjustmentLines(item, amounts)));
      const total = amounts.get(id);
      if (!total) continue;
      const prior = totals.at(-1);
      const entries = [...new Map(lines.map(line => [line.id, line])).values()].filter(line => line.value !== 0);
      const values = [prior.value, ...entries.map(line => line.value)];
      const difference = total.value - values.reduce((sum, value) => sum + value, 0);
      if (!reconciles(difference, [...values, total.value])) entries.push({id: 'difference', value: difference});
      bridges.push(entries);
      totals.push(total);
      lines = [];
    }
    const hasBreakdown = totals.length > 2 || bridges.some(entries => entries.some(line => line.id !== 'difference'));
    if (hasBreakdown && (totals.some(total => total.value) || bridges.some(entries => entries.length))) return {totals, bridges};
  }
  return null;
}
