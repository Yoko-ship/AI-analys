import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {safeHref} from '../../../lib/safeHref.js';
import {summaryKpis} from '../../../lib/terminalSummary.js';
import {useScreenData} from './TerminalPanels.jsx';
import {SummaryHistory} from './SummaryHistory.jsx';
import {BankOverview} from './BankOverview.jsx';
import './summaryScreen.css';

const LABELS={revenue:['Выручка','Tushum','Revenue'],interest_income:['Процентные доходы','Foiz daromadi','Interest income'],
  nav:['Чистые активы / NAV','Sof aktivlar / NAV','Net assets / NAV'],nav_per_share:['NAV на акцию','Bir aksiya uchun NAV','NAV per share'],price_to_nav:['Цена / NAV','Narx / NAV','Price / NAV'],premium_to_nav:['Премия / дисконт к NAV','NAVga ustama / chegirma','Premium / discount to NAV'],portfolio_to_assets:['Портфель / активы','Portfel / aktivlar','Portfolio / assets'],
  net_profit:['Чистая прибыль','Sof foyda','Net profit'],assets:['Активы','Aktivlar','Assets'],equity:['Капитал / NAV','Kapital / NAV','Equity / NAV'],
  gross_margin:['Валовая маржа','Yalpi marja','Gross margin'],net_margin:['Чистая маржа','Sof marja','Net margin'],
  earned_premiums:['Заработанные премии','Ishlab topilgan mukofotlar','Earned premiums'],combined_ratio:['Комбинированный коэффициент','Kombinatsiyalangan koeffitsient','Combined ratio'],loss_ratio:['Убыточность','Zararlilik','Loss ratio'],
  roe:['ROE · годовая','ROE · yillik','ROE · annualised'],roa:['ROA · годовая','ROA · yillik','ROA · annualised'],
  equity_to_assets:['Капитал / активы','Kapital / aktivlar','Equity / assets'],loans_to_deposits:['Кредиты / депозиты','Kreditlar / depozitlar','Loans / deposits']};

export function SummaryScreen({ticker,form,scope,lang,snapshot={},fromYear=2020,bankData,bankHistory}) {
  const {data:report,error}=useScreenData(`/api/v1/issuers/${encodeURIComponent(ticker)}/ai-report?standard=${form==='MSFO'?'ifrs':'nsbu'}&scope=${scope}&lang=${lang}`,{ticker,form,func:'SUM'});
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const fmt=n=>n==null?'—':Number(n).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const kpis=summaryKpis(report,snapshot);
  const available=['available','stale'].includes(report?.status);
  return <section className="terminal-summary">
    <dl className="terminal-summary-kpis">{kpis.cards.map(card=><div key={card.key}>
      <dt>{words(lang,...LABELS[card.key])}</dt><dd>{fmt(card.unit==='UZS'&&card.value!=null?card.value/1e9:card.value)}{card.value!=null&&card.unit==='%'?'%':''}</dd>
      <small>{card.period||'—'} · {card.unit==='UZS'?t('млрд UZS','mlrd UZS','UZS billion'):card.unit==='ratio'?'×':card.unit==='UZS/share'?t('UZS/акция','UZS/aksiya','UZS/share'):card.unit}</small>
    </div>)}</dl>
    {kpis.kind==='fund'&&report?.valuation?.blocked_reason&&<p className="terminal-warning">{report.valuation.blocked_reason==='SHARE_BASIS_NOT_RECONCILED'?t('Нужна сверка количества и номинала акций. NAV на акцию и цена/NAV недоступны.','Aksiyalar soni va nominalini tekshirish kerak. Bir aksiya NAVi va narx/NAV mavjud emas.','Share count and nominal value must be reconciled. NAV per share and price/NAV are unavailable.'):t('Цена/NAV недоступна: нет подходящей проверенной котировки на дату оценки.','Narx/NAV mavjud emas: baholash sanasiga mos tekshirilgan narx yo‘q.','Price/NAV is unavailable: no suitable verified quote for the valuation date.')}</p>}
    <div className="terminal-summary-narrative">
      <section className="terminal-summary-card"><h3>{t('Вывод','Xulosa','Conclusion')}</h3>
        <p className="terminal-context">{t('Последний разобранный отчёт','Oxirgi tahlil qilingan hisobot','Latest analysed filing')}: {report?.period||'—'} · {form} · {scope}</p>
        {error?<p role="alert">{t('Не удалось загрузить анализ.','Tahlil yuklanmadi.','Could not load the analysis.')}</p>:!report?<p role="status">{t('Загрузка анализа…','Tahlil yuklanmoqda…','Loading analysis…')}</p>:
          available?<><p className="terminal-summary-headline">{report.headline}</p><p className={`terminal-verdict ${report.verdict?.code||''}`}>{report.verdict_line}</p>
            {(report.sections||[]).filter(s=>['key_points','results','strength'].includes(s.id)).map(s=><p key={s.id}><strong>{s.title}. </strong>{s.text}</p>)}</>:
            <p className="terminal-warning">{report.availability?.reason_text||t('Проверенный анализ пока недоступен. Карточки показывают последний годовой отчёт.','Tekshirilgan tahlil hozircha yo‘q. Kartalar oxirgi yillik hisobotni ko‘rsatadi.','Verified analysis is unavailable. Cards show the latest annual filing.')}</p>}
        {(report?.sources||[]).filter(source=>source.url).map((source,i)=><a key={i} href={safeHref(source.url)} target="_blank" rel="noreferrer">{t('Источник отчёта','Hisobot manbasi','Filing source')} ↗ </a>)}
      </section>
      <section className="terminal-summary-card"><h3>{t('Риски и что смотреть','Xatarlar va kuzatuv','Risks and monitoring')}</h3>
        {available?(report.risks?.length?report.risks.map((risk,i)=><div className="terminal-risk" key={risk.code||i}><span className={`terminal-risk-level ${risk.severity}`}>{risk.severity==='high'?t('высокий','yuqori','high'):risk.severity==='medium'?t('средний','o‘rta','medium'):t('низкий','past','low')}</span><div><strong>{risk.title||risk.text||risk.message||risk.code}</strong><p>{risk.consequence||risk.description}</p></div></div>):<p className="muted">{t('Риски не отмечены в анализе.','Tahlilda xatarlar qayd etilmagan.','No risks flagged by the analysis.')}</p>):<p className="muted">{t('Нет проверенного анализа рисков.','Tekshirilgan xatar tahlili yo‘q.','Verified risk analysis is unavailable.')}</p>}
        {available&&report.monitoring_points?.length>0&&<><h4>{t('Контрольные точки','Kuzatuv nuqtalari','Monitoring points')}</h4>{report.monitoring_points.map((point,i)=><p key={point.id||i}><strong>{point.label||point.metric_code}</strong><br/>{point.risk_signal||point.required_disclosure}</p>)}</>}
      </section>
    </div>
    <SummaryHistory ticker={ticker} form={form} scope={scope} lang={lang} kind={kpis.kind} fromYear={fromYear}/>
    {kpis.kind==='bank'&&<BankOverview data={bankData} history={bankHistory} lang={lang}/>}
  </section>;
}
