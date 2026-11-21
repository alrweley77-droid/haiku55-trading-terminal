"""V2 isolated Binance USD-M universe discovery. Public market data only; no orders."""
import json
import math
import urllib.request

BASE = "https://fapi.binance.com"
EXCHANGE_INFO = BASE + "/fapi/v1/exchangeInfo"
TICKER_24H = BASE + "/fapi/v1/ticker/24hr"


def _positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def select_universe(exchange_info, tickers, *, limit=40, min_quote_volume=20_000_000,
                    max_spread_bps=15):
    """Return ranked symbols; fail closed on missing or malformed market data.

    Binance 24hr ticker includes bidPrice and askPrice; these are only a snapshot
    and cannot guarantee executable spread. No real trading is performed.
    """
    if not isinstance(exchange_info, dict) or not isinstance(tickers, list):
        raise ValueError("Invalid Binance response")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Invalid universe limit")
    allowed = {
        s["symbol"] for s in exchange_info.get("symbols", [])
        if isinstance(s, dict) and isinstance(s.get("symbol"), str)
        and s.get("status") == "TRADING"
        and s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("marginAsset") == "USDT"
    }
    ranked = []
    for t in tickers:
        if not isinstance(t, dict) or t.get("symbol") not in allowed:
            continue
        bid, ask = _positive(t.get("bidPrice")), _positive(t.get("askPrice"))
        volume = _positive(t.get("quoteVolume"))
        if bid is None or ask is None or volume is None or ask < bid:
            continue
        spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000
        if volume < min_quote_volume or spread_bps > max_spread_bps:
            continue
        ranked.append({"symbol": t["symbol"], "quote_volume_usd": volume,
                       "spread_bps": round(spread_bps, 4)})
    ranked.sort(key=lambda x: (-x["quote_volume_usd"], x["spread_bps"], x["symbol"]))
    return ranked[:limit]


def fetch_universe(*, limit=40, opener=None):
    """Fetch public metadata and a 24-hour snapshot, never private credentials."""
    def get(url):
        request = urllib.request.Request(url, headers={"User-Agent": "HAIKU55-V2-PAPER"})
        if opener is None:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        return opener(url)
    return select_universe(get(EXCHANGE_INFO), get(TICKER_24H), limit=limit)
