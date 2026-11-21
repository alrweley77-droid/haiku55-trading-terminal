"""Bar-close, one-position PAPER backtest with conservative next-bar fills.

Research only: stop/target intrabar ambiguity assumes STOP first. No lookahead:
signal uses bars through t, entry at t+1 open. Fee/slippage both sides.
"""
import math

from app.v2_ensemble import select_opportunities
from app.v2_signals import _validated


def backtest_one_symbol(symbol, candles, *, starting_cash=10_000.0,
                        notional_usd=500.0, fee_bps=4.0, slippage_bps=2.0,
                        stop_pct=0.6, target_pct=1.0, max_bars=30):
    if not isinstance(symbol, str) or not symbol.endswith("USDT"):
        raise ValueError("Invalid symbol")
    if _validated(candles) is None:
        raise ValueError("Need at least 35 valid closed candles")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in
               (starting_cash, notional_usd, stop_pct, target_pct, max_bars)):
        raise ValueError("Invalid backtest configuration")
    if not isinstance(max_bars, int):
        raise ValueError("max_bars must be integer")
    if not all(math.isfinite(v) and 0 <= v <= 100 for v in (fee_bps, slippage_bps)):
        raise ValueError("Invalid costs")
    cash, position, trades = float(starting_cash), None, []
    for i in range(35, len(candles)):
        bar = candles[i]
        open_px, high, low, close = (float(bar[k]) for k in ("open", "high", "low", "close"))
        if position is not None:
            side = position["side"]
            stop, target = position["stop"], position["target"]
            # Open gaps are filled at the worse available open, not an unattainable stop.
            if side == "LONG":
                reason = "STOP" if low <= stop else "TARGET" if high >= target else None
                fill = min(open_px, stop) if reason == "STOP" else max(open_px, target)
            else:
                reason = "STOP" if high >= stop else "TARGET" if low <= target else None
                fill = max(open_px, stop) if reason == "STOP" else min(open_px, target)
            if reason is None and i - position["entry_bar"] >= max_bars:
                reason, fill = "TIME", close
            if reason is not None:
                direction = 1 if side == "LONG" else -1
                exit_px = fill * (1 - direction * slippage_bps / 10000)
                exit_fee = abs(position["qty"] * exit_px) * fee_bps / 10000
                pnl = direction * (exit_px - position["entry"]) * position["qty"] - position["entry_fee"] - exit_fee
                cash += pnl
                trades.append({"side": side, "entry_bar": position["entry_bar"], "exit_bar": i,
                               "reason": reason, "pnl": round(pnl, 6)})
                position = None
            # Never open a second trade on the same bar after closing one.
            continue
        # Compute the signal using only completed bars BEFORE this execution bar.
        # Use next-bar open as execution price, with entry slippage and fees.
        previous = candles[:i]
        result = select_opportunities({symbol: {"candles": previous, "spread_bps": 1.0}})
        if not result["candidates"]:
            continue
        side = result["candidates"][0]["side"]
        direction = 1 if side == "LONG" else -1
        entry = open_px * (1 + direction * slippage_bps / 10000)
        qty = min(notional_usd, max(cash, 0.0)) / entry
        if qty <= 0:
            break
        position = {"side": side, "entry": entry, "qty": qty,
                    "entry_fee": qty * entry * fee_bps / 10000,
                    "stop": entry * (1 - direction * stop_pct / 100),
                    "target": entry * (1 + direction * target_pct / 100),
                    "entry_bar": i}
    realized = sum(t["pnl"] for t in trades)
    return {"mode": "PAPER_BACKTEST", "symbol": symbol,
            "starting_cash": starting_cash, "realized_cash": round(cash, 4),
            "realized_pnl": round(realized, 4), "closed_trades": len(trades),
            "open_position_at_end": position is not None,
            "win_rate_pct": round(100 * sum(t["pnl"] > 0 for t in trades) / len(trades), 2) if trades else 0,
            "trades": trades,
            "limitations": "One-symbol long/short model; no funding, liquidation, order-book depth, correlated exposure or partial fills."}
