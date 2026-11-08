"""Spreadsheet presentation of the terminal's selected financial table."""
import csv
import io
from decimal import Decimal, InvalidOperation

COPY = {
    'ru': ('Финансы', 'Источники', 'Показатель', 'Код', 'Единица', 'тыс. UZS', 'Нет данных — пустая ячейка. Выделенные значения требуют проверки. Подробности — в примечаниях и на листе «Источники».', 'Из отчётов'),
    'uz': ('Moliya', 'Manbalar', 'Ko‘rsatkich', 'Kod', 'Birlik', 'ming UZS', 'Ma’lumot yo‘q bo‘lsa, katak bo‘sh. Ajratilgan qiymatlarni tekshiring. Tafsilotlar izohlarda va Manbalar varag‘ida.', 'Hisobotlardan'),
    'en': ('Financials', 'Sources', 'Metric', 'Code', 'Unit', 'thousands UZS', 'Missing values are blank. Highlighted values need review. Details are in cell comments and the Sources sheet.', 'Reported ratios'),
}
CONTEXT = {
    'ru': {'separate': 'Отдельная отчётность', 'consolidated': 'Консолидированная отчётность', 'unknown': 'Периметр не подтверждён', 'annual': 'Годовые данные', 'quarter': 'Квартальные данные', 'interim': 'Промежуточные данные'},
    'uz': {'separate': 'Alohida hisobot', 'consolidated': 'Konsolidatsiyalangan hisobot', 'unknown': 'Qamrov tasdiqlanmagan', 'annual': 'Yillik ma’lumotlar', 'quarter': 'Choraklik ma’lumotlar', 'interim': 'Oraliq ma’lumotlar'},
    'en': {'separate': 'Separate statements', 'consolidated': 'Consolidated statements', 'unknown': 'Scope unconfirmed', 'annual': 'Annual data', 'quarter': 'Quarterly data', 'interim': 'Interim data'},
}


def selected_table(payload, tab, from_year, query):
    columns = [c for c in payload['columns'] if int(c['end'][:4]) >= from_year]
    rows = (payload.get('overview_rows', payload['rows']) if tab == 'summary' else
            payload['ratios'] if tab == 'ratios' else payload['rows'])
    rows = [r for r in rows if (tab != 'original' or r.get('source_form') != 'DERIVED')
            and query.lower() in ' '.join(str(r.get(k) or '') for k in
                                        ('label', 'display_ref', 'source_code', 'metric_id')).lower()]
    published = [r for r in payload.get('published_ratios', []) if tab == 'ratios'
                 and int(str(r['period'])[:4]) >= from_year
                 and query.lower() in str(r.get('label') or r['field']).lower()]
    return {**payload, 'columns': columns, 'rows': rows, 'ratios': [],
            'published_ratios': published, 'shareholders': []}


def numeric(cell):
    # Match the visible table: source values can remain visible with a quality
    # flag. Keep that amount and its warning rather than silently dropping it.
    if cell.get('value') is None:
        return None
    try:
        value = Decimal(str(cell['value']))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    # Excel only stores 15 significant digits. Preserve longer source values
    # as text instead of silently rounding them on opening the workbook.
    return str(value) if len(value.as_tuple().digits) > 15 else value


def table_rows(payload, lang):
    units = {'UZS_thousand': COPY[lang][5], 'percent': '%', 'ratio': '×', 'UZS_per_share': 'UZS / share'}
    for row in payload['rows']:
        cells = [row['cells'].get(c['key'], {}) for c in payload['columns']]
        if any(c.get('display_parts') for c in cells):
            # A displayed cell can contain several separate source amounts.
            # Give each component its own row; never invent a combined total.
            identity = lambda p: (p.get('source_form'), p.get('source_code'), p.get('metric_id'))
            parts = [{identity(p): p for p in c.get('display_parts', [])} for c in cells]
            keys = dict.fromkeys(key for period in parts for key in period)
            components = [(key[1] or key[2], [period.get(key, {}) for period in parts]) for key in keys]
        else:
            components = [(row.get('source_code'), cells)]
        for code, values in components:
            yield [row['label'], code, units.get(row.get('unit'), row.get('unit', '')),
                   *[numeric(c) for c in values]], values


def write_text(cell, value):
    cell.value = str(value) if value is not None else None
    cell.data_type = 's'  # Labels and evidence are always literal, never formulas.


def style_table(sheet, header_row, widths):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    for cell in sheet[header_row]:
        cell.fill = PatternFill('solid', fgColor='172A46')
        cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
    sheet.row_dimensions[header_row].height = 30
    for row in sheet.iter_rows(min_row=header_row + 1):
        for cell in row:
            cell.font = Font(name='Calibri', size=11, color='172A46')
            cell.fill = PatternFill('solid', fgColor='F1F4F8' if cell.row % 2 == 0 else 'FFFFFF')
            cell.border = Border(bottom=Side(style='hair', color='DDE3EC'))
            cell.alignment = Alignment(vertical='center', wrap_text=cell.column <= 3,
                                       horizontal='right' if cell.data_type == 'n' else 'left')
            if cell.data_type == 'n':
                decimals = min(2, max(0, -Decimal(str(cell.value)).normalize().as_tuple().exponent))
                pattern = '#,##0' + ('.' + '0' * decimals if decimals else '')
                cell.number_format = f'{pattern};[Red]-{pattern};0'
        sheet.row_dimensions[row[0].row].height = max(28, min(70, 16 * (1 + len(str(row[0].value or '')) // 48)))
    for index in range(1, sheet.max_column + 1):
        sheet.column_dimensions[get_column_letter(index)].width = widths[index - 1] if index <= len(widths) else 19
    sheet.auto_filter.ref = f'A{header_row}:{get_column_letter(sheet.max_column)}{sheet.max_row}'
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = f'1:{header_row}'
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0


def write_financial_sheet(sheet, payload, lang):
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    columns = payload['columns']
    context = ' · '.join(CONTEXT[lang].get(payload.get(k), payload.get(k, '')) for k in ('standard', 'scope', 'freq'))
    for number, text in enumerate((f"{payload['ticker']} · {payload.get('issuer_name', '')}",
                                   context, COPY[lang][6]), 1):
        sheet.merge_cells(start_row=number, start_column=1, end_row=number, end_column=3 + len(columns))
        write_text(sheet.cell(number, 1), text)
        sheet.cell(number, 1).font = Font(name='Calibri', size=16 if number == 1 else 11, bold=number == 1, color='172A46')
        sheet.row_dimensions[number].height = 25 if number == 1 else 21
    sheet['A3'].alignment = Alignment(wrap_text=True, vertical='center')
    sheet.row_dimensions[3].height = 32
    for col, label in enumerate([*COPY[lang][2:5], *[c['label'] for c in columns]], 1):
        write_text(sheet.cell(5, col), label)
    flagged = []
    for index, (values, cells) in enumerate(table_rows(payload, lang), 6):
        for col, value in enumerate(values, 1):
            cell = sheet.cell(index, col)
            if isinstance(value, Decimal):
                cell.value = value
            else:
                write_text(cell, value)
            if col >= 4:
                evidence = cells[col - 4]
                note = '\n'.join(str(evidence[k]) for k in ('quality', 'reason', 'formula', 'source_url') if evidence.get(k))
                if note:
                    cell.comment = Comment(note, 'UZStock')
                if evidence.get('quality') in {'warn', 'blocked'}:
                    flagged.append(cell)
    style_table(sheet, 5, [56, 14, 18])
    for cell in flagged:
        cell.fill = PatternFill('solid', fgColor='FFF0C2')
    sheet.freeze_panes = 'D6'


def export_table(payload, extension, *, lang, tab, from_year, query):
    from .exports import FIELDS, literal, records
    if lang not in COPY or tab not in {'summary', 'original', 'ratios'}:
        raise ValueError('Unknown table presentation')
    selected = selected_table(payload, tab, from_year, query)
    if extension == 'csv':
        stream = io.StringIO(newline='')
        # Match the selected language's number and list separators. Do not use
        # Excel's sep= directive: it disables UTF-8 BOM detection in Excel.
        decimal_comma = lang in {'ru', 'uz'}
        writer = csv.writer(stream, delimiter=';' if decimal_comma else ',')
        writer.writerow([*COPY[lang][2:5], *[c['label'] for c in selected['columns']]])
        for row, _ in table_rows(selected, lang):
            writer.writerow([str(v).replace('.', ',') if isinstance(v, Decimal) and decimal_comma else literal(v) for v in row])
        return stream.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8'
    if extension != 'xlsx':
        raise ValueError('Unknown export format')
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = COPY[lang][0]
    write_financial_sheet(sheet, selected, lang)
    published = selected['published_ratios']
    if published:
        periods = sorted({str(r['period']) for r in published}, reverse=True)
        fields = list(dict.fromkeys(r['field'] for r in published))
        report = {**selected, 'columns': [{'key': p, 'label': p} for p in periods],
                  'rows': [{'label': field, 'unit': next(r.get('unit', '') for r in published if r['field'] == field),
                            'cells': {str(r['period']): {**r, 'quality': 'warn'} for r in published if r['field'] == field}}
                           for field in fields]}
        write_financial_sheet(workbook.create_sheet(COPY[lang][7]), report, lang)
    evidence = workbook.create_sheet(COPY[lang][1])
    evidence.append(FIELDS)
    for index, row in enumerate(records(selected), 2):
        for col, field in enumerate(FIELDS, 1):
            write_text(evidence.cell(index, col), row[field])
    style_table(evidence, 1, [14, 14, 14, 18, 26, 56])
    evidence.freeze_panes = 'A2'
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
