import React from 'react';
import {amount,columnsFor,downloadStatement} from './model.js';

export const STATEMENT_TITLES={
  pl:['Отчёт о прибыли или убытке','Foyda va zarar hisoboti','Profit or loss'],
  bs:['Отчёт о финансовом положении','Moliyaviy holat hisoboti','Financial position'],
  cf:['Отчёт о движении денежных средств','Pul oqimlari hisoboti','Cash flow statement'],
  equity:['Отчёт об изменениях капитала','Kapital o‘zgarishi hisoboti','Changes in equity'],
};
export function Statements({data,tab,t,format,open}) {
  const [detail,setDetail]=React.useState(true),columns=columnsFor(data,tab);
  return <section className="investor-panel"><header className="investor-panel-head"><div><small>IFRS / {data.scope}</small><h2>{t(...STATEMENT_TITLES[tab])}</h2><p>{tab==='bs'?t('Остатки на отчётную дату','Hisobot sanasidagi qoldiqlar','Balances at the reporting date'):t('Потоки за указанный период','Ko‘rsatilgan davr oqimlari','Flows for the stated period')} · {t('млрд UZS','mlrd UZS','billion UZS')}</p></div><div className="investor-actions"><button type="button" aria-pressed={detail} onClick={()=>setDetail(v=>!v)}>{t('Детализация','Tafsilotlar','Details')}</button><button type="button" onClick={()=>downloadStatement(data,tab,detail)}>CSV</button></div></header>
    <div className="investor-table-scroll" tabIndex={0} role="region" aria-label={t(...STATEMENT_TITLES[tab])}><table className="investor-table" data-own-export><thead><tr><th>{t('Показатель','Ko‘rsatkich','Metric')}</th>{columns.map(c=><th key={c.key}>{tab==='bs'?c.end:c.label}<small>{c.basis==='ytd'?'YTD · ':''}{t('млрд UZS','mlrd UZS','billion UZS')}</small></th>)}</tr></thead><tbody>{(data.statements[tab]||[]).map(group=><React.Fragment key={group.label}><tr className="investor-group"><th colSpan={columns.length+1}>{group.label}</th></tr>{group.rows.filter(r=>detail||!r.detail).map(row=><tr key={row.id} data-field={row.field} className={row.grand?'investor-grand':row.total?'investor-total':row.detail?'investor-detail':''}><th scope="row">{row.label}{row.annotation&&<small>{t('Справочно, не суммировать','Ma’lumot uchun, qo‘shilmaydi','Reference only; do not add')}</small>}</th>{columns.map(c=>{const cell=row.cells[c.key],value=amount(cell,row.unit);return <td key={c.key}><button type="button" className="investor-number" onClick={()=>open(row,cell,c)} aria-label={`${row.label} · ${c.label}: ${format(value)}`}>{format(value)}{cell?.quality==='blocked'&&<span aria-hidden="true"> ⚑</span>}</button></td>;})}</tr>)}</React.Fragment>)}</tbody></table></div>
    <footer className="investor-footnote">{t('Итоги выделены и не суммируются повторно. Нажмите на число для источника.','Yakuniy qiymatlar qayta qo‘shilmaydi. Manba uchun raqamni bosing.','Totals are highlighted and are not added twice. Select a value to inspect its source.')}</footer>
  </section>;
}
