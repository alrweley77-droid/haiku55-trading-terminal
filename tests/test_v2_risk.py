import unittest
from app.v2_risk import RiskPolicy, size_paper_entry


def size(**kwargs):
    data = dict(equity=10000, day_open_equity=10000, daily_pnl=0,
                price=100, confidence=0.75, current_positions=[],
                side="LONG", symbol="BTCUSDT")
    data.update(kwargs)
    return size_paper_entry(**data)


class RiskTests(unittest.TestCase):
    def test_new_account_is_paper_and_capped(self):
        result = size()
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "PAPER")
        self.assertLessEqual(result["notional_usd"], 1200)
        self.assertLessEqual(result["estimated_stop_risk_usd"], 35.001)

    def test_daily_loss_gate(self):
        self.assertEqual(size(daily_pnl=-250)["reason"], "DAILY_LOSS_LIMIT")

    def test_portfolio_risk_and_duplicates(self):
        positions = [{"symbol": "ETHUSDT", "notional_usd": 1000, "stop_risk_usd": 150}]
        self.assertEqual(size(current_positions=positions)["reason"], "PORTFOLIO_RISK_LIMIT")
        self.assertEqual(size(symbol="ETHUSDT", current_positions=positions)["reason"], "ALREADY_OPEN")

    def test_invalid_or_low_confidence(self):
        self.assertEqual(size(confidence=0.4)["reason"], "LOW_CONFIDENCE")
        self.assertEqual(size(price=float("nan"))["reason"], "INVALID_NUMERIC_INPUT")

    def test_short_stop_above_entry(self):
        result = size(side="SHORT")
        self.assertGreater(result["stop"], result["entry"])

    def test_invalid_policy(self):
        with self.assertRaises(ValueError):
            RiskPolicy(leverage=20)


if __name__ == "__main__":
    unittest.main()
