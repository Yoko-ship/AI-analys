"""Source reconciliation must not multiply coupons or cross issuer boundaries."""
from datetime import date, timedelta

import pytest

import bond_terms
from collectors.financials.instruments import _filed_terms_for


@pytest.mark.parametrize("nominal,amount,freq,rate,days", [
    (100_000, 5424.66, 4, 22, 90),
    (1_000_000, 150_000, 1, 15, 365),
    (100_000, 2301.37, 12, 28, 30),
    (100_000, 9473.97, 2, 19, 182),
])
def test_sparse_filings_do_not_multiply_or_reduce_the_declared_rate(nominal, amount, freq, rate, days):
    accruals = [{"amount": amount, "pay_date": date(2025, 1, 1) + timedelta(days=days * i)}
                for i in (0, 3)]
    assert bond_terms._coupon_rate(nominal, accruals, freq, rate) == (rate, days, "fixed")


def test_annual_period_is_not_rounded_to_twelve_thirty_day_months():
    accruals = [{"amount": 150_000, "pay_date": date(year, 12, 11)} for year in (2024, 2025)]
    assert bond_terms._coupon_rate(1_000_000, accruals, 1) == (15, 365, "fixed")


def test_registers_explicit_day_cycle_is_preserved():
    accruals = [{"amount": 147945.21, "pay_date": date(2025, 12, 11)}]
    assert bond_terms._coupon_rate(1_000_000, accruals, 1, 15, 360) == (15, 360, "fixed")


@pytest.mark.parametrize("found,expected", [
    ([{"id": 483, "full_name_text": '"Xorazm kafolat savdo" AJ'},
      {"id": 944, "full_name_text": '"M K Leasing" mas\'uliyati cheklangan jamiyati'}], 944),
    ([{"id": 483, "full_name_text": '"Xorazm kafolat savdo" AJ'}], None),
    ([{"id": 1, "full_name_text": '"M K Leasing" AJ'},
      {"id": 2, "full_name_text": '"M K Leasing" MChJ'}], None),
])
def test_search_result_order_does_not_establish_issuer_identity(monkeypatch, found, expected):
    import catalogue.storage

    def no_catalog():
        raise RuntimeError("No saved issuer mapping")

    monkeypatch.setattr(catalogue.storage, "get_catalog_conn", no_catalog)
    monkeypatch.setattr(bond_terms, "_get", lambda *args: found)
    assert bond_terms.resolve_org_id("MKLS3B2", "«M K LEASING» XK MChJ") == expected


def test_apostrophe_variants_match_the_same_quoted_issuer():
    assert bond_terms._issuer_name('«O`zbekiston ipotekani» AJ') == bond_terms._issuer_name(
        '"O\'ZBEKISTON IPOTEKANI" aksiyadorlik jamiyati')


def test_irregular_accrual_does_not_reclassify_fixed_contract_as_floating():
    row = {"ticker": "FIXED", "coupon_type": "fixed", "coupon_rate": 22, "coupon_freq": 4}
    filed = _filed_terms_for(row, {"coupon_type": "floating", "coupon_freq": 4,
                                  "coupon_evidence": 4, "source_url": "accrual"})
    assert {**row, **filed} == row


def test_collection_keeps_placement_date_and_coupon_evidence(monkeypatch, tmp_path):
    import provenance

    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "collected.db"))
    row = {"ticker": "BOND", "nominal": 100_000, "issue_volume": 500_000,
           "coupon_freq": 4, "coupon_rate": 22, "issue_date": "2026-04-29"}
    facts = [{"id": 3, "fact_number": 32}, {"id": 2, "fact_number": 32},
             {"id": 4, "fact_number": 32}, {"id": 1, "fact_number": 25}]
    details = {
        1: {"paper_type": 3, "nominal_paper_cost": 100_000, "paper_num": 500_000,
            "date_decision": "2026-03-05", "date_registration": "2026-04-27"},
        2: {"sum_per": 5000, "date_solution": "2026-03-05",
            "start_date_other_securities": "2026-08-11"},
        3: {"sum_per": 5424.66, "date_solution": "2026-03-05",
            "start_date_other_securities": "2026-08-11", "end_date_other_securities": "2026-08-18"},
        4: {"sum_per": 6000, "date_solution": "2026-03-05",
            "start_date_other_securities": "2025-08-11"},
    }
    monkeypatch.setattr(bond_terms, "resolve_org_id", lambda *args: 837)
    monkeypatch.setattr(bond_terms, "issuer_facts", lambda org: facts)
    monkeypatch.setattr(bond_terms, "fact_detail", lambda fact_id, **kw: details.get(fact_id))
    result = bond_terms.collect_bond_terms([row], today=date(2026, 9, 26))
    ref = {**row, **_filed_terms_for(row, result["reference"][0])}
    assert (ref["coupon_rate"], ref["coupon_freq"], ref["issue_date"]) == (22, 4, "2026-04-29")
    assert result["reference"][0]["coupon_evidence"] == 1
    assert len(result["coupons"]) == 1
    coupon = result["coupons"][0]
    assert coupon["amount"] == 5424.66
    assert coupon["source_url"].endswith("/facts/3/")
    assert coupon["is_paid"] == 0  # elapsed payment window is not proof of payment
    provenance.upsert_bond_reference([ref])
    assert provenance.upsert_bond_coupons(result["coupons"]) == 1
    saved = provenance.bond_coupons()["BOND"][0]
    assert saved["source_url"] == coupon["source_url"] and saved["is_paid"] == 0


def test_refresh_replaces_bad_persisted_rate_and_restores_yield(monkeypatch, tmp_path):
    import bonds
    import provenance

    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "bonds.db"))
    ref = {"ticker": "TESTREPAIR", "isin": "UZ6056934AA1", "nominal": 100_000,
           "coupon_rate": 66, "coupon_freq": 12, "coupon_type": "fixed",
           "issue_date": "2026-04-29", "maturity_date": "2029-04-27", "day_count": "ACT/365"}
    provenance.upsert_bond_reference([ref])
    market = {"ticker": ref["ticker"], "type": "bond", "last_price": 112_584.98,
              "last_trade_date": "2026-09-15"}
    old = bonds.bond_row(market, reference=ref, today=date(2026, 9, 26))
    assert old["yield"]["blocked_reason"] == "COUPON_RATE_IMPLAUSIBLE"
    provenance.upsert_bond_reference([{**ref, "coupon_rate": 22, "coupon_freq": 4}])
    saved = provenance.bond_references()[ref["ticker"]]
    repaired = bonds.bond_row(market, reference=saved, today=date(2026, 9, 26))
    assert repaired["reference"]["coupon_rate"] == 22
    assert repaired["ytm"]["value"] is not None
    assert repaired["yield"]["blocked_reason"] is None



@pytest.fixture
def kept(tmp_path, monkeypatch):
    import openinfo_id_cache
    monkeypatch.setattr(openinfo_id_cache, "_state_dir", lambda: tmp_path)
    monkeypatch.setenv("OPENINFO_CACHE", "1")
    monkeypatch.setattr(bond_terms, "_FACT_LISTS", openinfo_id_cache.IdCache("bond-fact-lists"))
    monkeypatch.setattr(bond_terms, "_FACT_DETAILS", openinfo_id_cache.IdCache("bond-fact-details"))
    return tmp_path


def facts_portal(monkeypatch, facts):
    """openinfo's fact list, newest first, two to a page; records every call."""
    calls = []

    def get(path, params=None):
        calls.append((path, dict(params or {})))
        if path.startswith("/disclosure/facts/") and path != "/disclosure/facts/":
            return {"fact": [{"id": int(path.strip("/").rsplit("/", 1)[1])}]}
        page = params["page"]
        return {"count": len(facts), "results": facts[(page - 1) * 2:page * 2]}
    monkeypatch.setattr(bond_terms, "_PAGE_SIZE", 2)
    monkeypatch.setattr(bond_terms, "_get", get)
    return calls


def test_a_kept_fact_list_reads_only_the_new_facts_in_front_of_it(kept, monkeypatch):
    facts = [{"id": i} for i in (5, 4, 3, 2, 1)]
    facts_portal(monkeypatch, facts[2:])
    assert bond_terms.issuer_facts(837) == facts[2:]          # first run: the whole list
    calls = facts_portal(monkeypatch, facts)
    assert bond_terms.issuer_facts(837) == facts               # next run: 5, 4 are new
    assert [p["page"] for _, p in calls] == [1, 2]             # page 2 reaches the kept 3


def test_a_count_that_does_not_add_up_reads_the_whole_list_again(kept, monkeypatch):
    facts_portal(monkeypatch, [{"id": i} for i in (3, 2, 1)])
    bond_terms.issuer_facts(837)
    withdrawn = [{"id": 4}, {"id": 3}, {"id": 1}]               # 2 was withdrawn
    calls = facts_portal(monkeypatch, withdrawn)
    assert bond_terms.issuer_facts(837) == withdrawn
    assert [p["page"] for _, p in calls] == [1, 1, 2]           # incremental, then in full


def test_only_an_approved_fact_detail_is_kept(kept, monkeypatch):
    calls = facts_portal(monkeypatch, [])
    bond_terms.fact_detail(7, keep=True)
    bond_terms.fact_detail(7, keep=True)
    bond_terms.fact_detail(8, keep=False)
    bond_terms.fact_detail(8, keep=False)
    assert [p for p, _ in calls] == ["/disclosure/facts/7/", "/disclosure/facts/8/", "/disclosure/facts/8/"]


def test_the_cache_switch_restores_the_full_read(kept, monkeypatch):
    facts_portal(monkeypatch, [{"id": 1}])
    bond_terms.issuer_facts(837)
    monkeypatch.setenv("OPENINFO_CACHE", "0")
    calls = facts_portal(monkeypatch, [{"id": 2}, {"id": 1}])
    assert bond_terms.issuer_facts(837) == [{"id": 2}, {"id": 1}]
    assert [p["page"] for _, p in calls] == [1]
