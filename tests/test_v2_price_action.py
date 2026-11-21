import unittest
from app.v2_price_action import structure_break, liquidity_sweep, engulfing_reversal, evaluate_price_action


def bars(n=40):
    return [{"close_time": i+1, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 1000} for i in range(n)]


class PriceActionTests(unittest.TestCase):
    def test_structure_break_long_and_short(self):
        data = bars()
        data[-1].update(open=100, high=104, low=99, close=103)
        self.assertEqual(structure_break(data)["side"], "LONG")
        data[-1].update(open=100, high=101, low=96, close=97)
        self.assertEqual(structure_break(data)["side"], "SHORT")

    def test_liquidity_sweep_both_sides(self):
        data = bars()
        data[-1].update(open=99.6, high=100.5, low=97.5, close=100.2)
        self.assertEqual(liquidity_sweep(data)["side"], "LONG")
        data[-1].update(open=100.5, high=102.5, low=99.5, close=99.8)
        self.assertEqual(liquidity_sweep(data)["side"], "SHORT")

    def test_engulfing_bullish(self):
        data = bars()
        data[-6].update(open=103, high=104, low=102, close=103)
        data[-2].update(open=101, high=102, low=98, close=99)
        data[-1].update(open=98.5, high=102, low=98, close=101.5)
        self.assertEqual(engulfing_reversal(data)["side"], "LONG")

    def test_invalid_candles_do_not_trade(self):
        for result in evaluate_price_action(bars(10)):
            self.assertEqual(result["side"], "WAIT")


if __name__ == "__main__":
    unittest.main()
