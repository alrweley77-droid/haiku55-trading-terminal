"""Public Binance USD-M V2 candle adapter (read-only, PAPER research).

Only fully closed kline bars are returned. No API credentials or orders.
"""
import json
import math
import time
import urllib.parse
import urllib.request

BASE = "https://fapi.binance.com"
INTERVALS = frozenset(("1m", "3m", "5m", "15m", "30m", "1h"))
MAX_RESPONSE_BYTES = 2_000_000


def parse_closed_klines(payload, *, now_ms=None, minimum=35):
    if not isinstance(payload, list) or len(payload) < minimum:
        raise ValueError("Insufficient kline data")
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    result = []
    previous = -1
    for row in payload:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            raise ValueError("Invalid kline row")
        try:
            start, close_time = int(row[0]), int(row[6])
            o, h, l, c, v = (float(row[i]) for i in (1, 2, 3, 4, 5))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid kline value") from exc
        if (start <= previous or close_time < start or not all(math.isfinite(x) for x in (o, h, l, c, v))
                or min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c)):
            raise ValueError("Malformed kline")
        previous = start
        if close_time >= now_ms:
            # The latest in-progress bar is excluded, never used as a signal.
            continue
        result.append({"close_time": close_time, "open": o, "high": h,
                       "low": l, "close": c, "volume": v})
    if len(result) < minimum:
        raise ValueError("Not enough closed candles")
    return result


def fetch_closed_klines(symbol, *, interval="1m", limit=120, opener=None, now_ms=None):
    if not isinstance(symbol, str) or not symbol.endswith("USDT") or not symbol.isascii() or not symbol.isalnum():
        raise ValueError("Invalid symbol")
    if interval not in INTERVALS or not isinstance(limit, int) or not 40 <= limit <= 500:
        raise ValueError("Invalid interval or limit")
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = BASE + "/fapi/v1/klines?" + query
    if opener is not None:
        payload = opener(url)
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "HAIKU55-V2-PAPER"})
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Market data response too large")
            payload = json.loads(raw)
    return parse_closed_klines(payload, now_ms=now_ms)
