"""V2 PAPER orchestration: public closed candles + verified market snapshots.

A cycle plans only; executing plans requires a separate broker authorization.
This module intentionally has no live trading endpoints or credentials.
"""
import math
import time

from app.v2_market_data import fetch_closed_klines
from app.v2_planner import plan_paper_entries
from app.v2_risk import RiskPolicy


def build_markets(universe, *, fetcher=fetch_closed_klines,
                  quote_fetcher, now=None, interval="1m", max_age_seconds=10):
    """Build market inputs only when public bid/ask quote is fresh and valid.

    quote_fetcher(symbol) -> {bid, ask, observed_at}; time is Unix seconds.
    No price fallback is allowed.
    """
    now = time.time() if now is None else now
    if not isinstance(universe, list) or not callable(quote_fetcher):
        raise ValueError("Invalid market sources")
    markets, rejected = {}, {}
    for item in universe:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol.endswith("USDT"):
            continue
        try:
            quote = quote_fetcher(symbol)
            bid, ask, observed = (float(quote[k]) for k in ("bid", "ask", "observed_at"))
            if (not all(math.isfinite(v) for v in (bid, ask, observed))
                    or bid <= 0 or ask < bid or observed > now + 1
                    or now - observed > max_age_seconds):
                raise ValueError("STALE_OR_INVALID_QUOTE")
            spread = (ask - bid) / ((ask + bid) / 2) * 10000
            if spread > 15:
                raise ValueError("SPREAD_TOO_WIDE")
            candles = fetcher(symbol, interval=interval)
            if not isinstance(candles, list) or len(candles) < 35:
                raise ValueError("INVALID_CANDLES")
            markets[symbol] = {"candles": candles, "spread_bps": spread,
                               "mark_price": (bid + ask) / 2,
                               "observed_at": observed}
        except (KeyError, TypeError, ValueError, OSError, TimeoutError) as exc:
            rejected[symbol] = str(exc)
    return {"markets": markets, "rejected": rejected, "mode": "PAPER_DATA_ONLY"}


def paper_planning_cycle(universe, *, quote_fetcher, fetcher=fetch_closed_klines,
                         equity, day_open_equity, daily_pnl, current_positions,
                         policy=RiskPolicy(), now=None):
    snapshot = build_markets(universe, fetcher=fetcher,
                             quote_fetcher=quote_fetcher, now=now)
    plans = plan_paper_entries(snapshot["markets"], equity=equity,
                               day_open_equity=day_open_equity,
                               daily_pnl=daily_pnl,
                               current_positions=current_positions, policy=policy)
    return {"mode": "PAPER_PLAN_ONLY", "plans": plans["plans"],
            "risk_rejected": plans["rejected"],
            "market_rejected": snapshot["rejected"],
            "diagnostics": plans["signal_diagnostics"]}
