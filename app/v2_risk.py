"""HAIKU55 V2 PAPER risk policy. No real exchange execution.

Uses stop-distance sizing and aggregate portfolio risk rather than trade-count quotas.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RiskPolicy:
    max_positions: int = 5
    risk_per_trade_pct: float = 0.35
    max_portfolio_stop_risk_pct: float = 1.5
    max_daily_loss_pct: float = 2.5
    max_notional_per_trade_usd: float = 1200.0
    max_total_notional_pct: float = 150.0
    leverage: float = 3.0
    min_confidence: float = 0.65
    stop_pct: float = 0.65
    fee_bps: float = 4.0
    slippage_bps: float = 2.0

    def __post_init__(self):
        values = (self.risk_per_trade_pct, self.max_portfolio_stop_risk_pct,
                  self.max_daily_loss_pct, self.max_notional_per_trade_usd,
                  self.max_total_notional_pct, self.leverage,
                  self.min_confidence, self.stop_pct, self.fee_bps, self.slippage_bps)
        if self.max_positions < 1 or not all(math.isfinite(x) and x > 0 for x in values):
            raise ValueError("Invalid risk policy")
        if not 0 < self.min_confidence <= 1 or self.leverage > 10:
            raise ValueError("Invalid confidence or leverage")


def size_paper_entry(*, equity, day_open_equity, daily_pnl, price, confidence,
                     current_positions, side, symbol, policy=RiskPolicy()):
    """Return risk-gated simulated order, or a rejection reason.

    current_positions: iterable of {symbol, notional_usd, stop_risk_usd}.
    Daily loss includes both realized and unrealized PnL, supplied by caller.
    """
    if not isinstance(current_positions, (list, tuple)):
        return {"ok": False, "reason": "INVALID_POSITIONS"}
    if not isinstance(symbol, str) or not symbol.endswith("USDT") or side not in ("LONG", "SHORT"):
        return {"ok": False, "reason": "INVALID_ORDER"}
    values = (equity, day_open_equity, daily_pnl, price, confidence)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return {"ok": False, "reason": "INVALID_NUMERIC_INPUT"}
    if equity <= 0 or day_open_equity <= 0 or price <= 0 or not 0 <= confidence <= 1:
        return {"ok": False, "reason": "INVALID_ACCOUNT"}
    if confidence < policy.min_confidence:
        return {"ok": False, "reason": "LOW_CONFIDENCE"}
    if daily_pnl <= -day_open_equity * policy.max_daily_loss_pct / 100:
        return {"ok": False, "reason": "DAILY_LOSS_LIMIT"}
    if len(current_positions) >= policy.max_positions:
        return {"ok": False, "reason": "MAX_POSITIONS"}
    if any(p.get("symbol") == symbol for p in current_positions):
        return {"ok": False, "reason": "ALREADY_OPEN"}
    try:
        used_notional = sum(float(p["notional_usd"]) for p in current_positions)
        used_stop_risk = sum(float(p["stop_risk_usd"]) for p in current_positions)
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"ok": False, "reason": "INVALID_POSITIONS"}
    if not all(math.isfinite(x) and x >= 0 for x in (used_notional, used_stop_risk)):
        return {"ok": False, "reason": "INVALID_POSITIONS"}
    risk_room = equity * policy.max_portfolio_stop_risk_pct / 100 - used_stop_risk
    notional_room = equity * policy.max_total_notional_pct / 100 - used_notional
    # Reserve estimated entry and exit friction within the stop risk.
    friction_pct = 2 * (policy.fee_bps + policy.slippage_bps) / 100
    loss_per_notional = (policy.stop_pct + friction_pct) / 100
    if risk_room <= 0 or notional_room <= 0:
        return {"ok": False, "reason": "PORTFOLIO_RISK_LIMIT"}
    notional = min(equity * policy.risk_per_trade_pct / 100 / loss_per_notional,
                   risk_room / loss_per_notional, notional_room,
                   policy.max_notional_per_trade_usd)
    if notional < 10:
        return {"ok": False, "reason": "SIZE_TOO_SMALL"}
    direction = 1 if side == "LONG" else -1
    entry = price * (1 + direction * policy.slippage_bps / 10000)
    stop = entry * (1 - direction * policy.stop_pct / 100)
    return {"ok": True, "mode": "PAPER", "symbol": symbol, "side": side,
            "notional_usd": round(notional, 6), "quantity": round(notional / entry, 8),
            "entry": round(entry, 8), "stop": round(stop, 8),
            "estimated_stop_risk_usd": round(notional * loss_per_notional, 6),
            "estimated_margin_usd": round(notional / policy.leverage, 6),
            "leverage": policy.leverage}
