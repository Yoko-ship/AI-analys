

const FIN_FIELD_LABELS = {
  interest_income: ["Процентные доходы", "Foizli daromadlar", "Interest Income"],
  interest_expense: ["Процентные расходы", "Foizli xarajatlar", "Interest Expense"],
  net_revenue: ["Выручка", "Tushum", "Revenue"],
  net_profit: ["Чистая прибыль", "Sof foyda", "Net Profit"],
  gross_profit: ["Валовая прибыль", "Yalpi foyda", "Gross Profit"],
  operating_expenses: ["Операционные расходы", "Operatsion xarajatlar", "Operating Expenses"],
  operating_income: ["Операционная прибыль", "Operatsion foyda", "Operating Income"],
  cash: ["Денежные средства", "Pul mablaglari", "Cash"],
  total_assets: ["Активы", "Aktivlar", "Total Assets"],
  total_liabilities: ["Обязательства", "Majburiyatlar", "Total Liabilities"],
  total_equity: ["Капитал", "Kapital", "Total Equity"],
  gross_profit_margin: ["Валовая маржа", "Yalpi marja", "Gross Margin"],
  ebit_margin: ["EBIT-маржа", "EBIT marja", "EBIT Margin"],
  net_margin: ["Чистая маржа", "Sof marja", "Net Margin"],
  roe: ["ROE", "ROE", "ROE"],
  roa: ["ROA", "ROA", "ROA"],
  current_ratio: ["Текущая ликвидность", "Joriy likvidlik", "Current Ratio"],
  quick_ratio: ["Быстрая ликвидность", "Tez likvidlik", "Quick Ratio"],
  debt_ratio: ["Долг/Активы", "Qarz/Aktivlar", "Debt Ratio"],
  debt_to_equity: ["Долг/Капитал", "Qarz/Kapital", "Debt/Equity"],
  total_asset_turnover: ["Оборачиваемость активов", "Aktivlar aylanmasi", "Asset Turnover"],
  return_to_capital_employed: ["ROCE", "ROCE", "ROCE"],
};

const finLabel = (field, lang) =>
  (FIN_FIELD_LABELS[field] || [field, field, field])[lang === "uz" ? 1 : lang === "en" ? 2 : 0];

export { finLabel };
