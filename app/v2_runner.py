"""HAIKU55 V2 independent PAPER planning runner.

No live exchange orders, no existing Railway service modifications.
Default mode is a single dry-run cycle. External orchestration may schedule
this command repeatedly after review; each invocation is isolated.
"""
import argparse
import json
import sys
import time

from app.v2_cycle import paper_planning_cycle
from app.v2_universe import fetch_universe
from app.v2_market_data import fetch_closed_klines


def public_quote(symbol):
    """Read-only Binance USD-M best bid/ask with local receipt timestamp."""
    import urllib.parse
    import urllib.request
    url = "https://fapi.binance.com/fapi/v1/ticker/bookTicker?" + urllib.parse.urlencode({"symbol": symbol})
    request = urllib.request.Request(url, headers={"User-Agent": "HAIKU55-V2-PAPER"})
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read(16385)
    if len(raw) > 16384:
        raise ValueError("Quote response too large")
    data = json.loads(raw)
    if data.get("symbol") != symbol:
        raise ValueError("Quote symbol mismatch")
    return {"bid": float(data["bidPrice"]), "ask": float(data["askPrice"]),
            "observed_at": time.time()}


def run_once(*, universe_fetcher=fetch_universe, quote_fetcher=public_quote,
             candle_fetcher=fetch_closed_klines, equity=10000,
             day_open_equity=10000, daily_pnl=0, current_positions=None,
             limit=40):
    """One isolated research cycle; never calls a broker or creates orders."""
    if current_positions is None:
        current_positions = []
    universe = universe_fetcher(limit=limit)
    return paper_planning_cycle(
        universe, quote_fetcher=quote_fetcher, fetcher=candle_fetcher,
        equity=equity, day_open_equity=day_open_equity,
        daily_pnl=daily_pnl, current_positions=current_positions)


def main(argv=None):
    parser = argparse.ArgumentParser(description="HAIKU55 V2 PAPER-only dry-run")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    try:
        report = run_once(limit=args.limit)
    except Exception as exc:
        print(json.dumps({"mode": "PAPER_PLAN_ONLY", "ok": False,
                          "error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
