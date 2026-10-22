"""Investment records are replayed, never inferred from favourites or prices."""
from datetime import date
from decimal import Decimal as D

import pytest


def trade(kind="buy", *, ticker="AGBA", quantity="10", price="100", fees="0",
          amount="0", day="2026-01-01", sequence=1):
    return dict(id=str(sequence), sequence=sequence, ticker=ticker, kind=kind,
                quantity=quantity, price=price, fees=fees, amount=amount,
                trade_date=None if kind == "opening" else day, note="")


def test_average_cost_sales_fees_and_actual_dividends():
    from identity.portfolio_math import calculate_ledger
    result = calculate_ledger([
        trade(quantity="100", fees="100"),
        trade(quantity="100", price="120", day="2026-02-01", sequence=2),
        trade("sell", quantity="50", price="150", fees="50", day="2026-03-01", sequence=3),
        trade("dividend", quantity="0", price="0", amount="600", fees="60", day="2026-04-01", sequence=4),
    ])
    held = result["items"][0]
    assert held["quantity"] == D("150")
    assert held["average_cost"] == D("110.5")
    assert held["cost_value"] == D("16575")
    assert result["realized_pnl"] == D("1925")
    assert result["dividend_income"] == D("540")


def test_backdated_events_are_replayed_in_date_order_and_cannot_oversell():
    from identity.portfolio_math import calculate_ledger
    buy = trade(day="2026-02-01")
    sell = trade("sell", day="2026-01-01", sequence=2)
    with pytest.raises(ValueError, match="INSUFFICIENT_SHARES"):
        calculate_ledger([buy, sell])
    result = calculate_ledger([dict(sell, trade_date="2026-03-01"), buy])
    assert result["items"] == []
    assert result["realized_pnl"] == 0


def test_decimal_quantities_close_exactly_and_repurchase_resets_basis():
    from identity.portfolio_math import calculate_ledger
    rows = [trade(quantity="0.1", price="0.1"), trade(quantity="0.2", price="0.2", sequence=2),
            trade("sell", quantity="0.3", price="1", sequence=3)]
    result = calculate_ledger(rows)
    assert result["items"] == []
    assert result["realized_pnl"] == D("0.25")
    result = calculate_ledger(rows + [trade(quantity="1", price="500", sequence=4)])
    assert result["items"][0]["average_cost"] == 500
    assert result["realized_pnl"] == D("0.25")


def test_opening_balances_precede_dated_activity_without_inventing_a_purchase_date():
    from identity.portfolio_math import calculate_ledger
    result = calculate_ledger([trade("sell", quantity="2", price="110"),
                               trade("opening", sequence=99)])
    assert result["items"][0]["quantity"] == 8
    assert result["realized_pnl"] == 20
    with pytest.raises(ValueError, match="DUPLICATE_OPENING"):
        calculate_ledger([trade("opening"), trade("opening", sequence=2)])


@pytest.mark.parametrize("patch", [
    {"quantity": "NaN"}, {"price": "Infinity"}, {"fees": "-1"},
    {"quantity": "0"}, {"quantity": "0.0000001"}, {"quantity": "1000000000001"},
    {"price": "-1"}, {"kind": "other"}, {"ticker": " "},
    {"trade_date": "2999-01-01"}, {"trade_date": "2026-02-30"},
    {"amount": "10"}, {"kind": "dividend"},
])
def test_invalid_transactions_are_rejected_before_storage(patch):
    from identity.portfolio_math import normalize_transaction
    with pytest.raises(ValueError):
        normalize_transaction({**trade(), **patch})


def value(rows, **kwargs):
    from identity.portfolio_math import calculate_ledger
    from server.accounts.portfolio import value_portfolio
    return value_portfolio(calculate_ledger(rows), today=date(2026, 10, 22), **kwargs)


SECURITIES = {"AGBA": {"isin": "UZ7001560000", "type": "stock", "name": "Agrobank"},
              "UZTL": {"isin": "UZ7011340005", "type": "stock", "name": "Uztelecom"}}


def test_uses_newest_stored_execution_and_official_close_wins_same_session():
    sources = dict(securities=SECURITIES,
                   listings={"AGBA": {"last_price": 100, "last_trade_date": "2026-09-01"}},
                   quotes={"UZ7001560000": {"close_price": 589, "trade_date": "20261020"}},
                   stats={"UZ7001560000": {"close_price": 590, "trade_date": "20261021"}})
    result = value([trade()], **sources)
    assert result["items"][0]["last_price"] == 590
    assert result["items"][0]["price_date"] == "2026-10-21"
    assert result["items"][0]["days_since_trade"] == 1
    assert result["market_value"] == 5900
    sources["quotes"]["UZ7001560000"]["trade_date"] = "20261021"
    assert value([trade()], **sources)["market_value"] == 5890


@pytest.mark.parametrize("quote", [
    {"close_price": 0, "trade_date": "20261021"},
    {"close_price": "NaN", "trade_date": "20261021"},
    {"close_price": 600, "trade_date": "20261023"},
    {"close_price": 600, "trade_date": None},
])
def test_bad_prices_never_become_valuations(quote):
    result = value([trade()], securities=SECURITIES, listings={}, stats={}, quotes={"UZ7001560000": quote})
    assert result["market_value"] is None
    assert result["unrealized_pnl"] is None
    assert result["cost_value"] == 1000


def test_unpriced_holdings_make_total_incomplete_but_keep_all_costs_and_priced_subtotal():
    result = value([trade(), trade(ticker="UZTL", sequence=2)], securities=SECURITIES,
                   listings={}, stats={}, quotes={"UZ7001560000": {"close_price": 600, "trade_date": "20261021"}})
    assert result["cost_value"] == 2000
    assert result["priced_market_value"] == 6000
    assert result["market_value"] is None
    assert result["total_pnl"] is None
    assert result["priced_count"] == 1 and result["count"] == 2
    assert result["items"][0]["allocation_pct"] is None


def test_undated_registry_reference_and_another_isin_cannot_value_a_holding():
    result = value([trade()], securities=SECURITIES, stats={},
                   listings={"AGBA": {"reference_price": 600, "last_price": 600}},
                   quotes={"OTHER": {"ticker": "AGBA", "close_price": 600, "trade_date": "20261021"}})
    assert result["market_value"] is None


def test_empty_and_closed_portfolios_have_zero_holdings_value_and_keep_realized_returns():
    sources = dict(securities=SECURITIES, stats={}, listings={}, quotes={})
    assert value([], **sources)["market_value"] == 0
    result = value([trade(), trade("sell", price="120", sequence=2)], **sources)
    assert result["market_value"] == 0 and result["total_pnl"] == 200
