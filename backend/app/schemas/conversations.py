from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.languages import LanguageCode

ConversationLanguage = Literal["auto", "uz", "ru", "en"]
ConversationState = Literal[
    "IDLE",
    "INITIALIZING",
    "GREETING",
    "LISTENING",
    "TRANSCRIBING",
    "THINKING",
    "SPEAKING",
    "INTERRUPTED",
    "ERROR",
    "ENDED",
]


class ConversationStart(BaseModel):
    type: Literal["start"]
    token: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    language: ConversationLanguage

    model_config = ConfigDict(extra="forbid")


class ConversationControl(BaseModel):
    type: Literal["end", "audio_finished"]

    model_config = ConfigDict(extra="forbid")


class ConversationReadinessResponse(BaseModel):
    ready: bool
    vad_ready: bool
    whisper_ready: bool
    llm_ready: bool
    voices: list[dict[str, str]]
    install_status: Literal["idle", "running", "completed", "failed"]
    install_progress: float = Field(ge=0, le=100)
    install_message: str
    install_error: str | None = None

    model_config = ConfigDict(extra="forbid")


class ProductSearchPlan(BaseModel):
    product_query: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, max_length=120),
    ] = None

    model_config = ConfigDict(extra="forbid")


class ConversationReplyDraft(BaseModel):
    reply: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=800),
    ]

    model_config = ConfigDict(extra="forbid")


class ConversationEvent(BaseModel):
    type: Literal["state", "transcript", "assistant", "error", "meter"]
    state: ConversationState | None = None
    message: str | None = None
    text: str | None = None
    language: LanguageCode | None = None
    level: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")
