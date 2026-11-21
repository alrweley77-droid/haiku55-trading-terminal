import unittest
from unittest.mock import patch
from app.v2_runner import run_once, main


def candles(symbol, interval):
    return [{"close_time": i+1, "open": 100+i*.25,
             "high": 100+i*.25+.4, "low": 100+i*.25-.4,
             "close": 100+i*.25, "volume": 1000} for i in range(45)]


class RunnerTests(unittest.TestCase):
    def test_dry_run_has_no_broker(self):
        result = run_once(
            universe_fetcher=lambda limit: [{"symbol": "BTCUSDT"}],
            quote_fetcher=lambda symbol: {"bid": 110.99, "ask": 111.01,
                                          "observed_at": __import__("time").time()},
            candle_fetcher=candles)
        self.assertEqual(result["mode"], "PAPER_PLAN_ONLY")
        self.assertIn("plans", result)

    def test_fails_closed_on_universe_outage(self):
        def broken(limit):
            raise ConnectionError("offline")
        with patch("app.v2_runner.run_once", side_effect=ConnectionError("offline")):
            self.assertEqual(main(["--limit", "3"]), 1)


if __name__ == "__main__":
    unittest.main()
