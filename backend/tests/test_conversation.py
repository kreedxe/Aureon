from __future__ import annotations

from asyncio import run
from asyncio import sleep as async_sleep
from collections.abc import Callable
from pathlib import Path
from time import sleep as time_sleep
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from fastapi import WebSocket

from app.api.routes.conversations import stream_conversation
from app.core.config import settings
from app.schemas.conversations import (
    ConversationReadinessResponse,
    ConversationStart,
    ConversationState,
    ConversationSummaryDraft,
    ProductSearchPlan,
)
from app.schemas.languages import LanguageCode
from app.schemas.products import ProductInput
from app.services.conversation import ConversationService
from app.services.conversation_repository import ConversationRepository
from app.services.products import ProductRepository
from app.services.transcription import TranscriptionResult


class FakeAIEngine:
    def __init__(
        self,
        product_query: str | None = "Studio Headphones",
        catalog_requested: bool = True,
        reply: str = "I can check that for you.",
        plan_delay: float = 0,
    ) -> None:
        self.product_query = product_query
        self.catalog_requested = catalog_requested
        self.reply = reply
        self.plan_delay = plan_delay
        self.catalog_facts: str | None = None
        self.greeting_calls = 0
        self.summary_calls = 0
        self.product_plan_calls = 0

    def extract_product_query(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
    ) -> ProductSearchPlan:
        self.product_plan_calls += 1
        time_sleep(self.plan_delay)
        return ProductSearchPlan(
            catalog_requested=self.catalog_requested,
            product_query=self.product_query,
        )

    def generate_conversation_reply(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
        *,
        greeting: bool = False,
        catalog_facts: str | None = None,
    ) -> str:
        self.greeting_calls += int(greeting)
        self.catalog_facts = catalog_facts
        return self.reply

    def generate_conversation_summary(
        self,
        messages: list[dict[str, str]],
    ) -> ConversationSummaryDraft:
        self.summary_calls += 1
        return ConversationSummaryDraft(
            title="Studio Headphones inquiry",
            customer_name="Not provided",
            customer_age="Not provided",
            customer_location="Not provided",
            other_customer_details=["Not provided"],
            customer_interests=["Studio Headphones"],
            customer_needs=["Not provided"],
            purchase_intent="interested",
            purchase_outcome="no_purchase",
            tone="Neutral",
            important_details=["Not provided"],
            next_steps=["Not provided"],
        )


class FakeTranscriber:
    def __init__(self, text: str = "How much do the Studio Headphones cost?") -> None:
        self.text = text
        self.calls = 0

    def transcribe_samples(
        self,
        audio: np.ndarray,
        language: LanguageCode | None,
        report_progress: Callable[[float, str], None],
    ) -> TranscriptionResult:
        self.calls += 1
        return TranscriptionResult(
            text=self.text,
            language=language or "en",
            language_probability=0.98,
            model="small",
        )


class FakeSynthesizer:
    def synthesize(self, text: str, language: LanguageCode) -> bytes:
        return b"local-wav"


class FakeWebSocket:
    def __init__(self, incoming: list[dict[str, object]] | None = None) -> None:
        self.events: list[dict[str, object]] = []
        self.audio: bytes | None = None
        self.audio_outputs: list[bytes] = []
        self.incoming = incoming or []

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def send_bytes(self, audio: bytes) -> None:
        self.audio = audio
        self.audio_outputs.append(audio)

    async def receive(self) -> dict[str, object]:
        await async_sleep(0.01)
        if not self.incoming:
            raise AssertionError("The fake websocket has no more input.")
        return self.incoming.pop(0)


class FakeVAD:
    frame_samples = 512

    def reset(self) -> None:
        return None

    def probability(self, frame: np.ndarray) -> float:
        return 0.9 if float(np.max(frame)) > 0.1 else 0


class FakeHandshakeWebSocket:
    def __init__(self, token: str, repository: ConversationRepository) -> None:
        conversation = repository.create("en")
        self.payload = {
            "type": "start",
            "token": token,
            "language": "en",
            "conversation_id": conversation.id,
        }
        self.events: list[dict[str, object]] = []
        self.close_code: int | None = None
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                conversation_service=SimpleNamespace(
                    status=lambda: ConversationReadinessResponse(
                        ready=False,
                        vad_ready=False,
                        whisper_ready=True,
                        llm_ready=True,
                        voices=[],
                        install_status="idle",
                        install_progress=0,
                        install_message="Models need preparation.",
                    ),
                    claim_conversation=lambda _conversation_id: True,
                    release_conversation=lambda _conversation_id: None,
                ),
                conversation_repository=repository,
            )
        )

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> dict[str, str]:
        return self.payload

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def close(self, code: int, reason: str) -> None:
        self.close_code = code


@pytest.mark.parametrize(
    ("language", "expected_stock", "product_query", "llm_reply"),
    [
        ("en", "7 in stock", "Studio Headphones", "I can check that for you."),
        ("ru", "в наличии 7 шт.", "Studio Headphones", "I can check that for you."),
        ("uz", "omborda 7 dona", "Studio Headphones", "I can check that for you."),
        ("en", "7 in stock", None, "I can check that for you."),
        (
            "en",
            "7 in stock",
            "Studio Headphones",
            "Studio Headphones: 129.95 USD; 7 in stock.",
        ),
    ],
)
def test_conversation_turn_uses_live_sqlite_product_facts(
    tmp_path: Path,
    language: LanguageCode,
    expected_stock: str,
    product_query: str | None,
    llm_reply: str,
) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    products.create_product(
        ProductInput(
            name="Studio Headphones",
            description="Closed-back headphones.",
            price="129.95",
            currency="USD",
            stock_quantity=7,
            category="Audio",
            brand="Aureon",
        )
    )
    ai_engine = FakeAIEngine(product_query, reply=llm_reply)
    transcript = {
        "en": "How much do the Studio Headphones cost?",
        "ru": "Сколько стоят Studio Headphones?",
        "uz": "Studio Headphones narxi qancha?",
    }[language]
    service = ConversationService(
        ai_engine,
        FakeTranscriber(transcript),
        products,
    )  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    conversation = service.conversation_repository.create(language)
    websocket = FakeWebSocket()
    states: list[ConversationState] = []

    async def change_state(state: ConversationState, _message: str) -> None:
        states.append(state)

    run(
        service._process_utterance(
            cast(WebSocket, websocket),
            np.ones(8_000, dtype=np.float32),
            language,
            [],
            change_state,
            conversation.id,
        )
    )
    saved = service.conversation_repository.get(conversation.id)
    service.close()

    assistant_reply = next(
        event["text"] for event in websocket.events if event["type"] == "assistant"
    )
    assert "129.95 USD" in str(assistant_reply)
    assert expected_stock in str(assistant_reply)
    assert ai_engine.catalog_facts is not None
    assert "Studio Headphones" in ai_engine.catalog_facts
    assert str(assistant_reply).count("Studio Headphones:") == 1
    assert websocket.audio == b"local-wav"
    assert states == ["TRANSCRIBING", "THINKING", "SPEAKING"]
    assert saved is not None
    assert [message.role for message in saved.messages] == ["user", "assistant"]


def test_normal_greeting_does_not_query_catalog_or_append_disclaimer(tmp_path: Path) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    ai_engine = FakeAIEngine(
        product_query=None,
        catalog_requested=False,
        reply="Hello. How can I help?",
    )
    service = ConversationService(ai_engine, FakeTranscriber("Hello"), products)  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    conversation = service.conversation_repository.create("en")
    websocket = FakeWebSocket()
    search_calls = 0
    original_search = products.list_products

    def count_search(*args: object, **kwargs: object) -> tuple[list[object], list[str]]:
        nonlocal search_calls
        search_calls += 1
        return original_search(*args, **kwargs)  # type: ignore[arg-type,return-value]

    products.list_products = count_search  # type: ignore[method-assign]

    async def change_state(_state: ConversationState, _message: str) -> None:
        return None

    run(
        service._process_utterance(
            cast(WebSocket, websocket),
            np.ones(8_000, dtype=np.float32),
            "en",
            [],
            change_state,
            conversation.id,
        )
    )
    saved = service.conversation_repository.get(conversation.id)
    service.close()

    assert search_calls == 0
    assert ai_engine.catalog_facts is None
    assert len([event for event in websocket.events if event["type"] == "assistant"]) == 1
    assert "catalog" not in str(websocket.events[-1]).lower()
    assert saved is not None
    assert [message.role for message in saved.messages] == ["user", "assistant"]


def test_russian_smalltalk_does_not_repeat_catalog_disclaimer(tmp_path: Path) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    ai_engine = FakeAIEngine(
        product_query="",
        catalog_requested=True,
        reply="Здравствуйте! У меня всё хорошо. Чем могу помочь?",
    )
    service = ConversationService(
        ai_engine,
        FakeTranscriber("Здравствуйте, как прошёл ваш день?"),
        products,
    )  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    conversation = service.conversation_repository.create("ru")
    websocket = FakeWebSocket()
    history = [
        {
            "role": "assistant",
            "content": (
                "В локальном каталоге не нашлось подходящего товара, поэтому я не могу "
                "подтвердить цену или наличие."
            ),
        },
    ]
    search_calls = 0
    original_search = products.list_products

    def count_search(*args: object, **kwargs: object) -> tuple[list[object], list[str]]:
        nonlocal search_calls
        search_calls += 1
        return original_search(*args, **kwargs)  # type: ignore[arg-type,return-value]

    products.list_products = count_search  # type: ignore[method-assign]

    async def change_state(_state: ConversationState, _message: str) -> None:
        return None

    run(
        service._process_utterance(
            cast(WebSocket, websocket),
            np.ones(8_000, dtype=np.float32),
            "ru",
            history,
            change_state,
            conversation.id,
        )
    )
    assistant_reply = next(
        event["text"] for event in websocket.events if event["type"] == "assistant"
    )
    service.close()

    assert ai_engine.product_plan_calls == 0
    assert ai_engine.catalog_facts is None
    assert search_calls == 0
    assert "каталог" not in str(assistant_reply).casefold()
    assert "налич" not in str(assistant_reply).casefold()


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("Здравствуйте, как прошёл ваш день?", False),
        ("Сколько стоит Studio Headphones?", True),
        ("У вас есть наушники в наличии?", True),
        ("Что нового в магазине?", False),
    ],
)
def test_russian_catalog_intent_requires_explicit_shopping_language(
    transcript: str,
    expected: bool,
) -> None:
    assert ConversationService._has_explicit_catalog_intent(transcript, "ru") is expected


def test_missing_catalog_item_is_only_disclosed_for_a_catalog_request(tmp_path: Path) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    ai_engine = FakeAIEngine(
        product_query="Unlisted Model",
        catalog_requested=True,
        reply="I could not find a match.",
    )
    service = ConversationService(ai_engine, FakeTranscriber(), products)  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    conversation = service.conversation_repository.create("en")
    websocket = FakeWebSocket()

    async def change_state(_state: ConversationState, _message: str) -> None:
        return None

    run(
        service._process_utterance(
            cast(WebSocket, websocket),
            np.ones(8_000, dtype=np.float32),
            "en",
            [],
            change_state,
            conversation.id,
        )
    )
    assistant_reply = next(
        event["text"] for event in websocket.events if event["type"] == "assistant"
    )
    service.close()

    assert "could not find a matching item" in str(assistant_reply)
    assert ai_engine.catalog_facts is not None
    assert ai_engine.catalog_facts in str(assistant_reply)


def test_audio_during_inference_is_queued_and_each_utterance_gets_one_reply(
    tmp_path: Path,
) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    transcriber = FakeTranscriber()
    ai_engine = FakeAIEngine(
        product_query=None,
        catalog_requested=False,
        reply="I understand.",
        plan_delay=0.15,
    )
    service = ConversationService(ai_engine, transcriber, products)  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    service.vad = FakeVAD()  # type: ignore[assignment]
    conversation = service.conversation_repository.create("en")

    utterance = np.concatenate(
        [
            np.full(8 * 512, 12_000, dtype="<i2"),
            np.zeros(20 * 512, dtype="<i2"),
        ]
    ).tobytes()
    silence = np.zeros(512, dtype="<i2").tobytes()
    incoming: list[dict[str, object]] = [
        {"type": "websocket.receive", "bytes": utterance},
        {"type": "websocket.receive", "bytes": utterance},
        *[{"type": "websocket.receive", "bytes": silence} for _ in range(30)],
        {"type": "websocket.receive", "text": '{"type":"audio_finished"}'},
        *[{"type": "websocket.receive", "bytes": silence} for _ in range(30)],
        {"type": "websocket.receive", "text": '{"type":"audio_finished"}'},
        {"type": "websocket.receive", "text": '{"type":"end"}'},
    ]
    websocket = FakeWebSocket(incoming)
    start = ConversationStart(
        type="start",
        token="token",
        language="en",
        conversation_id=conversation.id,
    )

    run(service._receive_audio(websocket, start, [], "LISTENING"))  # type: ignore[arg-type]
    saved = service.conversation_repository.get(conversation.id)
    service.close()

    assert transcriber.calls == 2
    assert len([event for event in websocket.events if event["type"] == "assistant"]) == 2
    assert len(websocket.audio_outputs) == 2
    assert saved is not None
    assert [message.role for message in saved.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_conversation_start_greets_once_and_persists_summary(tmp_path: Path) -> None:
    products = ProductRepository(tmp_path / "products.sqlite3")
    ai_engine = FakeAIEngine(reply="Welcome to the shop.")
    service = ConversationService(ai_engine, FakeTranscriber(), products)  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    service.load_cached_models = lambda _report_progress: None  # type: ignore[method-assign]
    service._available_voice_languages = lambda: {"en"}  # type: ignore[method-assign]
    conversation = service.conversation_repository.create("en")
    websocket = FakeWebSocket(
        [
            {"type": "websocket.receive", "text": '{"type":"audio_finished"}'},
            {"type": "websocket.receive", "text": '{"type":"end"}'},
        ]
    )

    run(
        service.serve(
            websocket,  # type: ignore[arg-type]
            ConversationStart(
                type="start",
                token="token",
                language="en",
                conversation_id=conversation.id,
            ),
        )
    )
    saved = service.conversation_repository.get(conversation.id)
    service.close()

    assert ai_engine.greeting_calls == 1
    assert ai_engine.summary_calls == 1
    assert saved is not None
    assert saved.status == "completed"
    assert saved.summary is not None
    assert saved.summary.customer_name == "Not provided"
    assert [message.role for message in saved.messages] == ["assistant"]
    assert sum(event["type"] == "assistant" for event in websocket.events) == 1


def test_conversation_repository_keeps_distinct_history_and_only_deletes_explicitly(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "history.sqlite3"
    repository = ConversationRepository(database_path)
    first = repository.create("en")
    second = repository.create("ru")
    repository.append_message(first.id, "user", "Hello", "en", 0.9)
    repository.complete(first.id, None, "Summary not generated.")

    reopened = ConversationRepository(database_path)
    saved_first = reopened.get(first.id)
    saved_second = reopened.get(second.id)

    assert first.id != second.id
    assert saved_first is not None and saved_first.messages[0].text == "Hello"
    assert saved_first.summary_error == "Summary not generated."
    assert saved_second is not None and saved_second.messages == []
    reopened.recover_interrupted()
    interrupted = reopened.get(second.id)
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.summary_error is not None
    assert reopened.delete(first.id)
    assert reopened.get(first.id) is None
    assert reopened.get(second.id) is not None


def test_conversation_setup_requires_a_valid_language_and_token() -> None:
    with pytest.raises(ValueError):
        ConversationStart.model_validate(
            {"type": "start", "token": "token", "language": "fr", "conversation_id": "id"}
        )
    with pytest.raises(ValueError):
        ConversationStart.model_validate(
            {"type": "start", "token": "", "language": "en", "conversation_id": "id"}
        )


def test_websocket_authenticates_the_per_session_token_before_model_use(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "history.sqlite3")
    socket = FakeHandshakeWebSocket("not-the-session-token", repository)
    run(stream_conversation(socket))  # type: ignore[arg-type]
    assert socket.close_code == 4401
    assert socket.events == []

    socket = FakeHandshakeWebSocket(settings.session_token.get_secret_value(), repository)
    run(stream_conversation(socket))  # type: ignore[arg-type]
    assert socket.close_code == 4503
    assert socket.events[0]["state"] == "ERROR"
    assert "model" in str(socket.events[1]["message"]).lower()
