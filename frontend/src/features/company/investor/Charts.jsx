import React from 'react';
import {columnsFor,fieldValue,selectedColumn,primaryField,fundingShare} from './model.js';

export function Trend({data,t,format}) {
  const field=data.display_template==='fund'?'revenue':primaryField(data);
  const points=columnsFor(data,'pl').map(c=>({...c,income:fieldValue(data,field,c),profit:fieldValue(data,'profit',c)}));
  const values=points.flatMap(p=>[p.income,p.profit]).filter(v=>v!=null);
  const max=Math.max(0,...values),min=Math.min(0,...values),range=max-min||1;
  const y=v=>220-(v-min)/range*190,x=i=>60+(i+.5)*600/Math.max(1,points.length);
  return <section className="investor-panel investor-pad"><div className="investor-panel-head"><div><small>{t('Динамика бизнеса','Biznes dinamikasi','Business trends')}</small><h2>{t('Доходы и чистая прибыль','Daromad va sof foyda','Income and net profit')}</h2><p>{t('млрд UZS','mlrd UZS','billion UZS')}</p></div><span className="investor-pill">IFRS</span></div>{!values.length?<p className="investor-empty">{t('Нет проверенных значений для графика.','Grafik uchun tekshirilgan qiymatlar yo‘q.','No verified values to chart.')}</p>:<svg className="investor-trend" viewBox="0 0 700 270" role="img" aria-label={t('Доходы и прибыль','Daromad va foyda','Income and profit')}>
      {[min,min+range/2,max].map((v,i)=><g key={i}><line x1="48" x2="685" y1={y(v)} y2={y(v)} className="investor-gridline"/><text x="43" y={y(v)+3} textAnchor="end">{format(v)}</text></g>)}
      {points.map((p,i)=><g key={p.key}>{p.income!=null&&<rect x={x(i)-20} width="40" y={Math.min(y(0),y(p.income))} height={Math.max(1,Math.abs(y(p.income)-y(0)))} rx="4" fill="var(--iv-aqua)"><title>{p.label}: {format(p.income)}</title></rect>}{p.profit!=null&&<>{i>0&&points[i-1].profit!=null&&<line x1={x(i-1)} y1={y(points[i-1].profit)} x2={x(i)} y2={y(p.profit)} stroke="var(--iv-purple)" strokeWidth="3"/>}<circle cx={x(i)} cy={y(p.profit)} r="5" fill="var(--iv-purple)"><title>{t('Прибыль','Foyda','Profit')}: {format(p.profit)}</title></circle></>}<text x={x(i)} y="250" textAnchor="middle">{p.label}</text></g>)}
    </svg>}<div className="investor-legend"><span><i/>{t('Доходы','Daromad','Income')}</span><span><i className="purple"/>{t('Чистая прибыль','Sof foyda','Net profit')}</span></div></section>;
}
export function Funding({data,t,format}) {
  const column=selectedColumn(data,'stock'),assets=fieldValue(data,'assets',column),equity=fieldValue(data,'equity',column),liabilities=fieldValue(data,'liabilities',column);
  const share=fundingShare(assets,equity,liabilities);
  return <section className="investor-panel investor-pad"><div className="investor-panel-head"><div><small>{t('Структура финансирования','Moliyalashtirish tarkibi','Funding structure')}</small><h2>{t('Капитал и обязательства','Kapital va majburiyatlar','Equity and liabilities')}</h2></div><span className="investor-pill">{column?.end||'—'}</span></div><div className="investor-funding"><div className="investor-donut" style={{'--share':`${(share||0)*100}%`}}><div><strong>{share==null?'—':format(share*100)+'%'}</strong><small>{t('Капитал','Kapital','Equity')}</small></div></div><dl>{[[t('Собственный капитал','O‘z kapitali','Equity'),equity],[t('Обязательства','Majburiyatlar','Liabilities'),liabilities],[t('Всего активы','Jami aktivlar','Total assets'),assets]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{format(value)}</dd></div>)}</dl></div></section>;
}
export function CashFlows({data,t,format}) {
  const column=selectedColumn(data),values=['cfo','cfi','cff'].map(field=>fieldValue(data,field,column,'cf')),max=Math.max(1,...values.filter(v=>v!=null).map(Math.abs));
  return <section className="investor-panel investor-pad"><h2>{t('Денежные потоки','Pul oqimlari','Cash flows')}</h2><p className="investor-muted">{column?.label} · {t('млрд UZS','mlrd UZS','billion UZS')}</p>{[t('Операционный','Operatsion','Operating'),t('Инвестиционный','Investitsion','Investing'),t('Финансовый','Moliyaviy','Financing')].map((label,i)=><div className="investor-bar-row" key={label}><span>{label}</span><div className="investor-bar-track"><i style={{width:values[i]==null?'0':`${Math.abs(values[i])/max*100}%`,background:values[i]<0?'var(--iv-bad)':'var(--iv-aqua)'}}/></div><b>{format(values[i])}</b></div>)}</section>;
}
