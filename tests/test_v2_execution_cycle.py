import tempfile
import time
import unittest
from pathlib import Path
from app.v2_execution_cycle import execute_paper_cycle
from app.v2_paper_broker import V2PaperBroker


def candles(symbol, interval):
    return [{"close_time": i+1, "open": 100+i*.25,
             "high": 100+i*.25+.4, "low": 100+i*.25-.4,
             "close": 100+i*.25, "volume": 1000} for i in range(45)]


def universe(limit):
    return [{"symbol": "BTCUSDT"}]


def quote(symbol):
    return {"bid": 110.99, "ask": 111.01, "observed_at": time.time()}


class ExecutionCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.broker = V2PaperBroker(Path(self.tmp.name) / "cycle-v2.db")

    def cycle(self, **extra):
        args = dict(broker=self.broker, quote_fetcher=quote,
                    universe_fetcher=universe, candle_fetcher=candles)
        args.update(extra)
        return execute_paper_cycle(**args)

    def test_default_dry_run_never_opens(self):
        result = self.cycle()
        self.assertEqual(result["mode"], "PAPER_DRY_RUN")
        self.assertEqual(self.broker.status()["positions"], [])

    def test_explicit_paper_execution(self):
        result = self.cycle(execute=True)
        self.assertEqual(result["mode"], "PAPER")
        self.assertTrue(all(row["mode"] == "PAPER" for row in result["executed"] if row["ok"]))

    def test_stale_existing_position_prevents_execution(self):
        self.broker.open_risk_checked(symbol="ETHUSDT", side="LONG",
            confidence=.8, mark_price=100, observed_at=time.time(),
            day_open_equity=10000, daily_pnl=0)
        def stale(symbol):
            return {"bid": 100, "ask": 100.01, "observed_at": time.time()-100}
        result = self.cycle(execute=True, quote_fetcher=stale)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "PORTFOLIO_MARKS_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
