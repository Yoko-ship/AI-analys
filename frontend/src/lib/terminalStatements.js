import {factUzs} from './terminalSummary.js';

export function statementFacts(report) {
  if(!['available','stale'].includes(report?.status))return {};
  return Object.fromEntries((report.verified_facts||[]).map(fact=>[fact.metric_code||fact.metric,{
    ...fact,value:factUzs(fact,report.period),
    previous:factUzs({...fact,current:fact.previous,value:fact.previous},report.period),
  }]));
}

export function profitBridge(report,kind) {
  const facts=statementFacts(report);
  const value=key=>facts[key]?.value??null;
  const expense=key=>value(key)==null?null:-Math.abs(value(key));
  const total=key=>({key,value:value(key),total:true});
  const cost=key=>({key,value:expense(key)});
  const residual=(key,end,parts)=>({key,derived:true,value:end==null||parts.some(v=>v==null)?null:end-parts.reduce((a,b)=>a+b,0)});
  const tax=residual('tax_and_other',value('net_income'),[value('profit_before_tax')]);
  if(kind==='bank')return [total('interest_income'),cost(facts.interest_expenses?'interest_expenses':'interest_expense'),
    total('net_interest_income_before_provisions'),cost('credit_loss_provisions'),{key:'noninterest_income',value:value('noninterest_income')},cost('noninterest_expenses'),cost('operating_expenses'),
    residual('other_pretax',value('profit_before_tax'),[value('net_interest_income_before_provisions'),expense('credit_loss_provisions'),value('noninterest_income'),expense('noninterest_expenses'),expense('operating_expenses')]),
    total('profit_before_tax'),tax,total('net_income')];
  if(kind==='insurance')return [total('revenue'),cost('insurance_service_cost'),total('insurance_service_result'),cost('expenses'),
    residual('other_operating',value('operating_income'),[value('insurance_service_result'),expense('expenses')]),total('operating_income'),
    {key:'financial_income',value:value('financial_income')},cost('financial_expenses'),
    residual('other_pretax',value('profit_before_tax'),[value('operating_income'),value('financial_income'),expense('financial_expenses')]),
    total('profit_before_tax'),tax,total('net_income')];
  if(kind==='fund')return [total('dividend_income'),{key:'unrealized_fair_value_gain',value:value('unrealized_fair_value_gain')},cost('management_expenses'),
    residual('other_fund_result',value('net_income'),[value('dividend_income'),value('unrealized_fair_value_gain'),expense('management_expenses'),expense('tax')]),cost('tax'),total('net_income')];
  if(kind==='financial')return [];
  return [total('revenue'),cost('cost_of_sales'),total('gross_profit'),cost('period_expenses'),
    residual('other_operating',value('operating_income'),[value('gross_profit'),expense('period_expenses')]),total('operating_income'),
    {key:'financial_income',value:value('financial_income')},cost('financial_expenses'),
    residual('other_pretax',value('profit_before_tax'),[value('operating_income'),value('financial_income'),expense('financial_expenses')]),
    total('profit_before_tax'),tax,total('net_income')];
}

export function assetComposition(report,kind) {
  const facts=statementFacts(report),total=facts.total_assets?.value;
  if(total==null||total<=0)return {rows:[],reason:'ASSETS_UNAVAILABLE'};
  const parts=kind==='bank'?['loan_portfolio','due_from_banks','central_bank_balances','cash']:
    kind==='fund'?['portfolio_fair_value','dividends_receivable','cash']:
    ['fixed_assets','receivables','long_term_investments','inventories','construction_in_progress','short_term_investments','cash'];
  const rows=parts.filter(key=>facts[key]?.value!=null).map(key=>({key,value:facts[key].value,share:facts[key].value/total*100}));
  if(!rows.length)return {rows:[],reason:'COMPONENTS_UNAVAILABLE'};
  const sum=rows.reduce((value,row)=>value+row.value,0);
  if(rows.some(row=>row.value<0))return {rows,reason:'NEGATIVE_COMPONENT'};
  if(sum>total)return {rows,reason:'COMPONENTS_EXCEED_ASSETS'};
  if(sum<total)rows.push({key:'other',value:total-sum,share:(total-sum)/total*100,derived:true});
  return {rows,reason:null};
}
