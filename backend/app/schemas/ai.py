from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.languages import LanguageCode

AIAction = Literal["summary", "key_points", "action_items", "translation"]
AIJobStatus = Literal[
    "queued",
    "downloading",
    "loading_model",
    "processing",
    "completed",
    "failed",
]


class AIRequest(BaseModel):
    operation: AIAction
    target_language: LanguageCode | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_translation_target(self) -> AIRequest:
        if self.operation == "translation" and self.target_language is None:
            raise ValueError("Choose a target language for translation.")
        if self.operation != "translation" and self.target_language is not None:
            raise ValueError("A target language is only used for translation.")
        return self


class SummaryResult(BaseModel):
    operation: Literal["summary"] = "summary"
    language: LanguageCode
    summary: Annotated[str, StringConstraints(min_length=1)]
    model: str

    model_config = ConfigDict(extra="forbid")


class KeyPointsResult(BaseModel):
    operation: Literal["key_points"] = "key_points"
    language: LanguageCode
    key_points: list[Annotated[str, StringConstraints(min_length=1)]]
    model: str

    model_config = ConfigDict(extra="forbid")


class ActionItem(BaseModel):
    task: Annotated[str, StringConstraints(min_length=1)]
    owner: str | None = None
    due: str | None = None

    model_config = ConfigDict(extra="forbid")


class ActionItemsResult(BaseModel):
    operation: Literal["action_items"] = "action_items"
    language: LanguageCode
    action_items: list[ActionItem]
    decisions: list[Annotated[str, StringConstraints(min_length=1)]]
    model: str

    model_config = ConfigDict(extra="forbid")


class TranslationResult(BaseModel):
    operation: Literal["translation"] = "translation"
    source_language: LanguageCode
    target_language: LanguageCode
    translation: Annotated[str, StringConstraints(min_length=1)]
    model: str

    model_config = ConfigDict(extra="forbid")


AIResult = Annotated[
    SummaryResult | KeyPointsResult | ActionItemsResult | TranslationResult,
    Field(discriminator="operation"),
]


class AIJobResponse(BaseModel):
    id: str
    recording_id: str
    operation: AIAction
    status: AIJobStatus
    progress: float = Field(ge=0, le=100)
    message: str
    error: str | None = None
    result: AIResult | None = None

    model_config = ConfigDict(extra="forbid")


class AIModelStatusResponse(BaseModel):
    name: str
    filename: str
    size_bytes: int
    downloaded: bool
    loaded: bool
    status: Literal["not_downloaded", "downloaded", "loaded", "loading", "failed"]
    error: str | None = None

    model_config = ConfigDict(extra="forbid")
