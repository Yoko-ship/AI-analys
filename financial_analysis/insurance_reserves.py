"""One reserve-section calculation for JSON, workbook and analysis adapters."""
from .sector_numbers import decimal, number


def reserve_totals(gross, share, filed_net, other):
    gross, share, filed_net, other = map(decimal, (gross, share, filed_net, other))
    net = gross - share if gross is not None and share is not None else filed_net
    liabilities = net + other if net is not None and other is not None else None
    return {'net_insurance_reserves': number(net), 'total_liabilities': number(liabilities)}
