import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.engine import PaperEngine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / "ledger.db")
        self.engine = PaperEngine(self.path, starting_balance=10000)
        self.now = 1900000000.0
        self.engine.update_prices({"BTC": 100.0, "ETH": 200.0, "SOL": 50.0}, self.now)

    def tearDown(self):
        self.engine.db.close()
        self.folder.cleanup()

    def test_paper_trade_enters_with_stop_and_target(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        self.assertGreater(order["target"], order["entry"])
        self.assertLess(order["stop"], order["entry"])
        self.assertLessEqual(order["qty"] * order["entry"], 250.0)
        self.assertEqual(self.engine.status(self.now + 1)["mode"], "PAPER")

    def test_each_paper_trade_notional_is_capped_at_250_usd(self):
        # The cap applies to position notional, not leveraged margin.
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        self.assertLessEqual(order["qty"] * order["entry"], 250.0)
        self.assertEqual(self.engine.config["max_trade_notional_usd"], 250.0)

    def test_open_positions_share_a_portfolio_margin_cap(self):
        folder = tempfile.TemporaryDirectory()
        path = str(Path(folder.name) / "portfolio.db")
        engine = PaperEngine(path, starting_balance=1000)
        try:
            engine.update_prices(
                {"BTC": 100.0, "ETH": 200.0, "SOL": 50.0},
                self.now,
            )
            btc = engine.open("BTC", "LONG", 1, now=self.now + 1)
            eth = engine.open("ETH", "LONG", 1, now=self.now + 2)
            sol = engine.open("SOL", "LONG", 1, now=self.now + 3)
            self.assertTrue(btc["ok"])
            self.assertTrue(eth["ok"])
            self.assertTrue(sol["ok"])
            positions = engine._positions()
            notionals = [p["qty"] * p["entry"] for p in positions]
            total_notional = sum(notionals)
            status = engine.status(self.now + 3)
            futures = status["futures_simulation"]
            self.assertTrue(all(n <= 250.0 for n in notionals))
            self.assertLess(min(notionals), 250.0)
            self.assertLessEqual(futures["margin_used"], futures["margin_limit"])
            self.assertLessEqual(total_notional, 600.0)
            self.assertAlmostEqual(futures["notional_limit"], 600.0, delta=1.0)
        finally:
            engine.db.close()
            folder.cleanup()

    def test_target_closes_and_fees_recorded(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        self.engine.update_prices({"BTC": order["target"] * 1.005}, self.now + 2)
        self.assertEqual(len(self.engine.status(self.now + 2)["positions"]), 0)
        closed = self.engine.trades()
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["reason"], "TARGET")
        self.assertGreater(closed[0]["fee"], 0)
        self.assertGreater(closed[0]["pnl"], 0)

    def test_stop_closes_short(self):
        order = self.engine.open("ETH", "SHORT", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        self.engine.update_prices({"ETH": order["stop"] * 1.005}, self.now + 2)
        self.assertEqual(self.engine.trades()[0]["reason"], "STOP")
        self.assertLess(self.engine.trades()[0]["pnl"], 0)

    def test_duplicate_symbol_blocked(self):
        self.assertTrue(self.engine.open("BTC", "LONG", 1, now=self.now + 1)["ok"])
        self.assertEqual(self.engine.open("BTC", "SHORT", 1, now=self.now + 2)["reason"], "ALREADY_OPEN")

    def test_fails_closed_on_stale_data(self):
        self.assertEqual(self.engine.open("BTC", "LONG", 1, now=self.now + 90)["reason"], "STALE_MARKET_DATA")

    def test_invalid_order_blocked(self):
        self.assertEqual(self.engine.open("OTHER", "LONG", 1, now=self.now + 1)["reason"], "INVALID_ORDER")
        self.assertEqual(self.engine.open("BTC", "SIDEWAYS", 1, now=self.now + 1)["reason"], "INVALID_ORDER")

    def test_paused_and_kill_switch_latches(self):
        self.assertTrue(self.engine.set_control("pause", now=self.now + 1)["ok"])
        self.assertEqual(self.engine.open("BTC", "LONG", 1, now=self.now + 2)["reason"], "PAUSED")
        self.engine.set_control("resume", now=self.now + 2)
        self.assertTrue(self.engine.set_control("kill", now=self.now + 3)["ok"])
        self.assertEqual(self.engine.open("BTC", "LONG", 1, now=self.now + 4)["reason"], "KILL_SWITCH")
        self.assertEqual(self.engine.set_control("resume", now=self.now + 4)["reason"], "KILL_SWITCH_LATCHED_RESTART_REQUIRED")

    def test_db_persists_positions_and_kill_across_restart(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        self.engine.set_control("kill", now=self.now + 90)  # stale feed -> unresolved position remains
        self.engine.db.close()
        self.engine = PaperEngine(self.path)
        status = self.engine.status(self.now + 91)
        self.assertTrue(status["killed"])
        self.assertEqual(len(status["positions"]), 1)
        self.assertEqual(status["feed_status"], "STALE")

    def test_daily_loss_gate(self):
        self.engine._set("day_realized_pnl", -400)
        self.engine.db.commit()
        self.assertEqual(self.engine.open("SOL", "LONG", 1, now=self.now + 1)["reason"], "DAILY_LOSS_LIMIT")

    def test_rule_signal_warmup(self):
        self.assertEqual(self.engine.rule_signal("BTC")["side"], "WAIT")
        for k in range(40):
            self.engine.update_prices({"BTC": 100.0 + k * 0.15}, self.now + k + 1)
        self.assertIn(self.engine.rule_signal("BTC")["side"], ("LONG", "WAIT"))


    def test_mark_price_drives_paper_pnl_and_last_price_is_reference_only(self):
        self.engine.update_prices(
            {"BTC": 101.0}, self.now + 1,
            last_prices={"BTC": 102.0},
            funding={"BTC": {"last_rate": 0.0001, "next_funding_time_ms": 1900000000000}},
        )
        status = self.engine.status(self.now + 1)
        self.assertEqual(status["prices"]["BTC"], 101.0)
        self.assertEqual(status["last_prices"]["BTC"], 102.0)
        self.assertEqual(status["funding_indicative"]["BTC"]["last_rate"], 0.0001)
        self.assertIn("approximation", status["futures_simulation"]["margin_model"])

    def test_open_position_equity_includes_estimated_round_trip_fees(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        status = self.engine.status(self.now + 1)
        self.assertLess(status["equity"], status["cash"])
        self.assertLess(status["unrealized_pnl"], 0)

    def test_short_position_uses_mark_price_for_stop(self):
        order = self.engine.open("SOL", "SHORT", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        # Last price remains below the stop; only the mark price crosses it.
        self.engine.update_prices(
            {"SOL": order["stop"] * 1.001}, self.now + 2,
            last_prices={"SOL": order["entry"] * 0.99},
        )
        self.assertEqual(self.engine.trades()[0]["reason"], "STOP")


    def test_long_funding_payment_is_accrued_once_at_boundary(self):
        due = int((self.now + 5) * 1000)
        self.engine.update_prices(
            {"BTC": 100.0}, self.now + 1,
            funding={"BTC": {"last_rate": 0.001, "next_funding_time_ms": due}},
        )
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 2)
        self.assertTrue(order["ok"])
        pos = self.engine._positions()[0]
        expected = pos["qty"] * 100.0 * 0.001
        self.engine.update_prices(
            {"BTC": 100.0}, self.now + 6,
            funding={"BTC": {"last_rate": 0.0005, "next_funding_time_ms": due + 8 * 60 * 60 * 1000}},
        )
        pos_after = self.engine._positions()[0]
        self.assertAlmostEqual(pos_after["funding_paid"], expected, places=7)
        # Repeated polls at the same funding boundary must not double-charge.
        self.engine.update_prices({"BTC": 100.0}, self.now + 7)
        self.assertAlmostEqual(self.engine._positions()[0]["funding_paid"], expected, places=7)

    def test_short_receives_positive_funding_rate(self):
        due = int((self.now + 5) * 1000)
        self.engine.update_prices(
            {"ETH": 200.0}, self.now + 1,
            funding={"ETH": {"last_rate": 0.001, "next_funding_time_ms": due}},
        )
        order = self.engine.open("ETH", "SHORT", 1, now=self.now + 2)
        self.assertTrue(order["ok"])
        self.engine.update_prices({"ETH": 200.0}, self.now + 6)
        self.assertLess(self.engine._positions()[0]["funding_paid"], 0)

    def test_approximate_liquidation_closes_before_stop_or_target(self):
        order = self.engine.open("SOL", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        pos = self.engine._positions()[0]
        liq = self.engine.liquidation_price(pos)
        self.assertLess(liq, pos["stop"])
        self.engine.update_prices({"SOL": liq * 0.999}, self.now + 2)
        self.assertEqual(self.engine.trades()[0]["reason"], "LIQUIDATION_APPROX")

    def test_manual_close_realizes_fees_and_updates_cash(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        cash_before = self.engine.status(self.now + 1)["cash"]
        self.engine.update_prices({"BTC": 101.0}, self.now + 2)
        result = self.engine.close("BTC", now=self.now + 3)
        self.assertTrue(result["ok"])
        trade = self.engine.trades()[0]
        self.assertEqual(trade["reason"], "MANUAL")
        self.assertGreater(trade["fee"], 0)
        self.assertAlmostEqual(self.engine.status(self.now + 3)["cash"], cash_before + trade["pnl"], places=4)
        self.assertEqual(self.engine.status(self.now + 3)["positions"], [])

    def test_kill_with_fresh_feed_flattens_all_paper_positions(self):
        self.assertTrue(self.engine.open("BTC", "LONG", 1, now=self.now + 1)["ok"])
        self.assertTrue(self.engine.open("ETH", "SHORT", 1, now=self.now + 1)["ok"])
        result = self.engine.set_control("kill", now=self.now + 2)
        self.assertTrue(result["ok"])
        self.assertTrue(result["killed"])
        self.assertEqual(self.engine.status(self.now + 2)["positions"], [])
        self.assertEqual({t["reason"] for t in self.engine.trades()}, {"KILL"})
        self.assertEqual(self.engine.open("SOL", "LONG", 1, now=self.now + 3)["reason"], "KILL_SWITCH")

    def test_short_funding_debit_is_included_in_realized_pnl(self):
        due = int((self.now + 5) * 1000)
        self.engine.update_prices(
            {"ETH": 200.0}, self.now + 1,
            funding={"ETH": {"last_rate": 0.001, "next_funding_time_ms": due}},
        )
        order = self.engine.open("ETH", "SHORT", 1, now=self.now + 2)
        self.assertTrue(order["ok"])
        self.engine.update_prices({"ETH": 200.0}, self.now + 6)
        paid = self.engine._positions()[0]["funding_paid"]
        self.assertLess(paid, 0)
        self.engine.update_prices({"ETH": 199.0}, self.now + 7)
        result = self.engine.close("ETH", now=self.now + 8)
        self.assertTrue(result["ok"])
        trade = self.engine.trades()[0]
        self.assertAlmostEqual(trade["pnl"], result["pnl"], places=4)
        # A negative funding_paid is a credit to the short, so it increases realized PnL.
        self.assertGreater(trade["pnl"], (trade["exit"] - trade["entry"]) * -1 * trade["qty"] - trade["fee"])

    def test_manual_close_blocked_when_market_data_is_stale(self):
        order = self.engine.open("BTC", "LONG", 1, now=self.now + 1)
        self.assertTrue(order["ok"])
        result = self.engine.close("BTC", now=self.now + 90)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "STALE_MARKET_DATA")
        self.assertEqual(len(self.engine.status(self.now + 90)["positions"]), 1)

    def test_legacy_positions_table_receives_funding_columns(self):
        legacy_dir = tempfile.TemporaryDirectory()
        legacy_path = str(Path(legacy_dir.name) / "legacy.db")
        db = sqlite3.connect(legacy_path)
        db.execute("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE NOT NULL,
                side TEXT NOT NULL, qty REAL NOT NULL, entry REAL NOT NULL,
                stop REAL NOT NULL, target REAL NOT NULL, fee_in REAL NOT NULL,
                opened_at REAL NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL
            )
        """)
        db.commit()
        db.close()
        migrated = PaperEngine(legacy_path, starting_balance=1000)
        columns = {row["name"] for row in migrated.db.execute("PRAGMA table_info(positions)")}
        self.assertTrue({
            "funding_paid", "funding_rate", "next_funding_time_ms", "last_funding_time_ms"
        }.issubset(columns))
        migrated.db.close()
        legacy_dir.cleanup()

if __name__ == "__main__":
    unittest.main()
