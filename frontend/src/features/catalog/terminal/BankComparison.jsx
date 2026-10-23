import React from 'react';
import { words } from '../../../shared/TerminalTables.jsx';
import { safeHref } from '../../../lib/safeHref.js';

const groups = [
  ['main', [
    ['assets_share_pct', 'Доля активов, %', 'Aktivlar ulushi, %', 'Asset market share, %'],
    ['loans_share_pct', 'Доля кредитов, %', 'Kreditlar ulushi, %', 'Loan market share, %'],
    ['equity_share_pct', 'Доля капитала, %', 'Kapital ulushi, %', 'Capital market share, %'],
    ['deposits_share_pct', 'Доля депозитов, %', 'Depozitlar ulushi, %', 'Deposit market share, %'],
  ]],
  ['structure', [
    ['household_loans_bn', 'Кредиты физлиц', 'Jismoniy shaxslar kreditlari', 'Household loans'],
    ['company_loans_bn', 'Кредиты юрлиц', 'Yuridik shaxslar kreditlari', 'Corporate loans'],
    ['household_deposits_bn', 'Депозиты физлиц', 'Jismoniy shaxslar depozitlari', 'Household deposits'],
    ['company_deposits_bn', 'Депозиты юрлиц', 'Yuridik shaxslar depozitlari', 'Corporate deposits'],
  ]],
];

export function BankComparison({rows = [], lang, sectorSeries = {}}) {
  const banks = rows.filter(row => row.kind === 'bank');
  if (!banks.length) return null;
  const t = (...labels) => words(lang, ...labels);
  const format = value => value == null ? '—' : Number(value).toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU', {maximumFractionDigits: 2});
  return <section className="terminal-bank-comparison">
    <h3>{t('Банки · данные ЦБ', 'Banklar · MB ma’lumotlari', 'Banks · CBU observations')}</h3>
    <p className="muted">{t('Доли рынка — %. Кредиты и депозиты — млрд UZS. Даты ЦБ указаны отдельно от годовой отчётности.', 'Bozor ulushlari — %. Kreditlar va depozitlar — mlrd UZS. MB sanalari hisobot davridan alohida.', 'Market shares are percentages; loans and deposits are billion UZS. CBU dates are separate from financial reporting periods.')}</p>
    <div className="terminal-table-wrap"><table className="terminal-table">
      <thead><tr><th>{t('Банк', 'Bank', 'Bank')}</th>{groups.map(([kind, fields]) => <React.Fragment key={kind}>
        <th>{kind === 'main' ? t('Доли рынка · дата / источник', 'Bozor ulushlari · sana / manba', 'Market shares · date / source') : t('Структура · дата / источник', 'Tarkib · sana / manba', 'Structure · date / source')}</th>
        {fields.map(([key, ...labels]) => <th key={key}>{t(...labels)}</th>)}
      </React.Fragment>)}</tr></thead>
      <tbody>{banks.map(row => <tr key={row.ticker}><th>{row.ticker}</th>{groups.map(([kind, fields]) => <React.Fragment key={kind}>
        <td>{row.cbu?.[kind]?.source_url ? <a href={safeHref(row.cbu[kind].source_url)} target="_blank" rel="noreferrer">{row.cbu[kind].date} ↗</a> : '—'}</td>
        {fields.map(([key]) => <td key={key}>{format(row['cbu_' + key])}</td>)}
      </React.Fragment>)}</tr>)}</tbody>
    </table></div>
    {Object.entries(sectorSeries).filter(([key]) => ['capital', 'profitability'].includes(key)).map(([kind, dataset]) => <p className="muted" key={kind}>
      {t('Сектор ЦБ', 'MB sektori', 'CBU sector')} · <a href={safeHref(dataset.source_url)} target="_blank" rel="noreferrer">{dataset.date} ↗</a>
      {['roe', 'nim', 'capital_adequacy'].filter(key => dataset.metrics?.[key]).map(key => <span key={key}> · {key === 'capital_adequacy' ? t('Достаточность капитала', 'Kapital yetarliligi', 'Capital adequacy') : key.toUpperCase()}: {format(dataset.metrics[key].value)}%</span>)}
    </p>)}
  </section>;
}
