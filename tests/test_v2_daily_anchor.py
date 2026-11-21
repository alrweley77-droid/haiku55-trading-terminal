import tempfile
import time
import unittest
from pathlib import Path

from app.v2_paper_broker import V2PaperBroker


class DailyAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "daily-v2.db"
        self.broker = V2PaperBroker(self.path)

    def test_anchor_persists_after_restart_and_cash_change(self):
        self.assertEqual(self.broker.daily_anchor(day="2026-11-21"), 10000)
        self.assertTrue(self.broker.open_risk_checked(
            symbol="BTCUSDT", side="LONG", confidence=.8,
            mark_price=100, observed_at=time.time(),
            day_open_equity=10000, daily_pnl=0)["ok"])
        closed = self.broker.process_mark("BTCUSDT", mark_price=99,
                                           observed_at=time.time())
        self.assertTrue(closed["closed"])
        restarted = V2PaperBroker(self.path)
        self.assertEqual(restarted.daily_anchor(day="2026-11-21"), 10000)
        self.assertLess(restarted.daily_anchor(day="2026-11-22"), 10000)

    def test_invalid_day_rejected(self):
        with self.assertRaises(ValueError):
            self.broker.daily_anchor(day="today")


if __name__ == "__main__":
    unittest.main()
