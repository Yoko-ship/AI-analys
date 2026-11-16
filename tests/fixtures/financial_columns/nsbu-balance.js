import {readFileSync} from 'node:fs';

// Public annual filings already used by the ingestion regressions. Keep every
// filed balance row, including unregistered details, without copying the files.
export function filedBalance(ticker) {
  const insurance = ticker === 'KFSK';
  const filing = JSON.parse(readFileSync(`tests/fixtures/openinfo/${ticker.toLowerCase()}_2025_complete_rows.json`, 'utf8'));
  const form = insurance ? 'INSURANCE_BS' : 'F1';
  const metrics = {
    '012': 'ppe', '022': 'intangibles', '030': 'long_term_investments',
    '090': 'equipment_installation', '100': 'construction_in_progress',
    '110': 'long_term_receivables', '120': 'long_term_deferred_expenses', '130': 'noncurrent_assets',
    ...(insurance ? {
      '140': 'materials', '150': 'work_in_progress', '160': 'finished_goods',
      '170': 'prepaid_expenses', '180': 'deferred_expenses', '190': 'receivables',
      '410': 'cash', '460': 'short_term_investments', '470': 'other_current_assets',
      '480': 'current_assets', '490': 'total_assets', '570': 'total_equity',
      '500': 'share_capital', '510': 'share_premium', '520': 'reserve_capital',
      '530': 'treasury_shares', '540': 'retained_earnings',
      '550': 'target_receipts', '560': 'future_expense_reserves',
      '580': 'insurance_reserves_gross', '670': 'reinsurer_share_reserves',
      '720': 'insurance_reserves_net', '1190': 'nonreserve_liabilities',
    } : {
      '140': 'inventory', '190': 'prepaid_expenses', '200': 'deferred_expenses',
      '210': 'receivables', '320': 'cash', '370': 'short_term_investments',
      '380': 'other_current_assets', '390': 'current_assets', '400': 'total_assets',
      '480': 'total_equity', '770': 'total_liabilities',
      '410': 'share_capital', '420': 'share_premium', '430': 'reserve_capital',
      '440': 'treasury_shares', '450': 'retained_earnings',
      '460': 'target_receipts', '470': 'future_expense_reserves',
    }),
  };
  const source = filing.sheets.flatMap(sheet => sheet.source_rows);
  const start = source.findIndex(({cells}) => cells[1] === '010');
  const end = source.findIndex(({cells}, i) => i > start && cells[1] === (insurance ? '1200' : '780'));
  if (start < 0 || end < start) throw new Error(`Balance rows missing for ${ticker}`);
  const rows = source.slice(start, end + 1).filter(({cells}) => /^\d{3,4}$/.test(cells[1])).map(({cells}) => ({
    id: `${form}:${cells[1]}`, source_form: form, source_code: cells[1],
    metric_id: metrics[cells[1]] ?? null, label: cells[0], kind: 'stock', unit: 'UZS_thousand',
    cells: {'2025': {value: cells[3], raw_value: cells[3], quality: cells[3] == null ? 'missing' : 'valid',
      source_form: form, source_code: cells[1], source_url: filing.source_url,
      source_version: filing.source_url, period_end: filing.reporting_date,
      currency: 'UZS', unit_scale: '1000', scope: 'separate', standard: 'NSBU'}},
  }));
  return {ok: true, ticker, issuer_id: `fixture:${ticker}`, scope: 'separate', standard: 'NSBU',
    presentation: 'template', rows, chart_rows: rows,
    columns: [{key: '2025', label: '2025', end: filing.reporting_date, basis: 'annual'}]};
}
