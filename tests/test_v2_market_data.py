import unittest
from app.v2_market_data import fetch_closed_klines, parse_closed_klines


def fixture(count=40):
    return [[i * 60000, "100", "102", "99", "101", "1000",
             i * 60000 + 59999] for i in range(count)]


class MarketDataTests(unittest.TestCase):
    def test_excludes_open_candle(self):
        rows = fixture()
        result = parse_closed_klines(rows, now_ms=39 * 60000 + 30000)
        self.assertEqual(len(result), 39)
        self.assertEqual(result[-1]["close_time"], rows[-2][6])

    def test_rejects_too_few_closed(self):
        with self.assertRaises(ValueError):
            parse_closed_klines(fixture(), now_ms=20 * 60000)

    def test_invalid_price_rejected(self):
        rows = fixture()
        rows[5][2] = "nan"
        with self.assertRaises(ValueError):
            parse_closed_klines(rows, now_ms=10**12)

    def test_fetch_is_public_and_read_only(self):
        calls = []
        def opener(url):
            calls.append(url)
            return fixture()
        result = fetch_closed_klines("BTCUSDT", opener=opener, now_ms=10**12)
        self.assertEqual(len(result), 40)
        self.assertIn("/fapi/v1/klines?", calls[0])
        with self.assertRaises(ValueError):
            fetch_closed_klines("../BTCUSDT", opener=opener)


if __name__ == "__main__":
    unittest.main()
