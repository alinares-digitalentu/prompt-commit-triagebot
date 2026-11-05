import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def _create(client, monkeypatch, title="Ticket", category="bug", priority="P1"):
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda t, d: {"category": category, "priority": priority, "tags": []},
    )
    response = client.post("/tickets", json={"title": title, "description": "Descripción"})
    assert response.status_code == 201
    return response.json()


def test_list_is_ordered_newest_first_and_filters_combine_with_and(client, monkeypatch):
    first = _create(client, monkeypatch, "A", category="bug", priority="P1")
    second = _create(client, monkeypatch, "B", category="bug", priority="P3")
    _create(client, monkeypatch, "C", category="question", priority="P1")

    all_tickets = client.get("/tickets").json()
    assert [t["title"] for t in all_tickets] == ["C", "B", "A"]

    filtered = client.get("/tickets", params={"category": "bug", "priority": "P1"}).json()
    assert [t["id"] for t in filtered] == [first["id"]]
    assert second["id"] not in [t["id"] for t in filtered]


def test_list_rejects_filter_value_outside_enum(client):
    response = client.get("/tickets", params={"status": "archived"})

    assert response.status_code == 422


def test_patch_unknown_ticket_returns_404(client):
    response = client.patch("/tickets/999", json={"status": "closed"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "archived"},
        {"priority": "P9"},
        {"title": "Nuevo título"},
        {"status": "closed", "category": "bug"},
    ],
)
def test_patch_invalid_payload_returns_422(client, monkeypatch, payload):
    ticket = _create(client, monkeypatch)

    response = client.patch(f"/tickets/{ticket['id']}", json=payload)

    assert response.status_code == 422


def test_patch_can_reopen_closed_ticket(client, monkeypatch):
    ticket = _create(client, monkeypatch)
    client.patch(f"/tickets/{ticket['id']}", json={"status": "closed"})

    reopened = client.patch(f"/tickets/{ticket['id']}", json={"status": "open"})

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


def test_patch_with_same_values_does_not_touch_updated_at(client, monkeypatch):
    ticket = _create(client, monkeypatch, priority="P2")

    response = client.patch(f"/tickets/{ticket['id']}", json={"priority": "P2"})

    assert response.status_code == 200
    assert response.json()["updated_at"] == ticket["updated_at"]
