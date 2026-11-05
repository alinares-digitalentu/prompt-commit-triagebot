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
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','in_progress','resolved','closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_changed_at TEXT NOT NULL
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
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Reconstruye la tabla de una BD antigua (sin `resolved` ni `status_changed_at`).

    SQLite no permite modificar un CHECK existente, así que se recrea la tabla.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "status_changed_at" in columns:
        return
    with conn:
        conn.execute("ALTER TABLE tickets RENAME TO tickets_old")
        conn.execute(SCHEMA)
        conn.execute(
            "INSERT INTO tickets (id, title, description, category, priority, tags, status,"
            " created_at, updated_at, status_changed_at)"
            " SELECT id, title, description, category, priority, tags, status,"
            " created_at, updated_at, updated_at FROM tickets_old"
        )
        conn.execute("DROP TABLE tickets_old")


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
                " status, created_at, updated_at, status_changed_at)"
                " VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"]),
                    now,
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_ticket(row)


def get_ticket(ticket_id: int) -> dict | None:
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_ticket(row) if row else None


def list_tickets(
    category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Lista tickets (más recientes primero); los filtros se combinan con AND."""
    filters = {"category": category, "priority": priority, "status": status}
    active = {column: value for column, value in filters.items() if value is not None}
    where = " AND ".join(f"{column} = ?" for column in active)
    query = "SELECT * FROM tickets"
    if where:
        query += f" WHERE {where}"
    query += " ORDER BY created_at DESC, id DESC"
    with closing(get_connection()) as conn:
        rows = conn.execute(query, tuple(active.values())).fetchall()
    return [_row_to_ticket(row) for row in rows]


def update_ticket(ticket_id: int, changes: dict) -> dict | None:
    """Actualiza status/priority. `updated_at` solo cambia si algún valor cambia de verdad."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return None
        real_changes = {k: v for k, v in changes.items() if row[k] != v}
        if real_changes:
            now = _now()
            # `status_changed_at` ("en este estado desde") solo cambia si cambia el estado.
            stamped = {**real_changes, "updated_at": now}
            if "status" in real_changes:
                stamped["status_changed_at"] = now
            assignments = ", ".join(f"{column} = ?" for column in stamped)
            with conn:  # commit o rollback
                conn.execute(
                    f"UPDATE tickets SET {assignments} WHERE id = ?",
                    (*stamped.values(), ticket_id),
                )
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_ticket(row)
