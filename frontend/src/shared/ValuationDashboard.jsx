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
  const rows=Object.entries(models).filter(([,model])=>model.per_share?.value!=null);
  const values=rows.flatMap(([,m])=>[m.per_share.low,m.per_share.high]);
  if(price!=null)values.push(price);
  const min=Math.min(...values)*.9;
  const max=Math.max(...values)*1.1;
  const x=value=>24+(value-min)/(max-min||1)*472;
  const height=rows.length*60+45;
  const label=t('Методы и диапазоны оценки','Baholash usullari va oraliqlari','Valuation methods and ranges');
  return <svg className="terminal-fv-chart" role="img" aria-label={label} viewBox={`0 0 520 ${height}`}>
    <title>{label}</title>
    <desc>{t('Полоса — диапазон, точка — оценка, пунктир — текущая цена. Все значения в UZS на акцию.','Chiziq — oraliq, nuqta — baho, punktir — joriy narx. UZS/aksiya.','Band: range. Dot: estimate. Dashed line: current price. All values in UZS per share.')}</desc>
    {rows.map(([code,m],i)=>{
      const b=m.per_share,y=i*60+36;
      return <g key={code}><text x="24" y={y-20}>{names[code]}</text><text x="496" y={y-20} textAnchor="end" className="terminal-fv-range-label">{fmt(b.low)}–{fmt(b.high)}</text>
        <line x1={x(b.low)} x2={x(b.high)} y1={y} y2={y} className="terminal-fv-band"/>
        <circle cx={x(b.value)} cy={y} r="4" className="terminal-fv-dot"><title>{names[code]}: {fmt(b.value)} UZS/share</title></circle>
      </g>;
    })}
    {price!=null&&<g className="terminal-fv-price"><line x1={x(price)} x2={x(price)} y1="4" y2={height-30}/>
      <text x={x(price)} y={height-10} textAnchor={x(price)>440?'end':x(price)<80?'start':'middle'}>{t('Цена','Narx','Price')} {fmt(price)}</text></g>}
  </svg>;
}

export function ValuationDashboard({result,lang}) {
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const fmt=value=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const names={peers_pb:t('По аналогам · P/B','Analoglar · P/B','Peers · P/B'),peers_pe:t('По аналогам · P/E','Analoglar · P/E','Peers · P/E'),justified_pb:t('Обоснованный P/B','Asoslangan P/B','Justified P/B'),gordon:t('Дивиденды · Гордон','Dividendlar · Gordon','Dividends · Gordon')};
  const {models={},summary={},parameters:p={},inputs={},configuration={}}=result;
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
    <div className="terminal-warning terminal-fv-assumptions">
      {t('Расчёт по модели, не рекомендация.','Model hisobi, tavsiya emas.','Model calculation, not a recommendation.')} {t('Допущения','Farazlar','Assumptions')}: r = {fmt(p.key_rate)}% − {fmt(p.default_spread)}% + {fmt(p.equity_premium)}% = <b>{fmt(result.required_return)}%</b>; g = <b>{fmt(p.growth)}%</b>.
      <small>{configuration.as_of||result.reference_date} · {configuration.version} · {configuration.reference_only?t('Справочный сценарий из ТЗ; актуальные параметры ещё не утверждены.','TZ ma’lumotnoma ssenariysi; joriy parametrlar hali tasdiqlanmagan.','Reference scenario from the specification; current parameters are not yet approved.'):t('Параметры — ADM → Шаблоны.','Parametrlar — ADM → Andozalar.','Parameters — ADM → Templates.')}</small>
    </div>
    <dl className="terminal-fv-kpis">{kpis.map(([label,value,note])=><div key={label}><dt>{label}</dt><dd>{value}</dd><small>{note}</small></div>)}</dl>
    {summary.wide_spread&&<p className="terminal-warning">{t('Методы расходятся более чем в 3 раза. Смотрите каждый метод отдельно.','Usullar uch martadan ko‘p farq qiladi. Har birini alohida ko‘ring.','Methods differ by more than three times. Review each method separately.')}</p>}
    <div className="terminal-fv-detail">
      <section className="terminal-fv-card"><h3>{t('Методы и диапазоны','Usullar va oraliqlar','Methods and ranges')}</h3>
        <p className="muted">{t('Точка — оценка, полоса — диапазон; пунктир — цена.','Nuqta — baho, chiziq — oraliq; punktir — narx.','Dot: estimate. Band: range. Dashed line: price.')} · {unit}</p>
        {summary.method_count>0?<RangeChart models={models} price={result.current_price} names={names} fmt={fmt} t={t}/>:<p className="terminal-fv-empty">{t('Нет применимых методов. Причины указаны в расчётах.','Qo‘llanadigan usul yo‘q. Sabablar hisoblarda keltirilgan.','No applicable methods. See the calculation notes for reasons.')}</p>}
      </section>
      <section className="terminal-fv-card"><h3>{t('Как посчитано','Qanday hisoblangan','How it is calculated')}</h3>
        <div className="terminal-table-wrap"><table className="terminal-table terminal-fv-table"><thead><tr><th>{t('Метод','Usul','Method')}</th><th>{t('Основание','Asos','Basis')}</th><th>{unit}</th></tr></thead><tbody>
          {Object.entries(models).map(([code,m])=><tr key={code}><th scope="row">{names[code]||code}</th><td>{m.per_share?.reason?<span>{reason(m.per_share.reason)}</span>:formula(code,m)}</td><td>{fmt(m.per_share?.value)}</td></tr>)}
        </tbody></table></div>
        <p className="muted">{t('Аналоги: один тип, стандарт, периметр и год. Диапазон — межквартильный; для моделей — r ±1 п.п. с r > g.','Analoglar: bir tur, standart, perimetr va yil. Oraliq — kvartillar; modellar uchun r ±1 f.p., r > g.','Peers share the same type, standard, scope and year. Peer ranges use quartiles; model sensitivity uses r ±1 pp, bounded above g.')}</p>
      </section>
    </div>
  </>;
}
