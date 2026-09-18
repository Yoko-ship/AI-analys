"""Bank history recovery must revisit known reports and expose partial coverage."""
import pytest
from fastapi.testclient import TestClient

import api
import collector_financials as cf
import reports_catalog as rc


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "banks.db"))
    monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *args: None)
    monkeypatch.setattr(cf, "_bank_history_remote_attempt", lambda ticker: "")
    return rc.get_catalog_conn


def filing(connect, ticker, org, year=2022, quarter=0, form="NSBU", bank=True):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?) "
                     "ON CONFLICT(ticker) DO NOTHING", (ticker, ticker, org))
        rc._upsert_report(conn, ticker, report_form=form, period_type="quarter" if quarter else "annual",
                          year=year, quarter=quarter, title=None, published_at=f"{year + 1}-06-01",
                          pdf_url="https://openinfo.uz/report.pdf", excel_url=(
                              "https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type=bank"
                              if bank and form == "NSBU" else None),
                          excel_url_form1=None, openinfo_report_id=f"{year}{quarter}", object_id=None)
    conn.close()


def test_coverage_counts_missing_periods_and_fields_across_share_classes(catalog):
    filing(catalog, "BANK", "12", 2022)
    filing(catalog, "BANKP", "12", 2023)
    rc.upsert_financials_cache("BANKP", "NSBU", 2022, 0, {
        "revenue": 100, "net_income": 0, "total_assets": 1000,
        "total_equity": 200, "total_liabilities": 800, "cash": 0,
        "gross_profit": 50, "operating_income": 0,
    })
    coverage = rc.get_financial_history_coverage()
    assert coverage["BANK"] == coverage["BANKP"]
    bank = coverage["BANK"]
    assert bank["status"] == "PARTIAL"
    assert bank["expected_periods"] == 2
    assert bank["parsed_periods"] == 1
    assert bank["complete_periods"] == 0
    assert bank["missing_periods"] == ["2023"]
    assert bank["missing_fields"]["2022"] == ["operating_expenses"]


def test_ifrs_reports_do_not_count_nsbu_corrections_as_collected(catalog):
    filing(catalog, "IPTB", "17", 2022, form="MSFO")
    coverage = rc.get_financial_history_coverage("MSFO")["IPTB"]
    assert coverage["missing_periods"] == ["2022"]
    assert coverage["parsed_periods"] == 0


def test_bank_repair_rotates_issuers_and_reparses_known_history(catalog, monkeypatch):
    filing(catalog, "BANK", "12")
    filing(catalog, "BANKP", "12")
    filing(catalog, "OTHER", "13")
    filing(catalog, "INSURER", "14", bank=False)
    calls = []
    monkeypatch.setattr(rc, "sync_company", lambda *args, **kw: {})
    monkeypatch.setattr(cf, "backfill_company_quarter_history", lambda ticker, **kw: calls.append(("discover", ticker)) or 0)
    monkeypatch.setattr(cf, "backfill_financials", lambda year, *, tickers: calls.append(("annual", next(iter(tickers)))) or 0)
    monkeypatch.setattr(cf, "backfill_quarterly_financials", lambda year, *, tickers: calls.append(("quarter", next(iter(tickers)))) or 0)
    monkeypatch.setattr(cf, "_post", lambda *args: 0)
    monkeypatch.setattr(cf, "_stamp_step", lambda *args: None)
    assert cf.backfill_bank_financials(1) == 0
    assert calls == [("discover", "BANK"), ("annual", "BANK"), ("quarter", "BANK")]
    calls.clear()
    assert cf.backfill_bank_financials(1) == 0
    assert calls == [("discover", "OTHER"), ("annual", "OTHER"), ("quarter", "OTHER")]
    calls.clear()
    assert cf.backfill_bank_financials(10) == 0
    assert calls == []
    assert cf.backfill_bank_financials(1, force=True) == 0
    assert calls[1] == ("annual", "BANK")  # catalogue presence must not skip extraction


def test_failed_bank_is_marked_partial_and_does_not_starve_others(catalog, monkeypatch):
    filing(catalog, "BANK", "12")
    filing(catalog, "OTHER", "13")
    calls = []
    monkeypatch.setattr(rc, "sync_company", lambda ticker, *args, **kw: calls.append(ticker) or {"errors": ["source unavailable"]})
    monkeypatch.setattr(cf, "_post", lambda *args: 0)
    monkeypatch.setattr(cf, "_stamp_step", lambda *args: None)
    assert cf.backfill_bank_financials(1) == 1
    assert cf.backfill_bank_financials(1) == 1
    assert calls == ["BANK", "OTHER"]
    assert {f["value_text"] for f in rc.get_facts(dataset="bank_history") if f["field"] == "status"} == {"partial"}


def test_empty_failed_harvest_is_not_a_success(monkeypatch):
    monkeypatch.setattr(rc, "harvest_historical_quarters", lambda *a, **kw: {"rows": [], "errors": ["download failed"]})
    assert cf.backfill_company_quarter_history("BANK") == 1


def test_discovery_failure_is_not_silently_an_empty_feed(monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(rc, "_json_get", failed)
    with pytest.raises(RuntimeError, match="issuer 27, page 1"):
        rc.unified_quarterly_records(object(), 27)


def test_quarterly_conflict_explains_both_missing_quarters():
    gaps = []
    _, series = api.derive_quarterly_series({
        "2025Q1": {"revenue": 1143, "net_income": 24},
        "2025Q2": {"revenue": 2491, "net_income": 49},
        "2025Q3": {"revenue": 3876, "net_income": 90},
    }, {"2025": {"revenue": 3564, "net_income": 160}}, issues=gaps)
    assert "2025Q3" not in series["net_profit"]
    assert "2025Q4" not in series["net_profit"]
    assert any(g["period"] == "2025Q3" and g["code"] == "INCONSISTENT_CUMULATIVE_INCOME" for g in gaps)
    assert any(g["period"] == "2025Q4" and g["code"] == "MISSING_COMPARATIVE_INPUT" for g in gaps)


def test_br_bn_published_zero_is_not_a_missing_income_line():
    def parsed(label):
        return {"sheets": [{"table_rows": [{"label": label, "numeric_values": [0.0]}]}]}
    assert rc.compute_financial_ratios(parsed("6. ЧИСТЫЙ ДОХОД ДО ОПЕРАЦИОННЫХ РАСХОДОВ"), None)["source_values"]["gross_profit"] == 0.0
    assert rc.compute_financial_ratios(parsed("9. ЧИСТАЯ ПРИБЫЛЬ ДО УПЛАТЫ НАЛОГОВ"), None)["source_values"]["operating_income"] == 0.0
    assert rc._row_value([]) is None
    assert rc.compute_financial_ratios(parsed("е. Итого беспроцентных доходов"), None)["source_values"]["noninterest_income"] == 0.0


def test_fresh_collector_reads_remote_rotation_checkpoint(catalog, monkeypatch):
    filing(catalog, "BANK", "12")
    monkeypatch.setattr(cf, "_bank_history_remote_attempt", lambda ticker: "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(rc, "sync_company", lambda *args, **kw: pytest.fail("already repaired on production"))
    assert cf.backfill_bank_financials() == 0


def test_ifrs_api_distinguishes_an_unparsed_report_from_no_publication(catalog, monkeypatch):
    filing(catalog, "IPTB", "17", 2022, form="MSFO")
    monkeypatch.setattr(api, "get_company_index", lambda ticker: {"org_id": "17"})
    body = TestClient(api.app).get("/api/company/IPTB/financials?form=MSFO").json()
    assert body["series"] == {}
    assert body["periods"] == []
    assert body["availability"] == "NO_PARSED_FINANCIALS"
    assert body["reports_available"] is True
    assert {"period": "2022", "code": "REPORT_NOT_PARSED"} in body["data_gaps"]


def test_history_fetch_bypasses_snapshot_cache_and_downloads_combined_book_once(monkeypatch):
    url = "https://example.org/bank.xlsx"
    monkeypatch.setattr(rc, "get_report_urls", lambda *args: {
        "excel_url": url, "excel_url_form1": url,
    })
    monkeypatch.setattr(rc, "_make_session", object)
    monkeypatch.setattr(rc, "parse_excel_report_document", lambda *args: pytest.fail("history must read the current source"))
    calls = []
    parsed = {"ok": True, "sheets": []}
    monkeypatch.setattr(rc, "_parse_workbook_uncached", lambda session, url: calls.append(url) or parsed)
    data = rc.fetch_report_excel_data("BRBN", "NSBU", 2024, 0, use_snapshot_cache=False)
    assert calls == [url]
    assert data["income"] is parsed and data["balance"] is parsed


def test_history_fetch_preserves_separate_statement_links(monkeypatch):
    monkeypatch.setattr(rc, "get_report_urls", lambda *args: {
        "excel_url": "income.xlsx", "excel_url_form1": "balance.xlsx",
    })
    monkeypatch.setattr(rc, "_make_session", object)
    monkeypatch.setattr(rc, "_parse_workbook_uncached", lambda session, url: {"ok": True, "url": url})
    data = rc.fetch_report_excel_data("BANK", "NSBU", 2024, 0, use_snapshot_cache=False)
    assert data["income"]["url"] == "income.xlsx"
    assert data["balance"]["url"] == "balance.xlsx"


def test_history_missing_excel_has_actionable_failure(monkeypatch):
    monkeypatch.setattr(rc, "get_report_urls", lambda *args: {"pdf_url": "report.pdf"})
    data = rc.fetch_report_excel_data("BANK", "NSBU", 2015, 0, use_snapshot_cache=False)
    assert not data["ok"]
    assert "No Excel document" in data["error"]


@pytest.mark.parametrize("due_only", [False, True])
def test_scheduled_bank_history_respects_rotation_but_manual_repair_can_force(monkeypatch, due_only):
    import sys
    args = ["collector_financials.py", "--bank-history-only", "--bank-history-limit", "3"]
    if due_only:
        args.append("--bank-history-due-only")
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(cf, "preflight", lambda *args, **kwargs: None)
    calls = []
    monkeypatch.setattr(cf, "backfill_bank_financials", lambda *args, **kwargs: calls.append((args, kwargs)) or 0)
    assert cf.main() == 0
    assert calls == [((3,), {"force": not due_only, "ticker": None})]


def test_vps_history_worker_persists_catalog_and_does_not_duplicate_stateless_run():
    import ast
    import textwrap
    from pathlib import Path
    workflow = Path(".github/workflows/ci.yml").read_text()
    start = workflow.index("          def worker(")
    end = workflow.index("          for name, content in units.items():", start)
    source = textwrap.dedent(workflow[start:end])
    ast.parse(source)
    namespace = {}
    exec(compile(source, "VPS workers", "exec"), namespace)
    units = namespace["units"]
    history = units["/etc/systemd/system/uzstock-bank-history.service"]
    assert "-v uzstock_data:/app/data" in history
    assert "--bank-history-due-only --bank-history-limit 3" in history
    assert "--cpus 0.50" in history
    assert "BANK_HISTORY_BATCH=0" in units["/etc/systemd/system/uzstock-collector.service"]
    assert "OnCalendar=*-*-* 02:00:00" in units["/etc/systemd/system/uzstock-bank-history.timer"]
    assert workflow.count("uzstock-bank-history.timer uzstock-news-collector.timer") == 2
