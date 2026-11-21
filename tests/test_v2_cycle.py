import unittest
from app.v2_cycle import build_markets, paper_planning_cycle
from app.v2_universe import fetch_universe


def candles(symbol, interval):
    return [{"close_time": i+1, "open": 100+i*.25,
             "high": 100+i*.25+.4, "low": 100+i*.25-.4,
             "close": 100+i*.25, "volume": 1000} for i in range(45)]


class CycleTests(unittest.TestCase):
    def test_fresh_quotes_generate_paper_plans(self):
        quote = lambda symbol: {"bid": 110.99, "ask": 111.01, "observed_at": 1000}
        result = paper_planning_cycle([{"symbol": "BTCUSDT"}],
                    quote_fetcher=quote, fetcher=candles, now=1000,
                    equity=10000, day_open_equity=10000,
                    daily_pnl=0, current_positions=[])
        self.assertEqual(result["mode"], "PAPER_PLAN_ONLY")
        self.assertTrue(all(p["mode"] == "PAPER" for p in result["plans"]))

    def test_stale_quote_fails_closed(self):
        quote = lambda symbol: {"bid": 100, "ask": 101, "observed_at": 1}
        result = build_markets([{"symbol": "BTCUSDT"}], quote_fetcher=quote,
                               fetcher=candles, now=1000)
        self.assertEqual(result["markets"], {})
        self.assertIn("BTCUSDT", result["rejected"])

    def test_universe_joins_book_spreads(self):
        info = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING",
                             "contractType": "PERPETUAL", "quoteAsset": "USDT",
                             "marginAsset": "USDT"}]}
        def opener(url):
            if url.endswith("exchangeInfo"):
                return info
            if url.endswith("bookTicker"):
                return [{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.05"}]
            return [{"symbol": "BTCUSDT", "quoteVolume": "50000000"}]
        self.assertEqual(fetch_universe(opener=opener)[0]["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
