"""Cambio de Marta A (SPEC §9.5): varios responsables por ticket y filtro por responsable."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P1", "tags": []},
    )
    return TestClient(app)


def _create(client, title="T", **extra):
    response = client.post("/tickets", json={"title": title, "description": "D", **extra})
    assert response.status_code == 201
    return response.json()


def test_ticket_without_assignees_has_empty_list(client):
    assert _create(client)["assignees"] == []


def test_create_with_assignees_normalizes_trim_and_duplicates(client):
    ticket = _create(client, assignees=["  Ana ", "Luis", "ana", "LUIS", "Marta"])

    assert ticket["assignees"] == ["Ana", "Luis", "Marta"]


def test_patch_replaces_assignees_and_empty_list_clears_them(client):
    ticket = _create(client, assignees=["Ana"])

    replaced = client.patch(f"/tickets/{ticket['id']}", json={"assignees": ["Luis", "Marta"]})
    assert replaced.status_code == 200
    assert replaced.json()["assignees"] == ["Luis", "Marta"]

    cleared = client.patch(f"/tickets/{ticket['id']}", json={"assignees": []})
    assert cleared.status_code == 200
    assert cleared.json()["assignees"] == []


def test_patch_can_combine_assignees_with_status(client):
    ticket = _create(client)

    response = client.patch(
        f"/tickets/{ticket['id']}", json={"status": "in_progress", "assignees": ["Ana"]}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["assignees"] == ["Ana"]


def test_updated_at_changes_only_when_assignees_really_change(client, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T09:00:00Z")
    ticket = _create(client, assignees=["Ana", "Luis"])

    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T10:00:00Z")
    same = client.patch(
        f"/tickets/{ticket['id']}", json={"assignees": ["Ana", " Luis ", "luis"]}
    ).json()
    assert same["updated_at"] == "2026-01-01T09:00:00Z"

    changed = client.patch(f"/tickets/{ticket['id']}", json={"assignees": ["Ana"]}).json()
    assert changed["updated_at"] == "2026-01-01T10:00:00Z"
    assert changed["created_at"] == "2026-01-01T09:00:00Z"

    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T11:00:00Z")
    renamed = client.patch(f"/tickets/{ticket['id']}", json={"assignees": ["ana"]}).json()
    assert renamed["assignees"] == ["ana"]
    assert renamed["updated_at"] == "2026-01-01T11:00:00Z"


@pytest.mark.parametrize(
    "assignees",
    [
        [""],
        ["   "],
        ["x" * 51],
        ["a", "b", "c", "d", "e", "f"],
        "Ana",
        [1, 2],
        None,
    ],
)
def test_invalid_assignees_are_rejected_and_ticket_is_not_changed(client, assignees):
    ticket = _create(client, assignees=["Ana"])

    patch = client.patch(f"/tickets/{ticket['id']}", json={"assignees": assignees})
    post = client.post("/tickets", json={"title": "T", "description": "D", "assignees": assignees})

    assert patch.status_code == 422
    assert post.status_code == 422
    assert client.get("/tickets").json()[0]["assignees"] == ["Ana"]
    assert len(client.get("/tickets").json()) == 1


def test_filter_by_assignee_is_case_insensitive_and_combines_with_and(client):
    a = _create(client, "A", assignees=["Ana", "Luis"])
    _create(client, "B", assignees=["Marta"])
    c = _create(client, "C", assignees=["ana"])
    client.patch(f"/tickets/{c['id']}", json={"status": "closed"})

    by_ana = client.get("/tickets", params={"assignee": "ANA"}).json()
    assert {t["id"] for t in by_ana} == {a["id"], c["id"]}

    open_ana = client.get("/tickets", params={"assignee": "ana", "status": "open"}).json()
    assert [t["id"] for t in open_ana] == [a["id"]]


def test_filter_by_unknown_assignee_returns_empty_list(client):
    _create(client, assignees=["Ana"])

    response = client.get("/tickets", params={"assignee": "Nadie"})

    assert response.status_code == 200
    assert response.json() == []


def test_filter_by_empty_assignee_returns_422(client):
    assert client.get("/tickets", params={"assignee": ""}).status_code == 422


def test_filter_matches_non_ascii_names_ignoring_case(client):
    ticket = _create(client, assignees=["Álvaro"])

    found = client.get("/tickets", params={"assignee": "álvaro"}).json()

    assert [t["id"] for t in found] == [ticket["id"]]


def test_existing_database_without_assignees_column_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
        " description TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,"
        " tags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open',"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tickets (title, description, category, priority, created_at, updated_at)"
        " VALUES ('Viejo', 'D', 'bug', 'P1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")

    tickets = TestClient(app).get("/tickets").json()

    assert [t["title"] for t in tickets] == ["Viejo"]
    assert tickets[0]["assignees"] == []
