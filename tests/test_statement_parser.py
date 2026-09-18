"""Statement semantics, independent of issuer identity and historical ledgers."""
import pytest

from financial_ingestion import statements, validation


@pytest.fixture
def pages():
    return {
        1: 'Example reporting entity\nIFRS financial statements for 2024',
        7: '''Example reporting entity
Consolidated statement of financial position
(in thousands of UZS)
31 December 2024       31 December 2023
Cash and cash equivalents     4    1,234,567    900,000
Total assets                     5,000,000    4,000,000
Total liabilities                3,000,000    2,500,000
Total equity                     2,000,000    1,500,000''',
        8: '''Example reporting entity
Consolidated statement of profit or loss
(in thousands of UZS)
Year ended 31 December 2024       31 December 2023
Interest income                  500,000    400,000
Interest expense                 (100,000)    (90,000)
Operating expenses               (200,000)    (180,000)
Profit before tax                220,000    150,000
Profit for the year              190,000    120,000''',
    }


def parse(pages):
    return statements.proposals(pages, {'page_count': max(pages), 'ocr_pages': []})


def test_all_year_columns_with_source_evidence_and_no_issuer_rules(pages):
    primary, comparative = parse(pages)
    assert primary['classification']['period_end'] == '2024-12-31'
    assert comparative['classification']['period_end'] == '2023-12-31'
    assert comparative['classification']['role'] == 'COMPARATIVE'
    for p, cash in [(primary, '1234567'), (comparative, '900000')]:
        assert len(p['figures']) == 9
        assert p['figures']['cash']['raw_value'] == cash
        assert p['figures']['cash']['page'] == 7
        assert p['extraction']['requires_review']
        assert not p['extraction']['issuer_identity_verified']
        assert validation.validate(p, page_count=8)['valid']
    assert primary['figures']['operating_income']['raw_value'] == '420000'
    assert primary['figures']['operating_income']['components'][1]['coefficient'] == -1


def test_later_audit_signature_year_is_not_the_financial_year(pages):
    pages[1] += '\nAuditor signed 8 May 2025'
    assert {p['classification']['document_year'] for p in parse(pages)} == {2024}


def test_scope_and_dates_are_not_guessed_from_catalog(pages):
    separate = {n: text.replace('Consolidated ', '') for n, text in pages.items()}
    result = parse(separate)
    assert {p['classification']['scope'] for p in result} == {'separate'}
    assert [p['classification']['period_end'] for p in result] == ['2024-12-31', '2023-12-31']


def test_reversed_columns_retain_their_actual_years(pages):
    pages = {n: text.replace('2024', 'XXXX').replace('2023', '2024').replace('XXXX', '2023') for n, text in pages.items()}
    first, second = parse(pages)
    assert first['classification']['period_end'] == '2023-12-31'
    assert first['classification']['role'] == 'COMPARATIVE'
    assert second['classification']['role'] == 'PRIMARY'
    assert first['figures']['cash']['raw_value'] == '1234567'


def test_cumulative_interim_period_is_not_an_annual(pages):
    pages = {n: text.replace('31 December', '30 June').replace('Year ended', 'Six months ended') for n, text in pages.items()}
    assert {p['classification']['period_end'] for p in parse(pages)} == {'2024-06-30', '2023-06-30'}


def test_notes_cannot_override_primary_statement_values(pages):
    pages[9] = pages[7].replace('Consolidated statement of financial position', 'Notes to the consolidated financial statements').replace('5,000,000', '8,000,000')
    assert parse(pages)[0]['figures']['total_assets']['raw_value'] == '5000000'


def test_conflicting_statement_rows_remain_missing(pages):
    pages[7] += '\nTotal assets    6,000,000    4,000,000'
    result = parse(pages)
    assert 'total_assets' not in result[0]['figures']
    assert result[1]['figures']['total_assets']['raw_value'] == '4000000'


def test_unresolved_date_headers_do_not_create_periods(pages):
    pages = {n: text.replace('31 December', '') for n, text in pages.items()}
    assert parse(pages) == []


@pytest.mark.parametrize('tail,count,expected', [
    ('7    1535 079 577 1172 161 642', 2, ['1535079577','1172161642']),
    ('(1 234 567)    (987 654)', 2, ['-1234567','-987654']),
    ('12    123,456    98,765', 2, ['123456','98765']),
    ('123 456 789 000', 2, None),  # Column boundary was lost.
    ('100    —', 2, ['100','0']),
    ('100', 2, None),
    ('42,50    (18,25)', 2, ['42.50','-18.25']),
    ('18       744,422 464,263', 2, ['744422','464263']),
    ('7     823 602 774 573 127 294', 2, None),
])
def test_numeric_cells_do_not_concatenate_years(tail, count, expected):
    assert statements.cells(tail,count) == expected


def test_wrapped_russian_labels_and_interest_components():
    result = parse({1: 'МСФО\nОтчет о прибылях и убытках\nв тысячах УЗС\n31 декабря 2024    31 декабря 2023\n'
        'Процентные доходы, рассчитанные по эффективной процентной\n'
        '    23    1 621 700 930    1 115 719 262\nставке\n'
        'Прочие процентные доходы    23    582963850    458316779\n'
        'Чистая прибыль за год    10397585    5094575'})
    assert result[0]['figures']['interest_income']['raw_value'] == '2204664780'
    assert result[1]['figures']['interest_income']['raw_value'] == '1574036041'
    assert len(result[0]['figures']['interest_income']['components']) == 2


def test_separate_staff_costs_block_incomplete_operating_income_derivation(pages):
    pages[8] += '\nStaff costs    (100,000)    (80,000)'
    assert 'operating_income' not in parse(pages)[0]['figures']


def test_continuation_containing_interest_income_is_not_an_income_total(pages):
    pages[8] += '\nLoss on initial recognition of assets earning\ninterest income    (2,888)    (29,663)'
    result = parse(pages)
    assert result[0]['figures']['interest_income']['raw_value'] == '500000'


def test_associate_result_is_excluded_from_operating_income(pages):
    pages[8] += '\nДоля в результатах ассоциированных предприятий    234    (465)'
    assert parse(pages)[0]['figures']['operating_income']['raw_value'] == '419766'


def test_word_coordinates_keep_thousands_spaces_distinct_from_year_columns():
    from financial_ingestion.layout import word_lines,tsv_text
    words=[{'text':t,'x0':x,'x1':x+len(t)*5,'top':10,'bottom':20} for t,x in [('Cash',10),('7',170),('823',200),('602',218),('774',236),('573',275),('127',293),('294',311)]]
    text=word_lines(words)
    assert text=='Cash  7  823 602 774  573 127 294'
    assert statements.cells(text.split('Cash  ')[1],2)==['823602774','573127294']
    header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv=header+''.join(f"5\t1\t1\t1\t1\t{i}\t{w['x0']}\t10\t{w['x1']-w['x0']}\t10\t90\t{w['text']}\n" for i,w in enumerate(words))
    assert tsv_text(tsv)==text


def test_inaugural_period_and_standalone_quarter_are_not_relabelled_as_calendar_ytd(pages):
    pages[8]=pages[8].replace('Year ended 31 December 2024','Period from 18 May 2024 to 31 December 2024').replace('Profit for the year','Profit for the period')
    assert parse(pages)[0]['classification']['period_start']=='2024-05-18'
    assert parse(pages)[1]['classification']['period_start'] is None
    quarter={n:text.replace('31 December','30 June').replace('Year ended','Three months ended') for n,text in pages.items() if n!=8}
    quarter[8]='Consolidated statement of profit or loss\nin thousands of UZS\nThree months ended 30 June 2024  30 June 2023\nInterest income  500,000  400,000\nProfit for the period  100,000  90,000'
    assert parse(quarter)[0]['classification']['period_start']=='2024-04-01'


def test_note_on_wrapped_label_does_not_hide_amount_continuation():
    result = parse({1: 'МСФО\nОтчет о прибылях и убытках\nв тысячах УЗС\nза 2024 год    за 2023 год\n'
        'Процентные доходы, рассчитанные по эффективной процентной  20\n'
        '3  100 000  80 000\nставке\nПрочие процентные доходы  20  20 000  10 000'})
    assert result[0]['figures']['interest_income']['raw_value'] == '120000'
    assert result[1]['figures']['interest_income']['raw_value'] == '90000'


def test_opening_balance_column_is_not_a_second_comparative_year(pages):
    pages[7] = '''Consolidated statement of financial position
in thousands of UZS
31 December  31 December  1 January
2024  2023  2023
Total assets  5,000,000  4,000,000  3,000,000
Total liabilities  3,000,000  2,500,000  2,000,000
Total equity  2,000,000  1,500,000  1,000,000'''
    result = {p['classification']['period_end']:p for p in parse(pages)}
    assert result['2024-12-31']['figures']['total_assets']['raw_value'] == '5000000'
    assert result['2023-12-31']['figures']['total_assets']['raw_value'] == '4000000'
    assert result['2023-01-01']['figures']['total_assets']['raw_value'] == '3000000'
    assert 'net_income' not in result['2023-01-01']['figures']


def test_consistent_statement_unit_can_carry_but_conflicting_units_cannot(pages):
    pages[8] = pages[8].replace('(in thousands of UZS)', '')
    assert len(parse(pages)[0]['figures']) == 9
    pages[9] = pages[7].replace('thousands', 'millions')
    assert any(p['classification']['unit_scale'] is None for p in parse(pages))


def test_ocr_comma_whitespace_preserves_thousands_and_note_lists():
    assert statements.cells('21,33  1,002,690, 700  900,000',2) == ['1002690700','900000']


def test_extra_financial_column_is_not_discarded_as_a_note():
    assert statements.cells('1 200 000  900 000  800 000',2) is None
    assert statements.cells('1 200 000  900 000',1) is None
    assert statements.cells('(100 000  90 000',2) is None
    assert statements.cells('((100 000)  (90 000)',2) == ['-100000','-90000']


def test_parenthesized_loss_word_is_part_of_the_label():
    assert statements.row_label('Чистая прибыль (убыток) за период  (50 000)  (20 000)')[0] == 'net_income'


def test_ocr_boxes_with_different_glyph_heights_keep_the_same_row():
    from financial_ingestion.layout import word_lines
    words=[dict(text='Total',x0=10,x1=35,top=10,bottom=20),
           dict(text='assets',x0=38,x1=68,top=16,bottom=22),
           dict(text='100,000',x0=150,x1=185,top=9,bottom=22)]
    assert word_lines(words) == 'Total assets  100,000'


def test_annual_income_dates_can_reference_explicit_balance_columns(pages):
    pages[8] = pages[8].replace('Year ended 31 December 2024       31 December 2023','2024       2023')
    assert len(parse(pages)[0]['figures']) == 9
    pages.pop(7)
    assert parse(pages) == []


def test_single_effective_interest_category_requires_net_reconciliation(pages):
    pages[8] = pages[8].replace('Interest income', 'Interest income calculated using effective interest')
    pages[8] = pages[8].replace('Interest expense', 'Interest expense calculated using effective interest')
    assert 'interest_income' not in parse(pages)[0]['figures']
    pages[8] += '\nNet interest income  400,000  310,000'
    result = parse(pages)[0]
    assert result['figures']['interest_income']['raw_value'] == '500000'
    assert validation.validate(result,page_count=8)['valid']


def test_displaced_bold_balance_total_retains_its_numeric_row(pages):
    pages[7] = pages[7].replace('Total assets                     5,000,000    4,000,000','5,000,000    4,000,000\nTotal assets')
    assert parse(pages)[0]['figures']['total_assets']['raw_value'] == '5000000'


def test_income_reconciliation_catches_a_single_ocr_digit_error(pages):
    pages[8]=pages[8].replace('Profit for the year', 'Income tax expense               (30,000)    (30,000)\nProfit for the year')
    for proposal in parse(pages):
        assert validation.validate(proposal,page_count=8)['valid']
    pages[8]=pages[8].replace('220,000','220,009')
    primary,comparative=parse(pages)
    assert 'INCOME_MISMATCH' in validation.validate(primary,page_count=8)['errors']
    assert validation.validate(comparative,page_count=8)['valid']


def test_income_reconciliation_does_not_invent_an_absent_tax_line(pages):
    primary,_=parse(pages)
    assert 'income_reconciliation' not in primary
    assert validation.validate(primary,page_count=8)['valid']


def test_unreadable_tax_cells_cannot_disable_income_reconciliation(pages):
    pages[8]=pages[8].replace('Profit for the year', 'Income tax expense               (30,00?)    (30,000)\nProfit for the year')
    primary,_=parse(pages)
    assert 'INCOME_RECONCILIATION_INVALID' in validation.validate(primary,page_count=8)['errors']


def test_one_effective_interest_side_reconciles_with_a_direct_total(pages):
    pages[8] = pages[8].replace('Interest income', 'Interest income calculated using effective interest')
    pages[8] += '\nNet interest income  400,000  310,000'
    assert parse(pages)[0]['figures']['interest_income']['raw_value'] == '500000'
    pages[8] = pages[8].replace('400,000  310,000', '400,009  310,000')
    assert 'interest_income' not in parse(pages)[0]['figures']


def test_ocr_bracket_shapes_keep_negative_sign_and_require_closure():
    assert statements.cells('{100 000)  (90 000}',2) == ['-100000','-90000']
    assert statements.cells('{100 000  90 000',2) is None
    assert statements.row_label('Расходы Ha персонал и прочие операционные расходы  {100 000)')[0] == 'operating_expenses'


def test_associate_result_wording_is_subtracted_from_operating_income(pages):
    pages[8] += '\nДоля финансового результата ассоциированных компаний  10,000  5,000'
    assert parse(pages)[0]['figures']['operating_income']['raw_value'] == '410000'


def test_discontinued_result_reconciles_total_profit_without_changing_operating_result(pages):
    pages[8]=pages[8].replace('Profit for the year', 'Income tax expense  (40,000)  (35,000)\nProfit for the year')
    pages[8] += '\nПрибыль / (убыток) за год от прекращенной деятельности, за\nвычетом налога  10,000  5,000'
    primary,comparative=parse(pages)
    assert validation.validate(primary,page_count=8)['valid']
    assert validation.validate(comparative,page_count=8)['valid']
    assert primary['figures']['operating_income']['raw_value']=='420000'
    primary['income_reconciliation']['discontinued']['raw_value']='10009'
    assert 'INCOME_MISMATCH' in validation.validate(primary,page_count=8)['errors']


def test_dot_thousands_do_not_change_decimal_precision():
    assert statements.cells('33.250.441  (7.191.023)',2)==['33250441','-7191023']
    assert statements.cells('(217.789,742)  123.45',2)==['-217789742','123.45']
    assert statements.cells('1.23.456  1,000',2) is None
