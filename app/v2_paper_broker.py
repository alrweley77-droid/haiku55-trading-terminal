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

    def daily_anchor(self, *, day=None):
        """Persist UTC daily cash anchor, idempotent across process restarts.

        This is realized cash only; open positions still require fresh marks
        for risk checks. The anchor cannot be reset within the same UTC day.
        """
        from datetime import datetime, timezone
        if day is None:
            day = datetime.now(timezone.utc).date().isoformat()
        if not isinstance(day, str) or len(day) != 10:
            raise ValueError("INVALID_UTC_DAY")
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS v2_daily_anchors(
                utc_day TEXT PRIMARY KEY, cash_anchor REAL NOT NULL
                CHECK(cash_anchor > 0))""")
            row = db.execute("SELECT cash FROM v2_accounts WHERE id=1 AND mode='PAPER'").fetchone()
            if row is None or not _positive(row[0]):
                raise ValueError("INVALID_PAPER_ACCOUNT")
            db.execute("INSERT OR IGNORE INTO v2_daily_anchors(utc_day,cash_anchor) VALUES(?,?)",
                       (day, row[0]))
            anchor = db.execute("SELECT cash_anchor FROM v2_daily_anchors WHERE utc_day=?",
                                (day,)).fetchone()[0]
            db.commit()
        return float(anchor)

    def status(self):
        with sqlite3.connect(self.db_path) as db:
            cash = db.execute("SELECT cash FROM v2_accounts WHERE id=1").fetchone()[0]
            positions = db.execute("SELECT symbol,side,qty,entry,stop,target,strategy FROM v2_positions").fetchall()
            count = db.execute("SELECT COUNT(*) FROM v2_trades").fetchone()[0]
        return {"mode": "PAPER", "cash": cash, "positions": positions, "closed_trades": count}

    def open_plan(self, plan, *, mark_price, observed_at, max_age_seconds=10,
                  target_pct=1.0, fee_bps=4.0):
        """Legacy entry adapter intentionally disabled.

        Untrusted precomputed plans must never bypass the broker's atomic
        portfolio risk checks. Use open_risk_checked instead.
        """
        return {"ok": False, "reason": "USE_ATOMIC_RISK_CHECKED_ENTRY"}

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
                          policy=None, max_age_seconds=10, strategy="ENSEMBLE",
                          portfolio_marks=None):
        """Atomically recheck PAPER-only risk, freshness and exposure at entry."""
        from app.v2_risk import RiskPolicy, size_paper_entry
        policy = RiskPolicy() if policy is None else policy
        now = time.time()
        if (not all(_positive(x) for x in (mark_price, observed_at, max_age_seconds))
                or observed_at > now + 1 or now - observed_at > max_age_seconds):
            return {"ok": False, "reason": "STALE_OR_INVALID_MARK"}
        if not isinstance(strategy, str) or not strategy or len(strategy) > 80:
            return {"ok": False, "reason": "INVALID_STRATEGY"}
        if not all(isinstance(v, (int, float)) and math.isfinite(v)
                   for v in (day_open_equity, daily_pnl)) or day_open_equity <= 0:
            return {"ok": False, "reason": "INVALID_DAILY_ACCOUNTING"}
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            account = db.execute("SELECT cash FROM v2_accounts WHERE id=1 AND mode='PAPER'").fetchone()
            if account is None:
                return {"ok": False, "reason": "INVALID_ACCOUNT"}
            cash = float(account[0])
            rows = db.execute("SELECT symbol,qty,entry,stop FROM v2_positions").fetchall()
            positions = []
            unrealized = 0.0
            used_margin = 0.0
            if rows and not isinstance(portfolio_marks, dict):
                return {"ok": False, "reason": "OPEN_POSITIONS_REQUIRE_FRESH_PORTFOLIO_MARKS"}
            for open_symbol, qty, entry, stop in rows:
                quote = portfolio_marks.get(open_symbol) if portfolio_marks else None
                if not isinstance(quote, dict):
                    return {"ok": False, "reason": "MISSING_PORTFOLIO_MARK"}
                try:
                    bid = float(quote["bid"])
                    ask = float(quote["ask"])
                    stamp = float(quote["observed_at"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    return {"ok": False, "reason": "INVALID_PORTFOLIO_MARK"}
                if (not all(math.isfinite(v) for v in (bid, ask, stamp))
                        or bid <= 0 or ask < bid or stamp > now + 1
                        or now - stamp > max_age_seconds):
                    return {"ok": False, "reason": "STALE_PORTFOLIO_MARK"}
                # Bid for long liquidation; ask for short liquidation.
                position_side = db.execute(
                    "SELECT side FROM v2_positions WHERE symbol=?", (open_symbol,)
                ).fetchone()[0]
                direction = 1 if position_side == "LONG" else -1
                executable = bid if direction == 1 else ask
                unrealized += (executable - entry) * qty * direction
                notional = qty * entry
                if not all(math.isfinite(v) and v > 0 for v in (qty, entry, stop, notional)):
                    return {"ok": False, "reason": "INVALID_STORED_POSITION"}
                used_margin += notional / policy.leverage
                positions.append({"symbol": open_symbol, "notional_usd": notional,
                                  "stop_risk_usd": notional * (
                                      abs(stop / entry - 1)
                                      + 2 * (policy.fee_bps + policy.slippage_bps) / 10000)})
            equity = cash + unrealized
            if equity <= 0:
                return {"ok": False, "reason": "INSUFFICIENT_EQUITY"}
            # Reject an inconsistent caller-reported daily PnL. This prevents
            # understating today's losses by omitting open-position losses.
            effective_daily_pnl = min(daily_pnl, equity - day_open_equity)
            plan = size_paper_entry(
                equity=equity, day_open_equity=day_open_equity,
                daily_pnl=effective_daily_pnl,
                price=mark_price, confidence=confidence,
                current_positions=positions, side=side, symbol=symbol, policy=policy)
            if not plan["ok"]:
                return plan
            if used_margin + plan["estimated_margin_usd"] + plan["notional_usd"] * policy.fee_bps / 10000 > equity:
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
