"""Admin-only model scenarios; published financial inputs, explicit assumptions."""
from statistics import quantiles, median
from server.terminal.analytics import number, peers, ratio

# Values supplied in the TZ are a dated scenario, not a live macro estimate.
REFERENCE = {'key_rate':14.0,'default_spread':3.06,'equity_premium':8.89,'growth':9.8}
REFERENCE_DATE = '2026-10-15'


def calculate(base, candidates, parameters):
    p={k:number(parameters.get(k)) for k in REFERENCE}
    if any(v is None for v in p.values()):raise ValueError('All valuation assumptions must be finite')
    r=p['key_rate']-p['default_spread']+p['equity_premium'];g=p['growth']
    models={}
    def missing(reason,unit):return {'value':None,'low':None,'high':None,'reason':reason,'unit':unit}
    def band(value,low,high,unit):return {'value':value,'low':min(low,high),'high':max(low,high),'reason':None,'unit':unit}
    comparable=peers(base,candidates)
    for code,field in [('pb','equity'),('pe','net_profit')]:
        multiples=[number(row.get(code)) for row in comparable]
        multiples=[v for v in multiples if v is not None and v>0]
        amount=number(base.get(field))
        if len(multiples)<3:result=missing('INSUFFICIENT_PEERS','UZS issuer value')
        elif amount is None or amount<=0:result=missing('NON_POSITIVE_DENOMINATOR','UZS issuer value')
        else:
            lo,_,hi=quantiles(multiples,n=4,method='inclusive')
            result=band(median(multiples)*amount,lo*amount,hi*amount,'UZS issuer value')
        models['peers_'+code]={**result,'peer_count':len(multiples)}
    roe=number(base.get('roe'))
    pb=missing('NOT_A_BANK','P/B')
    if base.get('kind')=='bank':
        if r<=g:pb=missing('RETURN_NOT_ABOVE_GROWTH','P/B')
        elif roe is None:pb=missing('ROE_UNAVAILABLE','P/B')
        elif roe<g:pb=missing('ROE_BELOW_GROWTH','P/B')
        else:
            # ±1pp return sensitivity, bounded strictly above g.
            delta=min(1,(r-g)/2)
            pb=band((roe-g)/(r-g),(roe-g)/(r+delta-g),(roe-g)/(r-delta-g),'P/B')
    models['justified_pb']=pb
    dividend=number(((base.get('dividend') or {}).get('decision') or {}).get('ordinary_amount'))
    if r<=g:gd=missing('RETURN_NOT_ABOVE_GROWTH','UZS ordinary share')
    elif dividend is None or dividend<=0:gd=missing('RECENT_DIVIDEND_UNAVAILABLE','UZS ordinary share')
    else:
        delta=min(1,(r-g)/2);d1=dividend*(1+g/100)
        gd=band(d1/((r-g)/100),d1/((r+delta-g)/100),d1/((r-delta-g)/100),'UZS ordinary share')
    models['gordon']=gd
    return {'ok':True,'ticker':base.get('ticker'),'period':base.get('period'),'standard':base.get('standard'),'scope':base.get('scope'),
            'parameters':p,'required_return':r,'models':models,'public_enabled':False,
            'reference_date':REFERENCE_DATE,'sensitivity':'return ±1 percentage point, bounded above growth',
            'disclaimer':'Model calculation, not a recommendation'}
