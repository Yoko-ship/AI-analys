"""Exports retain the context required to interpret every financial cell."""
import csv
import io
import re

FIELDS = ('ticker', 'issuer_id', 'standard', 'scope', 'metric_id', 'label', 'period_start', 'period_end',
          'basis', 'unit', 'value', 'raw_value', 'currency', 'unit_scale', 'source_form', 'source_code',
          'source_url', 'source_version', 'page', 'sheet', 'row', 'quality', 'reason', 'formula',
          'origin', 'share_class')


def records(payload):
    for row in payload['rows'] + payload['ratios']:
        for column in payload['columns']:
            cell = row['cells'][column['key']]
            yield {key: {**payload, **row, 'period_end': column['end'], 'basis': column['basis'], **cell}.get(key) for key in FIELDS}
    for row in payload.get('published_ratios', []):
        item = {**payload, **row, 'metric_id': row['field'], 'label': row['field'],
                'period_end': row['period'], 'source_form': 'PUBLISHED_RAT', 'basis': 'published',
                'quality': 'warn', 'reason': 'SOURCE_PUBLISHED_METHOD_NOT_RECALCULATED'}
        yield {key: item.get(key) for key in FIELDS}
    for row in payload.get('shareholders', []):
        item = {**payload, **row, 'label': row['name'], 'value': row['share'], 'unit': 'percent',
                'period_end': row['date'], 'source_form': 'OWNERS', 'basis': 'as_of', 'origin': 'source_disclosure'}
        yield {key: item.get(key) for key in FIELDS}


def literal(value):
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', value):
            return "'" + value
    return value


def export(payload, extension):
    rows = list(records(payload))
    if extension == 'csv':
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        # Source labels can be spreadsheet formulas. Preserve literal text.
        for row in rows:
            writer.writerow({k: literal(v) for k, v in row.items()})
        return stream.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8'
    if extension == 'xlsx':
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Financial columns'
        sheet.append(FIELDS)
        for row in rows:
            sheet.append([str(row[k]) if row[k] is not None else None for k in FIELDS])
            for cell in sheet[sheet.max_row]:
                cell.data_type = 's'
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        stream = io.BytesIO()
        workbook.save(stream)
        return stream.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    raise ValueError('Unknown export format')
