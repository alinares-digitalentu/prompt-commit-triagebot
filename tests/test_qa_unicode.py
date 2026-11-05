"""QA adversarial (SPEC §9.8): entradas hostiles que antes provocaban un 500."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

JSON = {"content-type": "application/json"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P2", "tags": []},
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "body",
    [
        '{"title": "\\ud800", "description": "D"}',
        '{"title": "T", "description": "\\udfff"}',
        '{"title": "T", "description": "D", "assignees": ["\\ud800"]}',
    ],
)
def test_lone_surrogates_are_rejected_with_422_and_nothing_is_saved(client, body):
    response = client.post("/tickets", content=body, headers=JSON)

    assert response.status_code == 422
    assert client.get("/tickets").json() == []


def test_lone_surrogate_in_patch_assignees_is_422_and_keeps_old_value(client):
    ticket = client.post("/tickets", json={"title": "T", "description": "D", "assignees": ["Ana"]})
    ticket_id = ticket.json()["id"]

    response = client.patch(
        f"/tickets/{ticket_id}", content='{"assignees": ["\\ud800"]}', headers=JSON
    )

    assert response.status_code == 422
    assert client.get("/tickets").json()[0]["assignees"] == ["Ana"]
