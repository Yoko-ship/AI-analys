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

const sectorFields = [
  ['capital', 'capital_adequacy', 'Достаточность капитала', 'Kapital yetarliligi', 'Capital adequacy'],
  ['profitability', 'roe', 'ROE', 'ROE', 'ROE'],
  ['profitability', 'nim', 'NIM', 'NIM', 'NIM'],
];

export function BankComparison({rows = [], lang, sectorSeries = {}}) {
  const banks = rows.filter(row => row.kind === 'bank');
  if (!banks.length) return null;
  const t = (...labels) => words(lang, ...labels);
  const format = value => value == null ? '—' : Number(value).toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU', {maximumFractionDigits: 2});
  const sectorMetrics = sectorFields.flatMap(([group, key, ...labels]) => {
    const dataset = sectorSeries[group], metric = dataset?.metrics?.[key];
    return metric ? [{key, labels, value: metric.value, sourceUrl: dataset.source_url}] : [];
  });
  return <section className="terminal-bank-comparison">
    <h3>{t('Банки · данные ЦБ', 'Banklar · MB ma’lumotlari', 'Banks · CBU observations')}</h3>
    <p className="muted">{t('Доли рынка — %. Кредиты и депозиты — млрд UZS.', 'Bozor ulushlari — %. Kreditlar va depozitlar — mlrd UZS.', 'Market shares are percentages; loans and deposits are billion UZS.')}</p>
    <div className="terminal-table-wrap"><table className="terminal-table">
      <thead><tr><th>{t('Банк', 'Bank', 'Bank')}</th>{groups.map(([kind, fields]) => <React.Fragment key={kind}>
        {fields.map(([key, ...labels]) => <th key={key}>{t(...labels)}</th>)}
      </React.Fragment>)}</tr></thead>
      <tbody>{banks.map(row => <tr key={row.ticker}><th>{row.ticker}</th>{groups.map(([kind, fields]) => <React.Fragment key={kind}>
        {fields.map(([key]) => <td key={key}>{format(row['cbu_' + key])}</td>)}
      </React.Fragment>)}</tr>)}</tbody>
    </table></div>
    {sectorMetrics.length > 0 && <div className="terminal-bank-sector">
      <h4>{t('Банковский сектор · ЦБ', 'Bank sektori · MB', 'Banking sector · CBU')}</h4>
      <dl>{sectorMetrics.map(({key, labels, value, sourceUrl}) => <div key={key}>
        <dt>{sourceUrl ? <a href={safeHref(sourceUrl)} target="_blank" rel="noreferrer" title={t('Открыть данные ЦБ', 'MB ma’lumotlarini ochish', 'Open CBU data')}>{t(...labels)}</a> : t(...labels)}</dt>
        <dd>{value == null ? '—' : `${format(value)}%`}</dd>
      </div>)}</dl>
    </div>}
  </section>;
}
