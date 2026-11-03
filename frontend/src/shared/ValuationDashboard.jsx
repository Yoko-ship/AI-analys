import React from 'react';
import { words } from './TerminalTables.jsx';
import './terminalValuation.css';

const REASONS = {
  INSUFFICIENT_PEERS:['Менее трёх сопоставимых эмитентов','Taqqoslanadigan emitentlar uchtadan kam','Fewer than three comparable issuers'],
  NON_POSITIVE_DENOMINATOR:['Прибыль или капитал отсутствуют либо неположительны','Foyda yoki kapital yo‘q yoki musbat emas','Profit or equity is missing or non-positive'],
  ROE_BELOW_PEERS:['ROE ниже половины медианы аналогов','ROE analoglar medianasining yarmidan past','ROE is below half the peer median'],
  NOT_A_BANK:['Метод применяется только к банкам','Usul faqat banklar uchun','This method applies only to banks'],
  RETURN_NOT_ABOVE_GROWTH:['Требуемая доходность r должна быть выше роста g','Talab etilgan r daromadi g o‘sishidan yuqori bo‘lishi kerak','Required return r must exceed growth g'],
  ROE_UNAVAILABLE:['Нет данных для ROE','ROE uchun ma’lumot yo‘q','ROE is unavailable'],
  ROE_BELOW_GROWTH:['ROE ниже роста g — модель неприменима','ROE g o‘sishidan past — model qo‘llanmaydi','ROE is below growth g — model not applicable'],
  RECENT_DIVIDEND_UNAVAILABLE:['Нет недавнего дивиденда по обычной акции','Oddiy aksiya uchun yaqinda dividend yo‘q','No recent ordinary dividend'],
  MARKET_BASIS_UNAVAILABLE:['Нет проверенной цены или капитализации для расчёта на акцию','Aksiya hisobiga tekshirilgan narx yoki kapitalizatsiya yo‘q','A checked price or capitalisation is unavailable for the per-share calculation'],
  SOURCE_QUALITY:['Данные не прошли проверку качества','Ma’lumotlar sifat tekshiruvidan o‘tmagan','Source data did not pass quality checks'],
};

function RangeChart({models,price,names,fmt,t}) {
  const descriptionId=React.useId();
  const rows=Object.entries(models).filter(([,model])=>Number.isFinite(model.per_share?.value));
  const values=rows.flatMap(([,m])=>[m.per_share.low,m.per_share.value,m.per_share.high]).filter(Number.isFinite);
  const hasPrice=Number.isFinite(price);
  if(hasPrice)values.push(price);
  const low=Math.min(...values),high=Math.max(...values);
  const padding=Math.max((high-low)*.08,Math.abs(high)*.01,1);
  const min=low-padding,max=high+padding;
  const x=value=>`${(value-min)/(max-min)*100}%`;
  const label=t('Методы и диапазоны оценки','Baholash usullari va oraliqlari','Valuation methods and ranges');
  const rangeLabel=t('Диапазон','Oraliq','Range');
  const priceLabel=t('Текущая цена','Joriy narx','Current price');
  return <div className="terminal-fv-chart" role="img" aria-label={label} aria-describedby={descriptionId}>
    <span className="sr-only" id={descriptionId}>{rows.map(([code,{per_share:b}])=>`${names[code]}: ${fmt(b.value)}; ${rangeLabel}: ${fmt(b.low)}–${fmt(b.high)}.`).join(' ')} {hasPrice?`${priceLabel}: ${fmt(price)}.`:''} UZS/share.</span>
    <div className="terminal-fv-legend" aria-hidden="true">
      <span><i className="terminal-fv-key-dot"/>{t('Оценка','Baho','Estimate')}</span>
      <span><i className="terminal-fv-key-band"/>{rangeLabel}</span>
      {hasPrice&&<span><i className="terminal-fv-key-price"/>{t('Цена','Narx','Price')}</span>}
    </div>
    {rows.map(([code,{per_share:b}])=><div className="terminal-fv-chart-row" key={code} aria-hidden="true">
      <div className="terminal-fv-row-head"><span className="terminal-fv-method-name">{names[code]||code}</span><strong className="terminal-fv-estimate">{fmt(b.value)}</strong></div>
      <div className="terminal-fv-track">
        <span className="terminal-fv-track-base"/>
        {hasPrice&&<span className="terminal-fv-price-line" style={{left:x(price)}}/>}
        <span className="terminal-fv-band" style={{left:x(b.low??b.value),width:`${((b.high??b.value)-(b.low??b.value))/(max-min)*100}%`}}/>
        <span className="terminal-fv-dot" style={{left:x(b.value)}}/>
      </div>
      <div className="terminal-fv-range-label">{rangeLabel}<span>{fmt(b.low)} – {fmt(b.high)}</span></div>
    </div>)}
    {hasPrice&&<div className="terminal-fv-price-label" aria-hidden="true"><span><i className="terminal-fv-key-price"/>{priceLabel}</span><strong>{fmt(price)}</strong></div>}
  </div>;
}

export function ValuationDashboard({result,lang}) {
  const headingId=React.useId();
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const fmt=value=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const names={peers_pb:t('По аналогам · P/B','Analoglar · P/B','Peers · P/B'),peers_pe:t('По аналогам · P/E','Analoglar · P/E','Peers · P/E'),justified_pb:t('Обоснованный P/B','Asoslangan P/B','Justified P/B'),gordon:t('Дивиденды · Гордон','Dividendlar · Gordon','Dividends · Gordon')};
  const {models={},summary={},parameters:p={},inputs={}}=result;
  const reason=code=>words(lang,...(REASONS[code]||['Метод недоступен','Usul mavjud emas','Method unavailable']));
  const unit=t('UZS на акцию','UZS/aksiya','UZS/share');
  const range=summary.value==null?'—':`${fmt(summary.low)} – ${fmt(summary.high)}`;
  const comparison=summary.price_to_value_pct;
  const comparisonNote=comparison==null?'—':comparison>100?t('Цена выше оценки','Narx bahodan yuqori','Price above estimate'):comparison<100?t('Цена ниже оценки','Narx bahodan past','Price below estimate'):t('Цена равна оценке','Narx bahoga teng','Price equals estimate');
  const kpis=[
    [t('Цена','Narx','Price'),fmt(result.current_price),result.market_date||t('Дата недоступна','Sana yo‘q','Date unavailable')],
    [t('Оценка · медиана методов','Baho · usullar medianasi','Estimate · method median'),fmt(summary.value),unit],
    [t('Диапазон','Oraliq','Range'),range,summary.method_count>1?t('Между методами','Usullar orasida','Across methods'):t('Чувствительность метода','Usul sezgirligi','Method sensitivity')],
    [t('Цена к оценке','Narx / baho','Price / valuation'),comparison==null?'—':`${fmt(comparison)}%`,comparisonNote],
    ['r',`${fmt(result.required_return)}%`,t('Требуемая доходность','Talab etilgan daromad','Required return')],
    ['g',`${fmt(p.growth)}%`,t('Долгосрочный рост','Uzoq muddatli o‘sish','Long-term growth')],
  ];
  const formula=(code,m)=>{
    if(code==='peers_pb'||code==='peers_pe')return `${t('Медиана','Mediana','Median')} ${code==='peers_pb'?'P/B':'P/E'} ${fmt(m.multiple)} (${m.peer_count}) × ${t(code==='peers_pb'?'капитал на акцию':'прибыль на акцию',code==='peers_pb'?'aksiya hisobiga kapital':'aksiya hisobiga foyda',code==='peers_pb'?'equity per share':'earnings per share')}`;
    if(code==='justified_pb')return `(ROE ${fmt(inputs.roe)}% − g ${fmt(p.growth)}%) / (r ${fmt(result.required_return)}% − g) × ${t('капитал на акцию','aksiya hisobiga kapital','equity per share')}`;
    return `${t('Дивиденд','Dividend','Dividend')} ${fmt(inputs.dividend)} × (1 + g) / (r − g)`;
  };
  return <>
    <p className="terminal-context">{result.ticker} · {result.period||'—'} · {result.standard} · {result.scope==='consolidated'?t('консолидированная','konsolidatsiyalangan','consolidated'):t('отдельная','alohida','separate')}</p>
    <dl className="terminal-fv-kpis">{kpis.map(([label,value,note])=><div key={label}><dt>{label}</dt><dd>{value}</dd><small>{note}</small></div>)}</dl>
    {summary.wide_spread&&<p className="terminal-warning">{t('Методы расходятся более чем в 3 раза. Смотрите каждый метод отдельно.','Usullar uch martadan ko‘p farq qiladi. Har birini alohida ko‘ring.','Methods differ by more than three times. Review each method separately.')}</p>}
    <div className="terminal-fv-detail">
      <section className="terminal-fv-card" aria-labelledby={`${headingId}-ranges`}>
        <header className="terminal-fv-card-head"><h3 id={`${headingId}-ranges`}>{t('Методы и диапазоны','Usullar va oraliqlar','Methods and ranges')}</h3><p>{unit}</p></header>
        {summary.method_count>0?<RangeChart models={models} price={result.current_price} names={names} fmt={fmt} t={t}/>:<p className="terminal-fv-empty">{t('Нет применимых методов. Причины указаны в расчётах.','Qo‘llanadigan usul yo‘q. Sabablar hisoblarda keltirilgan.','No applicable methods. See the calculation notes for reasons.')}</p>}
      </section>
      <section className="terminal-fv-card terminal-fv-calculation" aria-labelledby={`${headingId}-calculation`}>
        <header className="terminal-fv-card-head"><h3 id={`${headingId}-calculation`}>{t('Как посчитано','Qanday hisoblangan','How it is calculated')}</h3><p>{unit}</p></header>
        <div className="terminal-table-wrap"><table className="terminal-table terminal-fv-table" aria-labelledby={`${headingId}-calculation`}><thead><tr><th scope="col">{t('Метод','Usul','Method')}</th><th scope="col">{t('Основание','Asos','Basis')}</th><th scope="col">{unit}</th></tr></thead><tbody>
          {Object.entries(models).map(([code,m])=><tr key={code} className={m.per_share?.value==null?'is-unavailable':undefined}><th scope="row">{names[code]||code}</th><td>{m.per_share?.reason?<span>{reason(m.per_share.reason)}</span>:formula(code,m)}</td><td>{fmt(m.per_share?.value)}</td></tr>)}
        </tbody></table></div>
        <p className="terminal-fv-note">{t('Аналоги: один тип, стандарт, периметр и год. Диапазон — межквартильный; для моделей — r ±1 п.п. с r > g.','Analoglar: bir tur, standart, perimetr va yil. Oraliq — kvartillar; modellar uchun r ±1 f.p., r > g.','Peers share the same type, standard, scope and year. Peer ranges use quartiles; model sensitivity uses r ±1 pp, bounded above g.')}</p>
      </section>
    </div>
  </>;
}
