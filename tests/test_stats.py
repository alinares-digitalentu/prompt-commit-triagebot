"""SPEC §9.8: GET /tickets/stats (petición de Marta por Slack)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    answers = iter(
        [
            {"category": "bug", "priority": "P1", "tags": []},
            {"category": "bug", "priority": "P2", "tags": []},
            {"category": "question", "priority": "P3", "tags": []},
        ]
    )
    monkeypatch.setattr("app.classifier.classify_ticket", lambda t, d: next(answers))
    return TestClient(app)


def _create(client, title):
    return client.post("/tickets", json={"title": title, "description": "D"}).json()["id"]


def test_stats_on_empty_database_has_all_keys_at_zero(client):
    body = client.get("/tickets/stats").json()

    assert body["total"] == 0
    assert body["by_category"] == {"bug": 0, "feature_request": 0, "question": 0, "urgent": 0}
    assert body["by_priority"] == {"P1": 0, "P2": 0, "P3": 0}
    assert body["by_status"] == {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}


def test_stats_counts_by_category_priority_and_status(client):
    _create(client, "a")
    _create(client, "b")
    third = _create(client, "c")
    client.patch(f"/tickets/{third}", json={"status": "closed"})

    body = client.get("/tickets/stats").json()

    assert body["total"] == 3
    assert body["by_category"]["bug"] == 2
    assert body["by_category"]["question"] == 1
    assert body["by_priority"] == {"P1": 1, "P2": 1, "P3": 1}
    assert body["by_status"]["open"] == 2
    assert body["by_status"]["closed"] == 1


def test_stats_route_is_not_swallowed_by_ticket_id_routes(client):
    assert client.get("/tickets/stats").status_code == 200
