"""V2 isolated PAPER fill ledger. No real trading API or credentials.

Every transition is a single SQLite transaction. Caller supplies verified fresh
public mark prices; this module never fetches or fabricates market data.
"""
import math
import sqlite3
import time
from app.v2_ledger import initialize_v2_ledger


def _positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


class V2PaperBroker:
    def __init__(self, db_path):
        self.db_path = initialize_v2_ledger(db_path)["db_path"]
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS v2_positions(
                symbol TEXT PRIMARY KEY, side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
                qty REAL NOT NULL, entry REAL NOT NULL, stop REAL NOT NULL,
                target REAL NOT NULL, entry_fee REAL NOT NULL, opened_at REAL NOT NULL,
                strategy TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS v2_trades(
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
                entry REAL NOT NULL, exit REAL NOT NULL, qty REAL NOT NULL,
                pnl REAL NOT NULL, reason TEXT NOT NULL, closed_at REAL NOT NULL)""")
            db.commit()

    def status(self):
        with sqlite3.connect(self.db_path) as db:
            cash = db.execute("SELECT cash FROM v2_accounts WHERE id=1").fetchone()[0]
            positions = db.execute("SELECT symbol,side,qty,entry,stop,target,strategy FROM v2_positions").fetchall()
            count = db.execute("SELECT COUNT(*) FROM v2_trades").fetchone()[0]
        return {"mode": "PAPER", "cash": cash, "positions": positions, "closed_trades": count}

    def open_plan(self, plan, *, mark_price, observed_at, max_age_seconds=10,
                  target_pct=1.0, fee_bps=4.0):
        """Apply a previously risk-approved plan; re-check price and freshness.

        A caller must re-run portfolio risk gates immediately before every entry.
        This adapter is not a substitute for the upstream risk engine.
        """
        now = time.time()
        if not isinstance(plan, dict) or plan.get("mode") != "PAPER":
            return {"ok": False, "reason": "INVALID_PAPER_PLAN"}
        if not all(_positive(v) for v in (mark_price, observed_at, max_age_seconds, target_pct)):
            return {"ok": False, "reason": "INVALID_MARK"}
        if not isinstance(fee_bps, (int, float)) or not math.isfinite(fee_bps) or fee_bps < 0:
            return {"ok": False, "reason": "INVALID_FEES"}
        if observed_at > now + 1 or now - observed_at > max_age_seconds:
            return {"ok": False, "reason": "STALE_MARK"}
        symbol, side = plan.get("symbol"), plan.get("side")
        entry, stop, qty = (plan.get(k) for k in ("entry", "stop", "quantity"))
        if (not isinstance(symbol, str) or not symbol.endswith("USDT")
                or side not in ("LONG", "SHORT") or not all(_positive(x) for x in (entry, stop, qty))):
            return {"ok": False, "reason": "INVALID_ORDER"}
        direction = 1 if side == "LONG" else -1
        if (stop - entry) * direction >= 0:
            return {"ok": False, "reason": "INVALID_STOP"}
        if abs(mark_price / entry - 1) > 0.002:
            return {"ok": False, "reason": "PRICE_MOVED"}
        target = entry * (1 + direction * target_pct / 100)
        entry_fee = qty * entry * fee_bps / 10000
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM v2_positions WHERE symbol=?", (symbol,)).fetchone():
                return {"ok": False, "reason": "ALREADY_OPEN"}
            db.execute("""INSERT INTO v2_positions
                (symbol,side,qty,entry,stop,target,entry_fee,opened_at,strategy)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (symbol, side, qty, entry, stop, target, entry_fee, now, plan.get("strategy", "UNKNOWN")))
            db.commit()
        return {"ok": True, "mode": "PAPER", "symbol": symbol, "side": side}

    def process_mark(self, symbol, *, mark_price, observed_at, fee_bps=4.0,
                     slippage_bps=2.0, max_age_seconds=10):
        """Mark-triggered simulated close. Stops can slip through price gaps."""
        now = time.time()
        if (not isinstance(symbol, str) or not all(_positive(v) for v in
                (mark_price, observed_at, max_age_seconds)) or observed_at > now + 1
                or now - observed_at > max_age_seconds):
            return {"ok": False, "reason": "INVALID_OR_STALE_MARK"}
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 100
                   for v in (fee_bps, slippage_bps)):
            return {"ok": False, "reason": "INVALID_COSTS"}
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            db.row_factory = sqlite3.Row
            pos = db.execute("SELECT * FROM v2_positions WHERE symbol=?", (symbol,)).fetchone()
            if pos is None:
                return {"ok": False, "reason": "NO_POSITION"}
            direction = 1 if pos["side"] == "LONG" else -1
            stopped = mark_price <= pos["stop"] if direction == 1 else mark_price >= pos["stop"]
            targeted = mark_price >= pos["target"] if direction == 1 else mark_price <= pos["target"]
            if not (stopped or targeted):
                return {"ok": True, "closed": False}
            reason = "STOP" if stopped else "TARGET"
            exit_px = mark_price * (1 - direction * slippage_bps / 10000)
            exit_fee = pos["qty"] * exit_px * fee_bps / 10000
            pnl = (exit_px - pos["entry"]) * direction * pos["qty"] - pos["entry_fee"] - exit_fee
            db.execute("UPDATE v2_accounts SET cash=cash+? WHERE id=1", (pnl,))
            db.execute("""INSERT INTO v2_trades(symbol,side,entry,exit,qty,pnl,reason,closed_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (symbol, pos["side"], pos["entry"], exit_px, pos["qty"], pnl, reason, now))
            db.execute("DELETE FROM v2_positions WHERE symbol=?", (symbol,))
            db.commit()
        return {"ok": True, "closed": True, "reason": reason, "pnl": round(pnl, 6)}

    def open_risk_checked(self, *, symbol, side, confidence, mark_price,
                          observed_at, day_open_equity, daily_pnl,
                          policy=None, max_age_seconds=10, strategy="ENSEMBLE"):
        """Atomically recheck PAPER-only risk, freshness and exposure at entry."""
        from app.v2_risk import RiskPolicy, size_paper_entry
        policy = RiskPolicy() if policy is None else policy
        now = time.time()
        if (not all(_positive(x) for x in (mark_price, observed_at, max_age_seconds))
                or observed_at > now + 1 or now - observed_at > max_age_seconds):
            return {"ok": False, "reason": "STALE_OR_INVALID_MARK"}
        if not isinstance(strategy, str) or len(strategy) > 80:
            return {"ok": False, "reason": "INVALID_STRATEGY"}
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            account = db.execute("SELECT cash FROM v2_accounts WHERE id=1 AND mode='PAPER'").fetchone()
            if account is None:
                return {"ok": False, "reason": "INVALID_ACCOUNT"}
            cash = float(account[0])
            rows = db.execute("SELECT symbol,qty,entry,stop FROM v2_positions").fetchall()
            # Fail closed until all open positions have independently verified,
            # fresh marks. Realized cash alone is not total account equity.
            if rows:
                return {"ok": False, "reason": "OPEN_POSITIONS_REQUIRE_FRESH_PORTFOLIO_MARKS"}
            plan = size_paper_entry(
                equity=cash, day_open_equity=day_open_equity, daily_pnl=daily_pnl,
                price=mark_price, confidence=confidence,
                current_positions=[], side=side, symbol=symbol, policy=policy)
            if not plan["ok"]:
                return plan
            if plan["estimated_margin_usd"] + plan["notional_usd"] * policy.fee_bps / 10000 > cash:
                return {"ok": False, "reason": "INSUFFICIENT_CASH"}
            direction = 1 if side == "LONG" else -1
            entry, stop, qty = plan["entry"], plan["stop"], plan["quantity"]
            if qty <= 0:
                return {"ok": False, "reason": "SIZE_TOO_SMALL"}
            target = entry * (1 + direction * 0.01)
            fee = qty * entry * policy.fee_bps / 10000
            db.execute("""INSERT INTO v2_positions
                (symbol,side,qty,entry,stop,target,entry_fee,opened_at,strategy)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (symbol, side, qty, entry, stop, target, fee, now, strategy))
            db.commit()
        return {"ok": True, "mode": "PAPER", "symbol": symbol,
                "side": side, "entry": entry, "stop": stop,
                "quantity": qty, "strategy": strategy}
