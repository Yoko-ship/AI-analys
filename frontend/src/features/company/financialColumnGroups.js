const EQUITY = new Set(['share_capital', 'share_premium', 'retained_earnings', 'treasury_shares', 'other_reserves', 'equity_owners', 'nci', 'total_equity']);
const DEBT = new Set(['borrowings_short', 'borrowings_long', 'lease_liabilities', 'trade_payables', 'contract_liabilities', 'provisions', 'current_liabilities', 'noncurrent_liabilities', 'deferred_tax_liability', 'total_liabilities', 'customer_funds', 'bank_funding', 'subordinated_debt', 'insurance_contract_liabilities', 'reinsurance_contract_liabilities', 'insurance_reserves_gross', 'preferred_share_liability', 'interest_bearing_debt']);

export function financialGroup(row, view) {
  if (row.display_group) return row.display_group;
  if (view !== 'summary') return row.source_form;
  const code = parseInt(row.source_code, 10);
  if (row.source_form === 'F1') return code < 410 ? 'ASSETS' : code <= 480 ? 'EQUITY' : 'DEBT';
  if (row.source_form === 'BANK_BS') return code < 15 ? 'ASSETS' : code < 26 || code === 31 ? 'DEBT' : 'EQUITY';
  if (row.source_form === 'INSURANCE_BS') return code < 500 ? 'ASSETS' : code <= 570 ? 'EQUITY' : 'DEBT';
  if (row.source_form === 'BS') return EQUITY.has(row.metric_id) ? 'EQUITY' : DEBT.has(row.metric_id) ? 'DEBT' : row.metric_id === 'total_equity_liabilities' ? 'DEBT' : 'ASSETS';
  if (row.source_form === 'DERIVED' && DEBT.has(row.metric_id)) return 'DEBT';
  return row.source_form;
}
