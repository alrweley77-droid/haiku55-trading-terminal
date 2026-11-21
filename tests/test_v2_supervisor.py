import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.v2_paper_broker import V2PaperBroker
from app.v2_supervisor import run_cycles


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "supervisor-v2.db"
        self.broker = V2PaperBroker(self.path)

    def test_dry_run_multiple_cycles_preserves_database(self):
        seen = []
        def cycle_fn(*, broker, execute):
            seen.append((broker.status()["cash"], execute))
            return {"ok": True, "mode": "PAPER_DRY_RUN"}
        reports = run_cycles(broker=self.broker, cycles=3, interval_seconds=1,
                             cycle_fn=cycle_fn, sleep_fn=lambda seconds: None)
        self.assertEqual(len(reports), 3)
        self.assertEqual(seen, [(10000, False)] * 3)
        self.assertEqual(V2PaperBroker(self.path).status()["cash"], 10000)

    def test_stops_on_failed_cycle(self):
        def cycle_fn(*, broker, execute):
            return {"ok": False, "reason": "MARKET_OFFLINE"}
        reports = run_cycles(broker=self.broker, cycles=3, interval_seconds=1,
                             cycle_fn=cycle_fn, sleep_fn=lambda seconds: None)
        self.assertEqual(len(reports), 1)

    def test_paper_execution_requires_explicit_environment_gate(self):
        with patch.dict(os.environ, {"HAIKU55_V2_PAPER_EXECUTE": ""}):
            with self.assertRaises(PermissionError):
                run_cycles(broker=self.broker, cycles=1, execute=True,
                           cycle_fn=lambda **kw: {"ok": True})
        with patch.dict(os.environ, {"HAIKU55_V2_PAPER_EXECUTE": "YES"}):
            reports = run_cycles(broker=self.broker, cycles=1, execute=True,
                                 cycle_fn=lambda **kw: {"ok": True})
        self.assertEqual(len(reports), 1)


if __name__ == "__main__":
    unittest.main()
