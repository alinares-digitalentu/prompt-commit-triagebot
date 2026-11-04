"""Tests propios del clasificador. El LLM se simula: no hay red ni API key real."""

import json

import pytest

from app import classifier

FALLBACK = {"category": "question", "priority": "P3", "tags": []}


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-falsa-de-test")


def fake_llm(monkeypatch, *responses):
    """Sustituye la llamada al LLM. Cada respuesta es un str (se devuelve) o una excepción."""
    calls = []
    pending = list(responses)

    def _fake(title, description):
        calls.append((title, description))
        response = pending.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(classifier, "_call_llm", _fake)
    return calls


def valid_json(**overrides):
    data = {"category": "bug", "priority": "P1", "tags": ["login", "blank-screen"]}
    data.update(overrides)
    return json.dumps(data)


def test_valid_response_is_returned(monkeypatch):
    fake_llm(monkeypatch, valid_json())

    result = classifier.classify_ticket("La app no carga", "Pantalla en blanco")

    assert result == {"category": "bug", "priority": "P1", "tags": ["login", "blank-screen"]}


def test_sdk_failure_twice_returns_fallback_after_one_retry(monkeypatch):
    calls = fake_llm(monkeypatch, RuntimeError("caído"), RuntimeError("caído otra vez"))

    result = classifier.classify_ticket("t", "d")

    assert result == FALLBACK
    assert len(calls) == 2


def test_retry_succeeds_after_first_failure(monkeypatch):
    calls = fake_llm(monkeypatch, TimeoutError("lento"), valid_json(category="urgent"))

    result = classifier.classify_ticket("t", "d")

    assert result["category"] == "urgent"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"category": "URGENT"},
        {"category": "inventada"},
        {"priority": "P9"},
        {"priority": "p1"},
        {"tags": "login"},
        {"tags": None},
    ],
)
def test_invalid_values_go_straight_to_fallback_without_retry(monkeypatch, bad):
    calls = fake_llm(monkeypatch, valid_json(**bad))

    result = classifier.classify_ticket("t", "d")

    assert result == FALLBACK
    assert len(calls) == 1


def test_non_json_is_retried_then_falls_back(monkeypatch):
    calls = fake_llm(monkeypatch, "esto no es json", "tampoco")

    result = classifier.classify_ticket("t", "d")

    assert result == FALLBACK
    assert len(calls) == 2


def test_json_wrapped_in_code_block_is_accepted(monkeypatch):
    fake_llm(monkeypatch, f"```json\n{valid_json()}\n```")

    result = classifier.classify_ticket("t", "d")

    assert result["category"] == "bug"


def test_tags_are_normalized(monkeypatch):
    messy = ["  Login ", "Blank Screen", "login", 42, "", "a" * 40, "uno", "dos", "tres"]
    fake_llm(monkeypatch, valid_json(tags=messy))

    tags = classifier.classify_ticket("t", "d")["tags"]

    assert tags[:2] == ["login", "blank-screen"]
    assert len(tags) <= 5
    assert len(set(tags)) == len(tags)
    assert all(tag == tag.lower() and 1 <= len(tag) <= 30 for tag in tags)


def test_missing_api_key_returns_fallback_without_calling_llm(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls = fake_llm(monkeypatch, valid_json())

    result = classifier.classify_ticket("t", "d")

    assert result == FALLBACK
    assert calls == []


def test_fallback_is_a_fresh_copy_each_time(monkeypatch):
    fake_llm(monkeypatch, *[RuntimeError("x") for _ in range(4)])

    first = classifier.classify_ticket("t", "d")
    first["tags"].append("contaminado")
    first["category"] = "bug"
    second = classifier.classify_ticket("t", "d")

    assert second == FALLBACK
    assert classifier.FALLBACK_CLASSIFICATION == FALLBACK
