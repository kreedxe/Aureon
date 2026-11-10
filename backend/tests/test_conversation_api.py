from pathlib import Path

from pydantic import SecretStr
from pytest import MonkeyPatch
from test_api import AUTH_HEADERS, request

from app.core.config import settings
from app.main import app
from app.schemas.conversations import ConversationSummary
from app.services.conversation_repository import ConversationRepository


def test_conversation_api_creates_lists_loads_and_deletes_history(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "session_token", SecretStr("test-session-token"))
    repository = ConversationRepository(tmp_path / "conversations.sqlite3")
    monkeypatch.setattr(app.state, "conversation_repository", repository, raising=False)

    created = request(
        "POST",
        "/api/v1/conversations",
        headers=AUTH_HEADERS,
        json={"language": "en"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = request("GET", "/api/v1/conversations", headers=AUTH_HEADERS)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [conversation_id]

    repository.append_message(conversation_id, "user", "I want headphones.", "en", 0.9)
    repository.append_message(
        conversation_id,
        "assistant",
        "Which kind do you need?",
        "en",
    )
    summary = ConversationSummary(
        title="Headphones",
        customer_name="Not provided",
        customer_age="Not provided",
        customer_location="Not provided",
        other_customer_details=["Not provided"],
        customer_interests=["Headphones"],
        customer_needs=["Not provided"],
        purchase_intent="interested",
        purchase_outcome="no_purchase",
        tone="Neutral",
        important_details=["Not provided"],
        next_steps=["Not provided"],
    )
    repository.complete(conversation_id, summary)

    loaded = request(
        "GET",
        f"/api/v1/conversations/{conversation_id}",
        headers=AUTH_HEADERS,
    )
    assert loaded.status_code == 200
    assert [message["role"] for message in loaded.json()["messages"]] == ["user", "assistant"]
    assert loaded.json()["summary"]["customer_name"] == "Not provided"
    assert request(
        "DELETE",
        f"/api/v1/conversations/{conversation_id}",
        headers=AUTH_HEADERS,
    ).status_code == 204
    assert request(
        "GET",
        f"/api/v1/conversations/{conversation_id}",
        headers=AUTH_HEADERS,
    ).status_code == 404


def test_active_conversations_cannot_be_deleted(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "session_token", SecretStr("test-session-token"))
    repository = ConversationRepository(tmp_path / "conversations.sqlite3")
    monkeypatch.setattr(app.state, "conversation_repository", repository, raising=False)
    conversation = repository.create("ru")

    response = request(
        "DELETE",
        f"/api/v1/conversations/{conversation.id}",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 409
    assert repository.get(conversation.id) is not None
