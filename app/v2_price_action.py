"""V2 discretionary-style price-action patterns expressed as testable PAPER rules.

Original implementations of common market-structure concepts; no claim that
SMC, ICT or price action has proven superiority. Closed candles only.
"""
from app.v2_signals import _validated


def _wait(reason):
    return {"side": "WAIT", "score": 0.0, "reason": reason}


def _signal(side, score, strategy, reason):
    return {"side": side, "score": score, "strategy": strategy, "reason": reason}


def structure_break(candles, lookback=20):
    """Close beyond prior swing range with a prior trend context."""
    rows = _validated(candles)
    if rows is None:
        return _wait("INVALID_CANDLES")
    if not isinstance(lookback, int) or not 5 <= lookback <= 30:
        return _wait("INVALID_LOOKBACK")
    prior = rows[-lookback-1:-1]
    last = rows[-1]
    ceiling = max(r[1] for r in prior)
    floor = min(r[2] for r in prior)
    previous_mid = (prior[0][3] + prior[-1][3]) / 2
    if last[3] > ceiling and last[3] > last[0] and last[3] > previous_mid:
        return _signal("LONG", 0.72, "MARKET_STRUCTURE", "CLOSE_ABOVE_PRIOR_RANGE")
    if last[3] < floor and last[3] < last[0] and last[3] < previous_mid:
        return _signal("SHORT", 0.72, "MARKET_STRUCTURE", "CLOSE_BELOW_PRIOR_RANGE")
    return _wait("NO_STRUCTURE_BREAK")


def liquidity_sweep(candles, lookback=20):
    """Wick through prior extreme followed by close back inside range."""
    rows = _validated(candles)
    if rows is None:
        return _wait("INVALID_CANDLES")
    if not isinstance(lookback, int) or not 5 <= lookback <= 30:
        return _wait("INVALID_LOOKBACK")
    prior = rows[-lookback-1:-1]
    last = rows[-1]
    high = max(r[1] for r in prior)
    low = min(r[2] for r in prior)
    candle_range = last[1] - last[2]
    if candle_range <= 0:
        return _wait("ZERO_RANGE")
    if last[2] < low and low < last[3] and last[3] > last[0] and (last[3] - last[2]) / candle_range > 0.6:
        return _signal("LONG", 0.69, "LIQUIDITY_SWEEP", "LOW_SWEEP_RECLAIM")
    if last[1] > high and high > last[3] and last[3] < last[0] and (last[1] - last[3]) / candle_range > 0.6:
        return _signal("SHORT", 0.69, "LIQUIDITY_SWEEP", "HIGH_SWEEP_REJECT")
    return _wait("NO_LIQUIDITY_SWEEP")


def engulfing_reversal(candles):
    """Two-bar engulfing body with preceding directional context."""
    rows = _validated(candles)
    if rows is None:
        return _wait("INVALID_CANDLES")
    a, b = rows[-2:]
    if a[3] < a[0] and b[3] > b[0] and b[0] <= a[3] and b[3] >= a[0]:
        if rows[-6][3] > a[3]:
            return _signal("LONG", 0.65, "CANDLESTICK", "BULLISH_ENGULFING")
    if a[3] > a[0] and b[3] < b[0] and b[0] >= a[3] and b[3] <= a[0]:
        if rows[-6][3] < a[3]:
            return _signal("SHORT", 0.65, "CANDLESTICK", "BEARISH_ENGULFING")
    return _wait("NO_ENGULFING")


PRICE_ACTION_STRATEGIES = (structure_break, liquidity_sweep, engulfing_reversal)


def evaluate_price_action(candles):
    return [strategy(candles) for strategy in PRICE_ACTION_STRATEGIES]
