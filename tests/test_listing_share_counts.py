"""A share count must be a count: agreed by openinfo twice and inside the charter.

openinfo answered org 102 (UzAuto Motors) with 1 344 000 017 200 shares five
times out of six and 270 000 000 once; the capital-sized figure reached the
board and put the market at 76 500 трлн сум.
"""
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

def _cls(ticker, isin, shares, par, charter, classes=2, price=None):
    return {"ticker": ticker, "isin": isin, "shares_outstanding": shares, "nominal": par,
            "charter_capital": charter, "org_id": "1", "org_equity_classes": classes,
            "last_price": price, "shares_source": "openinfo"}


def _registry(monkeypatch, entries):
    monkeypatch.setattr(store, "_share_registry_memo", {
        t: {"shares": s, "par": p} for t, (s, p) in entries.items()})


UZMK_CHARTER = 3_725_963_175_000.0


def test_classes_that_add_up_to_the_charter_are_kept(monkeypatch) -> None:
    _registry(monkeypatch, {})
    group = [_cls("UZMK", "UZ7021720006", 593_644_242.0, 5000.0, UZMK_CHARTER),
             _cls("UZMKP", "UZ702172K016", 151_548_393.0, 5000.0, UZMK_CHARTER)]
    assert store._charter_counts(group, {}) == group


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


def test_the_checked_in_registry_adds_up_to_the_charters_it_was_read_against() -> None:
    store._share_registry_memo = None
    reg = store._share_registry()
    charters = {("ALKB", "ALKBP"): 3_678_140_046_965.0, ("UZMK", "UZMKP"): UZMK_CHARTER,
                ("AGMK", "AGMKP"): 2_808_759_251_282.0}
    for tickers, charter in charters.items():
        assert sum(reg[t]["shares"] * reg[t]["par"] for t in tickers) == charter


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
