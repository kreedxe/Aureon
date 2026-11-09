import json
from itertools import product
from typing import Any

from pytest import MonkeyPatch

from app.schemas.ai import AIAction
from app.schemas.languages import LanguageCode
from app.services.ai_engine import LocalAIEngine

LANGUAGES: tuple[LanguageCode, ...] = ("uz", "ru", "en")
OPERATIONS: tuple[AIAction, ...] = ("summary", "key_points", "action_items", "translation")
TARGET_LANGUAGE: dict[LanguageCode, LanguageCode] = {"uz": "ru", "ru": "en", "en": "uz"}


class FakeLlama:
    def create_chat_completion(self, *, messages: list[dict[str, str]], **_: Any) -> dict[str, Any]:
        prompt = messages[-1]["content"]
        operation = next(
            operation
            for operation in OPERATIONS
            if LocalAIEngine._prompt(operation, "Example transcript") in prompt
        )
        responses = {
            "summary": {"summary": "Example summary"},
            "key_points": {"key_points": ["First point", "Second point"]},
            "action_items": {
                "action_items": [{"task": "Call the team", "owner": None, "due": None}],
                "decisions": ["Proceed with the plan"],
            },
            "translation": {"translation": "Example translation"},
        }
        return {
            "choices": [{"message": {"content": json.dumps(responses[operation])}}],
        }


def test_all_ai_operations_validate_in_all_supported_languages(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = LocalAIEngine()
    monkeypatch.setattr(engine, "_get_model", lambda _progress: FakeLlama())

    for operation, source_language in product(OPERATIONS, LANGUAGES):
        target_language = TARGET_LANGUAGE[source_language] if operation == "translation" else None
        result = engine.process(
            operation,
            "Example transcript",
            source_language,
            target_language,
            lambda _progress, _message: None,
        )

        assert result.operation == operation
        if operation == "translation":
            assert result.source_language == source_language
            assert result.target_language == target_language
            assert result.translation == "Example translation"
        else:
            assert result.language == source_language


def test_translation_requires_a_different_target_language(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = LocalAIEngine()
    monkeypatch.setattr(engine, "_get_model", lambda _progress: FakeLlama())

    try:
        engine.process(
            "translation",
            "Example transcript",
            "uz",
            "uz",
            lambda _progress, _message: None,
        )
    except ValueError as error:
        assert "must differ" in str(error)
    else:
        raise AssertionError("Translation into the source language must be rejected.")


def test_generation_schemas_require_only_model_generated_fields() -> None:
    summary_schema = LocalAIEngine._generation_schema_for("summary")
    assert set(summary_schema["properties"]) == {"summary"}
    assert summary_schema["required"] == ["summary"]

    action_schema = LocalAIEngine._generation_schema_for("action_items")
    assert set(action_schema["properties"]) == {"action_items", "decisions"}
    assert action_schema["required"] == ["action_items", "decisions"]
    assert action_schema["$defs"]["ActionItem"]["required"] == ["task", "owner", "due"]
