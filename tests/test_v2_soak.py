"""Deterministic offline V2 repeated-cycle and persistence regression tests."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.v2_paper_broker import V2PaperBroker
from app.v2_supervisor import run_cycles


class V2SoakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "soak-v2.db"
        self.broker = V2PaperBroker(self.path)

    def test_repeated_paper_entries_do_not_duplicate_after_restart(self):
        attempts = []
        def one_cycle(*, broker, execute):
            self.assertTrue(execute)
            result = broker.open_risk_checked(
                symbol="BTCUSDT", side="LONG", confidence=.8,
                mark_price=100, observed_at=time.time(),
                day_open_equity=10000, daily_pnl=0,
                portfolio_marks={"BTCUSDT": {"bid": 100, "ask": 100.01,
                                             "observed_at": time.time()}})
            attempts.append(result)
            return {"ok": True, "mode": "PAPER"}
        with patch.dict(os.environ, {"HAIKU55_V2_PAPER_EXECUTE": "YES"}):
            reports = run_cycles(broker=self.broker, execute=True, cycles=25,
                                 interval_seconds=1, sleep_fn=lambda _: None,
                                 cycle_fn=one_cycle)
        self.assertEqual(len(reports), 25)
        self.assertTrue(attempts[0]["ok"])
        self.assertTrue(all(not result["ok"] for result in attempts[1:]))
        self.assertTrue(all(result["reason"] == "ALREADY_OPEN" for result in attempts[1:]))
        self.assertEqual(len(V2PaperBroker(self.path).status()["positions"]), 1)

    def test_legacy_entry_is_always_rejected(self):
        for _ in range(10):
            result = self.broker.open_plan({"mode": "PAPER", "symbol": "BTCUSDT",
                "side": "LONG", "entry": 100, "stop": 99, "quantity": 1000},
                mark_price=100, observed_at=time.time())
            self.assertEqual(result["reason"], "USE_ATOMIC_RISK_CHECKED_ENTRY")
        self.assertEqual(self.broker.status()["positions"], [])


if __name__ == "__main__":
    unittest.main()
