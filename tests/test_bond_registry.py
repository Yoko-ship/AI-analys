"""The exchange's register of circulating issues, and the maths it unblocks.

``bonds.py`` was built on the finding that "the coupon rate, the maturity date
and the payment schedule are genuinely absent — searched for on the issue page
and in the card, they are not there". True of the security card; not true of the
exchange. uzse.uz publishes the whole register at ``/abouts/bonds/``, and with
it the yield half of the section stops being inert.

These tests fix the three things that could quietly go wrong with that:

* the register is a **spreadsheet a human maintains** — it already contradicts
  itself once (one ticker over two ISINs), so nothing may be trusted by position;
* the schedule between the two filed ends is a **reconstruction**, and every
  payload built on it has to say so;
* a **registered undertaking is not an executed fact**, so the filing wins.
"""
from __future__ import annotations

from datetime import date

import pytest

import bond_registry
import bonds

# A slice of the live sheet, verbatim: the title row above the header, the
# merged issuer cell left blank down a series, the trailing space inside an
# ISIN, the floating rate written as a formula, and the collision.
SHEET = """,Listing,,,,,,,,,,,
№,Eminentning nomi,Bozor segmenti,Tiker,QQ kodi,Nominal qiymati,QQ soni,Foiz stavkasi,Joylashtirish/muomalaga kiritish sanasi,So‘ndirish (to‘lash) sanasi,Joylashtirilgan QQ soni*,Kupon to‘lovini amalga oshirish usuli,Kupon to‘lovi davri (sikli)
1, «Kapitalbank» ATB,Bond Market,KPB4,UZ6047447AA6,1 000 000,50 000,MB qayta moliyalash stavkasi + 5 %,13.05.2020,21.05.2027,50 000,pul,Har oyda
2,«Biznes finans» MMT,Bond Market,BFMT3V2,UZ6057687AB2 ,100 000,200 000,"27,00%",09.10.2023,13.09.2026,200 000,pul,Har oyda
,,Bond Market,BFMT3V3,UZ6057687AC0,100 000,300 000,"27,00%",29.11.2024,20.11.2027,300 000,pul,Har 30 kunda
3,«O`IQMK» AJ,Bond Market,IQMK5E,UZ6056887AC7,1 000 000,50 000,"18,00%",16.09.2024,18.09.2029,50 000,pul,Har chorakda
4,«UMRC SPV» MChJ,Bond Market,OUSP19B3,UZ6059364AA8,100,401 360 998,"0,00%",31.07.2026,23.08.2045,,pul,Har 30 kunda
,,Bond Market,OUSP19B3,UZ6059367AB9,100,396 342 030,"0,00%",13.08.2026,13.08.2045,,pul,Har 30 kunda
5,«Natural Juice» MChJ,Bond Market,ONLJ4,UZ6057777AA3,1 000 000,15 000,"15,00%",15.12.2022,10.12.2027,15 000,pul,Yillik
"""


class TestRegisterParsing:
    def test_the_header_is_found_by_name_not_by_row_number(self):
        """A title row sits above it, and the sheet gains banners over time."""
        rows = bond_registry.parse_registry(SHEET)
        assert {r["ticker"] for r in rows} >= {"KPB4", "BFMT3V2", "IQMK5E", "ONLJ4"}

    def test_a_merged_issuer_cell_carries_down_its_series(self):
        rows = {r["ticker"]: r for r in bond_registry.parse_registry(SHEET)}
        # BFMT3V3's own row leaves the issuer blank — the sheet writes the name
        # once and merges it over the block.
        assert rows["BFMT3V3"]["issuer"] == rows["BFMT3V2"]["issuer"]

    def test_terms_land_as_numbers_and_iso_dates(self):
        rows = {r["ticker"]: r for r in bond_registry.parse_registry(SHEET)}
        one = rows["IQMK5E"]
        assert one["nominal"] == 1_000_000
        assert one["issue_volume"] == 50_000
        assert one["coupon_rate"] == 18.0
        assert one["coupon_freq"] == 4
        assert one["issue_date"] == "2024-09-16"
        assert one["maturity_date"] == "2029-09-18"

    def test_a_trailing_space_inside_an_isin_is_not_part_of_the_isin(self):
        rows = {r["ticker"]: r for r in bond_registry.parse_registry(SHEET)}
        assert rows["BFMT3V2"]["isin"] == "UZ6057687AB2"

    def test_a_rate_written_as_a_formula_is_floating_not_missing(self):
        """«MB qayta moliyalash stavkasi + 5 %» is a coupon — it is just not a
        number. Resolving it here would freeze the margin at today's key rate."""
        rows = {r["ticker"]: r for r in bond_registry.parse_registry(SHEET)}
        kpb = rows["KPB4"]
        assert kpb["coupon_rate"] is None
        assert kpb["coupon_type"] == "floating"
        assert "moliyalash" in kpb["float_base"]

    def test_a_zero_rate_is_a_rate(self):
        rows = {r["ticker"]: r for r in bond_registry.parse_registry(SHEET)}
        assert rows["OUSP19B3"]["coupon_rate"] == 0.0
        assert rows["OUSP19B3"]["coupon_type"] == "zero"

    @pytest.mark.parametrize("cycle,freq", [
        ("Har oyda", 12), ("Har 30 kunda", 12), ("Har chorakda", 4),
        ("Har 90 kunda", 4), ("Yarim yillik", 2), ("Yillik", 1),
    ])
    def test_the_cycle_vocabulary(self, cycle, freq):
        assert bond_registry.coupon_frequency(cycle) == freq

    def test_a_cycle_nobody_can_read_is_not_a_licence_to_assume_two(self):
        assert bond_registry.coupon_frequency("shartnomaga muvofiq") is None
        assert bond_registry.coupon_frequency("") is None


class TestSelfContradiction:
    def test_one_ticker_over_two_isins_publishes_nothing(self):
        """Live sheet, 2026-08-20: OUSP19B3 is written twice, over different
        ISINs, sizes and redemption dates. Taking the first would attach one
        series' terms to whichever paper actually trades under that code."""
        rows = bond_registry.resolve_ticker_conflicts(bond_registry.parse_registry(SHEET))
        assert "OUSP19B3" not in {r["ticker"] for r in rows}
        # And the rest of the register is unaffected by the one bad row.
        assert {"KPB4", "BFMT3V2", "IQMK5E", "ONLJ4"} <= {r["ticker"] for r in rows}

    def test_the_board_settles_the_collision_when_it_knows_the_traded_isin(self):
        rows = bond_registry.resolve_ticker_conflicts(
            bond_registry.parse_registry(SHEET),
            {"OUSP19B3": "UZ6059367AB9"})
        picked = next(r for r in rows if r["ticker"] == "OUSP19B3")
        assert picked["isin"] == "UZ6059367AB9"
        assert picked["maturity_date"] == "2045-08-13"


class TestSourcePrecedence:
    def test_the_card_wins_on_the_par_and_the_register_fills_the_terms(self):
        merged = {r["ticker"]: r for r in bond_registry.merge_reference(
            [{"ticker": "IQMK5E", "isin": "UZ6056887AC7", "nominal": 1_000_000.0,
              "source_url": "https://uzse.uz/isu_infos/BND?isu_cd=UZ6056887AC7"}],
            bond_registry.parse_registry(SHEET))}
        one = merged["IQMK5E"]
        assert one["source_url"].startswith("https://uzse.uz/isu_infos/")
        assert one["coupon_rate"] == 18.0 and one["maturity_date"] == "2029-09-18"

    def test_an_issue_the_card_walk_never_saw_is_still_added(self):
        """The walk starts from openinfo's info_rfb, which has no entry for an
        LLC issuer; the register has all of them."""
        merged = {r["ticker"] for r in bond_registry.merge_reference([], bond_registry.parse_registry(SHEET))}
        assert "ONLJ4" in merged


REF = {"ticker": "IQMK5E", "nominal": 1_000_000.0, "coupon_rate": 18.0,
       "coupon_freq": 4, "issue_date": "2024-09-16", "maturity_date": "2029-09-18"}
TODAY = date(2026, 8, 20)


class TestSchedule:
    def test_the_reconstruction_says_it_is_one(self):
        schedule = bonds.coupon_schedule(REF)
        assert schedule["source"] == "reconstructed"
        # Five years, quarterly.
        assert len(schedule["dates"]) == 20
        assert schedule["dates"][-1] == date(2029, 9, 18)
        assert schedule["amount"] == pytest.approx(45_000.0)

    def test_filed_payments_win_where_they_reach_redemption(self):
        filed = [{"pay_date": "2029-03-18", "amount": 45_000.0},
                 {"pay_date": "2029-09-18", "amount": 45_000.0}]
        schedule = bonds.coupon_schedule({**REF, "maturity_date": "2029-09-18"}, filed)
        assert schedule["source"] == "filed"
        assert schedule["dates"] == [date(2029, 3, 18), date(2029, 9, 18)]

    def test_a_filing_that_stops_short_only_corrects_the_reconstruction(self):
        """Issuers file one payment at a time. Treating two filed coupons as
        the whole schedule would discount a five-year bond as a one-year one."""
        schedule = bonds.coupon_schedule(REF, [{"pay_date": "2026-09-19", "amount": 45_000.0}])
        assert schedule["source"] == "reconstructed"
        assert len(schedule["dates"]) == 20
        # The filed date replaces the guess it lands beside, and does not add a
        # twenty-first payment.
        assert date(2026, 9, 19) in schedule["dates"]

    def test_without_two_ends_there_is_no_schedule(self):
        assert bonds.coupon_schedule({"nominal": 1000, "coupon_rate": 10})["dates"] == []
        assert bonds.coupon_schedule({"nominal": 1000, "coupon_rate": 10})["source"] is None


class TestYieldsTheRegisterUnblocks:
    def test_the_whole_stream_is_discounted_not_only_the_announced_coupon(self):
        """The regression this source fixes. Before it, the only future
        payments known were the ones the issuer had already announced —
        usually the next one — so a five-year bond was priced as if it paid one
        coupon and then the principal."""
        schedule = bonds.coupon_schedule(REF)
        flows = bonds.coupon_cashflows(REF, [], TODAY, schedule)
        # Thirteen coupons left plus the redemption of principal.
        assert len(flows) == 14
        assert flows[-1][1] == pytest.approx(1_000_000.0)

    def test_effective_yield_at_par_compounds_the_frequency(self):
        """A 27% coupon paid monthly returns 30,6% at par to a holder who
        reinvests — and this is the only yield an untraded issue has."""
        assert bonds.effective_yield_at_par(27.0, 12)["value"] == pytest.approx(30.60, abs=0.01)
        assert bonds.effective_yield_at_par(18.0, 4)["value"] == pytest.approx(19.25, abs=0.01)
        assert bonds.effective_yield_at_par(20.0, 1)["value"] == pytest.approx(20.0)

    def test_a_floating_coupon_has_no_yield_at_par_and_says_so(self):
        assert bonds.effective_yield_at_par(None, 12)["value"] is None

    def test_a_zero_coupon_issue_gets_a_yield_from_its_discount(self):
        """Five UMRC SPV series state «0,00%». A truth test on the rate read
        that as "no coupon disclosed" and withheld the most computable yields
        on the board."""
        ref = {"nominal": 100.0, "coupon_rate": 0.0, "coupon_freq": 12,
               "issue_date": "2026-08-13", "maturity_date": "2045-08-13"}
        row = bonds.bond_row({"ticker": "OUSP19B5", "type": "bond",
                              "last_price": 12.0, "close_price": 12.0},
                             reference=ref, coupons=[], today=TODAY)
        assert row["ytm"]["value"] == pytest.approx(11.8, abs=0.3)
        assert row["duration"]["value"] == pytest.approx(19.0, abs=0.2)
        assert row["accrued"]["value"] == 0.0

    def test_accrual_runs_from_the_latest_evidence_a_period_closed(self):
        row = bonds.bond_row({"ticker": "IQMK5E", "type": "bond",
                              "last_price": 1_000_000.0, "close_price": 1_000_000.0},
                             reference=REF, coupons=[], today=TODAY)
        # Reconstructed periods land 2026-06-18 → 2026-09-17; 63 days earned of
        # a 45 000 coupon, on a 365-day basis.
        assert row["accrued"]["value"] == pytest.approx(1_000_000 * 0.18 * 63 / 365, rel=0.05)
        assert row["accrued"]["value"] < 45_000

    def test_before_the_first_coupon_accrual_runs_from_placement(self):
        ref = {**REF, "issue_date": "2026-08-01", "maturity_date": "2031-08-01"}
        row = bonds.bond_row({"ticker": "X", "type": "bond", "last_price": 1_000_000.0},
                             reference=ref, coupons=[], today=TODAY)
        assert row["accrued"]["value"] == pytest.approx(1_000_000 * 0.18 * 19 / 365, rel=0.02)


class TestStatesAndResults:
    def test_the_row_names_its_state(self):
        live = bonds.bond_row({"ticker": "IQMK5E", "type": "bond", "last_price": 1e6},
                              reference=REF, today=TODAY)
        assert live["state"] == "live"
        placing = bonds.bond_row({"ticker": "X", "type": "bond", "last_price": None},
                                 reference={**REF, "issue_date": "2026-12-01",
                                            "maturity_date": "2030-12-01"}, today=TODAY)
        assert placing["state"] == "placing"
        last = bonds.bond_row({"ticker": "Y", "type": "bond", "last_price": 1e6},
                              reference={**REF, "issue_date": "2024-01-10",
                                         "maturity_date": "2026-10-10"}, today=TODAY)
        assert last["state"] == "last"

    def test_a_redeemed_issue_reports_what_it_returned_instead_of_a_blank(self):
        ref = {**REF, "issue_date": "2021-09-16", "maturity_date": "2026-03-18"}
        row = bonds.bond_row({"ticker": "Z", "type": "bond", "last_price": 1e6},
                             reference=ref, today=TODAY)
        assert row["state"] == "matured"
        assert row["ytm"]["value"] is None and row["ytm"]["status"] == "matured"
        # Eighteen quarterly coupons of 45 000 on a par of 1 000 000 over four
        # and a half years: 81% of par accumulated, 14,1% a year. NOT the 19,25%
        # the coupon compounds to — the holder is not assumed to have reinvested,
        # and the note says as much.
        assert row["realized"]["value"] == pytest.approx(14.08, abs=0.1)
        assert row["realized"]["coupons_paid"] == 18
        assert "не реинвестируются" in row["realized"]["note"]

    def test_the_schedule_block_counts_paid_and_remaining_payments(self):
        row = bonds.bond_row({"ticker": "IQMK5E", "type": "bond", "last_price": 1e6},
                             reference=REF, today=TODAY)
        block = row["schedule"]
        assert block["source"] == "reconstructed"
        assert block["total"] == 20
        assert block["paid"] + block["left"] == 20
        assert block["next_date"] > TODAY.isoformat()


class TestProvenanceOfTerms:
    def test_the_reference_names_which_source_states_each_term(self):
        state = bonds.reference_state({**REF, "coupon_source": "exchange_registry",
                                       "maturity_source": "openinfo_facts"})
        assert state["coupon_source"] == "exchange_registry"
        assert state["maturity_source"] == "openinfo_facts"

    def test_a_reference_with_no_source_recorded_says_nothing_rather_than_guessing(self):
        state = bonds.reference_state(REF)
        assert state["coupon_source"] is None and state["maturity_source"] is None


class TestTheBoardIsNotTheUniverse:
    def test_a_registered_issue_that_never_traded_still_appears(self):
        """Sixty-five issues are registered and about a sixth print on any given
        day. A section built from the trade feed alone told the reader the other
        fifty do not exist, rather than that nobody bought one lately."""
        board = bonds.build_bond_board(
            [{"ticker": "IQMK5E", "type": "bond", "last_price": 1_000_000.0}],
            references={"IQMK5E": REF,
                        "ONLJ4": {"ticker": "ONLJ4", "nominal": 1_000_000.0,
                                  "coupon_rate": 15.0, "coupon_freq": 1,
                                  "issue_date": "2022-12-15",
                                  "maturity_date": "2027-12-10",
                                  "issuer": "«NATURAL JUICE» MChJ"}})
        tickers = {r["ticker"] for r in board["items"]}
        assert tickers == {"IQMK5E", "ONLJ4"}
        untraded = next(r for r in board["items"] if r["ticker"] == "ONLJ4")
        assert untraded["price"] is None
        assert untraded["status"] == "not_traded"
        # And it is not empty: its terms are real and its yield at par is
        # computable without anyone ever having bought one.
        assert untraded["effective_at_par"]["value"] == pytest.approx(15.0)
        assert untraded["reference"]["is_complete"] is True


class TestPaymentCalendar:
    REFS = {
        "IQMK5E": {**REF, "placed_volume": 50_000.0, "issue_volume": 50_000.0,
                   "issuer": "«O`IQMK» AJ"},
        "ONLJ4": {"ticker": "ONLJ4", "nominal": 1_000_000.0, "coupon_rate": 15.0,
                  "coupon_freq": 1, "issue_date": "2022-12-15",
                  "maturity_date": "2027-12-10", "issue_volume": 15_000.0,
                  "issuer": "«NATURAL JUICE» MChJ"},
    }

    def test_every_scheduled_payment_of_every_issue_is_in_it(self):
        cal = bonds.market_cashflows(self.REFS, {}, TODAY, horizon_months=24)
        assert cal["issues"] == 2
        # Quarterly to Sep 2029 and annual to Dec 2027, inside a 24-month window.
        assert len(cal["flows"]) >= 8
        assert cal["flows"] == sorted(cal["flows"], key=lambda f: f["date"])

    def test_a_coupon_is_per_security_times_the_securities_placed(self):
        cal = bonds.market_cashflows(self.REFS, {}, TODAY)
        one = next(f for f in cal["flows"] if f["ticker"] == "IQMK5E")
        assert one["per_security"] == pytest.approx(45_000.0)
        assert one["coupon"] == pytest.approx(45_000.0 * 50_000)

    def test_the_placed_count_is_preferred_to_the_registered_one(self):
        """«QQ soni» is what was registered, «Joylashtirilgan QQ soni» what
        found a buyer. The money that leaves the issuer follows the second."""
        refs = {"X": {**REF, "issue_volume": 10_000.0, "placed_volume": 8_207.0}}
        cal = bonds.market_cashflows(refs, {}, TODAY)
        assert cal["flows"][0]["securities"] == 8_207.0

    def test_principal_lands_only_on_the_redemption_date(self):
        cal = bonds.market_cashflows(self.REFS, {}, TODAY, horizon_months=24)
        principal = [f for f in cal["flows"] if f["principal"]]
        assert [f["date"] for f in principal] == ["2027-12-10"]
        assert principal[0]["principal"] == pytest.approx(1_000_000.0 * 15_000)

    def test_the_months_are_a_contiguous_run_starting_this_month(self):
        cal = bonds.market_cashflows(self.REFS, {}, TODAY, horizon_months=14)
        assert len(cal["months"]) == 14
        assert (cal["months"][0]["year"], cal["months"][0]["month"]) == (2026, 8)
        assert (cal["months"][-1]["year"], cal["months"][-1]["month"]) == (2027, 9)
        # A month with no payment is still a month, and prints as an empty bar.
        assert all("coupon" in m and "principal" in m for m in cal["months"])

    def test_the_calendar_says_how_much_of_it_is_reconstructed(self):
        cal = bonds.market_cashflows(self.REFS, {}, TODAY)
        assert cal["reconstructed"] == len(cal["flows"])
        assert all(f["source"] == "reconstructed" for f in cal["flows"])
