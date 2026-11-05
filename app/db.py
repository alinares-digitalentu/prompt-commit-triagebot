import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

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
    assignees TEXT NOT NULL DEFAULT '[]',
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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)")}
    if "assignees" not in columns:  # base de datos anterior al cambio de Marta A
        conn.execute("ALTER TABLE tickets ADD COLUMN assignees TEXT NOT NULL DEFAULT '[]'")
        conn.commit()
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
            "INSERT INTO tickets (id, title, description, category, priority, tags, assignees,"
            " status, created_at, updated_at, status_changed_at)"
            " SELECT id, title, description, category, priority, tags, assignees, status,"
            " created_at, updated_at, updated_at FROM tickets_old"
        )
        conn.execute("DROP TABLE tickets_old")


# Días de plazo por prioridad: P1 vence hoy mismo, P2 mañana, P3 en dos días.
DEADLINE_DAYS = {"P1": 0, "P2": 1, "P3": 2}
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
OPEN_STATUSES = ("open", "in_progress")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_due_at(created_at: str, priority: str) -> str:
    """Fin del día (UTC) en que vence el ticket: creación + plazo de su prioridad."""
    created = datetime.strptime(created_at, DATE_FORMAT)
    due_day = created.date() + timedelta(days=DEADLINE_DAYS[priority])
    return f"{due_day.isoformat()}T23:59:59Z"


def _row_to_ticket(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    ticket["tags"] = json.loads(ticket["tags"])
    ticket["assignees"] = json.loads(ticket["assignees"])
    ticket["due_at"] = compute_due_at(ticket["created_at"], ticket["priority"])
    # Vencido: sigue abierto (no resuelto ni cerrado) y ya pasó su fecha límite.
    ticket["overdue"] = ticket["status"] in OPEN_STATUSES and _now() > ticket["due_at"]
    return ticket


def create_ticket(
    title: str, description: str, classification: dict, assignees: list[str] | None = None
) -> dict:
    now = _now()
    with closing(get_connection()) as conn:
        with conn:  # commit o rollback
            cur = conn.execute(
                "INSERT INTO tickets (title, description, category, priority, tags,"
                " assignees, status, created_at, updated_at, status_changed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
                (
                    title,
                    description,
                    classification["category"],
                    classification["priority"],
                    json.dumps(classification["tags"]),
                    json.dumps(assignees or []),
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
    assignee: str | None = None,
    overdue: bool | None = None,
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
    tickets = [_row_to_ticket(row) for row in rows]
    if assignee is not None:  # sin distinguir mayúsculas (SQLite lower() solo cubre ASCII)
        wanted = assignee.strip().casefold()
        tickets = [t for t in tickets if wanted in {a.casefold() for a in t["assignees"]}]
    if overdue is not None:
        tickets = [t for t in tickets if t["overdue"] == overdue]
    return tickets


def update_ticket(ticket_id: int, changes: dict) -> dict | None:
    """Actualiza status/priority/assignees. `updated_at` solo cambia si algo cambia de verdad."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return None
        current = _row_to_ticket(row)
        real_changes = {k: v for k, v in changes.items() if current[k] != v}
        if real_changes:
            now = _now()
            # `status_changed_at` ("en este estado desde") solo cambia si cambia el estado.
            stamped = {**real_changes, "updated_at": now}
            if "status" in real_changes:
                stamped["status_changed_at"] = now
            assignments = ", ".join(f"{column} = ?" for column in stamped)
            values = [
                json.dumps(v) if column == "assignees" else v for column, v in stamped.items()
            ]
            with conn:  # commit o rollback
                conn.execute(
                    f"UPDATE tickets SET {assignments} WHERE id = ?",
                    (*values, ticket_id),
                )
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_ticket(row)
