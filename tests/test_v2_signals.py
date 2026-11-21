import unittest
from app.v2_signals import score_candles, rank_candidates


def candles(trend=1):
    result = []
    for i in range(40):
        close = 100 + trend * i * 0.2
        result.append({"close_time": i + 1, "open": close - 0.1,
                       "high": close + 0.3, "low": close - 0.3,
                       "close": close, "volume": 1000})
    return result


class SignalTests(unittest.TestCase):
    def test_uptrend(self):
        result = score_candles(candles(1))
        self.assertEqual(result["side"], "LONG")

    def test_downtrend(self):
        result = score_candles(candles(-1))
        self.assertEqual(result["side"], "SHORT")

    def test_stale_or_malformed_candles_fail_closed(self):
        self.assertEqual(score_candles(candles()[:10])["side"], "WAIT")
        data = candles()
        data[-1]["close_time"] = data[-2]["close_time"]
        self.assertEqual(score_candles(data)["side"], "WAIT")

    def test_spread_filter(self):
        self.assertEqual(score_candles(candles(), spread_bps=20)["reason"], "SPREAD_FILTER")

    def test_rank_deduplicates_and_filters(self):
        result = rank_candidates([
            {"symbol": "BTCUSDT", "side": "LONG", "score": 0.7},
            {"symbol": "BTCUSDT", "side": "LONG", "score": 0.8},
            {"symbol": "ETHUSDT", "side": "WAIT", "score": 0.9},
            {"symbol": "SOLUSDT", "side": "SHORT", "score": 0.75},
        ])
        self.assertEqual([(x["symbol"], x["score"]) for x in result],
                         [("BTCUSDT", 0.8), ("SOLUSDT", 0.75)])


if __name__ == "__main__":
    unittest.main()
