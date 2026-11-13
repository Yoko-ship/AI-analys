import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import './ratioOverview.css';

const format=(value,lang)=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
const tone=value=>value==null?'is-missing':value<0?'negative':value>0?'positive':'';

function explanation(reason,lang) {
  if(!reason)return words(lang,'Нет квартального показателя в проверенных отчётах.','Tekshirilgan hisobotlarda chorak ko‘rsatkichi yo‘q.','No quarterly figure in verified filings.');
  const periods=[reason.required_period,...(reason.periods||[]),reason.start,reason.end].filter(Boolean).join(', ');
  const messages={
    NON_POSITIVE_BASE:['В периоде сравнения убыток или нулевая прибыль; рост г/г не рассчитывается.','Taqqoslash davrida zarar yoki nol foyda; yillik o‘sish hisoblanmaydi.','The comparison period has a loss or zero profit; YoY growth is undefined.'],
    MISSING_COMPARATIVE_INPUT:['Нет проверенного значения за сопоставимый квартал.','Mos chorak uchun tekshirilgan qiymat yo‘q.','The comparable quarter has no verified value.'],
    MISSING_QUARTERS:['Для LTM нужны четыре последовательных квартала; отсутствуют:','LTM uchun ketma-ket to‘rtta chorak kerak; yetishmaydi:','LTM requires four consecutive quarters; missing:'],
    INCOMPLETE_YEAR:['Доля в году доступна после публикации всех четырёх кварталов.','Yildagi ulush barcha to‘rtta chorak e’lon qilingach mavjud.','Share of year requires all four published quarters.'],
    NON_POSITIVE_YEAR:['Годовая прибыль нулевая или отрицательная.','Yillik foyda nol yoki manfiy.','Annual profit is zero or negative.'],
    NON_POSITIVE_ENDPOINT:['CAGR не рассчитывается при убытке или нулевой прибыли на границах периода.','Davr boshida yoki oxirida zarar yoki nol foyda bo‘lsa, CAGR hisoblanmaydi.','CAGR requires positive profit at both endpoints.'],
    MISSING_ENDPOINT:['Для CAGR нет проверенного значения на границе периода.','CAGR uchun davr chegarasida tekshirilgan qiymat yo‘q.','CAGR has a missing endpoint.'],
  };
  return `${words(lang,...(messages[reason.code]||messages.MISSING_COMPARATIVE_INPUT))}${periods?` ${periods}`:''}`;
}

function QuarterHeatmap({rows,years,lang}) {
  if(!years.length)return null;
  const title=words(lang,'Чистая прибыль · рост г/г, %','Sof foyda · yillik o‘sish, %','Net profit · YoY growth, %');
  return <section className="terminal-ratio-card terminal-heatmap-card">
    <header className="terminal-ratio-card-head">
      <h3>{title}</h3>
      <p className="terminal-ratio-meta">{years[0]}{years.length>1?`–${years.at(-1)}`:''}</p>
    </header>
    <div className="terminal-table-wrap" tabIndex={0} role="region" aria-label={title}>
      <table className="terminal-table terminal-heatmap">
        <caption className="sr-only">{title}</caption>
        <thead><tr><th scope="col">{words(lang,'Год','Yil','Year')}</th>{[1,2,3,4].map(quarter=><th scope="col" key={quarter}>Q{quarter}</th>)}</tr></thead>
        <tbody>{years.map(year=><tr key={year}>
          <th scope="row">{year}</th>
          {[1,2,3,4].map(quarter=>{
            const row=rows.find(row=>row.period===`${year}Q${quarter}`),value=row?.yoy;
            const title=value==null?explanation(row?.metric_reasons?.yoy,lang):`${year}Q${quarter}: ${format(row?.value,lang)} UZS`;
            return <td key={quarter} className={tone(value)}
              style={value==null?undefined:{'--heat-strength':`${10+14*Math.min(Math.abs(value)/100,1)}%`}}
              title={title} aria-label={value==null?`${year}Q${quarter}: ${title}`:undefined}>{format(value,lang)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}

export function QuarterlyMetrics({quarters,lang}) {
  const rows=quarters.rows||[];
  const years=[...new Set(rows.map(row=>row.period.slice(0,4)))].sort();
  const title=words(lang,'Кварталы · чистая прибыль','Choraklar · sof foyda','Quarters · net profit');
  const unit=words(lang,'млрд UZS','mlrd UZS','UZS billion');
  return <div className="terminal-quarterly-overview">
    <QuarterHeatmap rows={rows} years={years} lang={lang}/>
    <section className="terminal-ratio-card terminal-quarterly-card">
      <header className="terminal-ratio-card-head"><h3>{title}</h3><p className="terminal-ratio-meta">{unit}</p></header>
      <p className="terminal-ratio-meta">{words(lang,
        'Убыток или нулевая база: рост г/г и CAGR не рассчитываются. LTM требует 4 квартала, доля в году — полный год. Причина каждого пропуска указана в ячейке.',
        'Zarar yoki nol baza: yillik o‘sish va CAGR hisoblanmaydi. LTM uchun 4 chorak, yildagi ulush uchun to‘liq yil kerak. Har bir bo‘sh katak sababi ko‘rsatilgan.',
        'Loss or zero base: YoY and CAGR are undefined. LTM needs 4 quarters; share of year needs a complete year. Each empty cell explains its reason.')}</p>
      {quarters.reason&&<p className="terminal-warning">{words(lang,
        'Опубликован накопленный итог: его нельзя показывать как отдельный квартал.',
        'Hisobot jamlangan; alohida chorak emas.',
        'Published amounts are cumulative and cannot be shown as standalone quarters.')}</p>}
      <div className="terminal-table-wrap" tabIndex={0} role="region" aria-label={title}>
        <table className="terminal-table terminal-quarter-map">
          <caption className="sr-only">{title}</caption>
          <thead><tr>
            <th scope="col">{words(lang,'Квартал','Chorak','Quarter')}</th><th scope="col">{unit}</th><th scope="col">YoY, %</th>
            <th scope="col">LTM, {unit}</th><th scope="col">{words(lang,'Доля в году, %','Yildagi ulush, %','Share of year, %')}</th><th scope="col">CAGR 3Y, %</th>
          </tr></thead>
          <tbody>{rows.map(row=><tr key={row.period}>
            <th scope="row">{row.period}</th>
            {[row.value==null?null:row.value/1e9,row.yoy,row.ltm==null?null:row.ltm/1e9,row.seasonality,row.cg3].map((value,i)=>{
              const reason=value==null?explanation(row.metric_reasons?.[['value','yoy','ltm','seasonality','cg3'][i]],lang):undefined;
              return <td key={i} title={reason} aria-label={reason}
                className={i===1?tone(value):value==null?'is-missing':undefined}>{format(value,lang)}</td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  </div>;
}
