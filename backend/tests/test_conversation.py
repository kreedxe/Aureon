from __future__ import annotations

from asyncio import run
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.api.routes.conversations import stream_conversation
from app.core.config import settings
from app.schemas.conversations import ConversationReadinessResponse, ConversationStart
from app.schemas.languages import LanguageCode
from app.schemas.products import ProductInput
from app.services.conversation import ConversationService
from app.services.products import ProductRepository
from app.services.transcription import TranscriptionResult


class FakeAIEngine:
    def __init__(
        self,
        product_query: str | None = "Studio Headphones",
        reply: str = "I can check that for you.",
    ) -> None:
        self.product_query = product_query
        self.reply = reply
        self.catalog_facts: str | None = None

    def extract_product_query(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
    ) -> str | None:
        return self.product_query

    def generate_conversation_reply(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
        *,
        greeting: bool = False,
        catalog_facts: str | None = None,
    ) -> str:
        self.catalog_facts = catalog_facts
        return self.reply


class FakeTranscriber:
    def transcribe_samples(
        self,
        audio: np.ndarray,
        language: LanguageCode | None,
        report_progress: Callable[[float, str], None],
    ) -> TranscriptionResult:
        return TranscriptionResult(
            text="How much do the Studio Headphones cost?",
            language=language or "en",
            language_probability=0.98,
            model="small",
        )


class FakeSynthesizer:
    def synthesize(self, text: str, language: LanguageCode) -> bytes:
        return b"local-wav"


class FakeWebSocket:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.audio: bytes | None = None

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)

    async def send_bytes(self, audio: bytes) -> None:
        self.audio = audio


class FakeHandshakeWebSocket:
    def __init__(self, token: str) -> None:
        self.payload = {"type": "start", "token": token, "language": "en"}
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
                    )
                )
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
    repository = ProductRepository(tmp_path / "products.sqlite3")
    repository.create_product(
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
    ai_engine = FakeAIEngine(product_query, llm_reply)
    service = ConversationService(ai_engine, FakeTranscriber(), repository)  # type: ignore[arg-type]
    service.synthesizer = FakeSynthesizer()
    websocket = FakeWebSocket()
    states: list[str] = []

    async def change_state(state: str, _message: str) -> None:
        states.append(state)

    run(
        service._process_utterance(
            websocket,  # type: ignore[arg-type]
            np.ones(8_000, dtype=np.float32),
            language,
            [],
            change_state,  # type: ignore[arg-type]
        )
    )
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


def test_conversation_setup_requires_a_valid_language_and_token() -> None:
    with pytest.raises(ValueError):
        ConversationStart.model_validate({"type": "start", "token": "token", "language": "fr"})
    with pytest.raises(ValueError):
        ConversationStart.model_validate({"type": "start", "token": "", "language": "en"})


def test_websocket_authenticates_the_per_session_token_before_model_use() -> None:
    socket = FakeHandshakeWebSocket("not-the-session-token")
    run(stream_conversation(socket))  # type: ignore[arg-type]
    assert socket.close_code == 4401
    assert socket.events == []

    socket = FakeHandshakeWebSocket(settings.session_token.get_secret_value())
    run(stream_conversation(socket))  # type: ignore[arg-type]
    assert socket.close_code == 4503
    assert socket.events[0]["state"] == "ERROR"
    assert "model" in str(socket.events[1]["message"]).lower()
