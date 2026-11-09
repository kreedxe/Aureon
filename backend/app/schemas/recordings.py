from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.ai import AIResult
from app.schemas.languages import LanguageCode

TranscriptionLanguage = LanguageCode | None
TranscriptionStatus = Literal[
    "not_transcribed",
    "queued",
    "loading_model",
    "transcribing",
    "completed",
    "failed",
]


class TranscriptionResponse(BaseModel):
    text: str
    language: str
    language_probability: float = Field(ge=0, le=1)
    model: str

    model_config = ConfigDict(extra="forbid")


class RecordingResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    duration: float
    media_type: str
    transcription: TranscriptionResponse | None = None
    transcription_status: TranscriptionStatus = "not_transcribed"
    ai_results: dict[str, AIResult] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RecordingListResponse(BaseModel):
    recordings: list[RecordingResponse]


class RenameRecordingRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

    model_config = ConfigDict(extra="forbid")


class StartTranscriptionRequest(BaseModel):
    language: TranscriptionLanguage = None

    model_config = ConfigDict(extra="forbid")


class StartTranscriptionResponse(BaseModel):
    job_id: str

    model_config = ConfigDict(extra="forbid")


class TranscriptionJobResponse(BaseModel):
    id: str
    recording_id: str
    status: TranscriptionStatus
    progress: float = Field(ge=0, le=100)
    message: str
    error: str | None = None
    transcription: TranscriptionResponse | None = None

    model_config = ConfigDict(extra="forbid")
