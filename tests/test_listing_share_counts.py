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
