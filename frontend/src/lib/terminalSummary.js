const finite=value=>value==null||value===''||typeof value==='boolean'?null:Number.isFinite(Number(value))?Number(value):null;
const divide=(a,b,scale=100)=>a!=null&&b!=null&&b>0?a/b*scale:null;

export function reportKind(report,fallback) {
  const raw=report?.issuer?.organization_type||report?.sector_template_code||fallback;
  return ['investment_fund','investment_fund_ifrs_annual'].includes(raw)?'fund':raw==='non_financial'?'industry':raw;
}

export function factUzs(fact,period) {
  if(!fact||(fact.period&&fact.period!==period)||(fact.verification_status&&fact.verification_status!=='verified'))return null;
  const unit=String(fact.unit_normalized||fact.unit||'').toLowerCase();
  const scale={'uzs':1,'thousand uzs':1000,'million uzs':1e6,'billion uzs':1e9}[unit];
  const value=finite(fact.current??fact.value);
  return scale&&value!=null?value*scale:null;
}

// Canonical ROE comes from the shared calculation engine, never a similarly
// named statutory P1/P2 ratio. Money and ratios always share one report period.
export function summaryKpis(report,snapshot={}) {
  const hasReport=['available','stale'].includes(report?.status)&&Array.isArray(report.verified_facts);
  const period=hasReport?report.period:snapshot.period;
  const kind=reportKind(hasReport?report:null,snapshot.kind);
  const facts=Object.fromEntries((report?.verified_facts||[]).map(f=>[f.metric_code||f.metric,factUzs(f,period)]));
  const ratios=Object.fromEntries((report?.ratios||[]).map(r=>[r.metric_code,finite(r.value??r.raw_result)]));
  const v=hasReport?{revenue:facts.revenue??null,interest_income:facts.interest_income??null,
    net_profit:facts.net_income??null,assets:facts.total_assets??null,equity:facts.total_equity??null,
    roe:ratios.roe??null,roa:ratios.roa??null,earned_premiums:facts.revenue??null,
    combined_ratio:ratios.combined_ratio??null,loss_ratio:ratios.loss_ratio??null,
    equity_to_assets:divide(facts.total_equity,facts.total_assets),
    gross_margin:divide(facts.gross_profit,facts.revenue),net_margin:divide(facts.net_income,facts.revenue),
    loans_to_deposits:ratios.loans_to_deposits??null,
    nav:finite(report.nav?.value_mln_uzs)==null?facts.total_equity:finite(report.nav.value_mln_uzs)*1e6,
    nav_per_share:finite(report.nav?.per_exchange_share_uzs),price_to_nav:finite(report.valuation?.price_to_nav),
    premium_to_nav:finite(report.valuation?.premium_to_nav_pct),portfolio_to_assets:finite(report.portfolio?.portfolio_to_assets_pct)}:
    {...snapshot,nav:snapshot.equity,earned_premiums:snapshot.revenue,equity_to_assets:divide(snapshot.equity,snapshot.assets),net_margin:divide(snapshot.net_profit,snapshot.revenue)};
  const keys=kind==='bank'?['interest_income','net_profit','assets','equity_to_assets','roe','loans_to_deposits']:
    kind==='insurance'?['earned_premiums','net_profit','combined_ratio','loss_ratio','roe','equity_to_assets']:
    kind==='fund'?['nav','nav_per_share','price_to_nav','premium_to_nav','net_profit','portfolio_to_assets']:
    ['revenue','net_profit','gross_margin','net_margin','roe','equity_to_assets'];
  return {period,kind,basis:hasReport?'report':'annual',cards:keys.map(key=>({key,value:finite(v[key]),
    period:['price_to_nav','premium_to_nav'].includes(key)?report?.market_as_of:period,
    unit:['revenue','interest_income','net_profit','assets','equity','earned_premiums','nav'].includes(key)?'UZS':key==='nav_per_share'?'UZS/share':['loans_to_deposits','price_to_nav'].includes(key)?'ratio':'%'}))};
}

export const HISTORY_FIELDS=['net_revenue','interest_income','net_profit','total_assets','total_equity','total_liabilities'];

export function historyRows(data,fromYear=2020,quarterly=null) {
  const periods=(data?.periods||[]).map(String).filter(p=>/^\d{4}$/.test(p)&&Number(p)>=fromYear).sort();
  const rows=[];
  for(let year=Number(periods[0]);periods.length&&year<=Number(periods.at(-1));year++){
    const period=String(year),row={period,published:periods.includes(period)};
    for(const field of HISTORY_FIELDS){
      row[field]=row.published?finite(data.series?.[field]?.values?.[period]):null;
    }
    row.balance_complete=row.total_liabilities!=null&&row.total_equity!=null;
    rows.push(row);
  }
  if(!quarterly||(data?.standard&&quarterly.standard!==data.standard)||(data?.scope&&quarterly.scope&&quarterly.scope!==data.scope))return rows;
  const latest=(quarterly.periods||[]).filter(p=>/^\d{4}Q[1-4]$/.test(p)&&Number(p.slice(0,4))>=fromYear).sort().at(-1);
  if(!latest||(periods.length&&latest.slice(0,4)<=periods.at(-1)))return rows;
  const year=latest.slice(0,4),quarter=Number(latest.at(-1));
  const current={period:latest,label:`${year} · ${quarter*3}M`,published:true,current:true};
  for(const field of HISTORY_FIELDS){
    const values=quarterly.series?.[field]?.values||{};
    if(field.startsWith('total_')||quarterly.period_basis==='cumulative_ytd')current[field]=finite(values[latest]);
    else if(quarterly.standard==='NSBU'){
      const parts=Array.from({length:quarter},(_,i)=>finite(values[`${year}Q${i+1}`]));
      current[field]=parts.every(value=>value!=null)?parts.reduce((sum,value)=>sum+value,0):null;
    }else current[field]=null;
  }
  current.balance_complete=current.total_liabilities!=null&&current.total_equity!=null;
  rows.push(current);
  return rows;
}
