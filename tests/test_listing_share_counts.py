"""A share count must be a count: agreed by openinfo twice and inside the charter.

openinfo answered org 102 (UzAuto Motors) with 1 344 000 017 200 shares five
times out of six and 270 000 000 once; the capital-sized figure reached the
board and put the market at 76 500 трлн сум.
"""
from datetime import date

import pytest

import catalogue.market_store as store
import listings_collector as lc

UZMT = {"ticker": "UZMT", "nominal": 5000.0, "charter_capital": 1_353_923_515_000.0,
        "last_price": 56_500.0}


def test_a_count_whose_par_exceeds_the_charter_is_refused_for_the_stored_one() -> None:
    row = store._plausible_shares("UZMT", {**UZMT, "shares_outstanding": 1_344_000_017_200.0},
                                  (270_784_703.0, 5000.0))
    assert row["shares_outstanding"] == 270_784_703.0
    assert row["market_cap"] == 270_784_703.0 * 56_500.0


def test_a_bad_stored_count_gives_way_to_nothing_rather_than_a_bad_new_one() -> None:
    row = store._plausible_shares("UZMT", {**UZMT, "shares_outstanding": 1_344_000_017_200.0},
                                  (1_344_000_017_200.0, 5000.0))
    assert row["shares_outstanding"] is None and row["market_cap"] is None


def test_openinfo_does_not_replace_a_plausible_stored_count() -> None:
    """AGMK: openinfo flipped between 606M and 187M; the stored 606M stays."""
    row = {"ticker": "AGMK", "nominal": 3914.0, "charter_capital": 2.77e12,
           "shares_outstanding": 187_314_383.0, "shares_source": "openinfo", "last_price": 3914.0}
    assert store._plausible_shares("AGMK", row, (606_016_663.0, 3914.0))["shares_outstanding"] == 606_016_663.0


def test_an_exchange_count_replaces_the_stored_one() -> None:
    row = {"ticker": "AGMK", "nominal": 3914.0, "charter_capital": 2.77e12,
           "shares_outstanding": 650_000_000.0, "shares_source": "uzse", "last_price": 3914.0}
    assert store._plausible_shares("AGMK", row, (606_016_663.0, 3914.0)) is row


def test_openinfo_fills_a_gap() -> None:
    row = {"ticker": "X", "nominal": 1000.0, "charter_capital": 1e9,
           "shares_outstanding": 900_000.0, "shares_source": "openinfo"}
    assert store._plausible_shares("X", row, None) is row


def test_no_agreement_keeps_the_stored_count() -> None:
    row = store._plausible_shares("X", {"ticker": "X", "shares_outstanding": None}, (1000.0, None))
    assert row["shares_outstanding"] == 1000.0


class _Session:
    def __init__(self, answers):
        self.answers = list(answers)

    def get(self, url, timeout=None):
        shares = self.answers.pop(0)
        payload = {"info_rfb": {"isin_codes": [{"isu_cd": "UZ7003040001", "ticker": "UZMT",
                                                "list_shares": shares}]}}

        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return payload
        return R()


def test_two_reads_that_agree_are_taken() -> None:
    session = _Session([270_784_703, 270_784_703])
    detail = lc._org_detail(session, "102")
    assert detail["info_rfb"]["isin_codes"][0]["list_shares"] == 270_784_703
    assert session.answers == []          # no third read needed


def test_a_disagreement_is_settled_by_a_third_read() -> None:
    detail = lc._org_detail(_Session([1_344_000_017_200, 270_000_000, 1_344_000_017_200]), "102")
    # The majority wins here; the charter check in the upsert is what refuses it.
    assert detail["info_rfb"]["isin_codes"][0]["list_shares"] == 1_344_000_017_200


def test_three_different_answers_publish_no_count() -> None:
    detail = lc._org_detail(_Session([1, 2, 3]), "102")
    assert detail["info_rfb"]["isin_codes"][0]["list_shares"] is None


# --- An issuer's classes against its charter capital -------------------------
# openinfo's card, 2026-10-06: charter current, per-class list_shares from before
# the last issue. The exchange's counts at par add up to the charter exactly.

def _cls(ticker, isin, shares, par, charter, classes=2, price=None, traded=None):
    return {"ticker": ticker, "isin": isin, "shares_outstanding": shares, "nominal": par,
            "charter_capital": charter, "org_id": "1", "org_equity_classes": classes,
            "last_price": price, "shares_source": "openinfo",
            "last_trade_date": traded or (date.today().isoformat() if price else None)}


def _registry(monkeypatch, entries):
    monkeypatch.setattr(store, "_share_registry_memo", {
        t: {"shares": e[0], "par": e[1], **({"isin": e[2]} if len(e) > 2 else {})}
        for t, e in entries.items()})


UZMK_CHARTER = 3_725_963_175_000.0


def test_classes_that_add_up_to_the_charter_are_kept(monkeypatch) -> None:
    _registry(monkeypatch, {})
    group = [_cls("UZMK", "UZ7021720006", 593_644_242.0, 5000.0, UZMK_CHARTER),
             _cls("UZMKP", "UZ702172K016", 151_548_393.0, 5000.0, UZMK_CHARTER)]
    out = store._charter_counts(group, {})
    assert [r["shares_outstanding"] for r in out] == [593_644_242.0, 151_548_393.0]


def test_counts_that_fit_still_take_no_cap_from_a_par_price(monkeypatch) -> None:
    """UZIN: the card's counts fit the charter, but the ordinary line has only its par."""
    _registry(monkeypatch, {})
    charter = 303_452_228_000.0
    group = [{**_cls("UZIN", "UZ7056920018", 289_341_408.0, 1000.0, charter), "last_price": 1000.0},
             _cls("UZINP", "UZ7056921008", 14_110_820.0, 1000.0, charter, price=3650.0)]
    ordinary, preferred = store._charter_counts(group, {})
    assert ordinary["shares_outstanding"] == 289_341_408.0 and ordinary["market_cap"] is None
    assert preferred["market_cap"] == 14_110_820.0 * 3650.0


def test_a_stale_pair_is_replaced_by_a_registry_that_fits_the_charter(monkeypatch) -> None:
    _registry(monkeypatch, {"UZMK": (593_644_242, 5000), "UZMKP": (151_548_393, 5000)})
    group = [_cls("UZMK", "UZ7021720006", 43_322_393.0, 5000.0, UZMK_CHARTER, price=6800.0),
             _cls("UZMKP", "UZ702172K016", 906_420.0, 5000.0, UZMK_CHARTER, price=4100.0)]
    out = store._charter_counts(group, {})
    assert [r["shares_outstanding"] for r in out] == [593_644_242.0, 151_548_393.0]
    assert out[0]["market_cap"] == 593_644_242.0 * 6800.0


def test_a_registry_the_charter_has_moved_past_is_not_used(monkeypatch) -> None:
    """The next issue moves the charter; the old split must not survive it."""
    _registry(monkeypatch, {"UZMK": (593_644_242, 5000), "UZMKP": (151_548_393, 5000)})
    group = [_cls("UZMK", "UZ7021720006", 43_322_393.0, 5000.0, UZMK_CHARTER * 1.2, price=6800.0),
             _cls("UZMKP", "UZ702172K016", 906_420.0, 5000.0, UZMK_CHARTER * 1.2, price=4100.0)]
    out = store._charter_counts(group, {})
    assert all(r["shares_outstanding"] is None and r["market_cap"] is None for r in out)


def test_a_stale_pair_with_no_registry_withholds_the_cap(monkeypatch) -> None:
    _registry(monkeypatch, {})
    group = [_cls("UZMK", "UZ7021720006", 43_322_393.0, 5000.0, UZMK_CHARTER, price=6800.0),
             _cls("UZMKP", "UZ702172K016", 906_420.0, 5000.0, UZMK_CHARTER, price=4100.0)]
    assert [r["shares_outstanding"] for r in store._charter_counts(group, {})] == [None, None]


def test_a_single_class_is_charter_over_par(monkeypatch) -> None:
    _registry(monkeypatch, {})
    row = _cls("X", "UZ7000000001", 1_000_000.0, 5000.0, 25_000_000_000.0, classes=1, price=6000.0)
    (out,) = store._charter_counts([row], {})
    assert out["shares_outstanding"] == 5_000_000.0
    assert out["market_cap"] == 5_000_000.0 * 6000.0


def test_a_lone_row_of_a_two_class_card_is_not_given_the_whole_charter(monkeypatch) -> None:
    """A delisted preferred line still holds part of the charter."""
    _registry(monkeypatch, {})
    row = _cls("X", "UZ7000000001", 1_000_000.0, 5000.0, 25_000_000_000.0, classes=2)
    assert store._charter_counts([row], {})[0]["shares_outstanding"] is None


def test_the_stored_par_is_used_when_the_row_has_none(monkeypatch) -> None:
    """With uzse.uz off the collector sends no par; the stored one judges."""
    _registry(monkeypatch, {})
    row = {**_cls("X", "UZ7000000001", 1_000_000.0, None, 25_000_000_000.0, classes=1)}
    (out,) = store._charter_counts([row], {"X": (1_000_000.0, 5000.0)})
    assert out["shares_outstanding"] == 5_000_000.0


def test_without_a_par_nothing_is_judged(monkeypatch) -> None:
    _registry(monkeypatch, {})
    group = [_cls("A", "UZ7000000001", 10.0, None, 1e9), _cls("AP", "UZ700000K001", 1.0, None, 1e9)]
    assert store._charter_counts(group, {}) == group


def test_a_class_missing_from_the_pass_is_found_by_its_isin(monkeypatch) -> None:
    """GRBK: the card holds GRBKP too, so the lone GRBK row needs the pair."""
    _registry(monkeypatch, {"GRBK": (4_997_000_000, 100, "UZ7037610001"),
                            "GRBKP": (3_000_000, 100, "UZ703761K015")})
    row = _cls("GRBK", "UZ7037610001", 1_297_000_000.0, 100.0, 500_000_000_000.0, price=2458.0)
    (out,) = store._charter_counts([row], {})
    assert out["shares_outstanding"] == 4_997_000_000.0
    assert out["market_cap"] == 4_997_000_000.0 * 2458.0


def test_a_row_the_card_labels_otherwise_is_matched_by_isin(monkeypatch) -> None:
    _registry(monkeypatch, {"UZNG": (47_118_148_624, 500, "UZ7036270005"),
                            "UZNGP": (24_437_863, 500, "UZ7036271003")})
    charter = 23_571_293_243_500.0
    group = [_cls("UZNG", "UZ7036270005", 43_048_493_329.0, 500.0, charter),
             _cls("UZNG1", "UZ7036271003", 24_437_863.0, 500.0, charter, price=5400.0)]
    out = store._charter_counts(group, {})
    assert [r["shares_outstanding"] for r in out] == [47_118_148_624.0, 24_437_863.0]


def test_a_class_that_never_trades_gets_its_count_but_no_cap_at_par(monkeypatch) -> None:
    """UZNG's ordinary line carries only its 500 par: no cap is built on it."""
    _registry(monkeypatch, {"UZNG": (47_118_148_624, 500), "UZNGP": (24_437_863, 500)})
    charter = 23_571_293_243_500.0
    group = [{**_cls("UZNG", "UZ7036270005", 43_048_493_329.0, 500.0, charter),
              "reference_price": 500.0, "last_price": 500.0, "last_trade_date": None},
             _cls("UZNGP", "UZ7036271003", 24_437_863.0, 500.0, charter, price=5400.0)]
    ordinary, preferred = store._charter_counts(group, {})
    assert ordinary["shares_outstanding"] == 47_118_148_624.0 and ordinary["market_cap"] is None
    assert preferred["market_cap"] == 24_437_863.0 * 5400.0


def test_an_old_trade_still_builds_the_class_cap(monkeypatch) -> None:
    """An old trade is a trade: the board shows its cap, the multiples refuse it."""
    _registry(monkeypatch, {})
    row = _cls("X", "UZ7000000001", 1_000_000.0, 5000.0, 25_000_000_000.0, classes=1,
               price=6000.0, traded="2019-03-01")
    (out,) = store._charter_counts([row], {})
    assert out["shares_outstanding"] == 5_000_000.0 and out["market_cap"] == 5_000_000.0 * 6000.0


# openinfo's ustav_capitalization on the day each entry was read from uzse.uz.
REGISTRY_CHARTERS = {
    ("ALKB", "ALKBP"): 3_678_140_046_965.0, ("UZMK", "UZMKP"): UZMK_CHARTER,
    ("AGMK", "AGMKP"): 2_808_759_251_282.0,
    ("AGBA", "AGBAP"): 12_765_191_063_584.0, ("ALSM", "ALSMP"): 60_272_931_060.0,
    ("BRBN", "BRBNP"): 5_689_083_510_324.0, ("GRBK", "GRBKP"): 500_000_000_000.0,
    ("HMKB", "HMKBP"): 646_648_980_000.0, ("IPKY", "IPKYP"): 602_421_052_640.0,
    ("IPTB", "IPTBP"): 4_225_522_638_941.0, ("KASU", "KASUP"): 80_000_000_000.0,
    ("KFSK", "KFSKP"): 240_000_000_000.0, ("MCBA", "MCBAP"): 7_145_336_799_816.0,
    ("QATT", "QATTP"): 11_461_144_000.0, ("TNBN", "TNBNP"): 2_334_142_421_800.0,
    ("TRSB", "TRSBP"): 2_000_500_000_000.0, ("UPOS", "UPOSP"): 52_563_506_760.0,
    ("UZAL", "UZALP"): 1_016_808_998_010.0, ("UZIR", "UZIRP"): 185_773_565_000.0,
    ("UZNG", "UZNGP"): 23_571_293_243_500.0, ("UZTL", "UZTLP"): 978_514_666_998.0,
    ("UZIN", "UZINP"): 303_452_228_000.0,
}


# Single-class issuers the walk reaches only through the fallback row: the
# exchange's total_capital (BIOK's also equals openinfo org 396's charter).
REGISTRY_SINGLE = {"BIOK": 19_139_488_000.0, "TGMQ": 615_769_000.0, "MXUS": 3_148_983_500.0}


def test_the_checked_in_registry_adds_up_to_the_charters_it_was_read_against() -> None:
    store._share_registry_memo = None
    reg = store._share_registry()
    assert set(reg) == {t for tickers in REGISTRY_CHARTERS for t in tickers} | set(REGISTRY_SINGLE)
    for t, capital in REGISTRY_SINGLE.items():
        assert reg[t]["shares"] * reg[t]["par"] == capital
    for tickers, charter in REGISTRY_CHARTERS.items():
        assert sum(reg[t]["shares"] * reg[t]["par"] for t in tickers) == pytest.approx(charter, rel=1e-12)
        # One issuer per pair: the ISINs share the UZ7 + five-digit issuer code.
        assert len({reg[t]["isin"][:8] for t in tickers}) == 1


def test_the_upsert_holds_an_issuer_to_its_charter(tmp_path, monkeypatch) -> None:
    import catalogue.schema as catalogue_schema
    import catalogue.storage as catalogue_storage

    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "c.db"))
    conn = catalogue_storage.get_catalog_conn()
    catalogue_schema._init_schema(conn)
    with conn:
        # The stale counts already stored, as on prod.
        for t, isin, shares in (("ALKB", "UZ7044760005", 7_862_863_805.0),
                                ("ALKBP", "UZ704476K019", 18_000_000.0)):
            conn.execute("INSERT INTO catalog_listings (ticker, isin, shares_outstanding, nominal) "
                         "VALUES (?,?,?,?)", (t, isin, shares, 1.0))
    conn.close()
    _registry(monkeypatch, {"ALKB": (3_674_450_046_965, 1), "ALKBP": (3_690_000_000, 1)})
    charter = 3_678_140_046_965.0
    store.bulk_upsert_listings([
        {**_cls("ALKB", "UZ7044760005", 11_147_957_333.0, None, charter, price=0.9)},
        {**_cls("ALKBP", "UZ704476K019", 18_000_000.0, None, charter, price=4.25)},
        # A bond on the same card is not a share class.
        {"ticker": "ALKBND", "isin": "UZ60447699B9", "shares_outstanding": 30000.0,
         "charter_capital": charter, "org_id": "1", "org_equity_classes": 2},
    ])
    listings = store.get_all_listings()
    assert listings["ALKB"]["shares_outstanding"] == 3_674_450_046_965.0
    assert listings["ALKBP"]["shares_outstanding"] == 3_690_000_000.0
    assert listings["ALKB"]["market_cap"] == 3_674_450_046_965.0 * 0.9
    assert listings["ALKBND"]["shares_outstanding"] == 30000.0


def test_the_fallback_row_takes_the_registry_count_when_uzse_is_off(monkeypatch) -> None:
    """TGMQ: an empty openinfo card, uzse.uz refused on the server."""
    _registry(monkeypatch, {"TGMQ": (615_769, 1000, "UZ7035630001")})
    monkeypatch.setattr(lc, "_uzse_equity", lambda s, i: None)
    monkeypatch.setattr(lc, "_uzse_share_count", lambda s, i: None)
    monkeypatch.setattr(lc, "_last_conclusion", lambda s, i: {"date": "2026-10-06", "close": 23201.77})
    row = lc._known_equity_row(None, "TGMQ", {"isin": "UZ7035630001"})
    assert row["shares_outstanding"] == 615_769.0 and row["shares_source"] == "registry"
    assert row["nominal"] == 1000 and row["market_cap"] == 615_769.0 * 23201.77


def test_a_registry_entry_for_another_isin_is_not_used(monkeypatch) -> None:
    _registry(monkeypatch, {"TGMQ": (615_769, 1000, "UZ7000000009")})
    monkeypatch.setattr(lc, "_uzse_equity", lambda s, i: None)
    monkeypatch.setattr(lc, "_uzse_share_count", lambda s, i: None)
    monkeypatch.setattr(lc, "_last_conclusion", lambda s, i: None)
    assert lc._known_equity_row(None, "TGMQ", {"isin": "UZ7035630001"})["shares_outstanding"] is None


def test_a_registry_count_replaces_a_stale_stored_one() -> None:
    row = {"ticker": "BIOK", "nominal": 3350.0, "shares_outstanding": 5_713_280.0,
           "shares_source": "registry", "last_price": 14_400.0}
    assert store._plausible_shares("BIOK", row, (2_856_640.0, 3350.0)) is row


def test_a_row_with_no_org_takes_no_cap_at_par(tmp_path, monkeypatch) -> None:
    """Pinned ISINs carry no org, so the issuer check never sees them: the
    no-cap-at-par rule has to hold for them too. An old real trade still counts."""
    import catalogue.schema as catalogue_schema
    import catalogue.storage as catalogue_storage

    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(tmp_path / "c.db"))
    conn = catalogue_storage.get_catalog_conn()
    catalogue_schema._init_schema(conn)
    conn.close()
    _registry(monkeypatch, {})
    drbk = {"ticker": "DRBK", "isin": "UZ7050240009", "shares_outstanding": 100_000_000.0,
            "nominal": 5000.0, "last_price": 5000.0, "last_trade_date": "2019-10-31",
            "market_cap": 500_000_000_000.0, "shares_source": "uzse",
            "charter_capital": None, "org_id": None}
    par = {**drbk, "ticker": "OCBK", "isin": "UZ7048610008", "last_price": 1000.0,
           "reference_price": 1000.0, "last_trade_date": None}
    store.bulk_upsert_listings([drbk, par])
    listings = store.get_all_listings()
    assert listings["DRBK"]["market_cap"] == 500_000_000_000.0
    assert listings["OCBK"]["shares_outstanding"] == 100_000_000.0
    assert listings["OCBK"]["market_cap"] is None


def _search(monkeypatch, results, cards):
    asked = []

    def json_get(session, path, params=None):
        asked.append(params["search"])
        return {"results": results.get(params["search"], [])}

    monkeypatch.setattr(lc, "_json_get", json_get)
    monkeypatch.setattr(lc, "_org_detail", lambda s, org: {"info_rfb": {"isin_codes": cards[org]}})
    return asked


def test_an_unreached_share_is_found_by_its_ticker(monkeypatch) -> None:
    """EQQU: on the board with a price, but the walk never reached org 553."""
    _search(monkeypatch, {"EQQU": [{"id": 553, "exchange_ticket_name": "EQQU"}]},
            {"553": [{"ticker": "EQQU", "isu_cd": "UZ7007130006", "list_shares": 162897}]})
    cache: dict = {}
    assert lc._discover_org(None, "EQQU", "UZ7007130006", cache) == "553"
    assert "553" in cache


def test_a_card_without_the_isin_is_not_taken(monkeypatch) -> None:
    _search(monkeypatch, {"EQQU": [{"id": 9, "exchange_ticket_name": "EQQU"}]},
            {"9": [{"ticker": "EQQU", "isu_cd": "UZ7000000009"}]})
    assert lc._discover_org(None, "EQQU", "UZ7007130006", {}) is None


def test_a_name_match_without_the_ticker_is_not_read(monkeypatch) -> None:
    _search(monkeypatch, {"EQQU": [{"id": 9, "exchange_ticket_name": "EQQUX, ABC"}]},
            {"9": [{"ticker": "EQQU", "isu_cd": "UZ7007130006"}]})
    assert lc._discover_org(None, "EQQU", "UZ7007130006", {}) is None


def test_a_preferred_line_is_found_under_its_ordinary_ticker(monkeypatch) -> None:
    asked = _search(monkeypatch, {"ACME": [{"id": 7, "exchange_ticket_name": "ACME, ACMEB1"}]},
                    {"7": [{"ticker": "ACME", "isu_cd": "UZ7000010001"},
                           {"ticker": "ACMEP", "isu_cd": "UZ700001K011"}]})
    assert lc._discover_org(None, "ACMEP", "UZ700001K011", {}) == "7"
    assert asked == ["ACMEP", "ACME"]


def test_the_walk_reads_the_found_card(monkeypatch) -> None:
    """End to end: the leftover share gets the card's count, not the fallback."""
    monkeypatch.setattr(lc, "_make_session", lambda: None)
    monkeypatch.setattr(lc, "_org_ids", lambda: {})
    monkeypatch.setattr(lc, "_known_equities",
                        lambda: {"EQQU": {"isin": "UZ7007130006", "type": "stock"}})
    _search(monkeypatch, {"EQQU": [{"id": 553, "exchange_ticket_name": "EQQU"}]}, {})
    monkeypatch.setattr(lc, "_org_detail", lambda s, org: {
        "full_name_text": '"Elektrqishloqqurilish" AJ',
        "info_rfb": {"ustav_capitalization": 814_485_000.0, "isin_codes": [
            {"ticker": "EQQU", "isu_cd": "UZ7007130006", "list_shares": 162897,
             "stock_type": "01", "price": 5000.0}]}})
    monkeypatch.setattr(lc, "_uzse_equity", lambda s, i: None)
    monkeypatch.setattr(lc, "_last_conclusion", lambda s, i: {"date": "2026-10-06", "close": 313000.0})
    monkeypatch.setattr(lc, "_known_equity_row", lambda *a, **k: pytest.fail("fallback used"))
    (row,) = lc.collect_listing_rows()
    assert row["ticker"] == "EQQU" and row["shares_outstanding"] == 162897.0
    assert row["org_id"] == "553" and row["charter_capital"] == 814_485_000.0
