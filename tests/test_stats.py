"""Petición de Marta (Slack): GET /tickets/stats, conteos por categoría, prioridad y estado."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

ZERO_CATEGORIES = {"bug": 0, "feature_request": 0, "question": 0, "urgent": 0}
ZERO_PRIORITIES = {"P1": 0, "P2": 0, "P3": 0}
ZERO_STATUSES = {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


@pytest.fixture()
def create(client, monkeypatch):
    """Crea un ticket con la categoría y prioridad que se indiquen (clasificador simulado)."""

    def _create(title, category="bug", priority="P1"):
        monkeypatch.setattr(
            "app.classifier.classify_ticket",
            lambda t, d: {"category": category, "priority": priority, "tags": []},
        )
        return client.post("/tickets", json={"title": title, "description": "d"}).json()

    return _create


def test_stats_of_an_empty_board_are_all_zero(client):
    response = client.get("/tickets/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "by_category": ZERO_CATEGORIES,
        "by_priority": ZERO_PRIORITIES,
        "by_status": ZERO_STATUSES,
    }


def test_stats_count_tickets_by_category_priority_and_status(client, create):
    create("a", "bug", "P1")
    create("b", "bug", "P2")
    create("c", "question", "P3")
    urgent = create("d", "urgent", "P1")
    client.patch(f"/tickets/{urgent['id']}", json={"status": "in_progress"})

    stats = client.get("/tickets/stats").json()

    assert stats["total"] == 4
    assert stats["by_category"] == {**ZERO_CATEGORIES, "bug": 2, "question": 1, "urgent": 1}
    assert stats["by_priority"] == {"P1": 2, "P2": 1, "P3": 1}
    assert stats["by_status"] == {**ZERO_STATUSES, "open": 3, "in_progress": 1}


def test_stats_follow_status_changes(client, create):
    ticket = create("a")

    client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})
    resolved = client.get("/tickets/stats").json()["by_status"]
    client.patch(f"/tickets/{ticket['id']}", json={"status": "open"})
    reopened = client.get("/tickets/stats").json()["by_status"]

    assert resolved == {**ZERO_STATUSES, "resolved": 1}
    assert reopened == {**ZERO_STATUSES, "open": 1}


def test_every_breakdown_adds_up_to_the_total(client, create):
    for i, (category, priority) in enumerate(
        [("bug", "P1"), ("feature_request", "P2"), ("question", "P3"), ("bug", "P3")]
    ):
        create(f"t{i}", category, priority)

    stats = client.get("/tickets/stats").json()

    for key in ("by_category", "by_priority", "by_status"):
        assert sum(stats[key].values()) == stats["total"] == 4


def test_stats_route_is_not_confused_with_a_ticket_id(client, create):
    ticket = create("a")

    assert client.get("/tickets/stats").status_code == 200  # no 422 por «stats» no entero
    assert client.get(f"/tickets/{ticket['id']}").status_code == 200
    assert client.get("/tickets/abc").status_code == 422


def test_stats_is_read_only(client, create):
    create("a")

    assert client.post("/tickets/stats", json={}).status_code == 405
    assert client.patch("/tickets/stats", json={"status": "closed"}).status_code != 200
    assert client.get("/tickets/stats").json()["by_status"]["open"] == 1
