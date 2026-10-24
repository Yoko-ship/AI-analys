"""The JSON and workbook adapters retain TMYS's filed short-term investments."""
import json
from pathlib import Path

import pytest

from catalogue import parsing
import openinfo_reconcile as reconcile


def filing():
    path = Path(__file__).parent / 'fixtures/insurance/TMYS_quarter_769.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_tmys_json_import_retains_short_term_investments():
    metrics = reconcile.extract_metrics(filing())
    assert metrics['insurance']['short_term_investments'] == pytest.approx(222_215_190.4)


def test_tmys_workbook_import_retains_the_same_reported_amount():
    rows = filing()['quarter_balance_sheet_report']
    workbook = {'sheets': [{'table_rows': [
        {'label': r['title'], 'source_cells': [r['tnum'], r['value1'], r['value2']]}
        for r in rows
    ]}]}
    metrics = parsing.extract_insurance_balance(workbook)
    assert metrics['short_term_investments'] == pytest.approx(222_215_190.4)
