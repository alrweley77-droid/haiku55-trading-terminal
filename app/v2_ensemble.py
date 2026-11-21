"""V2 PAPER-only strategy ensemble: rank candidates without forcing trades.

Scores are heuristic priorities, not calibrated probabilities. No real orders.
"""
import math
from app.v2_signals import rank_candidates, score_candles
from app.v2_strategy_library import evaluate_strategies


def select_opportunities(markets, *, limit=5, min_score=0.65,
                         fee_bps_per_side=4.0, slippage_bps_per_side=2.0,
                         minimum_expected_move_bps=18.0):
    """Evaluate closed candles for eligible markets, returning ranked paper candidates.

    markets: {symbol: {candles: [...], spread_bps: float, updated_at: number}}
    Caller must independently enforce market freshness, exposure and position risk.
    A minimum move gate is a cost sanity check, NOT a profit forecast.
    """
    if not isinstance(markets, dict):
        raise ValueError("markets must be a dictionary")
    if any(not math.isfinite(v) or v < 0 for v in
           (fee_bps_per_side, slippage_bps_per_side, minimum_expected_move_bps)):
        raise ValueError("Invalid cost assumptions")
    round_trip_cost_bps = 2 * (fee_bps_per_side + slippage_bps_per_side)
    if minimum_expected_move_bps <= round_trip_cost_bps:
        raise ValueError("Expected move threshold must exceed round-trip costs")
    candidates = []
    diagnostics = {}
    for symbol, data in markets.items():
        if not isinstance(symbol, str) or not symbol.endswith("USDT") or not isinstance(data, dict):
            continue
        spread = data.get("spread_bps")
        if not isinstance(spread, (float, int)) or not math.isfinite(spread) or spread < 0:
            diagnostics[symbol] = "INVALID_SPREAD"
            continue
        if round_trip_cost_bps + spread >= minimum_expected_move_bps:
            diagnostics[symbol] = "COST_GATE"
            continue
        candles = data.get("candles")
        signals = evaluate_strategies(candles, spread_bps=spread)
        signals.append(score_candles(candles, spread_bps=spread))
        qualifying = [s for s in signals if s.get("side") in ("LONG", "SHORT")
                      and isinstance(s.get("score"), (int, float)) and s["score"] >= min_score]
        if not qualifying:
            diagnostics[symbol] = "NO_SIGNAL"
            continue
        by_side = {}
        for signal in qualifying:
            side = signal["side"]
            by_side.setdefault(side, []).append(signal)
        if len(by_side) > 1:
            diagnostics[symbol] = "CONFLICTING_STRATEGIES"
            continue
        side, votes = next(iter(by_side.items()))
        strongest = max(votes, key=lambda s: s["score"])
        candidates.append({
            "symbol": symbol, "side": side,
            "score": round(min(0.99, strongest["score"] + 0.015 * (len(votes) - 1)), 4),
            "strategy": strongest.get("strategy", "TREND"),
            "confirmations": len(votes),
            "round_trip_cost_bps": round(round_trip_cost_bps + spread, 4),
            "reason": strongest["reason"],
        })
        diagnostics[symbol] = "CANDIDATE"
    return {"candidates": rank_candidates(candidates, limit=limit, min_score=min_score),
            "diagnostics": diagnostics, "mode": "PAPER_RESEARCH"}
