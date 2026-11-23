from pathlib import Path

from catalogue import evidence, financial_store, history, parsing, refresh, sources, storage, sync
from collectors.openinfo.workbooks import _parse_excel_workbook


def test_audition_sweep_recovers_paired_statutory_forms(tmp_path, monkeypatch):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    issued = '2026-07-31T14:55:03'
    filenames = ['0d08bae1-e170-4849-8595-4421eadc42f8.xlsx', 'c88a3578-7d38-423c-a43a-a9fa52586e07.xlsx']
    docs = [{'id': n, 'organization': 382, 'status': 'approved', 'pub_date': issued,
             'pdf_file': 'audition/' + filename, 'title': title + ' за 1 полугодие 2026 г.'}
            for n, filename, title in zip((3141, 3142), filenames,
                                         ('ОТЧЕТ О ФИНАНСОВЫХ РЕЗУЛЬТАТАХ форма №2', 'БУХГАЛТЕРСКИЙ БАЛАНС'))]
    issuer = {'id': 382, 'inn': 200459808}

    def response(session, path, params=None):
        if path == '/reports/audition/':
            return {'results': docs}
        assert path == '/home/organizations/382/'
        return issuer

    header_year = 2026

    def workbook(session, url):
        form = ['income', 'balance'][filenames.index(url.rsplit('/', 1)[1])]
        raw = Path(f'tests/fixtures/openinfo/becm_2026h1_{form}.xlsx').read_bytes()
        parsed = _parse_excel_workbook(raw)
        if header_year != 2026:
            for sheet in parsed['sheets']:
                for row in sheet['source_rows']:
                    row['cells'] = [str(v).replace('2026', str(header_year)) if isinstance(v, str) else v
                                    for v in row['cells']]
        return {'ok': True, **parsed}

    monkeypatch.setattr(sources, '_json_get', response)
    monkeypatch.setattr(history, '_parse_workbook_uncached', workbook)
    conn = storage.get_catalog_conn()
    try:
        with conn:
            conn.execute("INSERT INTO catalog_companies(ticker, company_name, org_id) VALUES ('BECM','Bekobodsement','382')")

        def recovered():
            sync._sync_auditions(conn, object())
            return [dict(r) for r in conn.execute("SELECT * FROM catalog_reports WHERE report_form='NSBU'")]

        issuer['inn'] = 123456789
        assert recovered() == []
        issuer['inn'] = 200459808
        docs[0]['status'] = 'pending'
        assert recovered() == []
        docs[0]['status'] = 'approved'
        header_year = 2025
        assert recovered() == []
        header_year = 2026
        row, = recovered()
        assert (row['ticker'], row['period_type'], row['year'], row['quarter']) == ('BECM', 'quarter', 2026, 2)
        assert row['excel_url'].endswith(filenames[0]) and row['excel_url_form1'].endswith(filenames[1])
        assert recovered() == [row]

        from financial_columns import share_disclosures
        monkeypatch.setattr(share_disclosures, 'collect_form5', lambda *args, **kwargs: None)
        data = {'ok': True, 'income': workbook(None, row['excel_url']),
                'balance': workbook(None, row['excel_url_form1'])}
        values = parsing.compute_filing_values(data['income'], data['balance'])['source_values']
        rid = refresh._register_parse('BECM', 'NSBU', 2026, 2, data, values)
        assert rid
        financial_store.upsert_financials_cache('BECM', 'NSBU', 2026, 2, values, rid)
        for field, key in [('net_profit', 'excel_url'), ('total_assets', 'excel_url_form1')]:
            passport = evidence.get_financial_value_passport('BECM', '2026Q2', field)
            assert passport['status'] == 'SOURCED'
            assert passport['source']['excel_url'] == row[key]
    finally:
        conn.close()
