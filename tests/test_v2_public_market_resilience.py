"""Offline-only V2 public-market resilience tests; never contacts Binance."""
import json
import time
import unittest
from unittest.mock import patch

from app.v2_runner import public_quote
from app.v2_universe import fetch_universe
from app.v2_execution_cycle import _quote


class _Response:
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.data[:limit]


class PublicMarketResilienceTests(unittest.TestCase):
    def test_quote_read_only_and_symbol_verified(self):
        payload = json.dumps({"symbol": "BTCUSDT", "bidPrice": "100",
                              "askPrice": "100.01"}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)) as request:
            quote = public_quote("BTCUSDT")
        self.assertEqual(quote["bid"], 100)
        self.assertEqual(quote["ask"], 100.01)
        self.assertIn("/fapi/v1/ticker/bookTicker?", request.call_args.args[0].full_url)
        self.assertNotIn("/order", request.call_args.args[0].full_url)

    def test_quote_symbol_mismatch_rejected(self):
        payload = json.dumps({"symbol": "ETHUSDT", "bidPrice": "100",
                              "askPrice": "100.01"}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)):
            with self.assertRaises(ValueError):
                public_quote("BTCUSDT")

    def test_wide_spread_rejected_at_execution(self):
        with self.assertRaisesRegex(ValueError, "SPREAD_TOO_WIDE"):
            _quote(lambda symbol: {"bid": 100, "ask": 102,
                                   "observed_at": time.time()},
                   "BTCUSDT", now=time.time())

    def test_universe_filters_inactive_and_missing_books(self):
        def opener(url):
            if url.endswith("/exchangeInfo"):
                return {"symbols": [
                    {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
                     "quoteAsset": "USDT", "marginAsset": "USDT"},
                    {"symbol": "BADUSDT", "status": "BREAK", "contractType": "PERPETUAL",
                     "quoteAsset": "USDT", "marginAsset": "USDT"}]}
            if url.endswith("/24hr"):
                return [{"symbol": "BTCUSDT", "quoteVolume": "100000000"},
                        {"symbol": "BADUSDT", "quoteVolume": "100000000"}]
            return [{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.01"}]
        universe = fetch_universe(limit=10, opener=opener)
        self.assertEqual([r["symbol"] for r in universe], ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
