

const FIN_FIELD_LABELS = {
  // Statutory ratios are distinct from annualised ROA/ROE. Match the reporting
  // vocabulary in financial_analysis/metric_names.py when a source omits names.
  P1: ["Доходность активов на конец периода (P1)", "Davr oxiridagi aktivlar daromadliligi (P1)", "Return on closing assets (P1)"],
  P2: ["Прибыль до налога / оборотные активы (P2)", "Soliqdan oldingi foyda / joriy aktivlar (P2)", "Pre-tax profit / current assets (P2)"],
  P3: ["Прибыль до налога / задействованный капитал (P3)", "Soliqdan oldingi foyda / ishlatilgan kapital (P3)", "Pre-tax profit / capital employed (P3)"],
  P4: ["Доходность капитала до налога (P4)", "Kapitalning soliqdan oldingi daromadliligi (P4)", "Pre-tax return on closing equity (P4)"],
  P5: ["Валовая маржа (P5)", "Yalpi marja (P5)", "Gross margin (P5)"],
  P6: ["Валовая прибыль / себестоимость (P6)", "Yalpi foyda / tannarx (P6)", "Gross profit / cost of sales (P6)"],
  P7: ["Прибыль до налога / выручка (P7)", "Soliqdan oldingi foyda / tushum (P7)", "Pre-tax profit / revenue (P7)"],
  P8: ["Прибыль до налога / долгосрочные активы (P8)", "Soliqdan oldingi foyda / uzoq muddatli aktivlar (P8)", "Pre-tax profit / non-current assets (P8)"],
  absolute_liquidity: ["Абсолютная ликвидность", "Mutlaq likvidlik", "Cash ratio"],
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
