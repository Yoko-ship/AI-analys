"""Investor ratio selection and explicit arithmetic over compatible inputs."""
from decimal import Decimal
from .matrix import choose
from .periods import calculate as period_value, CONTEXT

COMMON = ['roe','roa','equity_to_assets']
SECTOR = {
    'bank':['loans_to_deposits','ecl_coverage','nim','cir','cost_of_risk'],
    'insurance':['insurance_service_margin','reinsurance_to_revenue','insurance_liabilities_assets'],
    'fund':['nav','nav_per_share','nav_growth'],
    'leasing':['gross_margin','operating_margin','ebitda_margin','net_debt_to_ebitda','current_ratio'],
    'general':['gross_margin','operating_margin','ebitda_margin','net_debt_to_ebitda','current_ratio'],
}
LABELS = {
    'equity_to_assets':'Капитал / активы','loans_to_deposits':'Кредиты / депозиты клиентов',
    'insurance_service_margin':'Маржа страховых услуг','reinsurance_to_revenue':'Перестрахование / страховая выручка',
    'insurance_liabilities_assets':'Страховые обязательства / активы','nav':'NAV','nav_per_share':'NAV / акция',
    'nav_growth':'Изменение NAV (без корректировки на выплаты и выпуски)',
    'gross_margin':'Валовая маржа','operating_margin':'Операционная маржа','ebitda_margin':'EBITDA margin',
    'net_debt_to_ebitda':'Net Debt / EBITDA',
}


def calculate(observations, existing, columns, sector):
    result={r['metric_id']:r for r in existing}
    wanted=COMMON+SECTOR.get(sector,SECTOR['general'])
    for column in columns:
        end,basis=column['end'],column['basis']
        def point(metric,at=end):
            return choose([r for r in observations if r['metric_id']==metric and r['period_end']==at])
        def flow(metric):
            rows=[r for r in observations if r['metric_id']==metric]
            return period_value(rows,end,basis) if basis in {'ttm','quarter'} else choose(
                [r for r in rows if r['period_end']==end and r.get('period_start')==end[:4]+'-01-01'])
        def emit(metric,parts,formula,fn,unit='percent',applicable=True):
            if metric not in wanted:
                return
            context={tuple(p.get(k) for k in CONTEXT) for p in parts if p.get('issuer_id')}
            cell={'value':None,'quality':'missing','reason':'INPUTS_MISSING','components':parts,'formula':formula,
                  'period_end':end,'basis':basis,'origin':'UZStock_calculated','unit':unit}
            if not applicable:
                cell.update(quality='not_applicable',reason='SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE')
            elif len(context)>1 or any(p.get('quality')=='blocked' for p in parts):
                cell.update(quality='blocked',reason='INCOMPATIBLE_OR_BLOCKED_INPUTS')
            elif all(p.get('value') is not None and p.get('quality') in {'valid','warn'} for p in parts):
                value=fn(*[Decimal(p['value']) for p in parts])
                cell.update(value=str(value) if value is not None else None,
                            quality=('warn' if any(p['quality']=='warn' for p in parts) else 'valid') if value is not None else 'blocked',
                            reason=None if value is not None else 'NONPOSITIVE_DENOMINATOR')
            row=result.setdefault(metric,{'id':'ratio:'+metric,'metric_id':metric,'label':LABELS[metric],
                                          'kind':'ratio','source_form':'RAT','unit':unit,'cells':{}})
            row['cells'][column['key']]=cell
        def divide(a,b):
            return a/b*100 if b>0 else None
        stock=basis!='ttm'
        emit('equity_to_assets',[point('total_equity'),point('total_assets')],'total equity / total assets × 100',divide,applicable=stock)
        emit('loans_to_deposits',[point('loans_gross'),point('customer_funds')],'gross loans / customer funds',lambda a,b:a/b if b>0 else None,unit='ratio',applicable=stock)
        for metric,numerator in [('gross_margin','gross_profit'),('operating_margin','operating_income'),('ebitda_margin','ebitda')]:
            emit(metric,[flow(numerator),flow('revenue')],f'{numerator} / revenue × 100',divide,applicable=basis!='as_of')
        model={r.get('accounting_model') for r in observations if r['period_end']==end}
        emit('insurance_service_margin',[flow('insurance_service_result'),flow('insurance_revenue')],
             'insurance service result / insurance revenue × 100',divide,applicable=model=={'IFRS17'} and basis!='as_of')
        emit('reinsurance_to_revenue',[flow('reinsurance_result'),flow('insurance_revenue')],
             'abs(net reinsurance result) / insurance revenue × 100',lambda a,b:divide(abs(a),b),applicable=model=={'IFRS17'} and basis!='as_of')
        emit('insurance_liabilities_assets',[point('insurance_contract_liabilities'),point('total_assets')],
             'insurance contract liabilities / total assets × 100',divide,applicable=model=={'IFRS17'} and stock)
        emit('nav',[point('nav')],'assets − liabilities',lambda a:a,unit='UZS_thousand',applicable=stock)
        emit('nav_per_share',[point('nav'),point('ordinary_shares')],
             'NAV in thousands UZS × 1000 / verified shares outstanding',lambda a,b:a*1000/b if b>0 else None,unit='UZS_per_share',applicable=stock)
        prior=f'{int(end[:4])-1}{end[4:]}'
        emit('nav_growth',[point('nav'),point('nav',prior)],'NAV / NAV one year earlier − 1; not adjusted for distributions or issuance',
             lambda a,b:(a/b-1)*100 if b>0 else None,applicable=stock)
        emit('net_debt_to_ebitda',[point('interest_bearing_debt'),point('unrestricted_cash'),flow('ebitda')],
             '(interest-bearing debt − unrestricted cash) / FY or actual TTM EBITDA; no quarterly extrapolation',
             lambda debt,cash,ebitda:(debt-cash)/ebitda if ebitda>0 else None,unit='ratio',applicable=basis in {'annual','ttm'})
    # Keep applicable definitions visible even when an unimported source stops
    # calculation. This is distinct from declaring a missing result to be zero.
    for metric in wanted:
        if metric not in result:
            result[metric]={'id':'ratio:'+metric,'metric_id':metric,'label':LABELS.get(metric,metric.upper()),
                            'unit':'ratio' if metric in {'current_ratio','loans_to_deposits','net_debt_to_ebitda'} else 'percent',
                            'source_form':'RAT','kind':'ratio','cells':{c['key']:{'value':None,'quality':'missing','reason':'INPUTS_MISSING'} for c in columns}}
    return [result[key] for key in wanted]
