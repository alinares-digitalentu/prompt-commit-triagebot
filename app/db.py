import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

DEFAULT_DATABASE_URL = "sqlite:///./triagebot.db"
URL_PREFIX = "sqlite:///"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('bug','feature_request','question','urgent')),
    priority TEXT NOT NULL CHECK (priority IN ('P1','P2','P3')),
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _db_path() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not url.startswith(URL_PREFIX):
        raise ValueError(f"DATABASE_URL must start with {URL_PREFIX}")
    return url[len(URL_PREFIX):]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    return ticket


def create_ticket(title: str, description: str, classification: dict) -> dict:
    now = _now()
    with closing(get_connection()) as conn:
        with conn:  # commit o rollback
            cur = conn.execute(
                "INSERT INTO tickets (title, description, category, priority, tags,"
                " status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"]),
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_ticket(row)
