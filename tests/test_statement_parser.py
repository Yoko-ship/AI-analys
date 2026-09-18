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
