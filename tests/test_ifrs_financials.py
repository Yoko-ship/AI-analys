"""IFRS PDFs have their own units, years, signed amounts and source passports."""
from copy import deepcopy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

import api
import ifrs_financials as ifrs
import provenance
import reports_catalog as rc


@pytest.mark.parametrize("url", [
    "https://mkbank.uz/upload/unreviewed.pdf",
    "https://openinfo.uz:8443/media/test.pdf",
    "https://user@openinfo.uz/media/test.pdf",
    "http://openinfo.uz/media/test.pdf",
    "https://openinfo.uz.evil.example/media/test.pdf",
])
def test_download_rejects_unapproved_source_before_network(monkeypatch, url):
    monkeypatch.setattr(ifrs.requests, "get", lambda *a, **kw: pytest.fail("Unexpected network request"))
    with pytest.raises(ValueError, match="IFRS source must"):
        ifrs.download_pdf(url)


def test_download_reviewed_issuer_source_and_limits(monkeypatch):
    from financial_ingestion import extract
    url = "https://mkbank.uz/upload/reviewed.pdf"
    monkeypatch.setattr(extract, "review_entries", lambda: [{"pdf_url": url}])
    monkeypatch.setattr(ifrs, "MAX_BYTES", 4)

    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        def iter_content(self, size):
            yield b"%PDF-1.7"

    response = Response()
    def get(source, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        return response
    monkeypatch.setattr(ifrs.requests, "get", get)
    assert ifrs.download_pdf(url) == b"%PDF-1.7"
    with pytest.raises(ValueError, match="download limit"):
        ifrs.download_pdf("https://openinfo.uz/media/unreviewed.pdf")
    response.status_code = 302
    with pytest.raises(ValueError, match="redirect/status"):
        ifrs.download_pdf(url)


@pytest.fixture
def review(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "ifrs.db"))
    monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a: None)
    stream = io.BytesIO()
    doc = canvas.Canvas(stream)
    doc.drawString(20, 20, "Synthetic test PDF, not a production filing")
    doc.save()
    payload = stream.getvalue()
    entry = deepcopy(ifrs.reviews()[0])
    entry["page_count"] = 1
    entry["sha256"] = hashlib.sha256(payload).hexdigest()
    for f in entry["figures"].values():
        f["page"] = 1
    conn = rc.get_catalog_conn()
    with conn:
        for ticker in ("BRBN", "BRBNP"):
            conn.execute("INSERT INTO catalog_companies (ticker,company_name,org_id) VALUES (?,?,?)",
                         (ticker, "Test bank", "23"))
        rc._upsert_report(conn, "BRBN", report_form="MSFO", period_type="annual", year=2024,
                          quarter=0, title="Test", published_at="2025-07-17", pdf_url=entry["pdf_url"],
                          excel_url=None, excel_url_form1=None, openinfo_report_id="3054", object_id=None)
    conn.close()
    return entry, payload


def run(review, apply=True, ticker="BRBN"):
    entry, payload = review
    return ifrs.import_reviewed(ticker, apply=apply, entries=[entry], fetch=lambda url: payload)


def test_dry_run_checks_source_without_publishing(review):
    result = run(review, apply=False)
    assert result["verified"] == [2024]
    assert result["published"] == []
    assert rc.get_financials_series("BRBN", "MSFO") == {}


def test_import_converts_millions_once_keeps_losses_and_source_pages(review):
    result = run(review)
    assert result["published"] == [2024]
    assert not result["errors"]
    values = rc.get_financials_series("BRBNP", "MSFO")["2024"]
    assert values["total_assets"] == 31_596_795_000  # stored THOUSANDS
    assert values["net_income"] == -1_367_921_000
    assert values["interest_income"] == 4_473_647_000
    assert values["interest_expense"] == -2_417_950_000
    assert "revenue" not in values and "gross_profit" not in values
    passport = rc.get_financial_value_passport("BRBN", "2024", "net_profit", "MSFO")
    assert passport["status"] == "SOURCED"
    source = passport["source"]
    assert source["page"] == 1
    assert source["raw_value"] == -1_367_921
    assert source["unit_scale"] == 1_000_000
    assert source["normalized_value"] == -1_367_921_000_000
    assert source["file_hash"] == review[0]["sha256"]
    assert source["extraction_version"] == ifrs.VERSION
    assert rc.get_financial_value_passport("BRBN", "2024", "interest_income", "MSFO")["status"] == "SOURCED"
    assert rc.get_financial_history_coverage("MSFO")["BRBN"]["status"] == "COLLECTED"


def test_api_uses_bank_lines_without_fabricating_revenue_or_nsbu_ratios(review, monkeypatch):
    run(review)
    rc.upsert_financials_cache("BRBN", "NSBU", 2024, 0, {"revenue": 99})
    monkeypatch.setattr(api, "get_facts", lambda *a, **kw: [
        {"field": "roe", "period": "2024", "value_num": 99, "dataset": "financial_indicators"}])
    got = TestClient(api.app).get("/api/company/BRBN/financials?form=MSFO").json()
    assert got["availability"] == "AVAILABLE"
    assert got["periods"] == ["2024"]
    assert got["series"]["interest_income"]["unit"] == "UZS"
    assert got["series"]["interest_income"]["values"]["2024"] == 4_473_647_000_000
    assert got["series"]["operating_expenses"]["values"]["2024"] == -1_110_514_000_000
    assert not ({"net_revenue", "gross_profit", "roe", "net_margin"} & got["series"].keys())
    assert rc.get_financials_series("BRBN", "NSBU")["2024"]["revenue"] == 99


def test_idempotent_and_preferred_share_import_does_not_duplicate_rows(review):
    run(review)
    run(review, ticker="BRBNP")
    conn = rc.get_catalog_conn()
    assert conn.execute("SELECT COUNT(*) FROM catalog_financials WHERE form='MSFO'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM report_figures").fetchone()[0] == 9
    conn.close()


def test_changed_pdf_is_rejected_without_overwriting_existing_figures(review):
    run(review)
    before = rc.get_financials_series("BRBN", "MSFO")
    entry, payload = review
    result = ifrs.import_reviewed("BRBN", apply=True, entries=[entry], fetch=lambda url: payload + b"changed")
    assert "changed" in result["errors"][0]["reason"]
    assert not result["published"]
    assert rc.get_financials_series("BRBN", "MSFO") == before


def test_year_correction_is_verified_and_survives_future_syncs(review, monkeypatch):
    entry, _ = review
    conn = rc.get_catalog_conn()
    with conn:
        conn.execute("UPDATE catalog_reports SET year=2025")
    monkeypatch.setattr(ifrs, "reviews", lambda: [entry])
    assert ifrs.reviewed_catalog_year(conn, "23", entry["pdf_url"], 2025) == 2025
    conn.close()
    assert run(review)["published"] == [2024]
    conn = rc.get_catalog_conn()
    assert conn.execute("SELECT year FROM catalog_reports").fetchone()[0] == 2024
    assert ifrs.reviewed_catalog_year(conn, "23", entry["pdf_url"], 2025) == 2024
    assert ifrs.reviewed_catalog_year(conn, "24", entry["pdf_url"], 2025) == 2025
    assert ifrs.reviewed_catalog_year(conn, "23", "https://openinfo.uz/media/other.pdf", 2025) == 2025
    conn.close()


def test_review_cannot_be_applied_to_a_different_issuer_or_url(review):
    entry, _ = review
    entry["org_id"] = "24"
    assert run(review)["published"] == []
    entry["org_id"] = "23"
    entry["pdf_url"] += "wrong"
    result = run(review)
    assert "not catalogued" in result["errors"][0]["reason"]
    assert not result["published"]


@pytest.mark.parametrize("change,reason", [
    ({"currency": "USD"}, "currency"),
    ({"scope": "separate"}, "perimeter"),
    ({"unit_scale": 1}, "unit"),
    ({"year": 2099}, "period"),
    ({"review_method": "ocr"}, "Unreviewed"),
    ({"period_evidence": ""}, "evidence"),
    ({"page_count": 2}, "page count"),
])
def test_rejects_ambiguous_document_metadata(review, change, reason):
    entry, payload = review
    entry.update(change)
    with pytest.raises(ValueError, match=reason):
        ifrs.validate_review(entry, payload)


@pytest.mark.parametrize("field,change,reason", [
    ("cash", {"page": 0}, "page"),
    ("cash", {"column_year": 2023}, "year column"),
    ("cash", {"raw_label": ""}, "label"),
    ("total_assets", {"raw_value": "1"}, "reconcile"),
    ("interest_expense", {"raw_value": "2417950"}, "sign"),
    ("net_income", {"raw_value": "NaN"}, "decimal"),
    ("net_income", {"raw_value": "1,000"}, "decimal"),
])
def test_rejects_ambiguous_or_inconsistent_figures(review, field, change, reason):
    entry, payload = review
    entry["figures"][field].update(change)
    with pytest.raises(ValueError, match=reason):
        ifrs.validate_review(entry, payload)


def test_thousands_are_not_scaled_twice_and_zero_is_preserved(review):
    entry, payload = review
    entry["unit_scale"] = 1000
    entry["figures"]["net_income"]["raw_value"] = "0"
    values = ifrs.validate_review(entry, payload)
    assert values["cash"] == 2_341_951
    assert values["net_income"] == 0


def test_review_ledger_has_seven_distinct_brbn_periods_and_complete_evidence():
    entries = ifrs.reviews()
    assert {e["year"] for e in entries if e["ticker"] == "BRBN"} == {2016, 2018, 2019, 2021, 2022, 2023, 2024}
    for entry in entries:
        assert len(entry["sha256"]) == 64
        assert set(entry["figures"]) == set(ifrs.FIELDS)
        amounts = {k: ifrs._number(v["raw_value"]) for k, v in entry["figures"].items()}
        assert abs(amounts["total_assets"] - amounts["total_liabilities"] - amounts["total_equity"]) <= 1
