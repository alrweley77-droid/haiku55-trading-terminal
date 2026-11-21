import unittest

from app.v2_backtest import backtest_one_symbol
from app.v2_ensemble import select_opportunities


def make_bars(n=70, slope=0.25):
    bars = []
    for i in range(n):
        px = 100 + i * slope
        bars.append({"close_time": i + 1, "open": px, "high": px + 0.4,
                     "low": px - 0.4, "close": px, "volume": 1000})
    return bars


class EnsembleTests(unittest.TestCase):
    def test_positive_trend_candidate(self):
        result = select_opportunities({"AAAUSDT": {"candles": make_bars(), "spread_bps": 1}})
        self.assertEqual(result["candidates"][0]["side"], "LONG")
        self.assertEqual(result["mode"], "PAPER_RESEARCH")

    def test_cost_gate_blocks_expensive_market(self):
        result = select_opportunities({"AAAUSDT": {"candles": make_bars(), "spread_bps": 10}})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["diagnostics"]["AAAUSDT"], "COST_GATE")

    def test_invalid_cost_assumptions_rejected(self):
        with self.assertRaises(ValueError):
            select_opportunities({}, fee_bps_per_side=10)


class BacktestTests(unittest.TestCase):
    def test_report_is_paper_only(self):
        result = backtest_one_symbol("AAAUSDT", make_bars())
        self.assertEqual(result["mode"], "PAPER_BACKTEST")
        self.assertEqual(result["starting_cash"], 10000)
        self.assertGreaterEqual(result["closed_trades"], 0)

    def test_no_future_data_on_first_execution(self):
        bars = make_bars()
        result = backtest_one_symbol("AAAUSDT", bars[:36])
        self.assertEqual(result["closed_trades"], 0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            backtest_one_symbol("AAAUSDT", make_bars(), stop_pct=-1)
        with self.assertRaises(ValueError):
            backtest_one_symbol("BTC", make_bars())


if __name__ == "__main__":
    unittest.main()
