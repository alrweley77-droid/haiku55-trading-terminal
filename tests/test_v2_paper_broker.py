import tempfile
import time
import unittest
from pathlib import Path

from app.v2_paper_broker import V2PaperBroker
from app.v2_risk import size_paper_entry


class PaperBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "isolated-v2.db"
        self.broker = V2PaperBroker(self.path)

    def plan(self):
        return size_paper_entry(equity=10000, day_open_equity=10000,
                                daily_pnl=0, price=100, confidence=0.8,
                                current_positions=[], side="LONG", symbol="BTCUSDT")

    def test_open_stop_and_persist(self):
        plan = self.plan()
        self.assertTrue(plan["ok"])
        result = self.broker.open_risk_checked(symbol="BTCUSDT", side="LONG", confidence=.8, mark_price=100, observed_at=time.time(), day_open_equity=10000, daily_pnl=0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.broker.status()["cash"], 10000)
        closed = self.broker.process_mark("BTCUSDT", mark_price=99, observed_at=time.time())
        self.assertTrue(closed["closed"])
        self.assertEqual(closed["reason"], "STOP")
        self.assertLess(V2PaperBroker(self.path).status()["cash"], 10000)
        self.assertEqual(V2PaperBroker(self.path).status()["closed_trades"], 1)

    def test_reject_stale_mark_and_duplicate(self):
        plan = self.plan()
        self.assertEqual(self.broker.open_risk_checked(symbol="BTCUSDT", side="LONG", confidence=.8, mark_price=100,
                         observed_at=time.time()-100, day_open_equity=10000, daily_pnl=0)["reason"], "STALE_OR_INVALID_MARK")
        self.assertTrue(self.broker.open_risk_checked(symbol="BTCUSDT", side="LONG", confidence=.8, mark_price=100,
                        observed_at=time.time(), day_open_equity=10000, daily_pnl=0)["ok"])
        self.assertEqual(self.broker.open_risk_checked(symbol="BTCUSDT", side="LONG", confidence=.8, mark_price=100,
                         observed_at=time.time(), day_open_equity=10000, daily_pnl=0,
                         portfolio_marks={"BTCUSDT": {"bid": 100, "ask": 100.01, "observed_at": time.time()}})["reason"], "ALREADY_OPEN")

    def test_legacy_adapter_cannot_bypass_risk(self):
        result = self.broker.open_plan(self.plan(), mark_price=100, observed_at=time.time())
        self.assertEqual(result["reason"], "USE_ATOMIC_RISK_CHECKED_ENTRY")
        self.assertEqual(self.broker.status()["positions"], [])

    def test_no_close_without_trigger(self):
        plan = self.plan()
        self.broker.open_plan(plan, mark_price=100, observed_at=time.time())
        result = self.broker.process_mark("BTCUSDT", mark_price=100, observed_at=time.time())
        self.assertTrue(result["ok"])
        self.assertFalse(result["closed"])


if __name__ == "__main__":
    unittest.main()
