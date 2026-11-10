from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from platformdirs import user_cache_dir
from pydantic import BaseModel

from app.schemas.ai import (
    ActionItemsResult,
    AIAction,
    AIResult,
    KeyPointsResult,
    SummaryResult,
    TranslationResult,
)
from app.schemas.conversations import (
    ConversationReplyDraft,
    ConversationSummaryDraft,
    ProductSearchPlan,
)
from app.schemas.languages import LanguageCode
from app.schemas.products import ProductDescriptionDraft, ProductDescriptionRequest

if TYPE_CHECKING:
    from llama_cpp import Llama

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]


class LocalAIEngine:
    model_name = "Qwen3 1.7B Instruct Q4_K_M"
    model_repository = "unsloth/Qwen3-1.7B-GGUF"
    model_filename = "Qwen3-1.7B-Q4_K_M.gguf"
    model_size_bytes = 1_107_409_472
    context_size = 8192
    max_output_tokens = 1200

    def __init__(self) -> None:
        self._model: Llama | None = None
        self._model_lock = Lock()
        self._inference_lock = Lock()
        self._status_lock = Lock()
        self._loading = False
        self._error: str | None = None

    @property
    def cache_dir(self) -> Path:
        return Path(user_cache_dir("Aureon", "Aureon")) / "qwen"

    def status(self) -> dict[str, Any]:
        from huggingface_hub import try_to_load_from_cache

        downloaded = isinstance(
            try_to_load_from_cache(
                self.model_repository,
                self.model_filename,
                cache_dir=str(self.cache_dir),
            ),
            str,
        )
        with self._status_lock:
            loading = self._loading
            error = self._error
        loaded = self._model is not None
        state = (
            "loaded"
            if loaded
            else "loading"
            if loading
            else "failed"
            if error
            else ("downloaded" if downloaded else "not_downloaded")
        )
        return {
            "name": self.model_name,
            "filename": self.model_filename,
            "size_bytes": self.model_size_bytes,
            "downloaded": downloaded,
            "loaded": loaded,
            "status": state,
            "error": error,
        }

    def close(self) -> None:
        with self._model_lock:
            self._model = None

    def process(
        self,
        operation: AIAction,
        transcript: str,
        source_language: LanguageCode,
        target_language: LanguageCode | None,
        report_progress: ProgressCallback,
    ) -> AIResult:
        model = self._get_model(report_progress)
        expected_model = self._schema_for(operation)
        language_instruction = (
            f"Write all generated text in {self._language_name(source_language)} "
            f"({source_language}). Preserve the transcript's meaning and do not translate it."
        )
        if operation == "translation":
            if target_language is None:
                raise ValueError("Choose a target language for translation.")
            if target_language == source_language:
                raise ValueError("The target language must differ from the transcript language.")
            language_instruction = (
                f"Translate the transcript faithfully from {self._language_name(source_language)} "
                f"({source_language}) into {self._language_name(target_language)} "
                f"({target_language}). Return only the translation in the requested JSON field."
            )

        prompt = self._prompt(operation, transcript)
        report_progress(62, "Processing transcript locally…")
        try:
            with self._inference_lock:
                response = model.create_chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are Aureon's private, local transcript assistant. "
                                f"{language_instruction} "
                                "Use only information stated in the transcript. "
                                "Do not invent facts. "
                                "Return one valid JSON object and no markdown. /no_think"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={
                        "type": "json_object",
                        "schema": self._generation_schema_for(operation),
                    },
                    temperature=0.2,
                    top_p=0.8,
                    max_tokens=self.max_output_tokens,
                    seed=42,
                )
            choice = response["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError(
                    "The local model reached its response limit. Try a shorter transcript."
                )
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("The local model returned an empty response.")
            output = json.loads(content)
            if not isinstance(output, dict):
                raise ValueError("The local model response must be a JSON object.")
            output["operation"] = operation
            output["model"] = self.model_name
            if operation == "translation":
                output["source_language"] = source_language
                output["target_language"] = target_language
            else:
                output["language"] = source_language
            result = expected_model.model_validate(output)
        except Exception as error:
            logger.exception("Local AI operation %s failed", operation)
            raise RuntimeError(
                f"Local AI could not produce a valid {operation.replace('_', ' ')} result: {error}"
            ) from error
        report_progress(98, "Validating the structured result…")
        return cast(AIResult, result)

    def generate_product_description(
        self,
        product: ProductDescriptionRequest,
        report_progress: ProgressCallback,
    ) -> ProductDescriptionDraft:
        model = self._get_model(report_progress)
        facts = {
            "name": product.name,
            "price": f"{product.price} {product.currency}",
            "category": product.category,
            "brand": product.brand,
            "specifications": product.specifications,
        }
        try:
            report_progress(62, "Drafting a description from catalog details…")
            with self._inference_lock:
                response = model.create_chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Write a concise, factual product description using only the "
                                "supplied catalog fields. Never infer benefits, materials, "
                                "dimensions, "
                                "compatibility, warranty, discounts, or technical specifications. "
                                "Use the language apparent from the product name and category. "
                                "Return one JSON object with a description string only. /no_think"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Create a short draft description based only on these "
                                "catalog facts:\n"
                                f"{json.dumps(facts, ensure_ascii=False)}"
                            ),
                        },
                    ],
                    response_format={
                        "type": "json_object",
                        "schema": {
                            "type": "object",
                            "properties": {"description": {"type": "string"}},
                            "required": ["description"],
                            "additionalProperties": False,
                        },
                    },
                    temperature=0.1,
                    top_p=0.8,
                    max_tokens=300,
                    seed=42,
                )
            choice = response["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("The model reached its response limit. Try again.")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("The local model returned an empty description.")
            result = ProductDescriptionDraft.model_validate(json.loads(content))
        except Exception as error:
            logger.exception("Local product description generation failed")
            raise RuntimeError(f"Could not draft a product description: {error}") from error
        report_progress(98, "Description draft is ready for review…")
        return result

    def prepare_model(self, report_progress: ProgressCallback) -> None:
        self._get_model(report_progress, local_files_only=False)

    def load_cached_model(self, report_progress: ProgressCallback) -> None:
        self._get_model(report_progress, local_files_only=True)

    def extract_product_query(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
    ) -> ProductSearchPlan:
        model = self._get_model(lambda _progress, _message: None, local_files_only=True)
        language_name = self._language_name(language)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a local product-catalog tool router. Set catalog_requested=true "
                    "only when the customer is actually asking about a shop product, price, "
                    "availability, stock, or a recommendation. Normal greetings, small talk, "
                    "and unrelated questions must have catalog_requested=false and "
                    "product_query=null. For a real catalog request, provide a short search "
                    f"query using context ({language_name}). Never answer or invent product facts. "
                    "Return the required JSON only. /no_think"
                ),
            },
            *history[-6:],
            {"role": "user", "content": transcript},
        ]
        try:
            output = self._json_completion(
                model,
                messages,
                ProductSearchPlan.model_json_schema(),
                max_tokens=120,
            )
            return ProductSearchPlan.model_validate(output)
        except Exception as error:
            logger.exception("Local conversation product-tool planning failed")
            raise RuntimeError(f"Could not plan a local product search: {error}") from error

    def generate_conversation_summary(
        self,
        messages: list[dict[str, str]],
    ) -> ConversationSummaryDraft:
        model = self._get_model(lambda _progress, _message: None, local_files_only=True)
        prompt = (
            "Create a structured summary of this shop conversation using only details "
            "explicitly stated in the transcript. Do not infer identity, age, location, budget, "
            "preferences, needs, or purchase outcome. Use 'Not provided' for missing scalar "
            "customer details and ['Not provided'] for empty detail lists. Use 'unknown' for "
            "purchase_intent if intent was not expressed. Choose 'purchased' only if a purchase "
            "was explicitly completed; expressed interest or commitment is not a purchase. "
            "Use 'requested_more_information' only when more information was explicitly "
            "requested, 'undecided' only when that is expressed, and otherwise 'no_purchase'. "
            "The title must reflect the opening customer discussion without adding facts. "
            "Return the required JSON only. /no_think"
        )
        try:
            output = self._json_completion(
                model,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(messages, ensure_ascii=False)},
                ],
                ConversationSummaryDraft.model_json_schema(),
                max_tokens=700,
            )
            return ConversationSummaryDraft.model_validate(output)
        except Exception as error:
            logger.exception("Local conversation summary generation failed")
            raise RuntimeError(f"Could not summarize the local conversation: {error}") from error

    def generate_conversation_reply(
        self,
        transcript: str,
        language: LanguageCode,
        history: list[dict[str, str]],
        *,
        greeting: bool = False,
        catalog_facts: str | None = None,
    ) -> str:
        model = self._get_model(lambda _progress, _message: None, local_files_only=True)
        language_name = self._language_name(language)
        if greeting:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Aureon, a concise and warm in-store voice assistant. "
                        f"Speak only in {language_name}. Welcome the customer and ask how you "
                        "can help. Do not claim to have checked products or mention any "
                        "catalog facts. Return a JSON object with a single 'reply' string. "
                        "/no_think"
                    ),
                },
                {"role": "user", "content": "Start the conversation with a brief greeting."},
            ]
        else:
            catalog_instruction = (
                " This is a retail shop: 'stock' means product inventory, not financial "
                "securities. Never give financial or investment disclaimers for shopping "
                "questions. The supplied local catalog results are authoritative. When they "
                "contain a match, acknowledge the item briefly without repeating its price "
                "or quantity; Python will append the exact facts. If they state no match, "
                "say you cannot confirm it and ask for the exact product name."
                if catalog_facts
                else ""
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Aureon, a concise, helpful local shop voice assistant. "
                        f"Reply only in {language_name}. Use the supplied conversation context, "
                        "ask a short follow-up question when it helps, and never invent facts. "
                        "A greeting has already been given at the start of this conversation; "
                        "if the customer greets you, acknowledge briefly without welcoming them "
                        "again or restarting the conversation. "
                        "Do not state prices, quantities, availability, or specifications; "
                        "Python appends any verified catalog facts separately. Do not claim a "
                        "catalog lookup occurred unless verified catalog results are supplied."
                        f"{catalog_instruction} "
                        "Return a JSON object with a single 'reply' string and no markdown. "
                        "/no_think"
                    ),
                },
                *(
                    [{"role": "system", "content": f"Verified catalog results: {catalog_facts}"}]
                    if catalog_facts
                    else []
                ),
                *history[-8:],
                {"role": "user", "content": transcript},
            ]
        try:
            output = self._json_completion(
                model,
                messages,
                ConversationReplyDraft.model_json_schema(),
                max_tokens=180,
            )
            return ConversationReplyDraft.model_validate(output).reply
        except Exception as error:
            logger.exception("Local conversation response generation failed")
            raise RuntimeError(
                f"Could not generate a local conversation response: {error}"
            ) from error

    def _json_completion(
        self,
        model: Llama,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        max_tokens: int,
    ) -> dict[str, Any]:
        with self._inference_lock:
            response = model.create_chat_completion(
                messages=messages,
                response_format={
                    "type": "json_object",
                    "schema": schema,
                },
                temperature=0.2,
                top_p=0.8,
                max_tokens=max_tokens,
                seed=42,
            )
        choice = response["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("The local model reached its response limit.")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("The local model returned an empty response.")
        output = json.loads(content)
        if not isinstance(output, dict):
            raise ValueError("The local model response must be a JSON object.")
        return output

    @staticmethod
    def _schema_for(operation: AIAction) -> type[BaseModel]:
        return {
            "summary": SummaryResult,
            "key_points": KeyPointsResult,
            "action_items": ActionItemsResult,
            "translation": TranslationResult,
        }[operation]

    @classmethod
    def _generation_schema_for(cls, operation: AIAction) -> dict[str, Any]:
        schema = cls._schema_for(operation).model_json_schema()
        generated_fields = {
            "summary": ("summary",),
            "key_points": ("key_points",),
            "action_items": ("action_items", "decisions"),
            "translation": ("translation",),
        }[operation]
        schema["properties"] = {field: schema["properties"][field] for field in generated_fields}
        schema["required"] = list(generated_fields)
        if operation == "action_items":
            schema["$defs"]["ActionItem"]["required"] = ["task", "owner", "due"]
        return schema

    @staticmethod
    def _language_name(language: LanguageCode) -> str:
        return {"uz": "Uzbek", "ru": "Russian", "en": "English"}[language]

    @staticmethod
    def _prompt(operation: AIAction, transcript: str) -> str:
        instructions = {
            "summary": 'Summarize the transcript concisely. Return JSON: {"summary": "..."}',
            "key_points": (
                'Extract the main points without adding facts. Return JSON: {"key_points": ["..."]}'
            ),
            "action_items": (
                "Extract every explicit commitment and concrete next step as an action item, "
                "and record decisions separately. Include a task when a person or team is stated "
                "to do something. Do not invent an owner or due date; use null when unknown. "
                "Always return both arrays, using [] when none are stated. "
                'Return JSON: {"action_items": [{"task": "...", "owner": null, "due": null}], '
                '"decisions": ["..."]}.'
            ),
            "translation": 'Translate the transcript. Return JSON: {"translation": "..."}',
        }
        return f"{instructions[operation]}\n\nTranscript:\n{transcript}"

    def _get_model(
        self,
        report_progress: ProgressCallback,
        *,
        local_files_only: bool = False,
    ) -> Llama:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            with self._status_lock:
                self._loading = True
                self._error = None
            try:
                from huggingface_hub import hf_hub_download
                from huggingface_hub.utils import tqdm as HuggingFaceTqdm
                from llama_cpp import Llama

                self.cache_dir.mkdir(parents=True, exist_ok=True)

                class DownloadProgress(HuggingFaceTqdm):
                    _filename = self.model_filename

                    def __init__(self, *args: Any, **kwargs: Any) -> None:
                        self._aureon_description = kwargs.get("desc")
                        super().__init__(*args, **kwargs)

                    def update(self, n: int | float = 1) -> bool | None:
                        result = super().update(n)
                        if self._aureon_description == self._filename and self.total:
                            downloaded = float(self.n)
                            total = float(self.total)
                            ratio = min(1.0, downloaded / total)
                            report_progress(
                                2 + ratio * 42,
                                f"Downloading Qwen model ({downloaded / 1e9:.2f} / "
                                f"{total / 1e9:.2f} GB).",
                            )
                        return result

                with self._status_lock:
                    self._loading = True
                report_progress(
                    1,
                    "Loading cached local Qwen model…"
                    if local_files_only
                    else "Preparing local Qwen model…",
                )
                model_path = hf_hub_download(
                    repo_id=self.model_repository,
                    filename=self.model_filename,
                    cache_dir=str(self.cache_dir),
                    local_files_only=local_files_only,
                    tqdm_class=DownloadProgress,
                )
                report_progress(46, "Loading Qwen model into memory…")
                self._model = Llama(
                    model_path=str(model_path),
                    n_ctx=self.context_size,
                    n_threads=max(1, min(8, os.cpu_count() or 1)),
                    verbose=False,
                )
                report_progress(60, "Qwen is ready. Preparing the AI task…")
            except Exception as error:
                logger.exception("Could not initialize local AI model")
                if local_files_only:
                    message = (
                        "The local Qwen model is not fully cached. Prepare the offline voice "
                        f"models before starting a conversation. Details: {error}"
                    )
                else:
                    message = (
                        "Could not load the local Qwen model. Check your internet connection "
                        f"for the first download and available memory. Details: {error}"
                    )
                with self._status_lock:
                    self._error = message
                raise RuntimeError(message) from error
            finally:
                with self._status_lock:
                    self._loading = False
        return self._model
