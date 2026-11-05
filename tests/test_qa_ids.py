"""Lab 5, escenario 8: IDs mal formados (-1, abc, 99999999999999999999)."""

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


@pytest.mark.parametrize("ticket_id", [-1, 0, HUGE_ID, -HUGE_ID])
def test_patch_with_out_of_range_id_returns_404_not_500(client, ticket_id):
    response = client.patch(f"/tickets/{ticket_id}", json={"status": "closed"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


def test_patch_with_non_numeric_id_returns_422(client):
    assert client.patch("/tickets/abc", json={"status": "closed"}).status_code == 422


@pytest.mark.parametrize("ticket_id", [-1, HUGE_ID])
def test_ui_update_with_out_of_range_id_shows_error_instead_of_500(client, ticket_id):
    response = client.post(f"/ui/tickets/{ticket_id}", data={"new_status": "closed"})

    assert response.status_code == 200
    assert "no existe" in response.text
