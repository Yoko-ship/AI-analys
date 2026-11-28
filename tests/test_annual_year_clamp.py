"""Annual periods require source evidence instead of upload-year clamping."""

import catalogue.financial_store as catalogue_financial_store
import pytest
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
import catalogue.sync as catalogue_sync
import catalogue.periods as catalogue_periods
import collectors.openinfo.transport as transport


@pytest.mark.parametrize("declared,original,expected,basis", [
    (2025, "2024-12-31", 2024, "reported"),
    (None, "2024-12-31", 2024, "reported"),
    (None, None, 2025, "publication_date"),
])
def test_sync_reads_original_annual_period_before_assigning_upload_year(tmp_path, monkeypatch, declared, original, expected, basis):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setattr(catalogue_financial_store, '_maybe_seed_financials', lambda *args: None)
    monkeypatch.setattr(catalogue_sources, '_make_session', lambda: object())
    monkeypatch.setattr(catalogue_sources, '_fetch_main_results', lambda *args: ([], 'bank'))
    monkeypatch.setattr(catalogue_sources, '_unified_pdf_id_map', lambda *args: {
        '362': {'pdf_id': 1234, 'pub_date': '2025-07-03T00:00:00'},
    })
    calls = []
    def fetch(session, path, params=None):
        calls.append(path)
        if path == '/reports/bank/annual/362/':
            return {'id': 362, 'organization': {'id': 30}, 'reporting_year': original}
        if (params or {}).get('report_type') == 'annual':
            return [{'id': 362, 'reporting_year': declared}]
        return []
    monkeypatch.setattr(catalogue_sources, '_json_get', fetch)
    monkeypatch.setattr(transport, '_json_get', fetch)
    result = catalogue_sync.sync_company('SQBN', 'SQB', force=True, org_id='30')
    assert not result['errors']
    assert calls.count('/reports/bank/annual/362/') == 1
    c = catalogue_storage.get_catalog_conn()
    try:
        assert [(r['year'], r['period_source']) for r in c.execute("SELECT * FROM catalog_reports WHERE ticker='SQBN'")] == [(expected, basis)]
    finally:
        c.close()


def test_reviewed_late_annuals_keep_balance_and_income_in_verified_year(tmp_path, monkeypatch):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    monkeypatch.setattr(catalogue_financial_store, '_maybe_seed_financials', lambda *args: None)
    monkeypatch.setattr(catalogue_sources, '_make_session', lambda: object())
    monkeypatch.setattr(catalogue_sources, '_fetch_main_results', lambda *args: ([], 'jsc'))
    monkeypatch.setattr(catalogue_sources, '_unified_pdf_id_map', lambda *args: {
        '3109': {'pdf_id': 13652, 'pub_date': '2020-09-30T17:17:00'},
        '3110': {'pdf_id': 13653, 'pub_date': '2020-10-02T10:50:10'},
    })
    def fetch(session, path, params=None):
        if (params or {}).get('report_type') == 'annual':
            return [{'id': 3109, 'reporting_year': 2018}, {'id': 3110, 'reporting_year': 2019}]
        return []
    monkeypatch.setattr(catalogue_sources, '_json_get', fetch)
    result = catalogue_sync.sync_company('TEST', 'Test issuer', force=True, org_id='374')
    assert not result['errors']
    c = catalogue_storage.get_catalog_conn()
    try:
        rows = c.execute("SELECT year,excel_url,excel_url_form1,openinfo_report_id FROM catalog_reports WHERE ticker='TEST' ORDER BY year").fetchall()
        assert [(r['year'], r['openinfo_report_id']) for r in rows] == [(2017, '3109'), (2018, '3110')]
        for row in rows:
            assert 'report_id=' + row['openinfo_report_id'] in row['excel_url']
            assert row['excel_url'] == row['excel_url_form1']
    finally:
        c.close()


class TestEffectiveAnnualYear:
    def test_an_upload_season_label_requires_original_period(self):
        # TRSB's FY2022 annual: labeled 2023, published 2023-05-23.
        assert catalogue_periods._effective_annual_year(2023, "2023-05-23T15:54:34") is None

    def test_hmkb_upload_season_label_requires_original_period(self):
        # HMKB record 189: labeled 2020, published 2020-10-13 → FY2019.
        assert catalogue_periods._effective_annual_year(2020, "2020-10-13T18:09:49") is None

    def test_biok_future_label_requires_original_period(self):
        # BIOK record 6007: labeled 2026, published 2026-07-07 → FY2025.
        assert catalogue_periods._effective_annual_year(2026, "2026-07-07T11:07:17") is None

    def test_a_late_filing_keeps_its_earlier_label(self):
        # AGMKP filed its FY2021 annual in 2023; the label is correct and a
        # clamp that moved years FORWARD would corrupt it.
        assert catalogue_periods._effective_annual_year(2021, "2023-05-16T08:28:06") == 2021

    def test_a_correct_label_in_season_is_untouched(self):
        assert catalogue_periods._effective_annual_year(2024, "2025-06-09T09:45:57") == 2024

    def test_no_publication_date_keeps_the_label(self):
        assert catalogue_periods._effective_annual_year(2018, None) == 2018
        assert catalogue_periods._effective_annual_year(2018, "") == 2018

    def test_garbage_publication_date_keeps_the_label(self):
        assert catalogue_periods._effective_annual_year(2018, "n/a") == 2018

    def test_the_corrupted_grbk_upload_is_excluded_from_ingestion(self):
        # Record 261's income statement is a copy of the 2016 filing under a
        # 2022 label — no relabel makes it true, it must not be ingested.
        assert ("11", "261") in catalogue_sources._ANNUAL_RECORD_EXCLUSIONS


def test_annual_approval_recovers_imkon_filing_when_quarter_index_works(tmp_path, monkeypatch):
    """The microfinance annual index rejects a bank-form annual approved in July."""
    from urllib.parse import urlparse, parse_qs
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setattr(catalogue_sources, "_make_session", lambda: object())
    pub = "2026-07-14T14:57:41"
    approved = {"id": 30718, "organization": 841, "object_id": 449, "pub_date": pub,
                "status": "approved", "report_type": "NSBU",
                "properties": {"org_type": "bank", "report_type": "annual", "report_title": "Годовой отчет Банка"}}
    detail = {"id": 449, "parent_id": 30718, "organization": {"id": 841}, "org_type": "microfinance",
              "reporting_year": "2025-12-31", "pub_date": pub, "status": "approved",
              "balance_sheet_report": [{"title": "14. Итого активов", "value": "45385484.00"}],
              "financial_results_report": [{"title": "Чистая прибыль (убыток)", "value": "-9808952.00"}]}
    monkeypatch.setattr(catalogue_sources, "_fetch_main_results", lambda *args: ([approved], "microfinance"))
    monkeypatch.setattr(catalogue_sources, "_unified_pdf_id_map", lambda *args: {})
    def fetch(session, path, params=None):
        if path == "/reports/bank/annual/449/":
            return detail
        if (params or {}).get("report_type") == "annual":
            raise ValueError("Micro-finance organizations only have quarterly reports.")
        if (params or {}).get("report_type") == "quarter":
            return [{"id": 62, "reporting_year": 2026, "quarter_no": "7"}]
        return []
    monkeypatch.setattr(catalogue_sources, "_json_get", fetch)
    def annual():
        catalogue_sync.sync_company("IFMT4", "IMKON FINANS", force=True, org_id="841")
        c = catalogue_storage.get_catalog_conn()
        try:
            return [dict(r) for r in c.execute("SELECT * FROM catalog_reports WHERE ticker='IFMT4' AND quarter=0")]
        finally:
            c.close()
    detail["organization"]["id"] = 1058
    assert annual() == []
    detail["organization"]["id"] = 841
    rows = annual()
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2025 and row["published_at"] == pub
    assert row["openinfo_report_id"] == "449" and row["pdf_url"].endswith("/to_pdf30718/")
    assert row["excel_url_form1"] == row["excel_url"]
    assert parse_qs(urlparse(row["excel_url"]).query)["org_type"] == ["bank"]


def test_resync_preserves_issuer_annual_pdf_and_clears_stale_export(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setattr(catalogue_sources, "_make_session", lambda: object())
    monkeypatch.setattr(catalogue_sources, "_fetch_main_results", lambda *args: ([], "jsc"))
    monkeypatch.setattr(catalogue_sources, "_unified_pdf_id_map", lambda *args: {})
    monkeypatch.setattr(catalogue_sources, "_json_get", lambda *args: [])
    issuer_pdf = "https://agmk.uz/storage/uploads/docs/bux-balans-2025-c-b_6ac8d9a597db87.43919499.pdf"
    with catalogue_storage.get_catalog_conn() as conn:
        conn.executemany(
            "INSERT INTO catalog_reports (ticker, report_form, period_type, year, pdf_url) "
            "VALUES ('AGMKP','NSBU','annual',?,?)",
            [(2025, issuer_pdf), (2023, "https://openinfo.uz/ru/reports/to_pdf5218/")],
        )

    result = catalogue_sync.sync_company("AGMKP", "Алмалыкский ГМК", force=True, org_id="372")
    assert not result["errors"]
    with catalogue_storage.get_catalog_conn() as conn:
        rows = conn.execute("SELECT year, pdf_url FROM catalog_reports WHERE ticker='AGMKP'")
        assert {r["year"]: r["pdf_url"] for r in rows} == {2023: None, 2025: issuer_pdf}
