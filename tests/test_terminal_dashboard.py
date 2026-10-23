from datetime import timedelta
from fastapi.testclient import TestClient
import api
from server.terminal import journal


def test_dashboard_uses_all_rows_not_the_first_page_and_excludes_staff():
    from server.terminal.dashboard import dashboard
    now = journal.now()
    for _ in range(1050):
        journal.emit("cmd_run", function="PL", ticker="SQBN", at=now)
    journal.emit("cmd_unknown", message="SQBX FA", at=now)
    journal.emit("cmd_run", function="FV", internal=True, at=now)
    journal.emit("screen_error", ticker="SQBN", at=now)
    journal.emit("screen_slow", ticker="SQBN", at=now)
    journal.emit("ai_published", at=now - timedelta(days=1, hours=1))
    data = dashboard(days=7, at=now)
    assert data["usage"]["commands"] == 1051
    assert data["usage"]["functions"][0] == {"name": "PL", "count": 1050}
    assert data["summary"]["hour_error_pct"] == 100 / 1050
    assert data["summary"]["ai_published_change"] == -1


def test_exact_period_journal_filters_do_not_mix_quarters_or_standards():
    journal.emit("load_ok", ticker="AGBA", standard="NSBU", period="2025")
    journal.emit("load_empty", ticker="AGBA", standard="MSFO", period="2025")
    journal.emit("load_ok", ticker="AGBA", standard="NSBU", period="2025Q1")
    result = journal.events(ticker="AGBA", standard="NSBU", period="2025")
    assert result["total"] == 1 and result["items"][0]["event"] == "load_ok"


def test_terminal_admin_apis_remain_protected():
    client = TestClient(api.app)
    for path in ("dashboard", "coverage", "export", "templates"):
        assert client.get("/api/admin/terminal/" + path).status_code == 401


def test_coverage_distinguishes_unpublished_year_from_an_empty_filed_year(monkeypatch):
    import asyncio
    import catalogue.filings as filings
    import server.company.financials as financials
    from server.terminal import service
    from server.terminal.dashboard import coverage
    monkeypatch.setattr(service,'universe',lambda:[{'ticker':'UTGA','name':'UTGA'},{'ticker':'SQBN','name':'SQBN'}])
    monkeypatch.setattr(filings,'get_company_reports',lambda t:[] if t=='UTGA' else [{'report_form':'NSBU','year':2024,'quarter':0,'excel_url':'https://openinfo.uz/empty.xlsx'}])
    async def empty(*args):return {'periods':[],'series':{},'data_gaps':[]}
    monkeypatch.setattr(financials,'financial_series',empty)
    rows={r['ticker']:r for r in asyncio.run(coverage())['rows']}
    assert rows['UTGA']['cells']['2024']=='unpublished'
    assert rows['SQBN']['cells']['2024']=='gap'
