# db.py
from __future__ import annotations
import sqlite3
import time
from typing import Any, Dict, List

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  client_id TEXT NOT NULL,
  email TEXT NOT NULL,
  service TEXT,
  timing TEXT,
  budget TEXT,
  source TEXT,
  conversation TEXT
);

CREATE TABLE IF NOT EXISTS billing_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  email TEXT NOT NULL,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  stripe_session_id TEXT,
  plan TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  client_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_billing_email ON billing_accounts(email);
CREATE INDEX IF NOT EXISTS idx_billing_client ON billing_accounts(client_id);
CREATE INDEX IF NOT EXISTS idx_billing_session ON billing_accounts(stripe_session_id);

CREATE INDEX IF NOT EXISTS idx_leads_ts ON leads(ts DESC);
CREATE INDEX IF NOT EXISTS idx_leads_client ON leads(client_id);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  client_id TEXT NOT NULL,
  event TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_client ON events(client_id);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
"""

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Better concurrency / fewer locks
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")     # wait 5s if locked
    conn.execute("PRAGMA journal_mode=WAL;")      # WAL helps multi-read/write
    conn.execute("PRAGMA synchronous=NORMAL;")

    return conn

def init_db(conn: sqlite3.Connection, retries: int = 12, base_sleep: float = 0.15) -> None:
    for i in range(retries):
        try:
            conn.executescript(SCHEMA)
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(base_sleep * (i + 1))
                continue
            raise
    raise sqlite3.OperationalError("database is locked (init_db)")

def insert_event(conn: sqlite3.Connection, client_id: str, event: str) -> None:
    conn.execute(
        "INSERT INTO events (ts, client_id, event) VALUES (?, ?, ?)",
        (int(time.time()), client_id, event),
    )
    conn.commit()

def insert_lead(
    conn: sqlite3.Connection,
    client_id: str,
    email: str,
    service: str = "",
    timing: str = "",
    budget: str = "",
    source: str = "chat",
    conversation: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO leads (ts, client_id, email, service, timing, budget, source, conversation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(time.time()), client_id, email, service, timing, budget, source, conversation),
    )
    conn.commit()

def list_leads(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, ts, client_id, email, service, timing, budget, source FROM leads ORDER BY ts DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in cur.fetchall()]

def stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    lead_count = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    event_counts = conn.execute(
        "SELECT event, COUNT(*) AS c FROM events GROUP BY event"
    ).fetchall()

    by_client = conn.execute(
        """
        SELECT client_id,
          SUM(CASE WHEN event='book_demo' THEN 1 ELSE 0 END) AS book_demo,
          SUM(CASE WHEN event='collect_email' THEN 1 ELSE 0 END) AS collect_email,
          COUNT(*) AS total_events
        FROM events
        GROUP BY client_id
        ORDER BY total_events DESC
        """
    ).fetchall()

    return {
        "leads_total": int(lead_count),
        "events": {r["event"]: int(r["c"]) for r in event_counts},
        "by_client": [dict(r) for r in by_client],
    }

def list_leads(conn: sqlite3.Connection, limit: int = 200, client_id: str | None = None) -> List[Dict[str, Any]]:
    if client_id:
        cur = conn.execute(
            "SELECT id, ts, client_id, email, service, timing, budget, source FROM leads WHERE client_id=? ORDER BY ts DESC LIMIT ?",
            (client_id, limit),
        )
    else:
        cur = conn.execute(
            "SELECT id, ts, client_id, email, service, timing, budget, source FROM leads ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in cur.fetchall()]

def stats(conn: sqlite3.Connection, client_id: str | None = None) -> Dict[str, Any]:
    if client_id:
        lead_count = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE client_id=?", (client_id,)).fetchone()["c"]
        event_counts = conn.execute(
            "SELECT event, COUNT(*) AS c FROM events WHERE client_id=? GROUP BY event",
            (client_id,),
        ).fetchall()
    else:
        lead_count = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        event_counts = conn.execute(
            "SELECT event, COUNT(*) AS c FROM events GROUP BY event"
        ).fetchall()

    return {
        "leads_total": int(lead_count),
        "events": {r["event"]: int(r["c"]) for r in event_counts},
    }

def kpi(conn: sqlite3.Connection, days: int = 7, client_id: str | None = None) -> Dict[str, Any]:
    """
    Daily counts for last N days.
    """
    # leads per day
    if client_id:
        leads_rows = conn.execute(
            """
            SELECT date(ts,'unixepoch') AS d, COUNT(*) AS c
            FROM leads
            WHERE client_id=? AND ts >= strftime('%s','now') - (? * 86400)
            GROUP BY d
            ORDER BY d ASC
            """,
            (client_id, days),
        ).fetchall()

        demo_rows = conn.execute(
            """
            SELECT date(ts,'unixepoch') AS d, COUNT(*) AS c
            FROM events
            WHERE client_id=? AND event='book_demo' AND ts >= strftime('%s','now') - (? * 86400)
            GROUP BY d
            ORDER BY d ASC
            """,
            (client_id, days),
        ).fetchall()
    else:
        leads_rows = conn.execute(
            """
            SELECT date(ts,'unixepoch') AS d, COUNT(*) AS c
            FROM leads
            WHERE ts >= strftime('%s','now') - (? * 86400)
            GROUP BY d
            ORDER BY d ASC
            """,
            (days,),
        ).fetchall()

        demo_rows = conn.execute(
            """
            SELECT date(ts,'unixepoch') AS d, COUNT(*) AS c
            FROM events
            WHERE event='book_demo' AND ts >= strftime('%s','now') - (? * 86400)
            GROUP BY d
            ORDER BY d ASC
            """,
            (days,),
        ).fetchall()

    return {
        "days": days,
        "leads_daily": [dict(r) for r in leads_rows],
        "book_demo_daily": [dict(r) for r in demo_rows],
    }

def funnel(conn: sqlite3.Connection, client_id: str, days: int = 7) -> Dict[str, Any]:
    leads = conn.execute(
        "SELECT COUNT(*) AS c FROM leads WHERE client_id=? AND ts >= strftime('%s','now') - (?*86400)",
        (client_id, days),
    ).fetchone()["c"]

    demos = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE client_id=? AND event='book_demo' AND ts >= strftime('%s','now') - (?*86400)",
        (client_id, days),
    ).fetchone()["c"]

    emails = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE client_id=? AND event='collect_email' AND ts >= strftime('%s','now') - (?*86400)",
        (client_id, days),
    ).fetchone()["c"]

    return {"days": days, "leads": int(leads), "book_demo": int(demos), "collect_email": int(emails)}