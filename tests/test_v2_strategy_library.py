import unittest

from app.v2_strategy_library import (
    ema_trend, bollinger_reversion, rsi_reversal,
    donchian_breakout, evaluate_strategies, STRATEGIES,
)


def candles(slope=0.2, count=45):
    result = []
    for i in range(count):
        price = 100 + i * slope
        result.append({"close_time": i + 1, "open": price,
                       "high": price + 0.4, "low": price - 0.4,
                       "close": price, "volume": 1000})
    return result


class StrategyLibraryTests(unittest.TestCase):
    def test_trend_directions(self):
        self.assertEqual(ema_trend(candles(0.2))["side"], "LONG")
        self.assertEqual(ema_trend(candles(-0.2))["side"], "SHORT")

    def test_donchian_volume_confirmation(self):
        bars = candles(1.0)
        self.assertEqual(donchian_breakout(bars)["side"], "WAIT")
        bars[-1]["volume"] = 2000
        self.assertEqual(donchian_breakout(bars)["side"], "LONG")

    def test_invalid_data_fail_closed(self):
        for strategy in STRATEGIES:
            self.assertEqual(strategy(candles(count=10))["side"], "WAIT")
            bars = candles()
            bars[-1]["close"] = float("nan")
            self.assertEqual(strategy(bars)["side"], "WAIT")

    def test_spread_blocks_all_strategies(self):
        result = evaluate_strategies(candles(), spread_bps=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reason"], "SPREAD_FILTER")

    def test_bollinger_and_rsi_return_structured_candidates(self):
        for strategy in (bollinger_reversion, rsi_reversal):
            result = strategy(candles())
            self.assertIn(result["side"], ("WAIT", "LONG", "SHORT"))
            self.assertTrue(0 <= result["score"] <= 1)


if __name__ == "__main__":
    unittest.main()
