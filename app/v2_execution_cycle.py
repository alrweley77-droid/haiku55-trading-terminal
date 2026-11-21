"""HAIKU55 V2 optional PAPER execution coordinator.

Disabled by default. Requires an explicit execute=True argument. No live
trading credentials, exchange order endpoint or production service changes.
"""
import math
import time

from app.v2_paper_broker import V2PaperBroker
from app.v2_runner import run_once, public_quote
from app.v2_universe import fetch_universe
from app.v2_market_data import fetch_closed_klines


def _quote(quote_fetcher, symbol, *, now, max_age=10):
    data = quote_fetcher(symbol)
    if not isinstance(data, dict):
        raise ValueError("INVALID_QUOTE")
    bid, ask, stamp = (float(data[k]) for k in ("bid", "ask", "observed_at"))
    if (not all(math.isfinite(x) for x in (bid, ask, stamp))
            or bid <= 0 or ask < bid or stamp > now + 1
            or now - stamp > max_age):
        raise ValueError("STALE_QUOTE")
    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10000
    if spread_bps > 15:
        raise ValueError("SPREAD_TOO_WIDE")
    return {"bid": bid, "ask": ask, "observed_at": stamp}


def execute_paper_cycle(*, broker, quote_fetcher=public_quote,
                        universe_fetcher=fetch_universe,
                        candle_fetcher=fetch_closed_klines,
                        day_open_equity=None, execute=False, limit=40):
    """One cycle: close triggered positions, plan, recheck, then paper-fill.

    In dry-run mode no DB write occurs, even if a broker is supplied.
    Execute mode requires an isolated V2PaperBroker and fresh quote per fill.
    """
    if not isinstance(broker, V2PaperBroker):
        raise ValueError("PAPER_BROKER_REQUIRED")
    persisted_anchor = broker.daily_anchor() if execute else broker.status()["cash"]
    if day_open_equity is not None and (not isinstance(day_open_equity, (int, float))
            or not math.isfinite(day_open_equity) or day_open_equity <= 0
            or abs(day_open_equity - persisted_anchor) > 0.000001):
        raise ValueError("DAILY_ANCHOR_MISMATCH")
    day_open_equity = persisted_anchor
    before = broker.status()
    existing = before["positions"]
    quote_errors = {}
    marks = {}
    now = time.time()
    for row in existing:
        symbol = row[0]
        try:
            marks[symbol] = _quote(quote_fetcher, symbol, now=now)
        except (KeyError, TypeError, ValueError, OSError, TimeoutError) as exc:
            quote_errors[symbol] = type(exc).__name__
    if quote_errors:
        return {"mode": "PAPER", "ok": False, "reason": "PORTFOLIO_MARKS_UNAVAILABLE",
                "quote_errors": quote_errors, "executed": []}
    closed = []
    if execute:
        for row in existing:
            symbol, side = row[0], row[1]
            q = marks[symbol]
            executable = q["bid"] if side == "LONG" else q["ask"]
            result = broker.process_mark(symbol, mark_price=executable,
                                         observed_at=q["observed_at"])
            if result.get("closed"):
                closed.append({"symbol": symbol, **result})
    current = broker.status()
    current_positions = []
    unrealized = 0.0
    for symbol, side, qty, entry, stop, target, strategy in current["positions"]:
        q = marks[symbol]
        executable = q["bid"] if side == "LONG" else q["ask"]
        unrealized += (executable - entry) * qty * (1 if side == "LONG" else -1)
        notional = qty * entry
        current_positions.append({"symbol": symbol, "notional_usd": notional,
                                  "stop_risk_usd": notional * (abs(stop / entry - 1) + .0012)})
    equity = current["cash"] + unrealized
    report = run_once(universe_fetcher=universe_fetcher, quote_fetcher=quote_fetcher,
                      candle_fetcher=candle_fetcher, equity=equity,
                      day_open_equity=day_open_equity,
                      daily_pnl=min(0, equity - day_open_equity),
                      current_positions=current_positions, limit=limit)
    if not execute:
        return {"mode": "PAPER_DRY_RUN", "ok": True, "planned": report["plans"],
                "closed": [], "executed": [], "diagnostics": report["diagnostics"]}
    executed = []
    for plan in report["plans"]:
        symbol = plan["symbol"]
        try:
            q = _quote(quote_fetcher, symbol, now=time.time())
        except (KeyError, TypeError, ValueError, OSError, TimeoutError):
            executed.append({"symbol": symbol, "ok": False, "reason": "QUOTE_UNAVAILABLE"})
            continue
        # Do not execute a plan if its entry reference has drifted.
        # A newly generated signal is required after a material move.
        planned_entry = plan.get("entry")
        mid = (q["bid"] + q["ask"]) / 2
        if (not isinstance(planned_entry, (int, float)) or
                not math.isfinite(planned_entry) or planned_entry <= 0 or
                abs(mid / planned_entry - 1) > 0.002):
            executed.append({"symbol": symbol, "ok": False, "reason": "PLAN_PRICE_MOVED"})
            continue
        fresh_marks = {}
        failed = False
        for position in broker.status()["positions"]:
            psymbol = position[0]
            try:
                fresh_marks[psymbol] = _quote(quote_fetcher, psymbol, now=time.time())
            except (KeyError, TypeError, ValueError, OSError, TimeoutError):
                failed = True
                break
        if failed:
            executed.append({"symbol": symbol, "ok": False, "reason": "PORTFOLIO_QUOTE_UNAVAILABLE"})
            continue
        # Risk is recomputed inside the broker's atomic SQLite transaction.
        result = broker.open_risk_checked(
            symbol=symbol, side=plan["side"], confidence=plan["signal_score"],
            mark_price=(q["bid"] + q["ask"]) / 2, observed_at=q["observed_at"],
            day_open_equity=day_open_equity,
            daily_pnl=min(0, broker.status()["cash"] - day_open_equity),
            portfolio_marks=fresh_marks, strategy=plan["strategy"])
        executed.append({"symbol": symbol, **result})
    return {"mode": "PAPER", "ok": True, "closed": closed,
            "executed": executed, "diagnostics": report["diagnostics"]}
