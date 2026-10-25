"""Investor statement vocabulary over approved, source-preserving IFRS cells.

The HTML reference is a design, not a source of financial observations. Keep
undisclosed fields visible and never infer their values from its demo ratios.
"""
import json
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
from datetime import date, timedelta

from .presentation import template_for
from .matrix import choose
from .periods import CONTEXT

FIELDS = json.loads(Path(__file__).with_name('investor_fields.json').read_text(encoding='utf-8'))
METRICS = {
    'revenue':'revenue', 'cogs':'cost_of_sales', 'grossProfit':'gross_profit',
    'salesExpense':'selling_expense', 'adminExpense':'admin_expense',
    'researchExpense':'research_expense', 'otherIncome':'other_operating_income',
    'otherExpense':'other_operating_expense', 'op':'operating_income',
    'depreciation':'depreciation_amortization', 'ebitda':'ebitda',
    'financeIncome':'finance_income', 'financeExpense':'finance_cost',
    'associates':'share_of_profit_associates', 'pretax':'profit_before_tax',
    'tax':'income_tax', 'profit':'net_income', 'owners':'profit_owners',
    'oci':'oci', 'totalIncome':'comprehensive_income',
    'interestRevenue':'interest_income', 'interestExpense':'interest_expense',
    'netInterest':'net_interest_before_ecl', 'feeIncome':'fee_income',
    'feeExpense':'fee_expense', 'netFee':'net_fee_income',
    'otherBankIncome':'other_operating_income', 'bankOperatingIncome':'operating_income_before_ecl',
    'personnel':'staff_costs', 'otherOperating':'other_operating_expense',
    'operatingProfitPreECL':'operating_profit_before_ecl', 'ecl':'credit_loss_expense',
    'insRevenue':'insurance_revenue', 'insServiceExpense':'insurance_service_expense',
    'reinsurance':'reinsurance_result', 'insServiceResult':'insurance_service_result',
    'investmentReturn':'investment_income', 'insFinance':'insurance_finance_expense',
    'investmentIncome':'investment_income', 'revaluation':'fair_value_gain_loss',
    'fundExpenses':'fund_expenses', 'ppe':'ppe', 'intangibles':'intangibles_goodwill',
    'longInvest':'long_term_financial_other_assets', 'noncurrentAssets':'noncurrent_assets',
    'inventory':'inventory', 'receivables':'trade_other_receivables', 'cash':'cash',
    'currentOther':'other_current_assets', 'currentAssets':'current_assets', 'assets':'total_assets',
    'issuedShareCapital':'share_capital', 'reserves':'other_reserves',
    'retainedEarnings':'retained_earnings', 'equity':'total_equity',
    'debtLong':'borrowings_long', 'debtShort':'borrowings_short',
    'noncurrentLiabilities':'noncurrent_liabilities', 'currentLiabilities':'current_liabilities',
    'liabilities':'total_liabilities', 'equityLiabilities':'total_equity_liabilities',
    'bankPlacement':'central_bank_and_bank_placements', 'loans':'loans_gross',
    'bankSecurities':'debt_equity_investments', 'bankOtherAssets':'other_assets',
    'customerDeposits':'customer_funds', 'bankInterbankLiab':'bank_funding',
    'borrowing':'interest_bearing_debt', 'bankOtherLiab':'other_liabilities',
    'insuranceInvest':'insurance_financial_investments', 'reinsAssets':'reinsurance_contract_assets',
    'insuranceRec':'trade_other_receivables', 'insOtherAssets':'other_assets',
    'insuranceLiab':'insurance_contract_liabilities', 'insOtherLiab':'other_liabilities',
    'inLeases':'net_lease_investment', 'leaseOtherAssets':'other_assets',
    'leaseOtherLiab':'other_liabilities', 'fundInvestments':'investment_portfolio',
    'fundOtherAssets':'other_assets', 'nav':'nav', 'cfo':'cfo', 'capex':'capex',
    'otherInvest':'other_investing_cash_flows', 'cfi':'cfi', 'cff':'cff',
    'changeCash':'delta_cash', 'cashStart':'cash_begin', 'cashEnd':'cash_end',
    'equityOpen':'equity_open', 'dividends':'dividends_declared',
    'newShares':'share_issuance', 'otherEquity':'other_equity_changes',
}
FORM = {'pl':'PL', 'bs':'BS', 'cf':'CF', 'equity':'Equity'}


def enrich(observations):
    """Only explicit, complete arithmetic; never approximate a missing item."""
    from .ifrs import metric
    # Older approved imports retain unmapped source lines. Resolve only exact
    # aliases, preserving their value, dates, review status and provenance.
    observations=[{**r,'metric_id':metric(r.get('raw_label',''),r.get('source_form'))}
                  if r.get('standard')=='MSFO' and not r.get('metric_id') else r for r in observations]
    result=list(observations)
    groups=defaultdict(list)
    for row in observations:
        if row.get('standard')=='MSFO':
            groups[tuple(row.get(k) for k in (*CONTEXT,'source_version','period_start','period_end','kind'))].append(row)
    for rows in groups.values():
        def add(metric, label, terms, *, signed_expenses=(), addbacks=()):
            if any(r.get('metric_id')==metric for r in rows):
                return
            parts=[choose([r for r in rows if r.get('metric_id')==field]) for field,_ in terms]
            if any(p.get('value') is None or p.get('quality') not in {'valid','warn'} for p in parts):
                return
            if any(Decimal(p['value'])>0 for p in parts if p.get('metric_id') in signed_expenses):
                return
            if any(Decimal(p['value'])<0 for p in parts if p.get('metric_id') in addbacks):
                return
            if len({p.get('unit') for p in parts})!=1:
                return
            result.append({**parts[0],'metric_id':metric,'raw_label':label,'source_form':'DERIVED',
                           'source_code':None,'raw_value':None,'origin':'UZStock_calculated',
                           'value':str(sum(Decimal(p['value'])*factor for p,(_,factor) in zip(parts,terms))),
                           'formula':' + '.join(f'{factor} × {field}' for field,factor in terms),
                           'components':parts,'quality':'warn' if any(p['quality']=='warn' for p in parts) else 'valid'})
        add('net_interest_before_ecl','Чистый процентный доход',[('interest_income',1),('interest_expense',1)],signed_expenses=('interest_expense',))
        add('net_fee_income','Чистый комиссионный доход',[('fee_income',1),('fee_expense',1)],signed_expenses=('fee_expense',))
        add('gross_profit','Валовая прибыль',[('revenue',1),('cost_of_sales',1)],signed_expenses=('cost_of_sales',))
        add('ebitda','EBITDA (расчётная)',[('operating_income',1),('depreciation_amortization',1)],addbacks=('depreciation_amortization',))
        add('comprehensive_income','Общий совокупный доход',[('net_income',1),('oci',1)])
        add('total_equity_liabilities','Капитал и обязательства',[('total_equity',1),('total_liabilities',1)])
        add('nav','Стоимость чистых активов',[('total_assets',1),('total_liabilities',-1)])
        add('capex','Покупка основных средств и НМА',[('purchase_ppe',1),('purchase_intangibles',1)],signed_expenses=('purchase_ppe','purchase_intangibles'))
        add('delta_cash','Изменение денег от потоков',[('cfo',1),('cfi',1),('cff',1)])
    return result


def missing(reason='SOURCE_VALUE_MISSING'):
    return {'value':None, 'quality':'missing', 'reason':reason}


def field_cells(payload, field, statement, observations=()):
    metric = METRICS[field]
    if field in {'cashStart','equityOpen'}:
        cells={}
        for column in payload['columns']:
            end=date.fromisoformat(column['end'])
            start=date(end.year,((end.month-1)//3)*3+1,1) if column['basis']=='quarter' else date(end.year,1,1)
            candidates=[r for r in observations if r.get('metric_id')==metric and r.get('kind')=='stock'
                        and r.get('statement_period_end')==column['end'] and r['period_end']<column['end']
                        and (column['basis']=='annual' or r['period_end']==(start-timedelta(days=1)).isoformat())]
            cells[column['key']] = ({'value':None,'quality':'not_applicable','reason':'STOCK_IS_AS_OF_DATE'}
                                    if column['basis']=='ttm' else choose(candidates))
        return cells
    # An annotation can reference PL, but cash/equity movements require their
    # own statement. Do not replace CF cash at year start with year-end BS cash.
    form = FORM[statement]
    if statement in {'cf','equity'} and field in {'profit','depreciation','oci','totalIncome'}:
        form = 'PL'
    if statement == 'equity' and field == 'equity':
        form = 'BS'
    candidates = [r for r in payload['rows'] if r['metric_id'] == metric and r['source_form'] in {form,'DERIVED'}]
    cells = {}
    for column in payload['columns']:
        parts = [r['cells'][column['key']] for r in candidates]
        if len(parts) == 1:
            cells[column['key']] = parts[0]
        elif parts and len({(p.get('value'), p.get('quality'), p.get('unit'), p.get('scope')) for p in parts}) > 1:
            cells[column['key']] = {'value':None,'quality':'blocked','reason':'CONFLICTING_SOURCE_VALUES','components':parts}
        else:
            cells[column['key']] = parts[0] if parts else missing()
    return cells


def project(payload, observations=()):
    if payload['standard'] != 'MSFO':
        raise ValueError('Investor view requires IFRS')
    sector = template_for(payload['template'], payload.get('issuer_name'))
    schema = FIELDS.get(sector, FIELDS['general'])
    statements = {}
    for statement, groups in schema.items():
        statements[statement] = []
        for group in groups:
            rows = []
            for spec in group['rows']:
                field = spec['id']
                rows.append({**spec, 'id':statement+':'+field, 'field':field, 'statement':statement,
                             'metric_id':METRICS[field], 'source_form':FORM[statement],
                             'kind':'stock' if statement=='bs' else 'flow', 'unit':'UZS_thousand',
                             'cells':field_cells(payload,field,statement,observations)})
            statements[statement].append({'label':group['g'], 'rows':rows})
    return {**payload, 'presentation':'investor', 'display_template':sector, 'statements':statements}
