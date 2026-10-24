"""T-16: dividends and capitalisation of UTGA, OCBK, UZAS, UVGT and ORFI.

Fixtures are the live rows as read on 2026-10-17 (openinfo's dividend calendar,
openinfo organization cards, uzstock.uz /api/market/multiples). Each defect is
pinned by the general rule that fixes it, with the cases the rule must NOT touch
next to the ones it must.
"""
from __future__ import annotations

from datetime import date

import pytest

import dividends
import fundamentals
import listings_collector as lc


def cal(fid, org, decision, pub, *, common=0.0, cs=None, ce=None,
        pref=0.0, ps=None, pe=None, name="issuer"):
    """One row of openinfo's /disclosure/dividend-calendar/, as served."""
    return {
        "id": fid, "organization_id": org, "organization": name, "ticker": None,
        "decision_date": decision, "pub_date": pub,
        "link": f"https://openinfo.uz/facts/32/{fid}",
        "common_share_amount": common, "common_share_percent": "0E-10",
        "common_share_start_date": cs, "common_share_end_date": ce,
        "priviliged_share_amount": pref, "priviliged_share_percent": "0E-10",
        "priviliged_share_start_date": ps, "priviliged_share_end_date": pe,
        "bond_amount": 0.0, "bond_percent": "0E-10",
        "bond_start_date": None, "bond_end_date": None,
    }


def ids(items):
    return sorted(int(i["filing_id"]) for i in items)


def collapse(*rows):
    kept, gone = dividends.collapse_refilings([dividends.normalize_row(r) for r in rows])
    return kept, gone


# ---------------------------------------------------------------------------
# One dividend, one record
# ---------------------------------------------------------------------------

class TestRefilings:
    def test_orfi_2016_correction_replaces_the_first_filing(self):
        """ORFI's 2016 register (31.05–29.07) was filed at 1 355 сум, then
        refiled a month later at 215 сум. Its decision date (28.07) postdates
        its own publication (01.07), so the window is what identifies it."""
        kept, gone = collapse(
            cal(81, "16", "2016-05-30", "2016-06-02T05:22:08", common=1355.0,
                cs="2016-05-31", ce="2016-07-29"),
            cal(171, "16", "2016-07-28", "2016-07-01T07:11:12", common=215.0,
                cs="2016-05-31", ce="2016-07-29"),
            cal(547, "16", "2017-05-31", "2017-06-06T08:10:56", common=700.0,
                cs="2017-06-01", ce="2017-07-29"),
        )
        assert ids(kept) == [171, 547]
        assert [(g["filing_id"], g["superseded_by"]) for g in gone] == [("81", "171")]

    def test_orfi_equal_ordinary_and_preferred_amounts_are_one_filing(self):
        """ORFI 2024–2026 declare the same amount for both classes: that is
        one filing with two columns, not a doubled dividend."""
        kept, gone = collapse(
            cal(4061, "16", "2026-06-26", "2026-07-02T11:17:18", common=458.88,
                cs="2026-06-26", ce="2026-08-25", pref=458.88, ps="2026-06-26", pe="2026-08-25"),
            cal(3577, "16", "2025-06-19", "2025-06-26T10:09:59", common=542.85,
                cs="2025-06-19", ce="2025-08-18", pref=542.85, ps="2025-06-19", pe="2025-08-18"),
        )
        assert ids(kept) == [3577, 4061] and not gone

    def test_a_resubmission_is_one_dividend(self):
        """Ammofos-Maxam filed 10 374,68 сум for 30.06.2017 twice (772, 833)."""
        kept, gone = collapse(
            cal(772, "373", "2017-06-30", "2017-07-13T10:00:00", common=10374.68,
                cs="2017-06-30", ce="2017-08-30"),
            cal(833, "373", "2017-06-30", "2017-09-08T10:00:00", common=10374.68,
                cs="2017-06-30", ce="2017-08-30"),
        )
        assert ids(kept) == [833] and gone[0]["superseded_by"] == "833"

    def test_same_day_filings_with_different_amounts_both_stand(self):
        """DD General filed 30,34 and 347,21 сум for one window on one day —
        possibly two payouts; the calendar cannot tell, so nothing is folded."""
        kept, gone = collapse(
            cal(2448, "879", "2022-06-27", "2022-06-28T09:00:00", common=30.34,
                cs="2022-06-27", ce="2022-08-25"),
            cal(2449, "879", "2022-06-27", "2022-06-28T15:00:00", common=347.21,
                cs="2022-06-27", ce="2022-08-25"),
        )
        assert ids(kept) == [2448, 2449] and not gone

    def test_a_later_years_decision_reusing_a_window_is_not_a_correction(self):
        """Surxondaryodonmahsulotlari's 2022 decision repeats its 2021 window,
        published a year after that window closed: two dividends."""
        kept, gone = collapse(
            cal(2019, "334", "2021-03-31", "2021-04-25T10:00:00", common=1172.65,
                cs="2021-04-01", ce="2021-06-01"),
            cal(2371, "334", "2022-03-31", "2022-04-12T10:00:00", common=44.18,
                cs="2021-04-01", ce="2021-06-01"),
        )
        assert ids(kept) == [2019, 2371] and not gone

    def test_quarterly_payers_keep_every_quarter(self):
        """Kapitalbank's preferred line pays 209 сум every quarter."""
        rows = [cal(fid, "29", day, f"{day}T10:00:00", pref=209.0)
                for fid, day in ((1969, "2021-02-17"), (1996, "2021-04-06"),
                                 (2184, "2021-07-08"), (2309, "2021-10-11"))]
        kept, gone = collapse(*rows)
        assert len(kept) == 4 and not gone

    def test_a_correction_of_one_class_leaves_the_other(self):
        """Jizzax HETK 1719 declared both classes; 1730, a day later, restated
        only the preferred one — 1719's ordinary payout stands."""
        kept, gone = collapse(
            cal(1719, "169", "2020-06-30", "2020-07-01T10:00:00", common=50.0,
                cs="2020-07-10", ce="2020-09-07", pref=250.0, ps="2020-07-10", pe="2020-09-07"),
            cal(1730, "169", "2020-06-30", "2020-07-02T10:00:00",
                pref=250.0, ps="2020-07-10", pe="2020-09-07"),
        )
        assert not gone
        first = next(k for k in kept if k["filing_id"] == "1719")
        assert first["ordinary_amount"] == 50.0 and first["preferred_amount"] is None

    def test_two_issuers_never_fold_into_each_other(self):
        kept, gone = collapse(
            cal(1, "10", "2025-06-30", "2025-07-01T10:00:00", common=100.0,
                cs="2025-07-01", ce="2025-08-30"),
            cal(2, "11", "2025-06-30", "2025-07-02T10:00:00", common=100.0,
                cs="2025-07-01", ce="2025-08-30"),
        )
        assert ids(kept) == [1, 2] and not gone

    def test_mapping_folds_before_fanning_out_to_both_classes(self):
        """The fold runs once per issuer, before each filing lands on ORFI and
        ORFIP — the two classes' copies are not re-filings of each other."""
        universe = [{"ticker": "ORFI", "org_id": "16", "names": [], "type": "stock"},
                    {"ticker": "ORFIP", "org_id": "16", "names": [], "type": "stock"}]
        rows = dividends.map_rows([
            cal(81, "16", "2016-05-30", "2016-06-02T05:22:08", common=1355.0,
                cs="2016-05-31", ce="2016-07-29"),
            cal(171, "16", "2016-07-28", "2016-07-01T07:11:12", common=215.0,
                cs="2016-05-31", ce="2016-07-29"),
        ], universe)
        assert sorted((r["ticker"], r["filing_id"]) for r in rows) == [
            ("ORFI", "171"), ("ORFIP", "171")]

    def test_stored_rows_are_folded_per_security_on_read(self):
        """A snapshot written before the rule still holds both copies."""
        stored = [{**dividends.normalize_row(r), "ticker": t}
                  for t in ("ORFI", "ORFIP")
                  for r in (cal(81, "16", "2016-05-30", "2016-06-02T05:22:08", common=1355.0,
                                cs="2016-05-31", ce="2016-07-29"),
                            cal(171, "16", "2016-07-28", "2016-07-01T07:11:12", common=215.0,
                                cs="2016-05-31", ce="2016-07-29"))]
        out = dividends._collapse_stored(stored)
        assert sorted((r["ticker"], r["filing_id"]) for r in out) == [
            ("ORFI", "171"), ("ORFIP", "171")]


# ---------------------------------------------------------------------------
# Server-side dividend yield and payout
# ---------------------------------------------------------------------------

TODAY = date(2026, 10, 17)


def stored(ticker, fid, decision, pub, ordinary, preferred=0.0):
    return {"ticker": ticker, "filing_id": str(fid), "org_id": "x",
            "decision_date": decision, "pub_date": pub,
            "ordinary_amount": ordinary, "preferred_amount": preferred}


class TestDividendMetrics:
    """The current terminal uses the latest ordinary decision, not a TTM sum.

    Payout ratios cannot be inferred by summing overlapping calendar notices.
    Share-class market validation is exercised before passing a price to DY.
    """
    def test_uzas_uses_the_latest_ordinary_decision(self):
        from server.terminal import analytics
        rows = [stored("UZAS", 4059, "2026-06-30", "2026-07-01T19:07:30", 404.0, 820.0),
                stored("UZAS", 3596, "2025-06-30", "2025-06-30T19:05:03", 330.0, 820.0)]
        out = analytics.dividend(rows, 178000.0, today=TODAY)
        assert out["dy"] == pytest.approx(404 / 178000 * 100)
        assert out["decision"]["filing_id"] == "4059"
        assert out["basis"] == "latest_decision"

    def test_orfi_has_no_yield_on_a_2021_price(self, monkeypatch):
        from server.terminal import analytics, service
        import catalogue.market_store as market_store
        import public_contract
        securities = {"ORFI": {"isin": "UZ7055870008", "issuer_id": "16", "share_type": "ordinary"}}
        listings = {"ORFI": {"shares_outstanding": 2867124015, "last_price": 573.95,
                             "last_trade_date": "2021-07-27"}}
        monkeypatch.setattr(service, "get_securities_map", lambda: securities)
        monkeypatch.setattr(market_store, "get_all_listings", lambda: listings)
        monkeypatch.setattr(market_store, "get_all_quotes", lambda: {})
        checked = public_contract.market_class_input
        monkeypatch.setattr(public_contract, "market_class_input", lambda row: checked(row, reference_date=TODAY))
        context = service.market_context()["ORFI"]
        rows = [stored("ORFI", 4061, "2026-06-26", "2026-07-02T11:17:18", 458.88, 458.88)]
        assert context["price"] is None
        assert analytics.dividend(rows, context["price"], today=TODAY)["dy"] is None

    def test_a_refiled_decision_counts_once(self):
        from server.terminal import analytics
        row = stored("UVGT", 4062, "2026-06-26", "2026-07-02T12:17:14", 281.03)
        out = analytics.dividend([row, dict(row)], 80000.0, today=TODAY)
        assert out["dy"] == pytest.approx(281.03 / 80000 * 100)
        assert out["decision"]["filing_id"] == "4062"

    def test_utga_ordinary_last_paid_in_2017_has_no_recent_yield(self):
        from server.terminal import analytics
        rows = [stored("UTGA", 3360, "2024-08-07", "2024-08-20T20:18:22", 0.0, 250.0),
                stored("UTGA", 872, "2017-10-21", "2017-11-17T06:40:57", 263.49, 250.0)]
        out = analytics.dividend(rows, 770000.0, today=TODAY)
        assert out["dy"] is None and out["decision"] is None

    def test_an_impossible_decision_date_cannot_establish_a_current_yield(self):
        from server.terminal import analytics
        # Publication is evidence of filing, not proof of a decision date.
        row = stored("DORI", 1, "2108-10-02", "2026-03-01T10:00:00", 100.0)
        out = analytics.dividend([row], 1000, today=TODAY)
        assert out["dy"] is None and out["decision"] is None

    def test_a_missing_or_zero_price_cannot_establish_yield(self):
        from server.terminal import analytics
        row = stored("UZAS", 4059, "2026-06-30", "2026-07-01T19:07:30", 404.0, 820.0)
        for price in (None, 0, -1):
            assert analytics.dividend([row], price, today=TODAY)["dy"] is None


# ---------------------------------------------------------------------------
# Capitalisation inputs
# ---------------------------------------------------------------------------

class TestZeroBalance:
    def test_ocbk_all_nought_bank_form_is_not_a_balance(self):
        """OCBK's 9M 2026 bank form: every line nought but cash. Its zeros were
        read as equity 0, and ROE/ROA said «negative equity»."""
        fin = {"year": 2026, "quarter": 3, "period_months": 9, "org_type": "bank",
               "balance": {"equity_start": 0.0, "equity_end": 0.0,
                           "assets_start": 0.0, "assets_end": 0.0}}
        ratio = {"total_equity": 1020971144000.0, "total_assets": 1190365557000.0,
                 "period": "2025"}
        snap = fundamentals.balance_snapshot(fin, ratio, today=TODAY)
        assert snap["source"] == "indicators"
        assert snap["equity"] == 1020971144000.0

    def test_a_real_balance_with_a_nought_opening_still_stands(self):
        fin = {"year": 2026, "quarter": 2, "period_months": 6,
               "balance": {"equity_start": 0.0, "equity_end": 500.0,
                           "assets_start": 0.0, "assets_end": 900.0}}
        snap = fundamentals.balance_snapshot(fin, {}, today=TODAY)
        assert snap["source"] == "filing" and snap["equity"] == 500.0


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


ORFI_CARD = {  # openinfo /home/organizations/16/, 2026-10-17
    "full_name_text": '"Orient finans bank" XATB',
    "info_rfb": {
        "ustav_capitalization": 3584405018750.0,
        "isin_codes": [
            {"ticker": "ORFI", "isu_cd": "UZ7055870008", "list_shares": 1175986762,
             "price": 1250.0, "stock_type": "01", "listing_date": "20210610"},
            {"ticker": "ORFIP", "isu_cd": "UZ7055871006", "list_shares": 400000,
             "price": 1250.0, "stock_type": "02", "listing_date": "20210610"},
        ],
    },
}


class TestPinnedIsinClass:
    def test_orfip_takes_its_class_from_the_card(self):
        """The pin stamped every pinned line «01»: ORFIP, openinfo stock_type
        02, was published as a second ordinary line with no share count."""
        code = lc._pinned_isin_code("ORFIP", "UZ7055871006", ORFI_CARD["info_rfb"])
        assert code["stock_type"] == "02"
        assert code["list_shares"] == 400000
        assert code["listing_date"] == "20210610"
        assert code["card_listed"] is True

    def test_a_card_that_does_not_list_the_pinned_isin_lends_nothing(self):
        """DRBK's org carries Asia Insurance's AISK: nothing of it may leak."""
        rfb = {"isin_codes": [{"ticker": "AISK", "isu_cd": "UZ7057300012",
                               "stock_type": "02", "list_shares": 5}]}
        code = lc._pinned_isin_code("DRBK", "UZ7050240009", rfb)
        assert code["stock_type"] == "01" and code["list_shares"] is None
        assert code["card_listed"] is False

    def test_the_walk_publishes_orfip_as_preferred_under_the_card_charter(self, monkeypatch):
        monkeypatch.setattr(lc, "_make_session", lambda: type(
            "S", (), {"get": lambda self, *a, **k: _Resp(ORFI_CARD)})())
        monkeypatch.setattr(lc, "_org_ids", lambda: {"ORFI": "16", "ORFIP": "16"})
        monkeypatch.setattr(lc, "_known_equities", lambda: {})
        monkeypatch.setattr(lc, "_uzse_equity", lambda *_a, **_k: None)
        monkeypatch.setattr(lc, "_last_conclusion", lambda *_a, **_k: None)
        monkeypatch.setattr(lc, "_filed_charters", lambda *_a, **_k: [3584405018750.0])
        monkeypatch.setattr(lc, "_discover_org", lambda *_a, **_k: None)
        rows = {r["ticker"]: r for r in lc.collect_listing_rows()}
        assert rows["ORFI"]["share_type"] == "ordinary"
        assert rows["ORFIP"]["share_type"] == "preferred"
        assert rows["ORFIP"]["shares_outstanding"] == 400000
        # The card is this issuer's, so its charter judges both counts together.
        assert rows["ORFIP"]["org_id"] == "16"
        assert rows["ORFIP"]["charter_capital"] == 3584405018750.0
        assert rows["ORFIP"]["org_equity_classes"] == 2

    def test_the_cards_stale_orfi_count_never_replaces_the_exchange_one(self):
        """The card still lists ORFI at 1 175 986 762 shares; the exchange's
        2 867 124 015 is stored. With ORFIP's 400 000 the stored pair fits the
        3 584 405 018 750 charter at 1 250 exactly, so the stale count only
        ever fills a gap and the issuer keeps its true share count."""
        import catalogue.market_store as ms

        stored = {"ORFI": (2867124015.0, 1250.0), "ORFIP": (None, 1250.0)}
        base = {"org_id": "16", "charter_capital": 3584405018750.0,
                "filed_charter_capital": [3584405018750.0], "org_equity_classes": 2,
                "nominal": None, "last_price": 2160.01, "last_trade_date": "2026-10-16",
                "shares_source": "openinfo"}
        rows = [ms._plausible_shares("ORFI", {**base, "ticker": "ORFI", "isin": "UZ7055870008",
                                              "shares_outstanding": 1175986762.0},
                                     stored["ORFI"]),
                ms._plausible_shares("ORFIP", {**base, "ticker": "ORFIP", "isin": "UZ7055871006",
                                               "shares_outstanding": 400000.0},
                                     stored["ORFIP"])]
        out = {r["ticker"]: r["shares_outstanding"] for r in ms._charter_counts(rows, stored)}
        assert out == {"ORFI": 2867124015.0, "ORFIP": 400000.0}
