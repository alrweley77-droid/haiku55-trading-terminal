import tempfile
import time
import unittest
from pathlib import Path
from app.v2_paper_broker import V2PaperBroker


class AtomicPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.broker = V2PaperBroker(Path(self.tmp.name) / "risk-v2.db")

    def order(self, **updates):
        args = dict(symbol="BTCUSDT", side="LONG", confidence=.8,
                    mark_price=100, observed_at=time.time(),
                    day_open_equity=10000, daily_pnl=0)
        args.update(updates)
        return self.broker.open_risk_checked(**args)

    def test_first_order_and_fail_closed_second(self):
        self.assertTrue(self.order()["ok"])
        result = self.order(symbol="ETHUSDT")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "OPEN_POSITIONS_REQUIRE_FRESH_PORTFOLIO_MARKS")
        self.assertEqual(len(self.broker.status()["positions"]), 1)

    def test_daily_loss_and_stale_quote(self):
        self.assertEqual(self.order(daily_pnl=-300)["reason"], "DAILY_LOSS_LIMIT")
        self.assertEqual(self.order(observed_at=time.time()-100)["reason"],
                         "STALE_OR_INVALID_MARK")
        self.assertEqual(len(self.broker.status()["positions"]), 0)

    def test_reopen_after_restart_does_not_reset_cash(self):
        self.assertTrue(self.order()["ok"])
        restarted = V2PaperBroker(self.broker.db_path)
        self.assertEqual(len(restarted.status()["positions"]), 1)
        self.assertEqual(restarted.status()["cash"], 10000)


if __name__ == "__main__":
    unittest.main()
