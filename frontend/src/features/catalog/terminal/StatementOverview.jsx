import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {profitBridge,assetComposition,statementFacts} from '../../../lib/terminalStatements.js';
import {reportKind} from '../../../lib/terminalSummary.js';
import {useScreenData} from './TerminalPanels.jsx';
import './summaryScreen.css';
import './statementOverview.css';

const LABELS={
  dividend_income:['Дивидендный доход','Dividend daromadi','Dividend income'],unrealized_fair_value_gain:['Нереализованная переоценка','Realizatsiya qilinmagan qayta baholash','Unrealised revaluation'],management_expenses:['Расходы на управление','Boshqaruv xarajatlari','Management expenses'],other_fund_result:['Прочий результат *','Boshqa natija *','Other result *'],tax:['Налог','Soliq','Tax'],portfolio_fair_value:['Инвестиционный портфель','Investitsiya portfeli','Investment portfolio'],dividends_receivable:['Дивиденды к получению','Olinadigan dividendlar','Dividends receivable'],
  insurance_service_cost:['Расходы по страхованию','Sug‘urta xarajatlari','Insurance service costs'],insurance_service_result:['Страховой результат','Sug‘urta natijasi','Insurance service result'],expenses:['Операционные расходы','Operatsion xarajatlar','Operating expenses'],
  revenue:['Выручка','Tushum','Revenue'],cost_of_sales:['Себестоимость','Tannarx','Cost of sales'],gross_profit:['Валовая прибыль','Yalpi foyda','Gross profit'],
  period_expenses:['Расходы периода','Davr xarajatlari','Period expenses'],other_operating:['Прочее операционное *','Boshqa operatsion *','Other operating *'],
  operating_income:['Операционная прибыль','Operatsion foyda','Operating profit'],financial_income:['Финансовые доходы','Moliyaviy daromad','Financial income'],
  financial_expenses:['Финансовые расходы','Moliyaviy xarajatlar','Financial expenses'],other_pretax:['Прочее до налога *','Soliqqacha boshqa *','Other pre-tax *'],
  profit_before_tax:['Прибыль до налога','Soliqqacha foyda','Pre-tax profit'],tax_and_other:['Налог и прочее *','Soliq va boshqa *','Tax and other *'],net_income:['Чистая прибыль','Sof foyda','Net profit'],
  interest_income:['Процентные доходы','Foiz daromadi','Interest income'],interest_expenses:['Процентные расходы','Foiz xarajatlari','Interest expense'],interest_expense:['Процентные расходы','Foiz xarajatlari','Interest expense'],
  net_interest_income_before_provisions:['ЧПД до резервов','Zaxiragacha sof foiz daromadi','Net interest before provisions'],credit_loss_provisions:['Резервы на потери','Zarar zaxiralari','Loss provisions'],
  noninterest_income:['Непроцентные доходы','Foizsiz daromad','Non-interest income'],noninterest_expenses:['Непроцентные расходы','Foizsiz xarajatlar','Non-interest expense'],operating_expenses:['Операционные расходы','Operatsion xarajatlar','Operating expenses'],
  fixed_assets:['Основные средства','Asosiy vositalar','Fixed assets'],receivables:['Дебиторская задолженность','Debitorlik qarzi','Receivables'],long_term_investments:['Долгосрочные инвестиции','Uzoq muddatli investitsiyalar','Long-term investments'],
  inventories:['Запасы','Zaxiralar','Inventories'],construction_in_progress:['Незавершённое строительство','Tugallanmagan qurilish','Construction in progress'],short_term_investments:['Краткосрочные инвестиции','Qisqa muddatli investitsiyalar','Short-term investments'],
  cash:['Денежные средства','Pul mablag‘lari','Cash'],loan_portfolio:['Кредитный портфель','Kredit portfeli','Loan portfolio'],due_from_banks:['Средства в банках','Banklardagi mablag‘lar','Due from banks'],central_bank_balances:['Средства в ЦБ','MBdagi mablag‘lar','Central bank balances'],
  other:['Прочие активы *','Boshqa aktivlar *','Other assets *'],total_assets:['Активы','Aktivlar','Assets'],total_equity:['Капитал','Kapital','Equity'],total_liabilities:['Обязательства','Majburiyatlar','Liabilities'],
};

function Waterfall({steps,title,label,fmt}) {
  let running=0;
  const points=steps.map(step=>{
    const start=step.total?0:running,end=step.total?step.value:running==null||step.value==null?null:running+step.value;
    running=end;
    return {...step,start,end};
  });
  const values=points.flatMap(p=>[p.start,p.end]).filter(v=>v!=null),min=Math.min(0,...values),max=Math.max(0,...values);
  const x=value=>185+(value-min)/(max-min||1)*290;
  return <svg className="terminal-statement-chart" role="img" aria-label={title} viewBox={`0 0 575 ${points.length*26+10}`}><title>{title}</title>
    <line x1={x(0)} x2={x(0)} y1="0" y2={points.length*26+6} className="terminal-chart-grid"/>
    {points.map((point,i)=>{
      const y=i*26+6,valid=point.start!=null&&point.end!=null;
      return <g key={point.key}><text x="177" y={y+14} textAnchor="end">{label(point.key)}</text>
        {valid&&<rect x={x(Math.min(point.start,point.end))} y={y+2} width={Math.max(1.5,Math.abs(x(point.end)-x(point.start)))} height="17" fill={point.total?'var(--terminal-chart,#4bb8e8)':point.value<0?'var(--negative,#e05252)':'var(--positive,#3fbf6a)'}><title>{label(point.key)}: {fmt(point.value/1e9)}</title></rect>}
        <text x="568" y={y+14} textAnchor="end">{point.value==null?'—':fmt(point.value/1e9)}</text>
      </g>;
    })}
  </svg>;
}

function Margins({history,kind,form,lang,fromYear}) {
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const periods=(history?.periods||[]).map(String).filter(p=>/^\d{4}$/.test(p)&&Number(p)>=fromYear).sort();
  const title=t('Маржинальность по годам','Yillar bo‘yicha marja','Annual margins');
  const bankIncomeLabel=form==='MSFO'?t('Чистая прибыль / процентные доходы','Sof foyda / foiz daromadi','Net profit / interest income'):t('Чистая прибыль / совокупные доходы','Sof foyda / jami daromad','Net profit / total income');
  const fields=kind==='bank'?[['net_profit',bankIncomeLabel,'var(--positive,#3fbf6a)']]:[['gross_profit',t('Валовая','Yalpi','Gross'),'var(--accent)'],['operating_income',t('Операционная','Operatsion','Operating'),'var(--terminal-chart,#4bb8e8)'],['net_profit',t('Чистая','Sof','Net'),'var(--positive,#3fbf6a)']];
  const denominator=kind==='bank'&&form==='MSFO'?'interest_income':'net_revenue';
  const years=periods.length?Array.from({length:Number(periods.at(-1))-Number(periods[0])+1},(_,i)=>String(Number(periods[0])+i)):[];
  const lines=fields.map(([field,name,color])=>({name,color,values:years.map(year=>{
    const n=history?.series?.[field]?.values?.[year],d=history?.series?.[denominator]?.values?.[year];
    return Number.isFinite(n)&&Number.isFinite(d)&&d>0?n/d*100:null;
  })}));
  const available=lines.filter(line=>line.values.some(v=>v!=null));
  const values=available.flatMap(line=>line.values).filter(v=>v!=null),min=Math.min(0,...values),max=Math.max(0,...values);
  const x=i=>45+i*490/Math.max(1,years.length-1),y=v=>15+(max-v)/(max-min||1)*190;
  return <section className="terminal-summary-card"><h3>{title}</h3><p className="muted">{form} · % · {t('Годовые отчёты; без пересчёта маржи на год','Yillik hisobotlar; marja qayta yilliklashtirilmaydi','Annual filings; margins are not annualised')}</p>
    {!available.length?<p className="muted">{t('Недостаточно данных для маржи.','Marja uchun ma’lumot yetarli emas.','Insufficient data for margins.')}</p>:<><svg className="terminal-history-chart" viewBox="0 0 575 240" role="img" aria-label={title}><title>{title}</title>
      <line x1="45" x2="535" y1={y(0)} y2={y(0)} className="terminal-chart-grid"/>
      {years.map((year,i)=><text key={year} x={x(i)} y="228" textAnchor="middle">{year}</text>)}
      {[max,0,...(min<0?[min]:[])].filter((v,i,a)=>a.indexOf(v)===i).map(v=><text key={v} x="38" y={y(v)+4} textAnchor="end">{v.toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:1})}%</text>)}
      {available.map(line=><g key={line.name}>{line.values.map((v,i)=>v==null?null:<g key={i}>{i>0&&line.values[i-1]!=null&&<line x1={x(i-1)} y1={y(line.values[i-1])} x2={x(i)} y2={y(v)} stroke={line.color} strokeWidth="2"/>}<circle cx={x(i)} cy={y(v)} r="3" fill={line.color}><title>{years[i]} · {line.name}: {v.toFixed(2)}%</title></circle></g>)}</g>)}
    </svg><div className="terminal-chart-legend">{available.map(line=><span key={line.name}><i style={{background:line.color}}/>{line.name}</span>)}</div></>}
  </section>;
}

function AssetChart({composition,title,label,fmt}) {
  const max=Math.max(100,...composition.rows.map(row=>row.share));
  return <svg className="terminal-statement-chart" role="img" aria-label={title} viewBox={`0 0 575 ${composition.rows.length*28+8}`}><title>{title}</title>
    {composition.rows.map((row,i)=><g key={row.key}><text x="220" y={i*28+18} textAnchor="end">{label(row.key)}</text><rect x="230" y={i*28+5} width={Math.max(0,row.share/max*270)} height="18" fill={row.derived?'var(--muted)':'var(--terminal-chart,#4bb8e8)'}><title>{label(row.key)}: {fmt(row.value/1e9)} UZS billion</title></rect><text x="565" y={i*28+18} textAnchor="end">{fmt(row.share)}%</text></g>)}
  </svg>;
}

function InsuranceResult({report,lang,fmt}) {
  const t=(...labels)=>words(lang,...labels);
  const ratios=(report.ratios||[]).filter(r=>['retention','loss_ratio','expense_ratio','combined_ratio','investment_to_premiums'].includes(r.metric_code));
  return <section className="terminal-summary-card"><h3>{t('Показатели страхового результата','Sug‘urta natijasi ko‘rsatkichlari','Insurance result ratios')}</h3>
    <p className="terminal-context">{report.period} · {t('Опубликованный отчёт','E’lon qilingan hisobot','Published filing')}</p>
    <table className="terminal-table"><tbody>{ratios.map(r=><tr key={r.metric_code}><th>{r[`name_${lang}`]||r.name_ru||r.metric_code}</th><td>{fmt(r.value)}{r.value!=null?'%':''}</td></tr>)}</tbody></table>
    <p className="muted">{t('Годовой ряд этих коэффициентов недоступен: в истории нет необходимых страховых строк.','Yillik qator uchun zarur sug‘urta satrlari mavjud emas.','Annual ratio history is unavailable because the necessary insurance lines are missing from the history feed.')}</p>
  </section>;
}

export function StatementOverview({ticker,form,scope,lang,section,fromYear=2020}) {
  const {data:report,error}=useScreenData(`/api/v1/issuers/${encodeURIComponent(ticker)}/ai-report?standard=${form==='MSFO'?'ifrs':'nsbu'}&scope=${scope}&lang=${lang}`,{ticker,form,func:section==='income'?'PL':'BS'});
  const {data:history}=useScreenData(section==='income'?`/api/company/${encodeURIComponent(ticker)}/financials?form=${form}&scope=${scope}`:null,{ticker,form,func:'PL'});
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const fmt=value=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const kind=reportKind(report);
  const label=key=>key==='revenue'&&kind==='insurance'?t('Заработанные премии','Ishlab topilgan mukofotlar','Earned premiums'):LABELS[key]?words(lang,...LABELS[key]):key;
  const facts=statementFacts(report),steps=profitBridge(report,kind),composition=assetComposition(report,kind);
  const amount=(key,previous=false)=>facts[key]?.[previous?'previous':'value']??null;
  const ratio=(n,d,scale=100)=>n!=null&&d!=null&&d>0?n/d*scale:null;
  const bridgeTitle=t('Мост: от доходов к чистой прибыли','Daromaddan sof foydagacha','Bridge: income to net profit');
  const assetTitle=t('Из чего состоят активы','Aktivlar tarkibi','Asset composition');
  const stability=[{label:t('Капитал / активы','Kapital / aktivlar','Equity / assets'),n:'total_equity',d:'total_assets',scale:100,unit:'%'},
    kind==='bank'?{label:t('Кредиты / депозиты','Kreditlar / depozitlar','Loans / deposits'),n:'loan_portfolio',d:'customer_funds',scale:1,unit:'×'}:
    ['insurance','fund','financial'].includes(kind)?{label:t('Деньги / текущие обязательства','Pul / joriy majburiyatlar','Cash / current liabilities'),n:'cash',d:'current_liabilities',scale:100,unit:'%'}:
    {label:t('Обязательства / капитал','Majburiyatlar / kapital','Liabilities / equity'),n:'total_liabilities',d:'total_equity',scale:1,unit:'×'}];
  const factKeys=section==='income'?steps.filter(step=>!step.derived).map(step=>step.key):
    ['total_assets',...composition.rows.filter(row=>!row.derived).map(row=>row.key),'total_liabilities','total_equity'];
  return <section className="terminal-statement-overview">
    <p className="terminal-context">{form} · {scope} · {report?.period||'—'} · {t('млрд UZS','mlrd UZS','UZS billion')}</p>
    {error?<p role="alert">{t('Не удалось загрузить разбор отчёта.','Hisobot tahlili yuklanmadi.','Could not load the report overview.')}</p>:!report?<p role="status">{t('Загрузка…','Yuklanmoqda…','Loading…')}</p>:!['available','stale'].includes(report.status)?<p className="terminal-warning">{report.availability?.reason_text||t('Проверенный разбор пока недоступен. Ниже — опубликованная история.','Tekshirilgan tahlil hali yo‘q. Quyida e’lon qilingan tarix.','Verified report facts are unavailable. Published history is shown below.')}</p>:
      <div className="terminal-summary-charts">{section==='income'?<>
        <section className="terminal-summary-card"><h3>{bridgeTitle}</h3>{steps.some(step=>step.value!=null)?<Waterfall steps={steps} title={bridgeTitle} label={label} fmt={fmt}/>:<p>{t('Нет полного набора применимых строк.','Mos satrlar to‘plami yo‘q.','Applicable statement lines are unavailable.')}</p>}<p className="muted">* {t('Расчётная разница между опубликованными строками. Пропуски не считаются нулём.','E’lon qilingan satrlar orasidagi hisoblangan farq. Bo‘sh qiymatlar nol emas.','Calculated difference between published lines. Missing values are not zero.')}</p></section>
        {kind==='insurance'?<InsuranceResult report={report} lang={lang} fmt={fmt}/>:kind==='fund'?<section className="terminal-summary-card"><h3>{t('Качество прибыли фонда','Fond foydasining sifati','Fund profit quality')}</h3><p>{t('Дивидендный доход и нереализованная переоценка показаны отдельно. Переоценка не означает поступление денежных средств.','Dividend daromadi va realizatsiya qilinmagan qayta baholash alohida ko‘rsatilgan. Qayta baholash pul tushumini anglatmaydi.','Dividend income and unrealised revaluation are shown separately. Revaluation does not represent a cash inflow.')}</p><p>{report.verdict_line}</p></section>:<Margins history={history} kind={kind} form={form} lang={lang} fromYear={fromYear}/>}
      </>:<>
        <section className="terminal-summary-card"><h3>{assetTitle}</h3>{composition.rows.length>0&&<AssetChart composition={composition} title={assetTitle} label={label} fmt={fmt}/>}
          {composition.reason&&<p className="terminal-warning">{t('Состав активов неполон или не согласуется с итогом. Проверьте строки отчёта.','Aktivlar tarkibi to‘liq emas yoki jami bilan mos emas. Hisobotni tekshiring.','Asset components are unavailable or do not reconcile with the total. Check the filing.')}</p>}<p className="muted">{t('* Прочие активы — расчётная разница с итогом активов.','* Boshqa aktivlar — aktivlar jamisi bilan hisoblangan farq.','* Other assets are the calculated residual to total assets.')}</p>
        </section>
        <section className="terminal-summary-card"><h3>{t('Устойчивость','Barqarorlik','Financial stability')}</h3><p className="muted">{t('База сравнения отчёта → конец периода','Hisobot taqqoslash bazasi → davr oxiri','Filing comparison basis → period end')}</p>
          <dl className="terminal-stability-kpis">{stability.map(item=><div key={item.n}><dt>{item.label}</dt><dd>{fmt(ratio(amount(item.n),amount(item.d),item.scale))}{item.unit}</dd><small>{t('Было','Avval','Previously')}: {fmt(ratio(amount(item.n,true),amount(item.d,true),item.scale))}{item.unit}</small></div>)}</dl>
          {report.sections?.filter(s=>s.id==='strength').map(s=><p key={s.id}>{s.text}</p>)}
        </section>
      </>}</div>}
    {factKeys.some(key=>facts[key])&&<div className="terminal-table-wrap"><table className="terminal-table terminal-statement-facts">
      <caption>{report.period} · {form} · {t('млрд UZS','mlrd UZS','UZS billion')}</caption>
      <thead><tr><th>{t('Строка отчёта','Hisobot satri','Filing line')}</th><th>{t('Сейчас','Hozir','Current')}</th><th>{t('База сравнения','Taqqoslash bazasi','Comparison basis')}</th><th>{t('Период базы','Baza davri','Basis period')}</th></tr></thead>
      <tbody>{factKeys.filter(key=>facts[key]).map(key=><tr key={key}><th>{label(key)}</th><td>{amount(key)==null?'—':fmt(amount(key)/1e9)}</td><td>{amount(key,true)==null?'—':fmt(amount(key,true)/1e9)}</td><td>{facts[key].comparison_basis==='opening'?t('Начало периода','Davr boshi','Period opening'):facts[key].comparison_basis==='previous'?t('Сопоставимый период','Mos davr','Comparable prior period'):'—'}</td></tr>)}</tbody>
    </table></div>}
  </section>;
}
