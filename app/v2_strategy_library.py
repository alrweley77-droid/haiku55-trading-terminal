"""Independent V2 PAPER strategy candidates. No exchange orders.

Strategies use only completed chronological candles and return candidate scores.
These are original implementations of common indicator-based trading rules,
not copied proprietary signals or claims of proven profitability.
"""
import math
from statistics import mean, pstdev

from app.v2_signals import _validated


def _wait(reason):
    return {"side": "WAIT", "score": 0.0, "reason": reason}


def _candidate(side, score, strategy, reason):
    return {"side": side, "score": round(score, 4), "strategy": strategy, "reason": reason}


def _series(candles):
    rows = _validated(candles)
    if rows is None:
        return None
    return [r[3] for r in rows], [r[1] for r in rows], [r[2] for r in rows], [r[4] for r in rows]


def _ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _rsi(closes, period=14):
    changes = [b - a for a, b in zip(closes[-period-1:-1], closes[-period:])]
    gains = sum(max(change, 0) for change in changes) / period
    losses = sum(max(-change, 0) for change in changes) / period
    if gains == 0 and losses == 0:
        return 50.0
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def ema_trend(candles):
    """EMA(9)/EMA(21) with EMA(34) directional confirmation."""
    data = _series(candles)
    if data is None:
        return _wait("INVALID_CANDLES")
    closes, _, _, _ = data
    fast, medium, slow = (_ema(closes, p) for p in (9, 21, 34))
    price = closes[-1]
    separation = abs(fast - medium) / price
    if separation < 0.0004:
        return _wait("EMA_NO_EDGE")
    if price > fast > medium > slow:
        return _candidate("LONG", min(0.86, 0.66 + separation * 12), "EMA_TREND", "EMA_BULL_STACK")
    if price < fast < medium < slow:
        return _candidate("SHORT", min(0.86, 0.66 + separation * 12), "EMA_TREND", "EMA_BEAR_STACK")
    return _wait("EMA_NOT_ALIGNED")


def bollinger_reversion(candles):
    """Bollinger(20,2) re-entry: previous close outside band, latest inside."""
    data = _series(candles)
    if data is None:
        return _wait("INVALID_CANDLES")
    closes, _, _, _ = data
    old, new = closes[-21:-1], closes[-20:]
    old_std, new_std = pstdev(old), pstdev(new)
    if min(old_std, new_std) <= 0:
        return _wait("FLAT_BANDS")
    old_lower, old_upper = mean(old) - 2 * old_std, mean(old) + 2 * old_std
    new_lower, new_upper = mean(new) - 2 * new_std, mean(new) + 2 * new_std
    if closes[-2] < old_lower and new_lower <= closes[-1] < mean(new):
        return _candidate("LONG", 0.67, "BOLLINGER_REVERSION", "REENTRY_FROM_LOWER_BAND")
    if closes[-2] > old_upper and mean(new) < closes[-1] <= new_upper:
        return _candidate("SHORT", 0.67, "BOLLINGER_REVERSION", "REENTRY_FROM_UPPER_BAND")
    return _wait("NO_BAND_REENTRY")


def rsi_reversal(candles):
    """RSI(14) recovery through 30 or reversal below 70."""
    data = _series(candles)
    if data is None:
        return _wait("INVALID_CANDLES")
    closes, _, _, _ = data
    prior, current = _rsi(closes[:-1]), _rsi(closes)
    if prior < 30 <= current:
        return _candidate("LONG", 0.66, "RSI_REVERSAL", "RSI_RECOVERED_30")
    if prior > 70 >= current:
        return _candidate("SHORT", 0.66, "RSI_REVERSAL", "RSI_FELL_BELOW_70")
    return _wait("NO_RSI_CROSS")


def donchian_breakout(candles, lookback=20):
    """20-bar Donchian breakout confirmed by above-average volume."""
    data = _series(candles)
    if data is None:
        return _wait("INVALID_CANDLES")
    closes, highs, lows, volumes = data
    if not isinstance(lookback, int) or not 5 <= lookback <= 30:
        return _wait("INVALID_LOOKBACK")
    if volumes[-1] < 1.25 * max(mean(volumes[-lookback-1:-1]), 1e-9):
        return _wait("BREAKOUT_LOW_VOLUME")
    if closes[-1] > max(highs[-lookback-1:-1]):
        return _candidate("LONG", 0.73, "DONCHIAN_BREAKOUT", "NEW_CHANNEL_HIGH")
    if closes[-1] < min(lows[-lookback-1:-1]):
        return _candidate("SHORT", 0.73, "DONCHIAN_BREAKOUT", "NEW_CHANNEL_LOW")
    return _wait("NO_CHANNEL_BREAK")


STRATEGIES = (ema_trend, bollinger_reversion, rsi_reversal, donchian_breakout)


def evaluate_strategies(candles, *, spread_bps, max_spread_bps=15.0):
    """Run all candidates with a shared spread gate; do not execute trades."""
    if not isinstance(spread_bps, (int, float)) or not math.isfinite(spread_bps) or not 0 <= spread_bps <= max_spread_bps:
        return [_wait("SPREAD_FILTER")]
    return [strategy(candles) for strategy in STRATEGIES]
