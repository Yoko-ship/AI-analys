"""Lossless NSBU row projection. No fetching, aggregation or ticker rules."""
from decimal import Decimal, InvalidOperation
import re

from financial_ingestion.statements import numeric
from .registry import metric, LABEL_RULES


def cell(raw):
    text = str(raw).strip() if raw is not None else ''
    result = {'raw_value': raw, 'value': None, 'quality': 'missing'}
    if text in {'', 'nan', 'None', '-', '—', '–'}:
        return result
    if text.lower() in {'x', 'х'}:
        return {**result, 'quality': 'not_applicable'}
    try:
        value = numeric(text)
        if value is None or not Decimal(value).is_finite():
            raise ValueError('nonfinite')
        return {**result, 'value': value, 'quality': 'valid'}
    except (InvalidOperation, ValueError, ArithmeticError):
        return {**result, 'quality': 'blocked', 'reason': 'AMOUNT_UNRESOLVED'}


def _flow_pair(raw):
    """Income minus expense columns; explicit crossed cells are inapplicable."""
    a, b = [cell(v) for v in raw]
    if a['quality'] == b['quality'] == 'not_applicable':
        return {'raw_value': raw, 'value': None, 'quality': 'not_applicable'}
    values = [Decimal(c['value']) if c['value'] is not None else
              Decimal(0) if c['quality'] == 'not_applicable' else None for c in (a, b)]
    if None in values:
        return {'raw_value': raw, 'value': None, 'quality': 'blocked' if any(
            c['quality'] == 'blocked' for c in (a, b)) else 'missing'}
    return {'raw_value': raw, 'value': str(values[0] - values[1]), 'quality': 'valid'}


def rows(workbook, *, template, default_form=None):
    result = []
    for sheet in workbook.get('sheets') or []:
        name = sheet.get('sheet', sheet.get('name', ''))
        active = default_form or ('F2' if re.search(r'форма\s*№?\s*2|финансовых результат', name, re.I) else 'F1')
        parent = None
        single_flow_column = False
        source = sheet.get('source_rows')
        if source is None:
            source = [{'row': r.get('row'), 'cells': r.get('source_cells') or r.get('values') or
                       [r.get('label'), *(r.get('numeric_values') or [])]}
                      for r in sheet.get('table_rows', [])]
        for row in source:
            raw = row['cells']
            first = next((i for i, v in enumerate(raw) if v is not None and str(v).strip() not in {'', 'nan'}), None)
            if first is None:
                continue
            label = str(raw[first])
            if re.search(r'отчет.*финансов.*результ|чистая выручка от реализации|доходы от оказания страховых услуг', label, re.I):
                active, parent = 'F2', None
            elif re.search(r'бухгалтерский баланс|баланс банка', label, re.I):
                active, parent = 'F1', None
            if re.match(r'^(мфо|кфс|кфc|оконх|окпо|соато|период квартала|присвоенные)', label, re.I):
                continue
            tail = raw[first + 1:]
            if template == 'bank':
                if active == 'F2' and tail and re.fullmatch(r'\(?тыс\.?\s*сум\.?\)?', str(tail[0]).strip(), re.I):
                    single_flow_column = all(v is None or str(v).strip() in {'', 'nan'} for v in tail[1:])
                numbered = re.match(r'^\s*(\d{1,2})[.\s]+(?:([а-лa])(?:\.(\d+))?[.)]\s+)?', label, re.I)
                sub = re.match(r'^\s*([а-лa])(?:\.(\d+))?[.)]\s+', label, re.I)
                if not numbered and not (sub and parent):
                    continue
                if numbered:
                    parent = numbered[1]
                    suffix, detail = numbered[2], numbered[3]
                else:
                    suffix, detail = sub[1], sub[2]
                code = parent + (suffix or '').lower().replace('a', 'а') + ('.' + detail if detail else '')
                # Excel merged blank columns are retained; a bank layout needs
                # two actual period slots, not a compressed numeric-only list.
                if len(tail) > 2 and all(v is None or str(v).strip() in {'', 'nan'} for v in tail[2:]):
                    tail = tail[:2]
                if len(tail) not in {1, 2}:
                    continue
                form = 'BANK_BS' if active == 'F1' else 'BANK_PL'
            else:
                # The code cell is immediately after the literal row label.
                # Unknown codes are kept; they are not forced into a known key.
                if not tail or not re.fullmatch(r'\d{1,4}(?:\.0)?', str(tail[0])):
                    continue
                code = f'{int(Decimal(str(tail[0]))):03d}'
                if int(code) <= 0:
                    continue
                tail = tail[1:]
                form = ('INSURANCE_BS' if active == 'F1' else 'INSURANCE_PL') if template == 'insurance' else active
                width = 2 if active == 'F1' or len(tail) == 2 else 4
                if len(tail) > width and all(v is None or str(v).strip() in {'', 'nan'} for v in tail[width:]):
                    tail = tail[:width]
                if len(tail) < width:
                    tail += [None] * (width - len(tail))
            if len(tail) == 4 and active == 'F2':
                previous, current = _flow_pair(tail[:2]), _flow_pair(tail[2:])
            elif template == 'bank' and (len(tail) == 1 or (active == 'F2' and single_flow_column)):
                previous, current = cell(None), cell(tail[0])
            elif len(tail) == 2:
                previous, current = cell(tail[0]), cell(tail[1])
            else:
                continue
            metric_id = metric(form, code)
            mapping_issue = None
            if metric_id in LABEL_RULES and not re.search(LABEL_RULES[metric_id], label, re.I):
                metric_id, mapping_issue = None, 'CODE_LABEL_MISMATCH'
            if template == 'bank' and active == 'F2' and code in {'1', '2', '4', '5', '7'} and all(
                    c['value'] is None for c in (current, previous)):
                metric_id = None  # a category header, not a second reported total
            result.append({'source_form': form, 'source_code': code, 'raw_label': label,
                           'metric_id': metric_id, 'mapping_issue': mapping_issue, 'kind': 'stock' if active == 'F1' else 'flow',
                           'unit': 'UZS_thousand', 'previous': previous, 'current': current,
                           'raw_cells': raw, 'sheet': name, 'row': row.get('row'),
                           'source_url': workbook.get('source_url')})
            if template == 'bank' and active == 'F1' and code == '31':
                active, parent = 'F2', None
    return result
