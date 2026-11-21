"""HAIKU55 V2 PAPER decision planner.

No order submission or persistence: an execution adapter must independently
validate prices, timestamps, funding, exchange precision, and risk before fills.
"""
import math
from app.v2_ensemble import select_opportunities
from app.v2_risk import RiskPolicy, size_paper_entry


def plan_paper_entries(markets, *, equity, day_open_equity, daily_pnl,
                       current_positions, policy=RiskPolicy(), limit=5):
    """Generate simulated entry plans from candidate signals and mark prices.

    Only one new candidate per symbol; respect aggregate portfolio risk as
    plans accumulate. No actual order is placed by this function.
    """
    result = select_opportunities(markets, limit=limit, min_score=policy.min_confidence,
                                  fee_bps_per_side=policy.fee_bps,
                                  slippage_bps_per_side=policy.slippage_bps)
    pending = list(current_positions)
    plans, rejected = [], {}
    for candidate in result["candidates"]:
        symbol = candidate["symbol"]
        market = markets[symbol]
        mark = market.get("mark_price")
        # A live adapter must also enforce a timestamp/freshness check.
        if not isinstance(mark, (int, float)) or not math.isfinite(mark) or mark <= 0:
            rejected[symbol] = "INVALID_MARK_PRICE"
            continue
        decision = size_paper_entry(
            equity=equity, day_open_equity=day_open_equity, daily_pnl=daily_pnl,
            price=mark, confidence=candidate["score"], current_positions=pending,
            side=candidate["side"], symbol=symbol, policy=policy)
        if not decision["ok"]:
            rejected[symbol] = decision["reason"]
            continue
        plans.append({**decision, "strategy": candidate["strategy"],
                      "confirmations": candidate["confirmations"],
                      "signal_score": candidate["score"]})
        pending.append({"symbol": symbol, "notional_usd": decision["notional_usd"],
                        "stop_risk_usd": decision["estimated_stop_risk_usd"]})
    return {"mode": "PAPER_PLAN_ONLY", "plans": plans, "rejected": rejected,
            "signal_diagnostics": result["diagnostics"]}
