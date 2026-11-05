import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

CREATED = "2026-11-04T10:00:00Z"  # miércoles por la mañana


@pytest.fixture()
def clock(monkeypatch):
    now = {"value": CREATED}
    monkeypatch.setattr(db, "_now", lambda: now["value"])
    return now


@pytest.fixture()
def priority(monkeypatch):
    """Prioridad que devolverá el clasificador simulado."""
    chosen = {"value": "P1"}
    monkeypatch.setattr(
        "app.classifier.classify_ticket",
        lambda title, description: {"category": "bug", "priority": chosen["value"], "tags": []},
    )
    return chosen


@pytest.fixture()
def client(tmp_path, monkeypatch, clock, priority):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(app)


def _create(client, title="T"):
    return client.post("/tickets", json={"title": title, "description": "D"}).json()


@pytest.mark.parametrize(
    ("chosen", "due"),
    [
        ("P1", "2026-11-04T23:59:59Z"),  # hoy mismo
        ("P2", "2026-11-05T23:59:59Z"),  # mañana
        ("P3", "2026-11-06T23:59:59Z"),  # en un par de días
    ],
)
def test_due_date_depends_on_priority(client, priority, chosen, due):
    priority["value"] = chosen

    ticket = _create(client)

    assert ticket["due_at"] == due
    assert ticket["overdue"] is False


def test_due_date_is_recalculated_when_priority_changes(client):
    ticket = _create(client)  # P1

    patched = client.patch(f"/tickets/{ticket['id']}", json={"priority": "P3"}).json()

    assert ticket["due_at"] == "2026-11-04T23:59:59Z"
    assert patched["due_at"] == "2026-11-06T23:59:59Z"


def test_ticket_becomes_overdue_after_its_deadline(client, clock):
    ticket = _create(client)  # P1: vence el 4 de noviembre a las 23:59:59

    clock["value"] = "2026-11-04T23:59:59Z"
    on_deadline = client.get("/tickets").json()[0]
    clock["value"] = "2026-11-05T00:00:00Z"
    after_deadline = client.get("/tickets").json()[0]

    assert on_deadline["id"] == after_deadline["id"] == ticket["id"]
    assert on_deadline["overdue"] is False
    assert after_deadline["overdue"] is True


@pytest.mark.parametrize("done", ["resolved", "closed"])
def test_resolved_or_closed_tickets_are_never_overdue(client, clock, done):
    ticket = _create(client)
    client.patch(f"/tickets/{ticket['id']}", json={"status": done})

    clock["value"] = "2026-12-01T00:00:00Z"

    assert client.get("/tickets").json()[0]["overdue"] is False


def test_reopened_ticket_past_its_deadline_is_overdue_again(client, clock):
    ticket = _create(client)
    client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})
    clock["value"] = "2026-11-10T09:00:00Z"

    reopened = client.patch(f"/tickets/{ticket['id']}", json={"status": "open"}).json()

    assert reopened["overdue"] is True


def test_api_filters_only_overdue_tickets(client, clock, priority):
    priority["value"] = "P1"
    late = _create(client, "late")
    priority["value"] = "P3"
    on_time = _create(client, "on-time")
    clock["value"] = "2026-11-05T12:00:00Z"

    overdue = client.get("/tickets", params={"overdue": "true"}).json()
    not_overdue = client.get("/tickets", params={"overdue": "false"}).json()
    everything = client.get("/tickets").json()

    assert [t["id"] for t in overdue] == [late["id"]]
    assert [t["id"] for t in not_overdue] == [on_time["id"]]
    assert len(everything) == 2


def test_api_rejects_invalid_overdue_value(client):
    assert client.get("/tickets", params={"overdue": "quizas"}).status_code == 422


def test_ui_marks_overdue_rows_and_filters_them(client, clock, priority):
    priority["value"] = "P1"
    _create(client, "tarde")
    priority["value"] = "P3"
    _create(client, "a-tiempo")
    clock["value"] = "2026-11-05T12:00:00Z"

    page = client.get("/").text
    all_rows = client.get("/ui/tickets").text
    only_overdue = client.get("/ui/tickets", params={"overdue": "1"}).text

    assert 'name="overdue"' in page and "Solo vencidos" in page
    assert "Vencido" in all_rows
    assert ">tarde<" in only_overdue and ">a-tiempo<" not in only_overdue
    assert "2026-11-04" in only_overdue  # fecha límite visible


def test_ui_ignores_unknown_overdue_value_and_keeps_filter_after_edit(client, clock):
    ticket = _create(client)
    clock["value"] = "2026-11-05T12:00:00Z"

    ignored = client.get("/ui/tickets", params={"overdue": "zombie"}).text
    edited = client.post(
        f"/ui/tickets/{ticket['id']}", data={"new_status": "resolved", "overdue": "1"}
    ).text

    assert ">T<" in ignored
    assert ">T<" not in edited  # al resolverlo deja de estar vencido y el filtro lo oculta
