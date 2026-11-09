import time
from pathlib import Path
from threading import Event
from typing import Any

from httpx import Response
from pytest import MonkeyPatch
from test_api import AUTH_HEADERS, request

from app.core.config import settings
from app.main import app
from app.schemas.ai import SummaryResult
from app.services.recordings import RecordingSession
from app.services.transcription import TranscriptionResult


class FakeTranscriber:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def transcribe(self, audio_path, language, duration, report_progress) -> TranscriptionResult:
        self.started.set()
        report_progress(20, "Downloading the local Whisper model (50 / 100 MB).")
        self.release.wait(timeout=2)
        report_progress(40, "Transcribing audio locally…")
        return TranscriptionResult(
            text="Salom, dunyo!",
            language=language or "uz",
            language_probability=0.98,
            model="small",
        )


def create_recording(
    content: bytes = b"audio bytes",
    filename: str = "voice.webm",
    content_type: str = "audio/webm;codecs=opus",
) -> Response:
    return request(
        "POST",
        "/api/v1/recordings",
        headers=AUTH_HEADERS,
        data={"name": "New recording", "duration": "3.5"},
        files={"audio": (filename, content, content_type)},
    )


def test_recording_lifecycle_and_transcription(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "session_token",
        type(settings.session_token)("test-session-token"),
    )
    session = app.state.recording_session
    transcriber = FakeTranscriber()
    monkeypatch.setattr(session, "transcriber", transcriber)

    created = create_recording()
    assert created.status_code == 201
    recording = created.json()
    recording_id = recording["id"]
    assert recording["name"] == "New recording"
    assert recording["duration"] == 3.5
    assert recording["transcription_status"] == "not_transcribed"

    renamed = request(
        "PATCH",
        f"/api/v1/recordings/{recording_id}",
        headers=AUTH_HEADERS,
        json={"name": "Uzbek greeting"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Uzbek greeting"

    started = request(
        "POST",
        f"/api/v1/recordings/{recording_id}/transcriptions",
        headers=AUTH_HEADERS,
        json={"language": "uz"},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert transcriber.started.wait(timeout=1)
    loading = request("GET", f"/api/v1/transcriptions/{job_id}", headers=AUTH_HEADERS).json()
    assert loading["status"] == "loading_model"
    assert loading["progress"] == 20
    assert "Downloading" in loading["message"]

    second = create_recording()
    assert second.status_code == 201
    assert (
        request(
            "DELETE",
            f"/api/v1/recordings/{recording_id}",
            headers=AUTH_HEADERS,
        ).status_code
        == 409
    )
    conflict = request(
        "POST",
        f"/api/v1/recordings/{second.json()['id']}/transcriptions",
        headers=AUTH_HEADERS,
        json={"language": None},
    )
    assert conflict.status_code == 409

    transcriber.release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = request("GET", f"/api/v1/transcriptions/{job_id}", headers=AUTH_HEADERS).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)
    assert job["status"] == "completed"
    assert job["transcription"] == {
        "text": "Salom, dunyo!",
        "language": "uz",
        "language_probability": 0.98,
        "model": "small",
    }

    listed = request("GET", "/api/v1/recordings", headers=AUTH_HEADERS).json()
    updated = next(item for item in listed["recordings"] if item["id"] == recording_id)
    assert updated["transcription"]["text"] == "Salom, dunyo!"
    assert updated["transcription_status"] == "completed"

    deleted = request("DELETE", f"/api/v1/recordings/{recording_id}", headers=AUTH_HEADERS)
    assert deleted.status_code == 204
    assert request("GET", "/api/v1/recordings", headers=AUTH_HEADERS).json()["recordings"]
    assert (
        request(
            "DELETE",
            f"/api/v1/recordings/{second.json()['id']}",
            headers=AUTH_HEADERS,
        ).status_code
        == 204
    )


def test_recording_upload_rejects_empty_and_unsupported_audio(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "session_token",
        type(settings.session_token)("test-session-token"),
    )
    assert create_recording(content=b"").status_code == 422
    assert create_recording(content_type="application/octet-stream").status_code == 415


def test_recording_api_requires_session_token() -> None:
    response = request("GET", "/api/v1/recordings")
    assert response.status_code == 401


def test_session_close_removes_temporary_recording_files() -> None:
    session = RecordingSession()
    staging_path: Path = session.create_staging_path(".webm")
    staging_path.write_bytes(b"temporary audio")

    session.close()

    assert not staging_path.parent.exists()


def test_ai_job_stores_generated_result_without_changing_transcript(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "session_token",
        type(settings.session_token)("test-session-token"),
    )
    session = app.state.recording_session
    created = create_recording()
    recording_id = created.json()["id"]
    recording = session.get_recording(recording_id)
    assert recording is not None
    original = TranscriptionResult(
        text="Original transcript.",
        language="en",
        language_probability=0.99,
        model="small",
    )
    recording.transcription = original

    class FakeAIEngine:
        def process(self, **kwargs: Any) -> SummaryResult:
            kwargs["report_progress"](62, "Processing transcript locally…")
            return SummaryResult(
                language=kwargs["source_language"],
                summary="A separate summary.",
                model="Qwen3 1.7B Instruct Q4_K_M",
            )

        def status(self) -> dict[str, Any]:
            return session.ai_engine.status()

    monkeypatch.setattr(session, "ai_engine", FakeAIEngine())
    response = request(
        "POST",
        f"/api/v1/recordings/{recording_id}/ai",
        headers=AUTH_HEADERS,
        json={"operation": "summary", "target_language": None},
    )
    assert response.status_code == 202
    job_id = response.json()["id"]

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = request("GET", f"/api/v1/ai/jobs/{job_id}", headers=AUTH_HEADERS).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)

    assert job["status"] == "completed"
    assert job["result"]["summary"] == "A separate summary."
    updated = request("GET", "/api/v1/recordings", headers=AUTH_HEADERS).json()
    result_recording = next(item for item in updated["recordings"] if item["id"] == recording_id)
    assert result_recording["transcription"]["text"] == "Original transcript."
    assert result_recording["ai_results"]["summary"]["summary"] == "A separate summary."

    class UpdatedTranscriber:
        def transcribe(self, *args, **kwargs) -> TranscriptionResult:
            return TranscriptionResult(
                text="Updated transcript.",
                language="en",
                language_probability=0.98,
                model="small",
            )

    monkeypatch.setattr(session, "transcriber", UpdatedTranscriber())
    started = request(
        "POST",
        f"/api/v1/recordings/{recording_id}/transcriptions",
        headers=AUTH_HEADERS,
        json={"language": "en"},
    )
    transcription_id = started.json()["job_id"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        transcription = request(
            "GET",
            f"/api/v1/transcriptions/{transcription_id}",
            headers=AUTH_HEADERS,
        ).json()
        if transcription["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)

    assert transcription["status"] == "completed"
    refreshed = request("GET", "/api/v1/recordings", headers=AUTH_HEADERS).json()
    result_recording = next(item for item in refreshed["recordings"] if item["id"] == recording_id)
    assert result_recording["transcription"]["text"] == "Updated transcript."
    assert result_recording["ai_results"] == {}
