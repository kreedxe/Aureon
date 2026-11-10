from datetime import datetime
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
ConversationStatus = Literal["active", "completed", "failed"]
PurchaseIntent = Literal["browsing", "comparing", "interested", "committed", "unknown"]
PurchaseOutcome = Literal[
    "purchased",
    "requested_more_information",
    "undecided",
    "no_purchase",
]


class ConversationCreate(BaseModel):
    language: ConversationLanguage

    model_config = ConfigDict(extra="forbid")


class ConversationMessageRecord(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    language: LanguageCode
    timestamp: datetime
    language_probability: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


class ConversationSummary(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    customer_name: str
    customer_age: str
    customer_location: str
    other_customer_details: list[str]
    customer_interests: list[str]
    customer_needs: list[str]
    purchase_intent: PurchaseIntent
    purchase_outcome: PurchaseOutcome
    tone: str
    important_details: list[str]
    next_steps: list[str]

    model_config = ConfigDict(extra="forbid")


class ConversationSummaryDraft(ConversationSummary):
    pass


class ConversationSummaryResponse(ConversationSummary):
    pass


class ConversationListItem(BaseModel):
    id: str
    title: str
    language: ConversationLanguage
    started_at: datetime
    ended_at: datetime | None
    status: ConversationStatus
    message_count: int

    model_config = ConfigDict(extra="forbid")


class ConversationDetail(ConversationListItem):
    messages: list[ConversationMessageRecord]
    summary: ConversationSummaryResponse | None
    summary_error: str | None

    model_config = ConfigDict(extra="forbid")


class ConversationStart(BaseModel):
    type: Literal["start"]
    token: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    language: ConversationLanguage
    conversation_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]

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
    catalog_requested: bool
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
    language_probability: float | None = Field(default=None, ge=0, le=1)
    level: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")
