"""
SQLite storage layer.

Tables:
    tokens        - memecoins we're tracking (fixed list + auto-discovered)
    swaps         - raw buy/sell events per wallet, pulled from Helius
    wallet_pnl    - computed realized P&L per wallet per token (FIFO matched)
"""

import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    mint TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    source TEXT DEFAULT 'manual',   -- 'manual' or 'discovered'
    added_at TEXT DEFAULT (datetime('now')),
    last_scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS swaps (
    signature TEXT,
    token_mint TEXT,
    wallet TEXT,
    side TEXT,              -- 'buy' or 'sell'
    token_amount REAL,      -- amount of the memecoin
    sol_amount REAL,        -- SOL value of the trade
    block_time INTEGER,
    PRIMARY KEY (signature, wallet, token_mint)
);

CREATE TABLE IF NOT EXISTS wallet_pnl (
    wallet TEXT,
    token_mint TEXT,
    realized_profit_sol REAL,
    total_bought_sol REAL,
    total_sold_sol REAL,
    trade_count INTEGER,
    win_rate REAL,
    last_updated TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (wallet, token_mint)
);

CREATE INDEX IF NOT EXISTS idx_swaps_wallet ON swaps(wallet);
CREATE INDEX IF NOT EXISTS idx_swaps_token ON swaps(token_mint);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def add_token(mint: str, symbol: str = "", name: str = "", source: str = "manual"):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tokens (mint, symbol, name, source) VALUES (?, ?, ?, ?)",
            (mint, symbol, name, source),
        )


def list_tokens():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM tokens ORDER BY added_at DESC").fetchall()


def mark_scanned(mint: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tokens SET last_scanned_at = datetime('now') WHERE mint = ?", (mint,)
        )


def insert_swaps(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO swaps
               (signature, token_mint, wallet, side, token_amount, sol_amount, block_time)
               VALUES (:signature, :token_mint, :wallet, :side, :token_amount, :sol_amount, :block_time)""",
            rows,
        )


def get_swaps_for_token(mint: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM swaps WHERE token_mint = ? ORDER BY wallet, block_time",
            (mint,),
        ).fetchall()


def upsert_wallet_pnl(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO wallet_pnl
               (wallet, token_mint, realized_profit_sol, total_bought_sol, total_sold_sol, trade_count, win_rate, last_updated)
               VALUES (:wallet, :token_mint, :realized_profit_sol, :total_bought_sol, :total_sold_sol, :trade_count, :win_rate, datetime('now'))
               ON CONFLICT(wallet, token_mint) DO UPDATE SET
                 realized_profit_sol=excluded.realized_profit_sol,
                 total_bought_sol=excluded.total_bought_sol,
                 total_sold_sol=excluded.total_sold_sol,
                 trade_count=excluded.trade_count,
                 win_rate=excluded.win_rate,
                 last_updated=datetime('now')""",
            rows,
        )


def top_profitable_wallets(min_profit: float, limit: int = 50):
    """Aggregate profit across ALL tracked tokens per wallet, ranked descending."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT
                wallet,
                SUM(realized_profit_sol) AS total_profit_sol,
                SUM(trade_count) AS total_trades,
                COUNT(DISTINCT token_mint) AS tokens_traded,
                AVG(win_rate) AS avg_win_rate
            FROM wallet_pnl
            GROUP BY wallet
            HAVING total_profit_sol >= ?
            ORDER BY total_profit_sol DESC
            LIMIT ?
            """,
            (min_profit, limit),
        ).fetchall()


def wallet_detail(wallet: str):
    with get_conn() as conn:
        return conn.execute(
            """SELECT wp.*, t.symbol, t.name FROM wallet_pnl wp
               JOIN tokens t ON t.mint = wp.token_mint
               WHERE wallet = ? ORDER BY realized_profit_sol DESC""",
            (wallet,),
        ).fetchall()
