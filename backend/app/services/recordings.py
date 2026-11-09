import atexit
import logging
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast
from uuid import uuid4

from app.schemas.ai import AIAction, AIJobStatus, AIResult
from app.schemas.languages import LanguageCode
from app.schemas.recordings import TranscriptionLanguage, TranscriptionStatus
from app.services.ai_engine import LocalAIEngine
from app.services.transcription import LocalWhisperTranscriber, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass
class Recording:
    id: str
    name: str
    created_at: datetime
    duration: float
    media_type: str
    audio_path: Path
    transcription: TranscriptionResult | None = None
    transcription_status: TranscriptionStatus = "not_transcribed"
    ai_results: dict[str, AIResult] | None = None


@dataclass
class TranscriptionJob:
    id: str
    recording_id: str
    language: TranscriptionLanguage
    status: TranscriptionStatus = "queued"
    progress: float = 0
    message: str = "Waiting to transcribe…"
    error: str | None = None
    transcription: TranscriptionResult | None = None


@dataclass
class AIJob:
    id: str
    recording_id: str
    operation: AIAction
    status: AIJobStatus = "queued"
    progress: float = 0
    message: str = "Waiting for the local AI engine…"
    error: str | None = None
    result: AIResult | None = None


class RecordingSession:
    max_recording_bytes = 512 * 1024 * 1024

    def __init__(self) -> None:
        self._temp_dir = tempfile.mkdtemp(prefix="aureon-session-")
        self._directory = Path(self._temp_dir)
        self._recordings: dict[str, Recording] = {}
        self._jobs: dict[str, TranscriptionJob] = {}
        self._active_job_id: str | None = None
        self._ai_jobs: dict[str, AIJob] = {}
        self._active_ai_job_id: str | None = None
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aureon-transcribe")
        self._ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aureon-ai")
        self.transcriber = LocalWhisperTranscriber()
        self.ai_engine = LocalAIEngine()
        self._closed = False
        atexit.register(self.close)

    def add_recording(
        self,
        name: str,
        duration: float,
        media_type: str,
        extension: str,
        audio_path: Path,
    ) -> Recording:
        recording_id = str(uuid4())
        destination = self._directory / f"{recording_id}{extension}"
        shutil.move(str(audio_path), destination)
        recording = Recording(
            id=recording_id,
            name=name,
            created_at=datetime.now(UTC),
            duration=duration,
            media_type=media_type,
            audio_path=destination,
        )
        with self._lock:
            self._recordings[recording_id] = recording
        return recording

    def create_staging_path(self, extension: str) -> Path:
        descriptor, path = tempfile.mkstemp(prefix="upload-", suffix=extension, dir=self._directory)
        os.close(descriptor)
        return Path(path)

    def list_recordings(self) -> list[Recording]:
        with self._lock:
            return sorted(self._recordings.values(), key=lambda item: item.created_at, reverse=True)

    def get_recording(self, recording_id: str) -> Recording | None:
        with self._lock:
            return self._recordings.get(recording_id)

    def rename_recording(self, recording_id: str, name: str) -> Recording | None:
        with self._lock:
            recording = self._recordings.get(recording_id)
            if recording is not None:
                recording.name = name
            return recording

    def delete_recording(self, recording_id: str) -> bool:
        with self._lock:
            if self._active_job_id is not None:
                active_job = self._jobs.get(self._active_job_id)
                if active_job is not None and active_job.recording_id == recording_id:
                    return False
            recording = self._recordings.pop(recording_id, None)
            if recording is None:
                return True
            recording.audio_path.unlink(missing_ok=True)
            return True

    def start_transcription(
        self,
        recording_id: str,
        language: TranscriptionLanguage,
    ) -> TranscriptionJob:
        with self._lock:
            recording = self._recordings.get(recording_id)
            if recording is None:
                raise KeyError(recording_id)
            if self._active_job_id is not None:
                active_job = self._jobs.get(self._active_job_id)
                if active_job is not None and active_job.status in {
                    "queued",
                    "loading_model",
                    "transcribing",
                }:
                    raise RuntimeError("Another recording is currently being transcribed.")
            if self._active_ai_job_id is not None:
                active_ai_job = self._ai_jobs.get(self._active_ai_job_id)
                if active_ai_job is not None and active_ai_job.status in {
                    "queued",
                    "downloading",
                    "loading_model",
                    "processing",
                }:
                    raise RuntimeError("Another local AI task is currently running.")

            job = TranscriptionJob(id=str(uuid4()), recording_id=recording_id, language=language)
            self._jobs[job.id] = job
            self._active_job_id = job.id
            recording.transcription_status = "queued"
            self._executor.submit(
                self._run_transcription,
                job.id,
                recording.audio_path,
                recording.duration,
            )
            return job

    def get_job(self, job_id: str) -> TranscriptionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start_ai_job(
        self,
        recording_id: str,
        operation: AIAction,
        target_language: LanguageCode | None,
    ) -> AIJob:
        with self._lock:
            recording = self._recordings.get(recording_id)
            if recording is None:
                raise KeyError(recording_id)
            if recording.transcription is None:
                raise ValueError("Transcribe this recording before using AI text tools.")
            if self._active_job_id is not None:
                raise RuntimeError("Wait for speech transcription to finish before using AI.")
            if self._active_ai_job_id is not None:
                active_job = self._ai_jobs.get(self._active_ai_job_id)
                if active_job is not None and active_job.status in {
                    "queued",
                    "downloading",
                    "loading_model",
                    "processing",
                }:
                    raise RuntimeError("Another local AI task is currently running.")

            job = AIJob(
                id=str(uuid4()),
                recording_id=recording_id,
                operation=operation,
            )
            self._ai_jobs[job.id] = job
            self._active_ai_job_id = job.id
            self._ai_executor.submit(
                self._run_ai_job,
                job.id,
                recording.transcription.text,
                recording.transcription.language,
                target_language,
            )
            return job

    def get_ai_job(self, job_id: str) -> AIJob | None:
        with self._lock:
            return self._ai_jobs.get(job_id)

    def _run_transcription(self, job_id: str, audio_path: Path, duration: float) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "loading_model"
            job.message = "Starting local transcription…"

        def update(progress: float, message: str) -> None:
            with self._lock:
                active_job = self._jobs.get(job_id)
                if active_job is not None:
                    active_job.status = "loading_model" if progress < 40 else "transcribing"
                    active_job.progress = max(active_job.progress, min(99, progress))
                    active_job.message = message
                    recording = self._recordings.get(active_job.recording_id)
                    if recording is not None:
                        recording.transcription_status = active_job.status

        try:
            result = self.transcriber.transcribe(
                audio_path,
                self._jobs[job_id].language,
                duration,
                update,
            )
        except Exception as error:
            logger.exception("Local transcription failed for job %s", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.message = "Transcription failed"
                job.error = str(error) or "The local transcription failed unexpectedly."
                recording = self._recordings.get(job.recording_id)
                if recording is not None:
                    recording.transcription_status = "failed"
        else:
            with self._lock:
                job = self._jobs[job_id]
                job.status = "completed"
                job.progress = 100
                job.message = "Transcription complete"
                job.transcription = result
                recording = self._recordings.get(job.recording_id)
                if recording is not None:
                    recording.transcription = result
                    recording.transcription_status = "completed"
                    recording.ai_results = {}
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _run_ai_job(
        self,
        job_id: str,
        transcript: str,
        source_language: str,
        target_language: str | None,
    ) -> None:
        with self._lock:
            job = self._ai_jobs[job_id]
            operation = job.operation

        def update(progress: float, message: str) -> None:
            with self._lock:
                active_job = self._ai_jobs.get(job_id)
                if active_job is None:
                    return
                active_job.progress = max(active_job.progress, min(99, progress))
                active_job.message = message
                if message.startswith("Downloading"):
                    active_job.status = "downloading"
                elif progress < 62:
                    active_job.status = "loading_model"
                else:
                    active_job.status = "processing"

        try:
            if source_language not in {"uz", "ru", "en"}:
                raise ValueError(
                    "AI text tools support Uzbek, Russian, and English transcripts only."
                )
            result = self.ai_engine.process(
                operation=operation,
                transcript=transcript,
                source_language=cast(LanguageCode, source_language),
                target_language=target_language,
                report_progress=update,
            )
        except Exception as error:
            logger.exception("Local AI operation %s failed for job %s", operation, job_id)
            with self._lock:
                job = self._ai_jobs[job_id]
                job.status = "failed"
                job.message = "Local AI task failed"
                job.error = str(error) or "The local AI task failed unexpectedly."
        else:
            with self._lock:
                job = self._ai_jobs[job_id]
                job.status = "completed"
                job.progress = 100
                job.message = "AI result ready"
                job.result = result
                recording = self._recordings.get(job.recording_id)
                if recording is not None:
                    if recording.ai_results is None:
                        recording.ai_results = {}
                    recording.ai_results[operation] = result
        finally:
            with self._lock:
                if self._active_ai_job_id == job_id:
                    self._active_ai_job_id = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._ai_executor.shutdown(wait=True, cancel_futures=True)
        self.ai_engine.close()
        shutil.rmtree(self._directory, ignore_errors=False)
