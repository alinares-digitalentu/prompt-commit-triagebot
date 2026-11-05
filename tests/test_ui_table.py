"""La tabla debe mostrar «En este estado desde» de verdad (cada fila, con su fecha)."""

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


def test_row_shows_status_changed_at_different_from_created_at(client, monkeypatch):
    monkeypatch.setattr(db, "_now", lambda: "2026-01-01T09:00:00Z")
    ticket = client.post("/tickets", json={"title": "T", "description": "D"}).json()

    monkeypatch.setattr(db, "_now", lambda: "2026-01-02T17:30:00Z")
    client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})

    html = client.get("/ui/tickets").text

    assert "2026-01-01T09:00:00Z" in html  # «Creado»
    assert "2026-01-02T17:30:00Z" in html  # «En este estado desde»


def test_every_row_has_one_cell_per_header(client):
    for title in ("A", "B"):
        client.post("/tickets", json={"title": title, "description": "D"})

    html = client.get("/ui/tickets").text
    headers = html.split("</thead>")[0].count("<th ")
    first_row = html.split("<tbody")[1].split("<tr>")[1]  # el título es <th scope="row">
    cells_in_first_row = first_row.count("<td ") + first_row.count("<th ")

    assert headers == cells_in_first_row


def test_empty_table_message_spans_all_columns(client):
    html = client.get("/ui/tickets").text
    headers = html.split("</thead>")[0].count("<th ")

    assert f'colspan="{headers}"' in html
