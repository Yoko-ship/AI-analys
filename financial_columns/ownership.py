"""Explicit percentage ownership tables, never inferred share counts."""
import re
from decimal import Decimal


def extract(pages):
    from financial_ingestion.statements import columns, cells
    from .ifrs import split_row
    result = []
    for page, text in pages.items():
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if re.search(r'shareholders|акционеры|акционеров', line, re.I)), None)
        if start is None:
            continue
        header = '\n'.join(lines[max(0, start-3):start+4])
        if not ('%' in header and re.search(r'ownership|interest|дол[яи]|акцион', header, re.I)):
            continue
        dates = columns(header)
        scope = 'consolidated' if re.search(r'consolidated|консолидирован', text[:1500], re.I) else 'separate' if re.search(r'separate|отдельн|индивидуальн', text[:1500], re.I) else 'unknown'
        share_class = 'preferred' if re.search(r'preferred|preference|привилегирован', header, re.I) else 'ordinary' if re.search(r'ordinary|обыкновен', header, re.I) else 'ownership_interest'
        if not dates or scope == 'unknown':
            continue
        table = []
        for line in lines[start+1:]:
            split = split_row(line.replace('%', ''))
            if not split:
                if table:
                    break
                continue
            name, tail = split
            if re.fullmatch(r'total|итого|всего', name.strip(), re.I):
                break
            values = cells(tail, len(dates))
            if not values or any(v is None or not 0 <= Decimal(v) <= 100 for v in values):
                continue
            for (_, end), value in zip(dates, values):
                table.append({'name': name, 'share': value, 'date': end, 'scope': scope,
                               'share_class': share_class, 'page': page, 'raw_line': line,
                               'quality': 'valid', 'unit': 'percent'})
        if all(sum(Decimal(r['share']) for r in table if r['date'] == end) <= 100 for _, end in dates):
            result.extend(table)
    return result
