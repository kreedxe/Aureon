from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from app.schemas.ai import AIJobResponse, AIModelStatusResponse, AIRequest
from app.schemas.recordings import (
    RecordingListResponse,
    RecordingResponse,
    RenameRecordingRequest,
    StartTranscriptionRequest,
    StartTranscriptionResponse,
    TranscriptionJobResponse,
    TranscriptionResponse,
)
from app.services.recordings import AIJob, Recording, RecordingSession, TranscriptionJob
from app.services.transcription import TranscriptionResult

router = APIRouter()

SUPPORTED_MEDIA_TYPES = {
    "audio/webm": (".webm", "audio/webm"),
    "audio/ogg": (".ogg", "audio/ogg"),
    "audio/mp4": (".m4a", "audio/mp4"),
    "audio/mpeg": (".mp3", "audio/mpeg"),
    "audio/wav": (".wav", "audio/wav"),
    "audio/x-wav": (".wav", "audio/wav"),
    "audio/flac": (".flac", "audio/flac"),
}
MAX_NAME_LENGTH = 120


def get_session(request: Request) -> RecordingSession:
    return request.app.state.recording_session


def transcription_response(result: TranscriptionResult | None) -> TranscriptionResponse | None:
    if result is None:
        return None
    return TranscriptionResponse(
        text=result.text,
        language=result.language,
        language_probability=result.language_probability,
        model=result.model,
    )


def recording_response(recording: Recording) -> RecordingResponse:
    return RecordingResponse(
        id=recording.id,
        name=recording.name,
        created_at=recording.created_at,
        duration=recording.duration,
        media_type=recording.media_type,
        transcription=transcription_response(recording.transcription),
        transcription_status=recording.transcription_status,
        ai_results=recording.ai_results or {},
    )


def job_response(job: TranscriptionJob) -> TranscriptionJobResponse:
    return TranscriptionJobResponse(
        id=job.id,
        recording_id=job.recording_id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
        transcription=transcription_response(job.transcription),
    )


def ai_job_response(job: AIJob) -> AIJobResponse:
    return AIJobResponse(
        id=job.id,
        recording_id=job.recording_id,
        operation=job.operation,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
        result=job.result,
    )


@router.get("/recordings", response_model=RecordingListResponse)
def list_recordings(request: Request) -> RecordingListResponse:
    session = get_session(request)
    return RecordingListResponse(
        recordings=[recording_response(recording) for recording in session.list_recordings()]
    )


@router.get("/ai/status", response_model=AIModelStatusResponse)
def get_ai_status(request: Request) -> AIModelStatusResponse:
    return AIModelStatusResponse(**get_session(request).ai_engine.status())


@router.post(
    "/recordings/{recording_id}/ai",
    response_model=AIJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ai_job(
    recording_id: str,
    payload: AIRequest,
    request: Request,
) -> AIJobResponse:
    session = get_session(request)
    recording = session.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.transcription is None:
        raise HTTPException(status_code=409, detail="Transcribe this recording before using AI.")
    if recording.transcription.language not in {"uz", "ru", "en"}:
        raise HTTPException(
            status_code=422,
            detail="AI text tools support Uzbek, Russian, and English transcripts only.",
        )
    if (
        payload.operation == "translation"
        and payload.target_language == recording.transcription.language
    ):
        raise HTTPException(
            status_code=422,
            detail="Choose a translation language different from the transcript language.",
        )
    try:
        job = session.start_ai_job(
            recording_id,
            payload.operation,
            payload.target_language,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Recording not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ai_job_response(job)


@router.get("/ai/jobs/{job_id}", response_model=AIJobResponse)
def get_ai_job(job_id: str, request: Request) -> AIJobResponse:
    job = get_session(request).get_ai_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI job not found.")
    return ai_job_response(job)


@router.post(
    "/recordings",
    response_model=RecordingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recording(
    request: Request,
    name: Annotated[str, Form(min_length=1, max_length=MAX_NAME_LENGTH)],
    duration: Annotated[float, Form(gt=0, le=43_200)],
    audio: Annotated[UploadFile, File()],
) -> RecordingResponse:
    session = get_session(request)
    media_type = (audio.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    media_info = SUPPORTED_MEDIA_TYPES.get(media_type)
    if media_info is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported audio format: {media_type or 'unknown'}.",
        )

    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Recording name cannot be empty.")
    extension, normalized_media_type = media_info
    staging_path = session.create_staging_path(extension)
    written = 0
    try:
        with staging_path.open("wb") as target:
            while chunk := await audio.read(1024 * 1024):
                written += len(chunk)
                if written > session.max_recording_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Recording exceeds the 512 MB session limit.",
                    )
                target.write(chunk)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise
    finally:
        await audio.close()

    if written == 0:
        staging_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The recording is empty.")

    recording = session.add_recording(
        name=clean_name,
        duration=duration,
        media_type=normalized_media_type,
        extension=extension,
        audio_path=Path(staging_path),
    )
    return recording_response(recording)


@router.patch("/recordings/{recording_id}", response_model=RecordingResponse)
def rename_recording(
    recording_id: str,
    payload: RenameRecordingRequest,
    request: Request,
) -> RecordingResponse:
    recording = get_session(request).rename_recording(recording_id, payload.name)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    return recording_response(recording)


@router.delete("/recordings/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recording(recording_id: str, request: Request) -> None:
    session = get_session(request)
    if session.get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if not session.delete_recording(recording_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This recording cannot be deleted while it is being transcribed.",
        )


@router.post(
    "/recordings/{recording_id}/transcriptions",
    response_model=StartTranscriptionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_transcription(
    recording_id: str,
    payload: StartTranscriptionRequest,
    request: Request,
) -> StartTranscriptionResponse:
    session = get_session(request)
    try:
        job = session.start_transcription(recording_id, payload.language)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Recording not found.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return StartTranscriptionResponse(job_id=job.id)


@router.get("/transcriptions/{job_id}", response_model=TranscriptionJobResponse)
def get_transcription_job(job_id: str, request: Request) -> TranscriptionJobResponse:
    job = get_session(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Transcription job not found.")
    return job_response(job)
