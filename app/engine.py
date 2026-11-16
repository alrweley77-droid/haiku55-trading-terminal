"""Persistent PAPER-only order engine. Never signs or sends real exchange orders."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ("BTC", "ETH", "SOL")


def utc_day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


class PaperEngine:
    def __init__(self, db_path="data/haiku55.db", starting_balance=10000.0):
        self.lock = threading.RLock()
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT UNIQUE NOT NULL,
                side TEXT NOT NULL, qty REAL NOT NULL, entry REAL NOT NULL,
                stop REAL NOT NULL, target REAL NOT NULL, fee_in REAL NOT NULL,
                opened_at REAL NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
                funding_paid REAL NOT NULL DEFAULT 0,
                funding_rate REAL NOT NULL DEFAULT 0,
                next_funding_time_ms INTEGER NOT NULL DEFAULT 0,
                last_funding_time_ms INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
                side TEXT NOT NULL, qty REAL NOT NULL, entry REAL NOT NULL,
                exit REAL NOT NULL, pnl REAL NOT NULL, fee REAL NOT NULL,
                reason TEXT NOT NULL, source TEXT NOT NULL,
                opened_at REAL NOT NULL, closed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                type TEXT NOT NULL, message TEXT NOT NULL
            );
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(positions)")}
        for name, definition in (
            ("funding_paid", "REAL NOT NULL DEFAULT 0"),
            ("funding_rate", "REAL NOT NULL DEFAULT 0"),
            ("next_funding_time_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("last_funding_time_ms", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                self.db.execute(f"ALTER TABLE positions ADD COLUMN {name} {definition}")
        self.prices: dict[str, float] = {}  # Binance mark prices used for PAPER risk checks
        self.last_prices: dict[str, float] = {}
        self.funding: dict[str, dict] = {}
        self.last_market_at = 0.0
        self.price_history = defaultdict(lambda: deque(maxlen=240))
        self.cooldowns: dict[str, float] = {}
        self.last_signal: dict = {}
        self.config = {
            "max_positions": 3,
            "risk_per_trade_pct": 0.5,
            "max_notional_pct": 60.0,
            "max_trade_notional_usd": 250.0,
            "leverage": 3.0,
            # Illustrative safety assumption only; NOT Binance's symbol/tier-specific MMR.
            "maintenance_margin_rate": 0.005,
            "daily_loss_limit_pct": 2.5,
            # PAPER-only protection: close remaining positions when the UTC daily loss gate is hit.
            "auto_close_on_daily_loss": True,
            "stop_pct": 1.0,
            "take_profit_pct": 2.0,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "cooldown_seconds": 600,
            "min_confidence": 0.65,
            "max_feed_age_seconds": 20,
        }
        with self.lock:
            if self._get("cash") is None:
                if starting_balance <= 0:
                    raise ValueError("Starting balance must be positive")
                self._set("cash", starting_balance)
                self._set("starting_balance", starting_balance)
                self._set("day", utc_day(time.time()))
                self._set("day_open_cash", starting_balance)
                self._set("day_realized_pnl", 0)
                self._set("paused", False)
                self._set("killed", False)
                self._event("BOOT", "Paper ledger created. No exchange credentials used.")
            self.db.commit()

    def _get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def _set(self, key, value):
        self.db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def _event(self, typ, message, now=None):
        self.db.execute("INSERT INTO events(at,type,message) VALUES(?,?,?)", (now or time.time(), typ, message))
        self.db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 300)")

    def _positions(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM positions ORDER BY opened_at DESC")]

    def _roll_day(self, now):
        day = utc_day(now)
        if self._get("day") != day:
            self._set("day", day)
            self._set("day_open_cash", self._get("cash"))
            self._set("day_realized_pnl", 0)
            self._event("DAY", "Daily risk limits reset (UTC).", now)

    def update_prices(self, prices: dict[str, float], now=None, last_prices=None, funding=None):
        """Update mark prices and indicative funding metadata from Binance public futures data."""
        now = time.time() if now is None else float(now)
        with self.lock:
            valid = {s: float(p) for s, p in prices.items() if s in SYMBOLS and
                     isinstance(p, (int, float, str)) and float(p) > 0}
            if not valid:
                return
            self._roll_day(now)
            self.prices.update(valid)
            now_ms = int(now * 1000)
            for position in self._positions():
                symbol = position["symbol"]
                incoming = (funding or {}).get(symbol, {})
                due_at = int(position.get("next_funding_time_ms") or 0)
                paid_at = int(position.get("last_funding_time_ms") or 0)
                mark = valid.get(symbol, self.prices.get(symbol, position["entry"]))
                # Accrue one observed funding boundary using the last published rate.
                # Multiple missed intervals cannot be reconstructed from this public feed.
                if due_at and now_ms >= due_at and paid_at < due_at:
                    direction = 1 if position["side"] == "LONG" else -1
                    payment = position["qty"] * mark * float(position.get("funding_rate") or 0) * direction
                    self.db.execute(
                        "UPDATE positions SET funding_paid=funding_paid+?, last_funding_time_ms=? WHERE id=?",
                        (payment, due_at, position["id"]),
                    )
                    self._event("FUNDING", f"{symbol} simulated funding {payment:+.4f} USD at boundary {due_at}", now)
                new_due = int(incoming.get("next_funding_time_ms") or 0)
                if new_due > due_at:
                    self.db.execute(
                        "UPDATE positions SET funding_rate=?, next_funding_time_ms=? WHERE id=?",
                        (float(incoming.get("last_rate") or 0), new_due, position["id"]),
                    )
            if last_prices:
                self.last_prices.update({s: float(p) for s, p in last_prices.items() if s in SYMBOLS and float(p) > 0})
            if funding:
                for symbol, details in funding.items():
                    if symbol in SYMBOLS and isinstance(details, dict):
                        self.funding[symbol] = details
            self.last_market_at = now
            for symbol, price in valid.items():
                self.price_history[symbol].append({"t": now, "p": price})
            for position in self._positions():
                price = valid.get(position["symbol"])
                if price is None:
                    continue
                liq_price = self.liquidation_price(position)
                liquidated = price <= liq_price if position["side"] == "LONG" else price >= liq_price
                if liquidated:
                    reason = "LIQUIDATION_APPROX"
                elif position["side"] == "LONG":
                    reason = "STOP" if price <= position["stop"] else "TARGET" if price >= position["target"] else None
                else:
                    reason = "STOP" if price >= position["stop"] else "TARGET" if price <= position["target"] else None
                if reason:
                    self._close(position, price, reason, now)

            # Optional PAPER-only daily loss protection. Evaluate the remaining portfolio
            # after normal stop/target/liquidation processing, then flatten at fresh marks.
            if self.config["auto_close_on_daily_loss"]:
                remaining = self._positions()
                day_open = float(self._get("day_open_cash"))
                daily_pnl = float(self._get("day_realized_pnl")) + sum(
                    self._unrealized(position) for position in remaining
                )
                loss_limit = day_open * self.config["daily_loss_limit_pct"] / 100
                if remaining and daily_pnl <= -loss_limit:
                    for position in remaining:
                        mark = valid.get(position["symbol"])
                        if mark is not None:
                            self._close(position, mark, "DAILY_LOSS_KILL", now)
                    self._event(
                        "RISK",
                        f"Daily loss protection triggered at {daily_pnl:.2f} USD; remaining PAPER positions closed.",
                        now,
                    )
            self.db.commit()

    def _unrealized(self, position):
        px = self.prices.get(position["symbol"], position["entry"])
        direction = 1 if position["side"] == "LONG" else -1
        gross = (px - position["entry"]) * position["qty"] * direction
        # Mark equity includes entry fee and an estimated taker fee to close.
        estimated_exit_fee = abs(position["qty"] * px) * self.config["fee_bps"] / 10000
        return gross - float(position.get("fee_in") or 0) - estimated_exit_fee - float(position.get("funding_paid") or 0)

    def liquidation_price(self, position):
        """Illustrative isolated liquidation threshold; not an exchange-accurate quote."""
        leverage = float(self.config["leverage"])
        mmr = float(self.config["maintenance_margin_rate"])
        distance = max(0.0, (1.0 / leverage) - mmr)
        if position["side"] == "LONG":
            return position["entry"] * (1.0 - distance)
        return position["entry"] * (1.0 + distance)

    def _close(self, position, observed_price, reason, now):
        direction = 1 if position["side"] == "LONG" else -1
        exit_px = observed_price * (1 - direction * self.config["slippage_bps"] / 10000)
        fee_out = abs(position["qty"] * exit_px) * self.config["fee_bps"] / 10000
        total_fee = position["fee_in"] + fee_out
        gross = (exit_px - position["entry"]) * direction * position["qty"]
        funding_paid = float(position.get("funding_paid") or 0)
        pnl = gross - total_fee - funding_paid
        cash = float(self._get("cash")) + pnl
        self._set("cash", cash)
        self._set("day_realized_pnl", float(self._get("day_realized_pnl")) + pnl)
        self.db.execute(
            """INSERT INTO trades(symbol,side,qty,entry,exit,pnl,fee,reason,source,opened_at,closed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (position["symbol"], position["side"], position["qty"], position["entry"],
             exit_px, pnl, total_fee, reason, position["source"], position["opened_at"], now),
        )
        self.db.execute("DELETE FROM positions WHERE id=?", (position["id"],))
        self.cooldowns[position["symbol"]] = now + self.config["cooldown_seconds"]
        self._event("CLOSE", f'{position["symbol"]} {position["side"]} {reason}: {pnl:+.2f} USD (paper)', now)
        return {"symbol": position["symbol"], "pnl": round(pnl, 4), "reason": reason}

    def close(self, symbol, now=None):
        now = time.time() if now is None else float(now)
        with self.lock:
            position = next((p for p in self._positions() if p["symbol"] == symbol), None)
            if not position:
                return {"ok": False, "reason": "NO_POSITION"}
            if symbol not in self.prices or now - self.last_market_at > self.config["max_feed_age_seconds"]:
                return {"ok": False, "reason": "STALE_MARKET_DATA"}
            result = self._close(position, self.prices[symbol], "MANUAL", now)
            self.db.commit()
            return {"ok": True, **result}

    def open(self, symbol, side, confidence=1.0, source="MANUAL", now=None):
        now = time.time() if now is None else float(now)
        with self.lock:
            self._roll_day(now)
            if symbol not in SYMBOLS or side not in ("LONG", "SHORT"):
                return {"ok": False, "reason": "INVALID_ORDER"}
            if self._get("killed"):
                return {"ok": False, "reason": "KILL_SWITCH"}
            if self._get("paused"):
                return {"ok": False, "reason": "PAUSED"}
            if symbol not in self.prices or now - self.last_market_at > self.config["max_feed_age_seconds"]:
                return {"ok": False, "reason": "STALE_MARKET_DATA"}
            if confidence < self.config["min_confidence"] or confidence > 1:
                return {"ok": False, "reason": "LOW_CONFIDENCE"}
            if self.cooldowns.get(symbol, 0) > now:
                return {"ok": False, "reason": "COOLDOWN"}
            positions = self._positions()
            if len(positions) >= self.config["max_positions"]:
                return {"ok": False, "reason": "MAX_POSITIONS"}
            if any(p["symbol"] == symbol for p in positions):
                return {"ok": False, "reason": "ALREADY_OPEN"}
            cash = float(self._get("cash"))
            used_margin = sum((p["qty"] * p["entry"]) / self.config["leverage"] for p in positions)
            day_open = float(self._get("day_open_cash"))
            unrealized = sum(self._unrealized(p) for p in positions)
            equity = max(0.0, cash + unrealized)
            # Portfolio-wide margin budget: all open positions share the configured equity limit.
            portfolio_margin_limit = equity * self.config["max_notional_pct"] / 100
            portfolio_margin_available = max(0.0, portfolio_margin_limit - used_margin)
            day_pnl = float(self._get("day_realized_pnl")) + unrealized
            if cash <= 0 or day_pnl <= -(day_open * self.config["daily_loss_limit_pct"] / 100):
                return {"ok": False, "reason": "DAILY_LOSS_LIMIT"}
            price = self.prices[symbol]
            direction = 1 if side == "LONG" else -1
            entry = price * (1 + direction * self.config["slippage_bps"] / 10000)
            stop_dist = entry * self.config["stop_pct"] / 100
            risk_budget = cash * self.config["risk_per_trade_pct"] / 100
            # Reserve for the new position's estimated entry/exit fees and entry slippage.
            # This keeps reported used margin within the portfolio cap after opening costs
            # reduce marked equity.
            margin_fraction = self.config["max_notional_pct"] / 100
            estimated_cost_rate = (
                self.config["slippage_bps"] + 2 * self.config["fee_bps"]
            ) / 10000
            max_notional_by_portfolio = portfolio_margin_available / (
                (1 / self.config["leverage"]) + margin_fraction * estimated_cost_rate
            )
            max_notional = min(
                max_notional_by_portfolio,
                self.config["max_trade_notional_usd"],
            )
            raw_qty = min(risk_budget / stop_dist, max_notional / entry)
            # Round down so floating-point/quantity precision can never exceed the notional cap.
            qty = math.floor(raw_qty * 100_000_000) / 100_000_000
            if qty <= 0:
                return {"ok": False, "reason": "SIZE_ZERO"}
            stop = entry - direction * stop_dist
            target = entry + direction * entry * self.config["take_profit_pct"] / 100
            fee_in = entry * qty * self.config["fee_bps"] / 10000
            funding_info = self.funding.get(symbol, {})
            funding_rate = float(funding_info.get("last_rate") or 0)
            next_funding_time = int(funding_info.get("next_funding_time_ms") or 0)
            self.db.execute(
                """INSERT INTO positions(
                    symbol,side,qty,entry,stop,target,fee_in,opened_at,source,confidence,
                    funding_paid,funding_rate,next_funding_time_ms,last_funding_time_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (symbol, side, qty, entry, stop, target, fee_in, now, source, confidence,
                 0.0, funding_rate, next_funding_time, 0),
            )
            self._event("OPEN", f"{side} {symbol} {qty:.6f} @ {entry:.2f} (paper; {source})", now)
            self.db.commit()
            return {"ok": True, "symbol": symbol, "side": side, "qty": qty,
                    "entry": round(entry, 4), "stop": round(stop, 4), "target": round(target, 4)}

    def set_control(self, action, now=None):
        now = time.time() if now is None else float(now)
        if action not in ("pause", "resume", "kill"):
            return {"ok": False, "reason": "UNKNOWN_CONTROL"}
        with self.lock:
            if action == "resume" and self._get("killed"):
                return {"ok": False, "reason": "KILL_SWITCH_LATCHED_RESTART_REQUIRED"}
            if action == "kill":
                # Latches across restarts, and flattens paper positions at last known fresh marks.
                self._set("killed", True)
                self._set("paused", True)
                if now - self.last_market_at <= self.config["max_feed_age_seconds"]:
                    for pos in self._positions():
                        if pos["symbol"] in self.prices:
                            self._close(pos, self.prices[pos["symbol"]], "KILL", now)
            else:
                self._set("paused", action == "pause")
            self._event("CONTROL", action.upper(), now)
            self.db.commit()
            return {"ok": True, "action": action, "killed": self._get("killed")}

    def status(self, now=None):
        now = time.time() if now is None else float(now)
        with self.lock:
            positions = []
            for pos in self._positions():
                pos["mark"] = self.prices.get(pos["symbol"])
                pos["upnl"] = round(self._unrealized(pos), 4)
                pos["funding_paid"] = round(float(pos.get("funding_paid") or 0), 6)
                pos["estimated_liquidation_price"] = round(self.liquidation_price(pos), 8)
                positions.append(pos)
            cash = float(self._get("cash"))
            upnl = sum(p["upnl"] for p in positions)
            closed = self.db.execute("SELECT count(*) AS n, sum(CASE WHEN pnl>0 THEN 1 ELSE 0 END) AS wins FROM trades").fetchone()
            return {
                "mode": "PAPER", "market_source": "Binance USDⓈ-M Futures mark price + last price + indicative funding (PAPER only)",
                "feed_status": "LIVE" if self.last_market_at and now - self.last_market_at <= self.config["max_feed_age_seconds"] else "STALE",
                "feed_age_seconds": round(now - self.last_market_at, 1) if self.last_market_at else None,
                "prices": {s: self.prices.get(s) for s in SYMBOLS},
                "last_prices": {s: self.last_prices.get(s) for s in SYMBOLS},
                "funding_indicative": self.funding,
                "price_basis": "Binance mark price for PAPER stops, PnL and risk; last price shown for reference",
                "history": {s: list(self.price_history[s])[-90:] for s in SYMBOLS},
                "cash": round(cash, 4), "equity": round(cash + upnl, 4),
                "unrealized_pnl": round(upnl, 4),
                "funding_paid_total": round(sum(float(p.get("funding_paid") or 0) for p in positions), 4),
                "futures_simulation": {
                    "leverage": self.config["leverage"],
                    "margin_used": round(sum((p["qty"] * p["entry"]) / self.config["leverage"] for p in positions), 4),
                    "margin_limit": round(max(0.0, cash + upnl) * self.config["max_notional_pct"] / 100, 4),
                    "margin_available": round(max(0.0, max(0.0, cash + upnl) * self.config["max_notional_pct"] / 100 - sum((p["qty"] * p["entry"]) / self.config["leverage"] for p in positions)), 4),
                    "notional_used": round(sum(p["qty"] * p["entry"] for p in positions), 4),
                    "notional_limit": round(max(0.0, cash + upnl) * self.config["max_notional_pct"] / 100 * self.config["leverage"], 4),
                    "max_trade_notional_usd": self.config["max_trade_notional_usd"],
                    "margin_model": "portfolio-wide 20% equity margin cap; isolated approximation; observed funding events accrued; illustrative liquidation threshold, not Binance tier-accurate"
                },
                "net_pnl": round(cash + upnl - float(self._get("starting_balance")), 4),
                "daily_realized_pnl": round(float(self._get("day_realized_pnl")), 4),
                "positions": positions, "trades_count": closed["n"],
                "win_rate": round(100 * (closed["wins"] or 0) / closed["n"], 2) if closed["n"] else 0,
                "paused": self._get("paused"), "killed": self._get("killed"),
                "risk": self.config.copy(), "signal": self.last_signal,
                "events": [dict(r) for r in self.db.execute("SELECT at,type,message FROM events ORDER BY id DESC LIMIT 30")],
            }

    def trades(self, limit=100):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 500),)
            )]

    def rule_signal(self, symbol):
        """Deterministic trend proxy. Explicitly NOT an AI model signal."""
        hist = self.price_history[symbol]
        if len(hist) < 36:
            return {"side": "WAIT", "confidence": 0, "reason": "Warm-up: 36 market ticks required"}
        p = hist[-1]["p"]
        short_return = (p / hist[-12]["p"] - 1) * 100
        long_return = (p / hist[-36]["p"] - 1) * 100
        if short_return > 0.10 and long_return > 0.18:
            return {"side": "LONG", "confidence": 0.68, "reason": "Positive 1m/3m trend"}
        if short_return < -0.10 and long_return < -0.18:
            return {"side": "SHORT", "confidence": 0.68, "reason": "Negative 1m/3m trend"}
        return {"side": "WAIT", "confidence": 0, "reason": "Trend threshold not met"}
