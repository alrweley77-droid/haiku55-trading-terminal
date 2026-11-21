"""HAIKU55 V2 signal research module. Deterministic PAPER candidates only.

Candles must be fully closed, chronological and supplied by the caller.
This module does not connect to an exchange or place orders.
"""
import math
from statistics import mean


def _validated(candles):
    if not isinstance(candles, (list, tuple)) or len(candles) < 35:
        return None
    rows = []
    previous = -1
    for candle in candles:
        if not isinstance(candle, dict):
            return None
        try:
            timestamp = int(candle["close_time"])
            o, h, l, c, v = (float(candle[k]) for k in ("open", "high", "low", "close", "volume"))
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        if (timestamp <= previous or not all(math.isfinite(x) for x in (o, h, l, c, v))
                or min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c)):
            return None
        previous = timestamp
        rows.append((o, h, l, c, v))
    return rows


def score_candles(candles, *, max_spread_bps=15.0, spread_bps=0.0):
    """Rank momentum, breakout and mean-reversion candidates; abstain on weak data.

    Price and volume signals are heuristic, not evidence of profitable trading.
    Return a side and score for research; separate risk gates must approve entry.
    """
    rows = _validated(candles)
    if rows is None:
        return {"side": "WAIT", "score": 0.0, "reason": "INVALID_OR_INSUFFICIENT_CANDLES"}
    if not math.isfinite(spread_bps) or spread_bps < 0 or spread_bps > max_spread_bps:
        return {"side": "WAIT", "score": 0.0, "reason": "SPREAD_FILTER"}
    closes = [r[3] for r in rows]
    volumes = [r[4] for r in rows]
    last = closes[-1]
    sma_fast, sma_slow = mean(closes[-8:]), mean(closes[-30:])
    momentum = last / closes[-6] - 1
    volume_ratio = volumes[-1] / max(mean(volumes[-21:-1]), 1e-9)
    prev_high = max(r[1] for r in rows[-21:-1])
    prev_low = min(r[2] for r in rows[-21:-1])
    ranges = [max(r[1] - r[2], abs(r[1] - closes[i-1]), abs(r[2] - closes[i-1]))
              for i, r in enumerate(rows) if i > 0]
    atr_pct = mean(ranges[-14:]) / last
    if atr_pct < 0.0004 or atr_pct > 0.10 or volume_ratio < 0.5:
        return {"side": "WAIT", "score": 0.0, "reason": "VOLATILITY_OR_VOLUME_FILTER"}
    bullish = sma_fast > sma_slow and momentum > 0.001
    bearish = sma_fast < sma_slow and momentum < -0.001
    if last > prev_high and bullish and volume_ratio >= 1.2:
        return {"side": "LONG", "score": round(min(0.95, 0.70 + abs(momentum)*5), 4),
                "strategy": "BREAKOUT", "reason": "BREAKOUT_WITH_VOLUME"}
    if last < prev_low and bearish and volume_ratio >= 1.2:
        return {"side": "SHORT", "score": round(min(0.95, 0.70 + abs(momentum)*5), 4),
                "strategy": "BREAKOUT", "reason": "BREAKDOWN_WITH_VOLUME"}
    if bullish and volume_ratio >= 0.8:
        return {"side": "LONG", "score": round(min(0.85, 0.65 + abs(momentum)*3), 4),
                "strategy": "MOMENTUM", "reason": "POSITIVE_TREND"}
    if bearish and volume_ratio >= 0.8:
        return {"side": "SHORT", "score": round(min(0.85, 0.65 + abs(momentum)*3), 4),
                "strategy": "MOMENTUM", "reason": "NEGATIVE_TREND"}
    deviation = (last / sma_slow - 1) / max(atr_pct, 1e-9)
    if deviation < -2 and momentum > 0 and volume_ratio >= 0.8:
        return {"side": "LONG", "score": 0.65, "strategy": "MEAN_REVERSION", "reason": "OVERSOLD_REBOUND"}
    if deviation > 2 and momentum < 0 and volume_ratio >= 0.8:
        return {"side": "SHORT", "score": 0.65, "strategy": "MEAN_REVERSION", "reason": "OVERBOUGHT_PULLBACK"}
    return {"side": "WAIT", "score": 0.0, "reason": "NO_QUALIFIED_SIGNAL"}


def rank_candidates(candidates, *, limit=5, min_score=0.65):
    """Return strongest eligible symbols, one signal per symbol."""
    best = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        symbol = candidate.get("symbol")
        score = candidate.get("score")
        if (not isinstance(symbol, str) or not symbol.endswith("USDT")
                or candidate.get("side") not in ("LONG", "SHORT")
                or not isinstance(score, (float, int)) or not math.isfinite(score)
                or not min_score <= score <= 1):
            continue
        if symbol not in best or score > best[symbol]["score"]:
            best[symbol] = candidate
    return sorted(best.values(), key=lambda c: (-c["score"], c["symbol"]))[:limit]
