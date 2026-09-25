"""The inputs of the yield map: evidence-based day count, the reference price,
the normalised ГЦБ curve, the indicative G-spread and the sanity gates.

Amounts below are real UZSE filings: BFMT3V3 paid 2 219.18 per 100 000 at
27 % (30 days / 365), ACMT1B2 2 378.08 at 28 % (31 days), ASAK4B5
22 191 780.82 per 500 000 000 at 18 % (90 days).
"""
from datetime import date

import pytest

import bonds

TODAY = date(2026, 9, 25)


def test_day_count_is_read_off_the_issuers_own_coupons():
    ref = {"nominal": 100_000, "coupon_rate": 27}
    got = bonds.infer_day_count(ref, [{"amount": 2219.18}, {"amount": 2293.15}])
    assert got["basis"] == "ACT/365" and got["source"] == "filed_coupons" and got["evidence"] == 2
    quarterly = bonds.infer_day_count({"nominal": 500_000_000, "coupon_rate": 18}, [{"amount": 22_191_780.82}])
    assert quarterly["basis"] == "ACT/365"
    # 30 days on a 360-day year: whole days only under /360.
    assert bonds.infer_day_count(ref, [{"amount": 100_000 * 0.27 * 30 / 360}])["basis"] == "ACT/360"


def test_day_count_stays_unknown_when_a_filing_does_not_fit():
    ref = {"nominal": 100_000, "coupon_rate": 27}
    assert bonds.infer_day_count(ref, [{"amount": 2219.18}, {"amount": 2250.00}]) is None
    assert bonds.infer_day_count(ref, []) is None
    assert bonds.infer_day_count({"nominal": 100_000}, [{"amount": 2219.18}]) is None


def test_the_source_of_the_basis_is_always_named():
    ref = {"nominal": 100_000, "coupon_rate": 27}
    assert bonds.with_day_count_evidence({**ref, "day_count": "ACT/360"}, [])["day_count_source"] == "disclosed"
    assert bonds.with_day_count_evidence(ref, [{"amount": 2219.18}])["day_count_source"] == "filed_coupons"
    fallback = bonds.with_day_count_evidence(ref, [])
    assert fallback["day_count_source"] == "market_convention" and fallback["day_count"] == "ACT/365"


def _sessions(*rows):
    return [{"trade_date": d, "close_price": c, "turnover": t, "quantity": q} for d, c, t, q in rows]


def test_reference_price_is_volume_weighted_over_recent_sessions():
    history = _sessions(("20260924", 119_999, 359_997, 3), ("20260922", 122_000, 10_062_991, 88),
                        ("20260921", 107_000, 7_062_136, 66))
    got = bonds.reference_price(history, TODAY)
    assert got["method"] == "vwap" and got["sessions"] == 3
    assert got["value"] == pytest.approx((359_997 + 10_062_991 + 7_062_136) / (3 + 88 + 66))
    assert (got["from"], got["to"]) == ("2026-09-21", "2026-09-24")


def test_reference_price_falls_back_to_the_median_and_respects_the_window():
    history = _sessions(("20260924", 101, None, None), ("20260923", 150, None, None), ("20260922", 103, None, None),
                        ("20260701", 50, 5000, 100))                      # outside 30 days
    got = bonds.reference_price(history, TODAY)
    assert got["method"] == "median_close" and got["value"] == 103 and got["sessions"] == 3
    assert bonds.reference_price(_sessions(("20260701", 100, 100, 1)), TODAY) is None


@pytest.mark.parametrize("name, segment", [
    ("«Ipak Yo'li» AITB", "bank"), ("«ANOR BANK» AJ", "bank"),
    ("«O`zbekiston ipotekani qayta moliyalashtirish kompaniyasi»AJ", "mortgage"), ('"UMRC SPV" MChJ', "mortgage"),
    ("«DELTA MIKROMOLIYA TASHKILOTI» AJ", "mfo"), ("«AGAT CREDIT» MMT AJ", "mfo"),
    ("«M K LEASING» XK MChJ", "leasing"), ("«Hamkor invest lizing» MChJ", "leasing"),
    ("«SARDOBA TEKSTIL» MChJ", "corporate"),
])
def test_issuer_segments(name, segment):
    assert bonds.issuer_segment(name) == segment


def test_gov_points_are_put_on_the_corporate_basis():
    # A discount bill's simple yield compounds to a slightly higher effective one.
    assert bonds.gov_effective_rate(12.0, 182, "discount") == pytest.approx(((1 + 0.12 * 182 / 365) ** (365 / 182) - 1) * 100)
    assert bonds.gov_effective_rate(12.25, 1095, "coupon") == 12.25
    # A 3-year par bond at 12.25 % has a duration of about 2.68 years, a bill its term.
    assert bonds.gov_point_duration(12.25, 1095, "coupon") == pytest.approx(2.68, abs=0.01)
    assert bonds.gov_point_duration(11.97, 364, "discount") == pytest.approx(364 / 365)
    points = bonds.gov_curve_points([
        {"term_days": 364, "wavg_rate": 11.97, "auction_date": "2026-09-03", "income_type": "discount"},
        {"term_days": 1095, "wavg_rate": 12.25, "auction_date": "2026-09-03", "income_type": "coupon"},
    ], today=TODAY)
    assert [round(p["duration_years"], 2) for p in points] == [1.0, 2.68]
    assert points[0]["age_days"] == 22


def test_the_curve_says_when_it_is_read_beyond_its_evidence():
    points = [{"duration_years": 1.0, "rate_effective": 12.0}, {"duration_years": 2.68, "rate_effective": 12.5}]
    assert bonds.gov_curve_at(1.84, points) == (pytest.approx(12.25), False)
    assert bonds.gov_curve_at(0.4, points) == (12.0, True)
    assert bonds.gov_curve_at(5.0, points) == (12.5, True)
    # Raw auction points still work (tenor on the axis, published rate).
    assert bonds.gov_curve_at(1.0, [{"term_days": 365, "rate": 11.0}]) == (11.0, False)


REF = {"nominal": 100_000, "coupon_rate": 27, "coupon_freq": 12, "coupon_type": "fixed",
       "issue_date": "2024-11-21", "maturity_date": "2027-11-20", "isin": "UZ6057687AC0", "currency": "UZS",
       "issuer": '"BIZNES FINANS MIKROMOLIYA TASHKILOTI" MChJ'}
CURVE = [{"duration_years": 1.0, "rate_effective": 11.97}, {"duration_years": 2.68, "rate_effective": 12.25}]


def _row(price=110_000, when="2026-09-24"):
    return {"ticker": "BFMT3V3", "type": "bond", "last_price": price, "close_price": price, "last_trade_date": when}


def test_a_traded_bond_gets_an_indicative_yield_and_g_spread():
    history = _sessions(("20260924", 110_000, 1_100_000, 10), ("20260923", 108_000, 1_080_000, 10))
    row = bonds.bond_row(_row(), reference=REF, coupons=[{"amount": 2219.18}], today=TODAY,
                         gov_points=CURVE, history=history)
    assert row["day_count_source"] == "filed_coupons"
    assert row["segment"] == "mfo"
    assert row["pricing"]["method"] == "vwap" and row["pricing"]["value"] == pytest.approx(109_000)
    assert row["ytm"]["status"] == "indicative" and 10 < row["ytm"]["value"] < 30
    g = row["g_spread"]
    assert g["status"] == "indicative" and g["basis"] == "effective_annual"
    assert g["bps"] == pytest.approx((row["ytm"]["value"] - g["curve_rate"]) * 100)
    assert g["horizon_years"] == pytest.approx(row["duration"]["value"])


def test_an_untraded_bond_is_no_price_not_no_reference():
    row = bonds.bond_row({"ticker": "BFMT3V3", "type": "bond"}, reference=REF, coupons=[], today=TODAY,
                         gov_points=CURVE)
    assert row["ytm"]["value"] is None
    assert "NO_VERIFIED_TRADE" in {q["code"] for q in row["data_quality"]}
    assert row["g_spread"]["value"] is None


def test_an_implausible_coupon_blocks_the_yield_and_says_so():
    row = bonds.bond_row(_row(), reference={**REF, "coupon_rate": 66}, coupons=[], today=TODAY, gov_points=CURVE)
    assert row["ytm"]["value"] is None and row["g_spread"]["value"] is None
    assert "COUPON_RATE_IMPLAUSIBLE" in {q["code"] for q in row["data_quality"]}


def test_an_absurd_yield_is_withheld_as_a_data_fault():
    row = bonds.bond_row(_row(price=40_000), reference=REF, coupons=[], today=TODAY, gov_points=CURVE)
    assert row["ytm"]["value"] is None
    assert "YIELD_OUT_OF_RANGE" in {q["code"] for q in row["data_quality"]}
