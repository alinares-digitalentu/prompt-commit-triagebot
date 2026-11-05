import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": "P1", "tags": ["login"]},
    )
    return TestClient(app)


def _create(client, title="Ticket", **extra):
    return client.post("/ui/tickets", data={"title": title, "description": "Descripción", **extra})


def test_index_renders_form_filters_and_table(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'hx-post="/ui/tickets"' in response.text
    assert 'name="category"' in response.text
    assert "No hay tickets." in response.text


def test_ui_create_returns_table_fragment_with_new_ticket(client):
    response = _create(client, "La app no carga")

    assert response.status_code == 200
    assert "<html" not in response.text
    assert "La app no carga" in response.text
    assert len(client.get("/tickets").json()) == 1


@pytest.mark.parametrize("data", [{"title": "   ", "description": "x"}, {"title": "x"}])
def test_ui_create_invalid_shows_error_and_stores_nothing(client, data):
    response = client.post("/ui/tickets", data=data)

    assert response.status_code == 200
    assert "obligatorios" in response.text
    assert client.get("/tickets").json() == []


def test_ui_escapes_html_in_ticket_text(client):
    _create(client, "<script>alert(1)</script>")

    response = client.get("/ui/tickets")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_ui_list_applies_filters_and_ignores_invalid_values(client):
    first = client.post("/tickets", json={"title": "A", "description": "d"}).json()
    client.post("/tickets", json={"title": "B", "description": "d"})
    client.patch(f"/tickets/{first['id']}", json={"status": "closed"})

    closed = client.get("/ui/tickets", params={"status": "closed"}).text
    invalid = client.get("/ui/tickets", params={"status": "zombie"}).text

    assert ">A<" in closed and ">B<" not in closed
    assert ">A<" in invalid and ">B<" in invalid


def test_ui_update_changes_status_and_priority(client):
    ticket = client.post("/tickets", json={"title": "A", "description": "d"}).json()

    response = client.post(
        f"/ui/tickets/{ticket['id']}", data={"new_status": "in_progress", "new_priority": "P3"}
    )

    assert response.status_code == 200
    updated = client.get("/tickets").json()[0]
    assert (updated["status"], updated["priority"]) == ("in_progress", "P3")


def test_ui_update_unknown_ticket_or_bad_value_shows_error(client):
    ticket = client.post("/tickets", json={"title": "A", "description": "d"}).json()

    missing = client.post("/ui/tickets/999", data={"new_status": "closed"})
    bad = client.post(f"/ui/tickets/{ticket['id']}", data={"new_status": "inventado"})

    assert missing.status_code == bad.status_code == 200
    assert "no existe" in missing.text
    assert "no válido" in bad.text
    assert client.get("/tickets").json()[0]["status"] == "open"
