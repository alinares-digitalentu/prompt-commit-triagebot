"""Pantalla del cambio de Marta A (SPEC §9.5): columna y filtro de responsables."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P1", "tags": []},
    )
    return TestClient(app)


def _create(client, title="Ticket", **extra):
    return client.post("/ui/tickets", data={"title": title, "description": "D", **extra})


def test_index_has_assignee_filter_and_column(client):
    _create(client)

    page = client.get("/").text

    assert 'name="assignee"' in page
    assert "Responsables" in page


def test_create_from_form_saves_comma_separated_assignees(client):
    response = _create(client, "T", assignees=" Ana, Luis ,ana,, Marta ")

    assert response.status_code == 200
    assert client.get("/tickets").json()[0]["assignees"] == ["Ana", "Luis", "Marta"]


def test_create_form_with_too_many_assignees_shows_error_and_creates_nothing(client):
    response = _create(client, "T", assignees="a,b,c,d,e,f")

    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert "responsables" in response.text.lower()
    assert client.get("/tickets").json() == []


def test_row_edit_replaces_assignees(client):
    _create(client, "T", assignees="Ana")
    ticket_id = client.get("/tickets").json()[0]["id"]

    response = client.post(f"/ui/tickets/{ticket_id}", data={"new_assignees": "Luis, Marta"})

    assert response.status_code == 200
    assert client.get("/tickets").json()[0]["assignees"] == ["Luis", "Marta"]


def test_row_edit_with_empty_field_clears_assignees(client):
    _create(client, "T", assignees="Ana")
    ticket_id = client.get("/tickets").json()[0]["id"]

    client.post(f"/ui/tickets/{ticket_id}", data={"new_assignees": ""})

    assert client.get("/tickets").json()[0]["assignees"] == []


def test_row_edit_without_assignees_field_keeps_them(client):
    _create(client, "T", assignees="Ana")
    ticket_id = client.get("/tickets").json()[0]["id"]

    client.post(f"/ui/tickets/{ticket_id}", data={"new_status": "closed"})

    ticket = client.get("/tickets").json()[0]
    assert ticket["status"] == "closed"
    assert ticket["assignees"] == ["Ana"]


def test_row_edit_with_invalid_assignees_shows_error_and_keeps_old_value(client):
    _create(client, "T", assignees="Ana")
    ticket_id = client.get("/tickets").json()[0]["id"]

    response = client.post(f"/ui/tickets/{ticket_id}", data={"new_assignees": "a,b,c,d,e,f"})

    assert 'role="alert"' in response.text
    assert client.get("/tickets").json()[0]["assignees"] == ["Ana"]


def test_ui_filter_by_assignee_keeps_only_matching_rows(client):
    _create(client, "De Ana", assignees="Ana")
    _create(client, "De Luis", assignees="Luis")

    response = client.get("/ui/tickets", params={"assignee": "ANA"})

    assert "De Ana" in response.text
    assert "De Luis" not in response.text


def test_assignee_filter_survives_a_row_edit(client):
    _create(client, "De Ana", assignees="Ana")
    _create(client, "De Luis", assignees="Luis")
    ticket_id = client.get("/tickets", params={"assignee": "Ana"}).json()[0]["id"]

    response = client.post(
        f"/ui/tickets/{ticket_id}", data={"new_status": "in_progress", "assignee": "Ana"}
    )

    assert "De Ana" in response.text
    assert "De Luis" not in response.text


def test_assignee_names_are_escaped_in_html(client):
    _create(client, "T", assignees="<script>alert(1)</script>")

    page = client.get("/").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
