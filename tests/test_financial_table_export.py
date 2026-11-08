"""The BIOK download must open as the displayed period table in Excel."""
import csv
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from financial_columns.exports import export
from server.company.financial_routes import router


@pytest.fixture
def biok():
    return json.loads(Path('tests/fixtures/financial_columns/biok_export_matrix.json').read_text(encoding='utf-8'))


def test_biok_table_download_has_period_columns_numeric_amounts_and_source_sheet(biok, monkeypatch):
    from financial_columns import service
    from financial_columns.presentation import select_statement
    monkeypatch.setattr(service, 'load', lambda ticker, **kwargs: select_statement(biok, kwargs['statement']))
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get('/api/company/BIOK/financials/columns.xlsx?layout=table&tab=summary&statement=income&lang=ru')
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content))
    sheet = book.active
    assert sheet.title == 'Финансы'
    assert [c.value for c in sheet[5]] == ['Показатель', 'Код', 'Единица', '2024', '2025', '2026 · 9M']
    assert [c.value for c in sheet[6]] == ['Чистая выручка от реализации', '010', 'тыс. UZS', 147678236, 142434170, 112957111]
    assert [c.value for c in sheet[7]][3:] == [-20714060, -18645393, -11675525]
    assert sheet['D7'].data_type == 'n'
    assert sheet.freeze_panes == 'D6'
    assert sheet.auto_filter.ref == 'A5:F7'
    evidence = list(book['Источники'].values)
    headers = evidence[0]
    item = next(r for r in evidence[1:] if r[headers.index('source_code')] == '040')
    assert item[headers.index('value')] == '-20714060'
    assert 'report_id=5302' in item[headers.index('source_url')]


def test_biok_csv_matches_russian_excel_separator_and_preserves_cyrillic(biok):
    content, media = export(biok, 'csv', layout='table', lang='ru', tab='original', from_year=2025, query='Расходы периода')
    assert content.startswith(b'\xef\xbb\xbf')
    assert not content.decode('utf-8-sig').startswith('sep=')  # Excel drops Unicode detection with this directive.
    assert media == 'text/csv; charset=utf-8'
    rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig')), delimiter=';'))
    assert rows == [['Показатель', 'Код', 'Единица', '2025', '2026 · 9M'],
                    ['Расходы периода', '040', 'тыс. UZS', '-18645393', '-11675525']]


def test_table_retains_zero_and_missing_and_does_not_execute_source_labels(biok):
    row = biok['rows'][2]
    row['label'] = '=HYPERLINK("https://example.test", "test")'
    row['cells']['2025'].update(value=None, quality='missing')
    row['cells']['2026-09-30'].update(value='99', quality='blocked')
    content, _ = export(biok, 'xlsx', layout='table', tab='original', query='interest_income', lang='en')
    book = load_workbook(io.BytesIO(content))
    sheet = book.active
    assert sheet['A6'].value == row['label'] and sheet['A6'].data_type == 's'
    assert sheet['D6'].value == 0 and sheet['D6'].data_type == 'n'
    assert sheet['E6'].value is None and sheet['F6'].value == 99
    assert sheet['F6'].comment and 'blocked' in sheet['F6'].comment.text
    assert sheet['F6'].fill.fgColor.rgb == '00FFF0C2'
    content, _ = export(biok, 'csv', layout='table', tab='original', query='interest_income')
    assert "'=HYPERLINK" in content.decode('utf-8-sig')


def test_biok_borrowing_components_stay_separate_in_the_same_period_columns(biok):
    content, _ = export(biok, 'xlsx', layout='table', tab='summary', query='Банковские кредиты', from_year=2025)
    rows = list(load_workbook(io.BytesIO(content)).active.values)[5:]
    assert [r[1] for r in rows] == ['570', '580', '730', '740']
    assert [r[3:] for r in rows] == [(2454390, 1453393), (0, 0), (7694292, 2852716), (0, 0)]


def test_ratio_export_does_not_mix_in_statements_or_shareholders(biok):
    biok['ratios'] = [{'id':'roe', 'metric_id':'roe', 'label':'ROE', 'unit':'percent',
                      'cells': {'2025': {'value':'12.5', 'quality':'warn', 'reason':'ANNUALIZED'}}}]
    biok['shareholders'] = [{'name':'An owner','share':'59','date':'2025-12-31'}]
    content, _ = export(biok, 'xlsx', layout='table', tab='ratios', lang='en', from_year=2025)
    sheet = load_workbook(io.BytesIO(content)).active
    assert sheet.max_row == 6
    assert [c.value for c in sheet[6]] == ['ROE', None, '%', 12.5, None]
    assert sheet['D6'].comment and 'ANNUALIZED' in sheet['D6'].comment.text


@pytest.mark.parametrize('lang,separator,value', [('ru',';','12,5'), ('uz',';','12,5'), ('en',',','12.5')])
def test_csv_uses_the_language_number_and_column_separators(biok, lang, separator, value):
    biok['rows'][0]['cells']['2024']['value'] = '12.5'
    content, _ = export(biok, 'csv', layout='table', tab='original', query='revenue', lang=lang)
    rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig')), delimiter=separator))
    assert rows[1][3] == value
    assert len(rows[1]) == 6


@pytest.mark.parametrize('value,expected,kind', [
    ('-20714060', -20714060, 'n'), ('123456789012345', 123456789012345, 'n'),
    ('1234567890123456', '1234567890123456', 's'), ('NaN', None, 'n'), ('Infinity', None, 'n'),
])
def test_numeric_cells_do_not_lose_precision_or_export_nonfinite_numbers(biok, value, expected, kind):
    biok['rows'][0]['cells']['2024']['value'] = value
    content, _ = export(biok, 'xlsx', layout='table', tab='original', query='revenue')
    cell = load_workbook(io.BytesIO(content)).active['D6']
    assert cell.value == expected
    if expected is not None:
        assert cell.data_type == kind
    if kind == 'n' and expected is not None:
        assert '.' not in cell.number_format  # Excel must not show a dangling decimal separator on integers.


def test_company_reported_ratios_have_their_own_period_table_and_evidence(biok):
    biok['published_ratios'] = [{'field':'roe', 'period':'2025', 'value':'12.5', 'unit':'%',
                                'source_url':'https://openinfo.uz/reports/5302'}]
    content, _ = export(biok, 'xlsx', layout='table', tab='ratios', lang='en')
    book = load_workbook(io.BytesIO(content))
    assert book['Reported ratios']['D5'].value == '2025'
    assert book['Reported ratios']['D6'].value == 12.5
    assert any('PUBLISHED_RAT' in row for row in book['Sources'].values)


@pytest.mark.parametrize('parameter', ['layout=wrong', 'tab=owners', 'lang=xx', 'from_year=abc'])
def test_export_rejects_unknown_table_options(parameter):
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get('/api/company/BIOK/financials/columns.xlsx?' + parameter).status_code == 422
