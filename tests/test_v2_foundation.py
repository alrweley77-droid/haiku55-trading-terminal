import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.v2_universe import select_universe
from app.v2_ledger import initialize_v2_ledger


class UniverseTests(unittest.TestCase):
    def test_filters_and_ranks(self):
        info = {"symbols": [
            {"symbol": "AAAUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT"},
            {"symbol": "BBBUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT"},
            {"symbol": "CCCUSDT", "status": "BREAK", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT"},
        ]}
        ticks = [
            {"symbol": "AAAUSDT", "bidPrice": "100", "askPrice": "100.01", "quoteVolume": "30000000"},
            {"symbol": "BBBUSDT", "bidPrice": "100", "askPrice": "100.01", "quoteVolume": "50000000"},
            {"symbol": "CCCUSDT", "bidPrice": "100", "askPrice": "100.01", "quoteVolume": "90000000"},
        ]
        self.assertEqual([r["symbol"] for r in select_universe(info, ticks)], ["BBBUSDT", "AAAUSDT"])
        ticks[1]["askPrice"] = "105"
        self.assertEqual([r["symbol"] for r in select_universe(info, ticks)], ["AAAUSDT"])

    def test_missing_spread_is_rejected(self):
        info = {"symbols": [{"symbol": "AAAUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT"}]}
        self.assertEqual(select_universe(info, [{"symbol": "AAAUSDT", "quoteVolume": "99999999"}]), [])
        with self.assertRaises(ValueError):
            select_universe([], [])


class LedgerTests(unittest.TestCase):
    def test_idempotent_and_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "haiku55.db"
            sqlite3.connect(old).close()
            target = Path(temp) / "haiku55-v2.db"
            self.assertEqual(initialize_v2_ledger(target)["cash"], 10000)
            with sqlite3.connect(target) as db:
                db.execute("UPDATE v2_accounts SET cash=9000 WHERE id=1")
                db.commit()
            self.assertEqual(initialize_v2_ledger(target)["cash"], 9000)
            self.assertEqual(old.stat().st_size, 0)
            with self.assertRaises(ValueError):
                initialize_v2_ledger(old)


if __name__ == "__main__":
    unittest.main()
