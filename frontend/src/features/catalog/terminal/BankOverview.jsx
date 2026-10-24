import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {safeHref} from '../../../lib/safeHref.js';

export function BankOverview({data={},history=[],lang}) {
  const t=(...labels)=>words(lang,...labels);
  const fmt=value=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const main=data?.main||{},npl=data?.npl||{};
  const source=row=><small>{row.date||'—'} {row.source_url&&<a href={safeHref(row.source_url)} target="_blank" rel="noreferrer">CBU ↗</a>}</small>;
  return <section className="terminal-bank-overview">
    <h3>{t('Банк · ежемесячные данные ЦБ','Bank · MB oylik ma’lumotlari','Bank · monthly CBU observations')}</h3>
    <p className="muted">{t('Даты ЦБ отличаются от периода отчётности. Место по активам учитывает все банки таблицы ЦБ, включая небиржевые.','MB sanalari hisobot davridan farq qiladi. Aktivlar o‘rni barcha banklarni qamrab oladi.','CBU dates differ from financial reporting periods. Asset rank includes all banks in the CBU table, including unlisted banks.')}</p>
    <dl className="terminal-summary-kpis terminal-bank-kpis">
      <div><dt>{t('Доля активов, %','Aktivlar ulushi, %','Asset market share, %')}</dt><dd>{fmt(main.assets_share_pct)}</dd>{source(main)}</div>
      <div><dt>{t('Место по активам','Aktivlar bo‘yicha o‘rin','Asset rank')}</dt><dd>{main.assets_rank==null?'—':`${main.assets_rank} / ${main.rank_population}`}</dd>{source(main)}</div>
      <div><dt>NPL, %</dt><dd>{fmt(npl.npl_pct)}{npl.npl_flag?' ⚑':''}</dd>{source(npl)}</div>
    </dl>
    <details className="terminal-history-data"><summary>{t('Ежемесячная история ЦБ','MB oylik tarixi','Monthly CBU history')}</summary>
      {!history.length?<p className="muted">{t('Опубликованная история пока недоступна.','E’lon qilingan tarix mavjud emas.','Published history is unavailable.')}</p>:<div className="terminal-table-wrap"><table className="terminal-table">
        <caption>{t('Млрд UZS; отсутствующие месяцы не восстанавливаются.','Mlrd UZS; yo‘q oylar to‘ldirilmaydi.','Billion UZS; missing months are not interpolated.')}</caption>
        <thead><tr>{[t('Дата / источник','Sana / manba','Date / source'),t('Активы','Aktivlar','Assets'),t('Кредиты','Kreditlar','Loans'),t('Депозиты','Depozitlar','Deposits'),t('Капитал','Kapital','Equity'),t('Доля активов, %','Aktivlar ulushi, %','Asset share, %'),t('Место','O‘rin','Rank')].map(label=><th key={label}>{label}</th>)}</tr></thead>
        <tbody>{history.map(row=><tr key={row.date}><th>{source(row)}</th>{['assets_bn','loans_bn','deposits_bn','equity_bn','assets_share_pct'].map(key=><td key={key}>{fmt(row[key])}</td>)}<td>{row.assets_rank==null?'—':`${row.assets_rank} / ${row.rank_population}`}</td></tr>)}</tbody>
      </table></div>}
    </details>
  </section>;
}
