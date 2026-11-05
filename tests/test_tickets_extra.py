"""Tests propios adicionales de la API (Lab 3). Sin red ni API key: el clasificador se simula."""

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


def test_list_is_empty_when_there_are_no_tickets(client):
    response = client.get("/tickets")

    assert response.status_code == 200
    assert response.json() == []


def test_title_and_description_are_trimmed_before_saving(client):
    response = client.post(
        "/tickets",
        json={"title": "  La app no carga  ", "description": "\n Pantalla en blanco \t"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "La app no carga"
    assert data["description"] == "Pantalla en blanco"


def test_real_patch_changes_updated_at_but_not_created_at(client, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T09:00:00Z")
    ticket = client.post("/tickets", json={"title": "T", "description": "D"}).json()

    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T10:00:00Z")
    patched = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"}).json()

    assert patched["created_at"] == "2026-01-01T09:00:00Z"
    assert patched["updated_at"] == "2026-01-01T10:00:00Z"

    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T11:00:00Z")
    same = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"}).json()

    assert same["updated_at"] == "2026-01-01T10:00:00Z"
