from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from app.schemas.conversations import (
    ConversationControl,
    ConversationLanguage,
    ConversationReadinessResponse,
    ConversationStart,
    ConversationState,
)
from app.schemas.languages import LanguageCode
from app.schemas.products import ProductResponse
from app.services.ai_engine import LocalAIEngine
from app.services.products import ProductRepository
from app.services.speech_synthesis import LocalSpeechSynthesizer
from app.services.transcription import LocalWhisperTranscriber
from app.services.voice_activity import SileroVoiceActivityDetector

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]


class ConversationService:
    silence_frames = 20
    minimum_speech_frames = 8
    maximum_utterance_frames = 2_800
    speech_threshold = 0.55
    supported_languages = {"uz", "ru", "en"}

    def __init__(
        self,
        ai_engine: LocalAIEngine,
        transcriber: LocalWhisperTranscriber,
        product_repository: ProductRepository,
    ) -> None:
        self.ai_engine = ai_engine
        self.transcriber = transcriber
        self.product_repository = product_repository
        self.vad = SileroVoiceActivityDetector()
        self.synthesizer = LocalSpeechSynthesizer()
        self._status_lock = threading.Lock()
        self._install_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="aureon-voice-setup",
        )
        self._install_status: dict[str, Any] = {
            "status": "idle",
            "progress": 0.0,
            "message": "Offline voice models have not been prepared.",
            "error": None,
        }

    def status(self) -> ConversationReadinessResponse:
        voices = self.synthesizer.voices()
        supported_voices = [
            voice for voice in voices if self._voice_language(voice) in {"en", "ru", "uz"}
        ]
        english_available = any(self._voice_language(voice) == "en" for voice in voices)
        russian_available = any(self._voice_language(voice) == "ru" for voice in voices)
        llm_ready = bool(self.ai_engine.status()["downloaded"])
        whisper_ready = self.transcriber.cached
        vad_ready = self.vad.cached
        with self._status_lock:
            install = self._install_status.copy()
        return ConversationReadinessResponse(
            ready=(
                vad_ready
                and whisper_ready
                and llm_ready
                and english_available
                and russian_available
            ),
            vad_ready=vad_ready,
            whisper_ready=whisper_ready,
            llm_ready=llm_ready,
            voices=supported_voices,
            install_status=install["status"],
            install_progress=install["progress"],
            install_message=install["message"],
            install_error=install["error"],
        )

    def start_installation(self) -> ConversationReadinessResponse:
        with self._status_lock:
            already_running = self._install_status["status"] == "running"
            if not already_running:
                self._install_status = {
                    "status": "running",
                    "progress": 0.0,
                    "message": "Preparing the local voice models…",
                    "error": None,
                }
        if already_running:
            return self.status()
        self._install_executor.submit(self._install_models)
        return self.status()

    def load_cached_models(self, report_progress: ProgressCallback) -> None:
        self.vad.load()
        self.transcriber.load_cached_model(
            lambda progress, message: report_progress(15 + progress * 0.2, message)
        )
        self.ai_engine.load_cached_model(
            lambda progress, message: report_progress(40 + progress * 0.5, message)
        )

    def close(self) -> None:
        self._install_executor.shutdown(wait=True, cancel_futures=True)

    async def serve(
        self,
        websocket: WebSocket,
        start: ConversationStart,
    ) -> None:
        session_id = str(uuid4())
        state: ConversationState = "INITIALIZING"
        history: list[dict[str, str]] = []
        language = start.language
        voice_language: LanguageCode = "en" if language == "auto" else language
        await self._send_state(websocket, state, "Loading cached local speech models…")
        try:
            await asyncio.to_thread(
                self.load_cached_models,
                lambda _progress, _message: None,
            )
            if voice_language not in self._available_voice_languages():
                raise RuntimeError(
                    f"No installed offline speech voice supports {voice_language}. "
                    "Install a compatible local voice before starting this conversation."
                )
            state = "GREETING"
            await self._send_state(websocket, state, "Generating a local greeting…")
            greeting = await asyncio.to_thread(
                self.ai_engine.generate_conversation_reply,
                "",
                voice_language,
                [],
                greeting=True,
            )
            greeting_audio = await asyncio.to_thread(
                self.synthesizer.synthesize,
                greeting,
                voice_language,
            )
            history.append({"role": "assistant", "content": greeting})
            state = "SPEAKING"
            await self._send_json(
                websocket,
                {"type": "assistant", "text": greeting, "language": voice_language},
            )
            await self._send_state(websocket, state, "Speaking the greeting…")
            await websocket.send_bytes(greeting_audio)

            state = "SPEAKING"
            await self._receive_audio(websocket, start, history, state)
        except WebSocketDisconnect:
            logger.info("Voice conversation %s disconnected", session_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("Voice conversation %s failed", session_id)
            await self._send_state(websocket, "ERROR", "The local conversation could not continue.")
            await self._send_json(
                websocket,
                {"type": "error", "message": str(error) or "The local voice pipeline failed."},
            )
        finally:
            try:
                await self._send_state(websocket, "ENDED", "Conversation ended.")
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def _receive_audio(
        self,
        websocket: WebSocket,
        start: ConversationStart,
        history: list[dict[str, str]],
        initial_state: ConversationState,
    ) -> None:
        state = initial_state
        response_task: asyncio.Task[None] | None = None
        remainder = bytearray()
        recent_frames: list[np.ndarray] = []
        utterance_frames: list[np.ndarray] = []
        speech_started = False
        silent_frame_count = 0
        voiced_frame_count = 0
        last_meter = 0.0
        self.vad.reset()
        await self._send_state(websocket, "LISTENING", "Listening automatically…")

        async def change_state(new_state: ConversationState, message: str) -> None:
            nonlocal state
            state = new_state
            await self._send_state(websocket, new_state, message)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if message.get("text") is not None:
                    control = self._parse_control(message["text"])
                    if control is None:
                        await self._send_json(
                            websocket,
                            {
                                "type": "error",
                                "message": "Received an unsupported conversation command.",
                            },
                        )
                        continue
                    if control.type == "end":
                        return
                    if control.type == "audio_finished" and state == "SPEAKING":
                        await change_state("LISTENING", "Listening automatically…")
                    continue

                audio_bytes = message.get("bytes")
                if not isinstance(audio_bytes, bytes):
                    continue
                remainder.extend(audio_bytes)
                while len(remainder) >= self.vad.frame_samples * 2:
                    frame_bytes = bytes(remainder[: self.vad.frame_samples * 2])
                    del remainder[: self.vad.frame_samples * 2]
                    frame = np.frombuffer(frame_bytes, dtype="<i2").astype(np.float32) / 32768.0
                    probability = await asyncio.to_thread(self.vad.probability, frame)
                    now = asyncio.get_running_loop().time()
                    if now - last_meter >= 0.1:
                        rms = float(np.sqrt(np.mean(np.square(frame))))
                        await self._send_json(
                            websocket,
                            {"type": "meter", "level": min(1.0, rms * 4.0)},
                        )
                        last_meter = now

                    is_voice = probability >= self.speech_threshold
                    if not speech_started:
                        recent_frames.append(frame)
                        if len(recent_frames) > 10:
                            recent_frames.pop(0)
                        if not is_voice:
                            continue
                        speech_started = True
                        utterance_frames = [*recent_frames]
                        voiced_frame_count = 1
                        silent_frame_count = 0
                        if state in {"SPEAKING", "THINKING", "TRANSCRIBING", "GREETING"}:
                            await change_state(
                                "INTERRUPTED",
                                "Customer speech detected; stopping assistant playback.",
                            )
                            if response_task is not None and not response_task.done():
                                response_task.cancel()
                        continue

                    utterance_frames.append(frame)
                    if is_voice:
                        voiced_frame_count += 1
                        silent_frame_count = 0
                    else:
                        silent_frame_count += 1
                    should_finish = (
                        silent_frame_count >= self.silence_frames
                        or len(utterance_frames) >= self.maximum_utterance_frames
                    )
                    if not should_finish:
                        continue

                    speech_started = False
                    recent_frames = []
                    audio = np.concatenate(utterance_frames)
                    utterance_frames = []
                    if voiced_frame_count < self.minimum_speech_frames:
                        continue
                    response_task = asyncio.create_task(
                        self._process_utterance(
                            websocket,
                            audio,
                            start.language,
                            history,
                            change_state,
                        )
                    )
        finally:
            if response_task is not None and not response_task.done():
                response_task.cancel()
                try:
                    await response_task
                except asyncio.CancelledError:
                    pass

    async def _process_utterance(
        self,
        websocket: WebSocket,
        audio: np.ndarray,
        requested_language: ConversationLanguage,
        history: list[dict[str, str]],
        change_state: Callable[[ConversationState, str], Awaitable[None]],
    ) -> None:
        try:
            await change_state("TRANSCRIBING", "Transcribing speech locally…")
            asr_language = None if requested_language == "auto" else requested_language
            result = await asyncio.to_thread(
                self.transcriber.transcribe_samples,
                audio,
                asr_language,
                lambda _progress, _message: None,
            )
            if result.language not in self.supported_languages:
                raise RuntimeError(
                    f"Whisper detected {result.language}, but Aureon conversations support only "
                    "Uzbek, Russian, and English."
                )
            language = result.language if requested_language == "auto" else requested_language
            await self._send_json(
                websocket,
                {
                    "type": "transcript",
                    "text": result.text,
                    "language": language,
                    "language_probability": result.language_probability,
                },
            )
            await change_state("THINKING", "Thinking with the local assistant…")
            product_query = await asyncio.to_thread(
                self.ai_engine.extract_product_query,
                result.text,
                language,
                history,
            )
            catalog_requested = bool(product_query) or self._has_catalog_intent(
                result.text, language
            )
            products: list[ProductResponse] = []
            if product_query:
                products, _categories = self.product_repository.list_products(
                    query=product_query,
                    sort="name",
                )
                if not products:
                    products = self._catalog_matches(f"{product_query} {result.text}")
            elif catalog_requested:
                products = self._catalog_matches(result.text)
            if catalog_requested:
                products = products[:5]
            catalog_facts = self._catalog_facts(products, language) if catalog_requested else None
            reply = await asyncio.to_thread(
                self.ai_engine.generate_conversation_reply,
                result.text,
                language,
                history,
                catalog_facts=catalog_facts,
            )
            if catalog_facts and catalog_facts.casefold() not in reply.casefold():
                reply = f"{reply} {catalog_facts}"
            audio = await asyncio.to_thread(self.synthesizer.synthesize, reply, language)
            history.extend(
                [
                    {"role": "user", "content": result.text},
                    {"role": "assistant", "content": reply},
                ]
            )
            del history[:-16]
            await self._send_json(
                websocket,
                {"type": "assistant", "text": reply, "language": language},
            )
            await change_state("SPEAKING", "Speaking the local response…")
            await websocket.send_bytes(audio)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("Local conversation turn failed")
            await self._send_json(
                websocket,
                {"type": "error", "message": str(error) or "The local voice pipeline failed."},
            )
            await change_state("ERROR", "The local conversation could not continue.")

    def _install_models(self) -> None:
        try:
            self._report_install(5, "Downloading or verifying the local Whisper model…")
            self.transcriber.prepare_model(
                lambda progress, message: self._report_install(
                    5 + progress * 0.25,
                    message,
                )
            )
            self._report_install(35, "Downloading or verifying the local Qwen model…")
            self.ai_engine.prepare_model(
                lambda progress, message: self._report_install(
                    35 + progress * 0.45,
                    message,
                )
            )
            self._report_install(85, "Preparing the local Silero voice detector…")
            self.vad.download_and_load(
                lambda progress, message: self._report_install(
                    85 + (progress * 0.1),
                    message,
                )
            )
            readiness = self.status()
            missing_voices = [
                language
                for language in ("English", "Russian")
                if language.lower()[:2]
                not in {self._voice_language(voice) for voice in readiness.voices}
            ]
            if missing_voices:
                raise RuntimeError(
                    f"No installed local speech voice was found for {', '.join(missing_voices)}."
                )
            if not readiness.ready:
                raise RuntimeError(
                    "One or more offline voice models are not ready. Check the model cache "
                    "and installed local speech voices."
                )
        except Exception as error:
            logger.exception("Could not prepare offline voice models")
            with self._status_lock:
                self._install_status.update(
                    status="failed",
                    message="Offline model preparation failed.",
                    error=str(error) or "The model preparation failed unexpectedly.",
                )
            return
        with self._status_lock:
            self._install_status.update(
                status="completed",
                progress=100.0,
                message="Local models are ready. Conversations work without internet.",
                error=None,
            )

    def _report_install(self, progress: float, message: str) -> None:
        with self._status_lock:
            self._install_status.update(
                progress=max(0.0, min(99.0, progress)),
                message=message,
            )

    def _available_voice_languages(self) -> set[str]:
        return {self._voice_language(voice) for voice in self.synthesizer.voices()}

    def voice_available(self, language: str) -> bool:
        return language in self._available_voice_languages()

    @staticmethod
    def _voice_language(voice: dict[str, str]) -> str:
        return voice["language"].split("-", maxsplit=1)[0].split("_", maxsplit=1)[0].lower()

    @staticmethod
    def _catalog_facts(products: list[ProductResponse], language: LanguageCode) -> str:
        if not products:
            return {
                "en": (
                    "I could not find a matching item in the local catalog, so I cannot confirm "
                    "its price or stock. Could you share the exact product name?"
                ),
                "ru": (
                    "В локальном каталоге не нашлось подходящего товара, поэтому я не могу "
                    "подтвердить цену или наличие. Подскажите точное название?"
                ),
                "uz": (
                    "Mahalliy katalogdan mos mahsulot topilmadi, shuning uchun uning narxi yoki "
                    "mavjudligini tasdiqlay olmayman. Aniq nomini ayta olasizmi?"
                ),
            }[language]
        facts: list[str] = []
        for product in products:
            price = f"{product.price} {product.currency}"
            if product.availability == "discontinued":
                availability = {
                    "en": "discontinued",
                    "ru": "снят с продажи",
                    "uz": "sotuvdan olingan",
                }[language]
            elif product.stock_quantity == 0:
                availability = {
                    "en": "out of stock (0 available)",
                    "ru": "нет в наличии (0 шт.)",
                    "uz": "mavjud emas (0 dona)",
                }[language]
            else:
                availability = {
                    "en": f"{product.stock_quantity} in stock",
                    "ru": f"в наличии {product.stock_quantity} шт.",
                    "uz": f"omborda {product.stock_quantity} dona",
                }[language]
            facts.append(f"{product.name}: {price}; {availability}.")
        return " ".join(facts)

    def _catalog_matches(self, search_text: str) -> list[ProductResponse]:
        normalized_search_text = self._normalize_search_text(search_text)
        products, _categories = self.product_repository.list_products(sort="name")
        query_terms = set(normalized_search_text.split()) - {
            "a",
            "and",
            "are",
            "available",
            "cost",
            "do",
            "does",
            "for",
            "how",
            "in",
            "is",
            "much",
            "price",
            "stock",
            "the",
            "they",
            "what",
            "with",
            "есть",
            "ли",
            "наличии",
            "сколько",
            "стоит",
            "цена",
            "bormi",
            "mavjud",
            "narx",
            "omborda",
            "qancha",
        }
        matches: list[ProductResponse] = []
        for product in products:
            product_terms = set(self._normalize_search_text(product.name).split())
            if product_terms and len(product_terms & query_terms) >= min(2, len(product_terms)):
                matches.append(product)
        return matches

    @staticmethod
    def _has_catalog_intent(transcript: str, language: LanguageCode) -> bool:
        normalized = transcript.casefold()
        keywords = {
            "en": (
                "price",
                "cost",
                "how much",
                "stock",
                "available",
                "in stock",
                "do you have",
                "product",
                "catalog",
            ),
            "ru": (
                "цен",
                "сто",
                "сколько",
                "налич",
                "есть ли",
                "товар",
                "каталог",
            ),
            "uz": (
                "narx",
                "qancha",
                "ombor",
                "mavjud",
                "bormi",
                "mahsulot",
                "tovar",
            ),
        }[language]
        return any(keyword in normalized for keyword in keywords)

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        return re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE).strip()

    @staticmethod
    async def _send_state(
        websocket: WebSocket,
        state: ConversationState,
        message: str,
    ) -> None:
        await ConversationService._send_json(
            websocket,
            {"type": "state", "state": state, "message": message},
        )

    @staticmethod
    async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    @staticmethod
    def _parse_control(raw: str) -> ConversationControl | None:
        try:
            return ConversationControl.model_validate_json(raw)
        except ValueError:
            return None
