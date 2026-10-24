"""Admin-only model scenarios; published financial inputs, explicit assumptions."""
from statistics import quantiles, median
from server.terminal.analytics import number, peers, ratio

# Values supplied in the TZ are a dated scenario, not a live macro estimate.
REFERENCE = {'key_rate':14.0,'default_spread':3.06,'equity_premium':8.89,'growth':9.8}
REFERENCE_DATE = '2026-10-15'


def source_usable(row):
    # Unrelated missing cells/older years aren't grounds to reject a model,
    # but cached multiples must never bypass the publication quarantine.
    return not any(issue.get('code') in {'VALUE_QUARANTINE', 'SOURCE_UNAVAILABLE'}
                   and issue.get('period', row.get('period')) == row.get('period')
                   for issue in row.get('issues', []))


def share_projection(base, models):
    """Project raw methods onto one basis before comparing or aggregating.

    Price / checked issuer capitalisation is equivalent to the mockup's
    price / current P/B (or P/E), after multiplying by equity (or earnings).
    Raw outputs remain available to existing versioned admin rule tests.
    """
    price = number(base.get('price'))
    price = price if price is not None and price > 0 else None
    factor = ratio(price, base.get('market_cap'))
    equity = number(base.get('equity'))
    factors = {'peers_pb': factor, 'peers_pe': factor, 'gordon': 1,
               'justified_pb': equity * factor if equity is not None and factor is not None else None}
    for code, model in models.items():
        scale = factors[code]
        reason = 'SOURCE_QUALITY' if not source_usable(base) else model['reason']
        if reason is None and (scale is None or scale <= 0):
            reason = 'MARKET_BASIS_UNAVAILABLE'
        model['per_share'] = {key: model[key] * scale if reason is None else None
                              for key in ('value', 'low', 'high')}
        model['per_share'].update(reason=reason, unit='UZS/share')
    usable = [m['per_share'] for m in models.values() if m['per_share']['value'] is not None]
    summary = {'value': None, 'low': None, 'high': None, 'price_to_value_pct': None,
               'method_count': len(usable), 'unit': 'UZS/share', 'wide_spread': False}
    if usable:
        values = [m['value'] for m in usable]
        value = median(values)
        low = min(values) if len(usable) > 1 else usable[0]['low']
        high = max(values) if len(usable) > 1 else usable[0]['high']
        summary.update(value=value, low=low, high=high, price_to_value_pct=ratio(price, value, 100),
                       wide_spread=len(usable) > 1 and low > 0 and high / low > 3)
    return {'current_price': price, 'market_date': base.get('market_date'), 'summary': summary,
            'inputs': {field: number(base.get(field)) for field in ('roe', 'equity', 'net_profit', 'market_cap')}}


def calculate(base, candidates, parameters):
    p={k:number(parameters.get(k)) for k in REFERENCE}
    if any(v is None for v in p.values()):raise ValueError('All valuation assumptions must be finite')
    r=p['key_rate']-p['default_spread']+p['equity_premium'];g=p['growth']
    models={}
    def missing(reason,unit):return {'value':None,'low':None,'high':None,'reason':reason,'unit':unit}
    def band(value,low,high,unit):return {'value':value,'low':min(low,high),'high':max(low,high),'reason':None,'unit':unit}
    comparable=[row for row in peers(base,candidates) if source_usable(row)]
    peer_returns=[v for row in comparable if (v:=number(row.get('roe'))) is not None]
    peer_roe=median(peer_returns) if peer_returns else None
    roe=number(base.get('roe'))
    for code,field in [('pb','equity'),('pe','net_profit')]:
        multiples=[number(row.get(code)) for row in comparable]
        multiples=[v for v in multiples if v is not None and v>0]
        amount=number(base.get(field))
        if len(multiples)<3:result=missing('INSUFFICIENT_PEERS','UZS issuer value')
        elif amount is None or amount<=0:result=missing('NON_POSITIVE_DENOMINATOR','UZS issuer value')
        elif code=='pb' and roe is not None and peer_roe is not None and peer_roe>0 and roe<peer_roe/2:
            result=missing('ROE_BELOW_PEERS','UZS issuer value')
        else:
            lo,_,hi=quantiles(multiples,n=4,method='inclusive')
            result=band(median(multiples)*amount,lo*amount,hi*amount,'UZS issuer value')
        models['peers_'+code]={**result,'peer_count':len(multiples),
                              'multiple':median(multiples) if multiples else None,'peer_roe':peer_roe}
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
    projection=share_projection(base,models)
    projection['inputs']['dividend']=dividend
    return {'ok':True,'ticker':base.get('ticker'),'period':base.get('period'),'standard':base.get('standard'),'scope':base.get('scope'),
            **projection,
            'parameters':p,'required_return':r,'models':models,'public_enabled':False,
            'reference_date':REFERENCE_DATE,'sensitivity':'return ±1 percentage point, bounded above growth',
            'disclaimer':'Model calculation, not a recommendation'}
