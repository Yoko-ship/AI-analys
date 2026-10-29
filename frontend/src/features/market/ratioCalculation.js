const LABELS = {
  current_ratio: ['Текущая ликвидность', 'Joriy likvidlik', 'Current ratio'],
  quick_ratio: ['Быстрая ликвидность', 'Tez likvidlik', 'Quick ratio'],
  debt_ratio: ['Долг/Активы', 'Qarz/Aktivlar', 'Debt/Assets'],
  total_asset_turnover: ['Оборачиваемость активов', 'Aktivlar aylanmasi', 'Asset turnover'],
  return_to_capital_employed: ['ROCE', 'ROCE', 'ROCE'],
  current_assets: ['Текущие активы', 'Joriy aktivlar', 'Current assets'],
  current_liabilities: ['Текущие обязательства', 'Joriy majburiyatlar', 'Current liabilities'],
  inventories: ['Запасы', 'Zaxiralar', 'Inventories'],
  total_assets: ['Активы', 'Aktivlar', 'Assets'],
  total_liabilities: ['Обязательства', 'Majburiyatlar', 'Liabilities'],
  revenue: ['Выручка', 'Tushum', 'Revenue'],
  operating_income: ['Операционная прибыль', 'Operatsion foyda', 'Operating profit'],
};
const languageIndex = lang => lang === 'en' ? 2 : lang === 'uz' ? 1 : 0;
export const ratioCalculationLabel = (field, lang) => LABELS[field]?.[languageIndex(lang)] || field;

export function ratioCalculationDescription(field, calculation, lang) {
  if (!calculation) return '';
  const i = languageIndex(lang);
  const pick = (ru, uz, en) => [ru, uz, en][i];
  const number = value => new Intl.NumberFormat(lang === 'en' ? 'en-US' : lang === 'uz' ? 'uz-UZ' : 'ru-RU', {
    maximumFractionDigits: 6,
  }).format(value);
  const formula = calculation.formula.replace(/\b[a-z_]+\b/g, key => ratioCalculationLabel(key, lang)).replaceAll('*', '×');
  const amounts = calculation.formula.replace(/\b[a-z_]+\b/g, key => number(calculation.operands[key])).replaceAll('*', '×');
  const basis = calculation.annualized
    ? pick(`За ${calculation.period_months} мес., приведено к году; это не прогноз.`,
      `${calculation.period_months} oylik natija yillikka keltirilgan; bu prognoz emas.`,
      `${calculation.period_months} months, annualized; this is not a forecast.`)
    : pick('Без приведения к году.', 'Yillikka keltirilmagan.', 'No annualization.');
  const coefficient = field === 'return_to_capital_employed'
    ? pick('ROCE показан коэффициентом: 0,18 = 18%.', 'ROCE koeffitsiyentda: 0,18 = 18%.', 'ROCE is a coefficient: 0.18 = 18%.') : '';
  return [pick('Расчёт UZStock', 'UZStock hisob-kitobi', 'UZStock calculation'), calculation.period,
    `${formula}.`, `${amounts} = ${number(calculation.value)}${calculation.unit === 'percent' ? '%' : ''}.`,
    pick('Суммы — тыс. сум, баланс на конец периода.', 'Summalar — ming so‘m, davr oxiridagi balans.',
      'Amounts in thousand UZS; closing balance.'), basis, coefficient,
  ].filter(Boolean).join(' ');
}
