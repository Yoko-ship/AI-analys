from datetime import date, timedelta

from technical_backtest import run_sma20_backtest


def _points(count=130):
    start = date(2024, 1, 1)
    # Two broad waves guarantee both a cross above and a cross below the SMA.
    values = [100 + (index % 40) * 2 if index % 80 < 40 else 180 - (index % 40) * 2
              for index in range(count)]
    return [{"trade_date": (start + timedelta(days=index)).isoformat(),
             "close_price": value, "trade_count": 1} for index, value in enumerate(values)]


def test_sma_backtest_requires_a_real_session_history():
    assert run_sma20_backtest(_points(99))["status"] == "NO_DATA"


def test_sma_backtest_executes_after_the_signal_not_on_it():
    result = run_sma20_backtest(_points())
    assert result["status"] == "AVAILABLE"
    assert result["parameters"]["fee_bps_per_side"] == 15
    assert result["period"]["observations"] == 130
    for trade in result["trades"]:
        assert trade["execution_date"] > trade["signal_date"]
