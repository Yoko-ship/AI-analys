"""Full IFRS forms augment (and never bypass) the reviewed publication path."""
from financial_ingestion import statements, validation
from financial_columns import ifrs


def document():
    return {1: 'IFRS separate financial statements for 2024',
            2: '''Separate statement of financial position
(in thousands of UZS)
31 December 2024       31 December 2023
Property, plant and equipment    8    200    150
Inventories                     9    0      —
Other unfamiliar asset          10   25     20
Total assets                         300    250
Total liabilities                    200    180
Total equity                         100    70''',
            3: '''Separate statement of profit or loss
(in thousands of UZS)
Year ended 31 December 2024       31 December 2023
Revenue                              200    180
Cost of sales                        (150)  (140)
Profit for the year                  (10)   5''',
            4: '''Separate statement of cash flows
(in thousands of UZS)
Year ended 31 December 2024       31 December 2023
Net cash from operating activities   20     15
Purchase of property, plant and equipment (30)  (25)
Income tax paid                      —      (2)''',
            5: '''Separate statement of changes in equity
(in thousands of UZS)
Share capital   Retained earnings   Total equity
Balance at 1 January 2024      50    20    70
Dividends declared            —     (5)   (5)''',
            6: 'Notes to the separate financial statements\n8. Property, plant and equipment\nFully depreciated assets remain in use.'}


def test_all_source_forms_and_unmapped_lines_survive_candidate_extraction():
    pages = document()
    proposal = statements.proposals(pages, {'page_count': 6})[0]
    assert {f['form'] for f in proposal['source_forms']} == {'BS', 'PL', 'CF', 'Equity', 'Notes'}
    assert proposal['source_coverage']['notes'] == 'present'
    assert 'Dividends declared' in next(f['text'] for f in proposal['source_forms'] if f['form'] == 'Equity')
    rows = proposal['source_rows']
    ppe = next(r for r in rows if r['metric_id'] == 'ppe')
    assert ppe['page'] == 2
    assert ppe['raw_value'] == '200'
    assert ppe['raw_label'] == 'Property, plant and equipment'
    assert next(r for r in rows if r['metric_id'] == 'purchase_ppe')['raw_value'] == '-30'
    assert next(r for r in rows if r['metric_id'] == 'inventory')['raw_value'] == '0'
    assert next(r for r in rows if r['metric_id'] == 'income_tax_paid')['quality'] == 'missing'
    assert any(r['raw_label'] == 'Other unfamiliar asset' and r['metric_id'] is None for r in rows)
    assert validation.validate(proposal, page_count=6)['valid']
    proposal['source_rows'][0]['page'] = 99
    assert 'SOURCE_ROW_EVIDENCE_INVALID' in validation.validate(proposal, page_count=6)['errors']


def test_unknown_scope_and_missing_notes_are_explicit_in_the_source_passport():
    forms = ifrs.extract({2: document()[2].replace('Separate ', '')}, page_count=9)
    assert forms['rows'][0]['scope'] == 'unknown'
    assert forms['coverage']['notes'] == 'missing'
    assert forms['coverage']['complete'] is False
    assert 'NOTES_MISSING' in forms['coverage']['issues']


def test_bilingual_aliases_identify_the_same_metric_without_summing():
    assert ifrs.metric('Property, plant and equipment', 'BS') == 'ppe'
    assert ifrs.metric('Основные средства', 'BS') == 'ppe'
    assert ifrs.metric('Cash and cash equivalents', 'CF') == 'cash_end'
    assert ifrs.metric('Cash and cash equivalents', 'BS') == 'cash'
    assert ifrs.metric('Stage 3 loans', 'Notes') == 'stage3_loans'
    assert ifrs.metric('Stage 3 loans', 'Notes') != 'npl'


def test_native_notes_after_the_statement_page_budget_are_retained(monkeypatch):
    from financial_ingestion import extract
    from types import SimpleNamespace
    from contextlib import nullcontext
    pages = [SimpleNamespace(extract_words=lambda n=n: f'Notes to the financial statements\nDisclosure page {n}', close=lambda: None)
             for n in range(1, 81)]
    monkeypatch.setattr(extract.pdfplumber, 'open', lambda _: nullcontext(SimpleNamespace(pages=pages)))
    monkeypatch.setattr(extract.layout, 'word_lines', lambda words: words)
    text, evidence = extract.page_texts(b'not-a-live-document')
    assert len(text) == 80
    assert text[80].endswith('80')
    assert evidence['text_pages'] == list(range(1, 81))


def test_shareholder_disclosures_keep_date_scope_and_percentage_evidence():
    pages = document()
    pages[6] = '''Notes to the separate financial statements
Shareholders: ordinary shares, ownership interest (%)
31 December 2024       31 December 2023
State investment company       75.5%       80%
Other shareholders             24.5%       20%'''
    primary, comparative = statements.proposals(pages, {'page_count': 6})
    owners = primary['shareholders']
    assert len(owners) == 2
    assert owners[0]['name'] == 'State investment company'
    assert owners[0]['share'] == '75.5'
    assert owners[0]['date'] == '2024-12-31'
    assert owners[0]['scope'] == 'separate'
    assert owners[0]['share_class'] == 'ordinary'
    assert owners[0]['page'] == 6
    assert comparative['shareholders'][0]['share'] == '80'
    assert validation.validate(primary, page_count=6)['valid']
    owners[0]['share'] = '150'
    assert 'SHAREHOLDER_EVIDENCE_INVALID' in validation.validate(primary, page_count=6)['errors']


def test_earnings_per_share_keeps_its_own_unit_and_is_not_a_summable_flow():
    text = document()[3].replace('(in thousands of UZS)', '(in thousands of UZS, except per-share amounts)')
    text += '\nBasic earnings per share             12.50     10.00'
    row = next(r for r in ifrs.extract({3:text}, page_count=3)['rows'] if r['metric_id'] == 'eps_basic')
    assert row['unit_scale'] == '1'
    assert row['unit'] == 'UZS_per_share'
    assert row['kind'] == 'per_share'


def test_hmkb_damaged_text_layer_is_not_a_complete_financial_import():
    import json
    from pathlib import Path
    fixture = json.loads(Path('tests/fixtures/ifrs_hmkb_2025_broken_text.json').read_text(encoding='utf-8'))
    pages = {int(k): v for k, v in fixture['pages'].items()}
    result = ifrs.extract(pages, page_count=fixture['page_count'])
    assert not result['coverage']['complete']
    assert 'STATEMENT_ROWS_MISSING' in result['coverage']['issues']
    assert result['rows'] == []


def test_table_of_contents_is_not_notes_and_cash_opening_has_opening_date():
    pages = document()
    pages[1] = 'Contents\nNotes to the financial statements 6\nStatement of financial position 2'
    pages[4] += '\nCash and cash equivalents at beginning of year  20  10'
    result = ifrs.extract(pages, page_count=6)
    assert not any(f['page'] == 1 for f in result['forms'])
    opening = next(r for r in result['rows'] if r['metric_id'] == 'cash_begin')
    assert opening['period_end'] == '2023-12-31'
    assert opening['period_start'] == '2023-12-31'


def test_undated_flow_is_blocked_instead_of_given_a_calendar_year():
    text = document()[3].replace('Year ended', 'As at')
    row = next(r for r in ifrs.extract({3:text}, page_count=1)['rows'] if r['metric_id'] == 'net_income')
    assert row['quality'] == 'blocked'
    assert row['reason'] == 'PERIOD_START_UNRESOLVED'


def test_ownership_table_stops_before_another_note_table():
    from financial_columns import ownership
    text = '''Notes to the separate financial statements
Shareholders: ordinary shares, ownership interest (%)
31 December 2024       31 December 2023
State investment company       75.5%       80%
Other shareholders             24.5%       20%
Loans to related parties
Directors                      20         30'''
    assert len(ownership.extract({6:text})) == 4


def test_opening_cash_stays_with_the_reviewed_cash_flow_statement():
    pages = document()
    pages[4] += '\nCash and cash equivalents at beginning of year  20  10'
    primary = statements.proposals(pages, {'page_count': 6})[0]
    opening = next(r for r in primary['source_rows'] if r['metric_id'] == 'cash_begin')
    assert opening['period_end'] == '2023-12-31'
    assert validation.validate(primary, page_count=6)['valid']


def test_insurance_model_requires_applied_policy_not_a_future_standard_mention():
    from financial_columns.ifrs import accounting_model
    assert accounting_model({1:'The Company applies IFRS 17 Insurance Contracts.'})['model'] == 'IFRS17'
    assert accounting_model({1:'The Company applies IFRS 4 Insurance Contracts. IFRS 17 is not yet effective.'})['model'] == 'legacy'
    assert accounting_model({1:'IFRS 17 becomes effective next year.'})['model'] is None


def test_notes_use_local_table_dates_instead_of_the_report_heading_date():
    text = '''Notes to the separate financial statements
For the year ended 31 December 2025
(in thousands of UZS)
Loan disclosures
31 December 2025       31 December 2024
Interest-earning assets  1000  800
The following amounts relate to an undated portfolio.
Stage 3 loans  12  15'''
    rows = ifrs.extract({6:text}, page_count=6)['rows']
    earning = [r for r in rows if r['metric_id'] == 'earning_assets']
    assert [(r['period_end'],r['raw_value']) for r in earning] == [('2025-12-31','1000'),('2024-12-31','800')]
    assert not any(r['metric_id'] == 'stage3_loans' and r['quality'] == 'valid' for r in rows)
