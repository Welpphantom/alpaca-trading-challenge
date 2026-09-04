"""Decision journal: every proposal, veto, order, fill, and account snapshot.

This is the system's memory and the source for Telegram reports, the
dashboard's decision feed, and the judging write-up. Nothing trades without
leaving a row here.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                -- UTC ISO8601
    kind TEXT NOT NULL,              -- proposal | veto | approval | order | fill |
                                     -- close | snapshot | error | note
    agent TEXT NOT NULL,             -- research | strategy | risk | execution | system
    symbol TEXT,                     -- underlying, if applicable
    payload TEXT NOT NULL,           -- JSON: structured details
    rationale TEXT                   -- prose: the agent's written reasoning
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind);

CREATE TABLE IF NOT EXISTS open_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_ts TEXT NOT NULL,
    closed_ts TEXT,
    status TEXT NOT NULL DEFAULT 'open',   -- open | closed | expired
    underlying TEXT NOT NULL,
    structure TEXT NOT NULL,
    legs TEXT NOT NULL,                    -- JSON list of {symbol, side, ratio}
    qty INTEGER NOT NULL,
    net_price REAL NOT NULL,               -- positive; credit/debit via is_credit
    is_credit INTEGER NOT NULL,
    max_loss_per_lot_usd REAL NOT NULL,
    expiry TEXT NOT NULL,
    exit_price REAL,
    realized_pnl_usd REAL
);
"""


class Journal:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    def log(
        self,
        kind: str,
        agent: str,
        payload: dict,
        rationale: str | None = None,
        symbol: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (ts, kind, agent, symbol, payload, rationale) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                kind,
                agent,
                symbol,
                json.dumps(payload, default=str),
                rationale,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    # ── position book (source of truth for open risk) ────────────────────

    def open_position(self, *, underlying: str, structure: str, legs: list[dict],
                      qty: int, net_price: float, is_credit: bool,
                      max_loss_per_lot_usd: float, expiry: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO open_positions (opened_ts, underlying, structure, legs, qty, "
            "net_price, is_credit, max_loss_per_lot_usd, expiry) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), underlying, structure,
             json.dumps(legs), qty, net_price, int(is_credit),
             max_loss_per_lot_usd, expiry),
        )
        self.conn.commit()
        return cur.lastrowid

    def close_position(self, position_id: int, *, status: str = "closed",
                       exit_price: float | None = None,
                       realized_pnl_usd: float | None = None) -> None:
        self.conn.execute(
            "UPDATE open_positions SET status=?, closed_ts=?, exit_price=?, "
            "realized_pnl_usd=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), exit_price,
             realized_pnl_usd, position_id),
        )
        self.conn.commit()

    def open_positions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM open_positions WHERE status='open' ORDER BY opened_ts")
        return [{**dict(r), "legs": json.loads(r["legs"])} for r in rows]

    def open_risk_usd(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(max_loss_per_lot_usd * qty), 0) AS risk "
            "FROM open_positions WHERE status='open'").fetchone()
        return float(row["risk"])

    def open_position_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM open_positions WHERE status='open'").fetchone()
        return int(row["n"])

    def events_since(self, since_utc_iso: str, kind: str | None = None) -> list[dict]:
        q = "SELECT * FROM events WHERE ts >= ?"
        args: list = [since_utc_iso]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY ts"
        return [
            {**dict(r), "payload": json.loads(r["payload"])}
            for r in self.conn.execute(q, args)
        ]
