"""Lab 5, escenario 8: GET /tickets/{id} (SPEC §9.2) con ids válidos y mal formados."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

HUGE_ID = 99999999999999999999  # no cabe en un INTEGER de SQLite


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P2", "tags": []},
    )
    return TestClient(app)


@pytest.mark.parametrize("ticket_id", [-1, HUGE_ID])
def test_get_ticket_by_out_of_range_id_returns_404(client, ticket_id):
    response = client.get(f"/tickets/{ticket_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_get_ticket_by_id_returns_the_ticket(client):
    created = client.post("/tickets", json={"title": "A", "description": "d"}).json()

    response = client.get(f"/tickets/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_ticket_with_non_numeric_id_returns_422(client):
    assert client.get("/tickets/abc").status_code == 422
