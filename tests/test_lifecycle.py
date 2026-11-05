import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    return path


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P3", "tags": []},
    )
    return TestClient(app)


@pytest.fixture()
def clock(monkeypatch):
    """Reloj controlable para comprobar cuándo cambian las fechas."""
    now = {"value": "2026-11-05T10:00:00Z"}
    monkeypatch.setattr("app.db._now", lambda: now["value"])
    return now


def _create(client):
    return client.post("/tickets", json={"title": "Ticket", "description": "Descripción"}).json()


def test_ticket_can_be_marked_resolved_and_filtered(client):
    ticket = _create(client)

    patched = client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})
    resolved = client.get("/tickets", params={"status": "resolved"}).json()

    assert patched.status_code == 200
    assert patched.json()["status"] == "resolved"
    assert [t["id"] for t in resolved] == [ticket["id"]]


@pytest.mark.parametrize("previous", ["resolved", "closed"])
def test_resolved_or_closed_ticket_can_be_reopened(client, previous):
    ticket = _create(client)
    client.patch(f"/tickets/{ticket['id']}", json={"status": previous})

    reopened = client.patch(f"/tickets/{ticket['id']}", json={"status": "open"})

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


def test_status_changed_at_is_set_on_creation(client, clock):
    ticket = _create(client)

    assert ticket["status_changed_at"] == ticket["created_at"] == "2026-11-05T10:00:00Z"


def test_status_changed_at_moves_only_when_status_changes(client, clock):
    ticket = _create(client)
    url = f"/tickets/{ticket['id']}"

    clock["value"] = "2026-11-05T11:00:00Z"
    after_priority = client.patch(url, json={"priority": "P1"}).json()
    clock["value"] = "2026-11-05T12:00:00Z"
    after_status = client.patch(url, json={"status": "resolved"}).json()
    clock["value"] = "2026-11-05T13:00:00Z"
    after_same_status = client.patch(url, json={"status": "resolved"}).json()
    clock["value"] = "2026-11-05T14:00:00Z"
    after_reopen = client.patch(url, json={"status": "open"}).json()

    assert after_priority["status_changed_at"] == "2026-11-05T10:00:00Z"
    assert after_priority["updated_at"] == "2026-11-05T11:00:00Z"
    assert after_status["status_changed_at"] == "2026-11-05T12:00:00Z"
    assert after_same_status["status_changed_at"] == "2026-11-05T12:00:00Z"
    assert after_reopen["status_changed_at"] == "2026-11-05T14:00:00Z"
    assert after_reopen["created_at"] == "2026-11-05T10:00:00Z"


def test_unknown_status_is_still_rejected(client):
    ticket = _create(client)

    response = client.patch(f"/tickets/{ticket['id']}", json={"status": "archived"})

    assert response.status_code == 422


def test_ui_shows_resolved_state_since_when_and_reopen_button(client, clock):
    ticket = _create(client)
    client.post(f"/ui/tickets/{ticket['id']}", data={"new_status": "resolved"})

    clock["value"] = "2026-11-05T15:30:00Z"
    html = client.get("/ui/tickets").text

    assert 'value="resolved" selected' in html
    assert "En este estado desde" in html
    assert "2026-11-05T10:00:00Z" in html
    assert "Reabrir" in html


def test_ui_reopen_button_sets_status_open(client):
    ticket = _create(client)
    client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})

    response = client.post(f"/ui/tickets/{ticket['id']}", data={"new_status": "open"})

    assert response.status_code == 200
    assert client.get("/tickets").json()[0]["status"] == "open"
    assert "Reabrir" not in response.text


def test_ui_filter_offers_and_applies_resolved(client):
    first = _create(client)
    _create(client)
    client.patch(f"/tickets/{first['id']}", json={"status": "resolved"})

    page = client.get("/").text
    only_resolved = client.get("/ui/tickets", params={"status": "resolved"}).text

    assert '<option value="resolved">' in page
    assert only_resolved.count("<tr>") == 2  # cabecera + 1 ticket


def test_old_database_is_migrated_without_losing_tickets(db_path, client):
    old = sqlite3.connect(db_path)
    old.execute(
        """CREATE TABLE tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL CHECK (priority IN ('P1','P2','P3')),
            tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','closed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    old.execute(
        "INSERT INTO tickets (title, description, category, priority, tags, status,"
        " created_at, updated_at) VALUES ('Viejo', 'd', 'bug', 'P1', '[]', 'closed',"
        " '2026-01-01T09:00:00Z', '2026-01-02T09:00:00Z')"
    )
    old.commit()
    old.close()

    tickets = client.get("/tickets").json()
    patched = client.patch(f"/tickets/{tickets[0]['id']}", json={"status": "resolved"})

    assert len(tickets) == 1
    assert tickets[0]["title"] == "Viejo"
    assert tickets[0]["status_changed_at"] == "2026-01-02T09:00:00Z"
    assert patched.status_code == 200
    assert patched.json()["status"] == "resolved"
    assert _create(client)["id"] == tickets[0]["id"] + 1
