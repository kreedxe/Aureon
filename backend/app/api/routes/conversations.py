from __future__ import annotations

import asyncio
import hmac
import logging
from uuid import uuid4

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.schemas.conversations import ConversationReadinessResponse, ConversationStart
from app.services.conversation import ConversationService
from app.services.recordings import RecordingSession

logger = logging.getLogger(__name__)
router = APIRouter()


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


@router.get("/conversations/status", response_model=ConversationReadinessResponse)
def get_conversation_status(request: Request) -> ConversationReadinessResponse:
    return get_conversation_service(request).status()


@router.post(
    "/conversations/install",
    response_model=ConversationReadinessResponse,
    status_code=202,
)
def install_conversation_models(request: Request) -> ConversationReadinessResponse:
    return get_conversation_service(request).start_installation()


@router.websocket("/conversations/stream")
async def stream_conversation(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = str(uuid4())
    try:
        raw_start = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        start = ConversationStart.model_validate(raw_start)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4400, reason="Conversation setup was not received.")
        return
    except ValueError:
        await websocket.close(code=4400, reason="Invalid conversation setup.")
        return

    expected_token = settings.session_token.get_secret_value()
    if not hmac.compare_digest(start.token, expected_token):
        await websocket.close(code=4401, reason="Unauthorized.")
        return

    service = websocket.app.state.conversation_service
    readiness = service.status()
    if not readiness.ready:
        await websocket.send_json(
            {
                "type": "state",
                "state": "ERROR",
                "message": "Prepare the local voice models before starting a conversation.",
            }
        )
        await websocket.send_json(
            {
                "type": "error",
                "message": (
                    "A required local model or an English/Russian offline voice is missing. "
                    "Prepare offline voice models in Aureon before starting."
                ),
            }
        )
        await websocket.close(code=4503, reason="Local models are not ready.")
        return
    if start.language != "auto" and not service.voice_available(start.language):
        await websocket.send_json(
            {
                "type": "error",
                "message": (
                    f"No installed offline speech voice supports {start.language}. "
                    "Choose a language with a local voice or install a compatible system voice."
                ),
            }
        )
        await websocket.close(code=4503, reason="No compatible local speech voice.")
        return

    recording_session: RecordingSession = websocket.app.state.recording_session
    if not recording_session.begin_conversation(session_id):
        await websocket.send_json(
            {
                "type": "error",
                "message": (
                    "A recording transcription, local AI task, or another conversation is "
                    "already running. Wait for it to finish before starting a conversation."
                ),
            }
        )
        await websocket.close(code=4409, reason="Another local AI task is active.")
        return

    try:
        await service.serve(websocket, start)
    except WebSocketDisconnect:
        logger.info("Voice conversation %s disconnected", session_id)
    finally:
        recording_session.end_conversation(session_id)
