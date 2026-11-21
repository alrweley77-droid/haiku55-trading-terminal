"""Isolated V2 paper-ledger bootstrap; never touches legacy database."""
import os
import sqlite3
from pathlib import Path

V2_STARTING_BALANCE = 10_000.00


def initialize_v2_ledger(db_path, *, starting_balance=V2_STARTING_BALANCE):
    """Idempotently create a new V2-only ledger. Reject legacy DB paths."""
    path = Path(db_path).expanduser().resolve()
    if "v2" not in path.name.lower() or path.suffix != ".db":
        raise ValueError("V2 requires an explicitly named, separate *v2*.db file")
    if not 0 < starting_balance < 1_000_000_000:
        raise ValueError("Invalid simulated balance")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS v2_accounts (id INTEGER PRIMARY KEY CHECK(id=1), starting_cash REAL NOT NULL, cash REAL NOT NULL, mode TEXT NOT NULL CHECK(mode='PAPER'))")
        conn.execute("INSERT OR IGNORE INTO v2_accounts(id,starting_cash,cash,mode) VALUES(1,?,?, 'PAPER')", (starting_balance, starting_balance))
        row = conn.execute("SELECT starting_cash,cash,mode FROM v2_accounts WHERE id=1").fetchone()
        conn.commit()
    return {"starting_cash": row[0], "cash": row[1], "mode": row[2], "db_path": str(path)}
