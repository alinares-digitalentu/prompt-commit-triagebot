"""Lab 5, escenario 7: no debe poder haber tickets duplicados."""

import concurrent.futures

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

CLASSIFICATION = {"category": "bug", "priority": "P2", "tags": []}


@pytest.fixture()
def calls(monkeypatch):
    """Cuenta las llamadas al clasificador (cada una costaría tokens reales)."""
    counter = {"n": 0}

    def fake(title, description):
        counter["n"] += 1
        return CLASSIFICATION

    monkeypatch.setattr("app.classifier.classify_ticket", fake)
    return counter


@pytest.fixture()
def client(tmp_path, monkeypatch, calls):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def _post(client, title="La app no carga", description="Pantalla en blanco"):
    return client.post("/tickets", json={"title": title, "description": description})


def test_same_ticket_twice_is_rejected_with_409(client):
    first = _post(client)

    second = _post(client)

    assert first.status_code == 201
    assert second.status_code == 409
    assert str(first.json()["id"]) in second.json()["detail"]
    assert len(client.get("/tickets").json()) == 1


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("LA APP NO CARGA", "pantalla en blanco"),
        ("  La app no carga ", " Pantalla en blanco  "),
        ("La  app   no carga", "Pantalla\nen blanco"),
    ],
)
def test_duplicates_ignore_case_and_extra_whitespace(client, title, description):
    _post(client)

    assert _post(client, title, description).status_code == 409


def test_same_title_with_other_description_is_not_a_duplicate(client):
    _post(client)

    assert _post(client, description="Otro problema distinto").status_code == 201


def test_duplicate_is_rejected_without_calling_the_classifier(client, calls):
    _post(client)

    _post(client)

    assert calls["n"] == 1


def test_resolved_ticket_still_blocks_a_duplicate(client):
    first = _post(client).json()
    client.patch(f"/tickets/{first['id']}", json={"status": "resolved"})

    assert _post(client).status_code == 409


def test_closed_ticket_allows_registering_the_problem_again(client):
    first = _post(client).json()
    client.patch(f"/tickets/{first['id']}", json={"status": "closed"})

    assert _post(client).status_code == 201


def test_ui_shows_a_message_instead_of_creating_the_duplicate(client):
    data = {"title": "La app no carga", "description": "Pantalla en blanco"}
    client.post("/ui/tickets", data=data)

    response = client.post("/ui/tickets", data=data)

    assert response.status_code == 200
    assert "Ya existe un ticket igual" in response.text
    assert len(client.get("/tickets").json()) == 1


def test_simultaneous_identical_requests_create_exactly_one_ticket(client):
    def attempt(_):
        try:
            db.create_ticket("Mismo", "texto", CLASSIFICATION)
            return "creado"
        except db.DuplicateTicketError:
            return "duplicado"

    with concurrent.futures.ThreadPoolExecutor(10) as pool:
        results = list(pool.map(attempt, range(10)))

    assert results.count("creado") == 1
    assert results.count("duplicado") == 9
    assert len(client.get("/tickets").json()) == 1
