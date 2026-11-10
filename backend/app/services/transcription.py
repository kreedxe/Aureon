from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

import numpy as np
from platformdirs import user_cache_dir

from app.schemas.recordings import TranscriptionLanguage

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    model: str


class LocalWhisperTranscriber:
    model_name = "small"
    model_repository = "Systran/faster-whisper-small"

    def __init__(self) -> None:
        self._model = None
        self._model_lock = Lock()
        self._inference_lock = Lock()

    @property
    def cached(self) -> bool:
        from huggingface_hub import try_to_load_from_cache

        model_path = try_to_load_from_cache(
            self.model_repository,
            "model.bin",
            cache_dir=str(self.cache_dir),
        )
        return isinstance(model_path, str) and Path(model_path).is_file()

    @property
    def cache_dir(self) -> Path:
        return Path(user_cache_dir("Aureon", "Aureon")) / "whisper"

    def prepare_model(self, report_progress: ProgressCallback) -> None:
        self._get_model(report_progress, local_files_only=False)

    def load_cached_model(self, report_progress: ProgressCallback) -> None:
        self._get_model(report_progress, local_files_only=True)

    def transcribe(
        self,
        audio_path: Path,
        language: TranscriptionLanguage,
        duration: float,
        report_progress: ProgressCallback,
    ) -> TranscriptionResult:
        model = self._get_model(report_progress)
        report_progress(40, "Transcribing audio locally…")
        try:
            with self._inference_lock:
                segments, info = model.transcribe(
                    str(audio_path),
                    language=language,
                    task="transcribe",
                    beam_size=5,
                    vad_filter=True,
                )
                text_parts: list[str] = []
                last_progress = 40.0
                for segment in segments:
                    text_parts.append(segment.text)
                    if duration > 0:
                        progress = min(96.0, 40.0 + (segment.end / duration) * 56.0)
                        if progress - last_progress >= 1:
                            report_progress(progress, "Transcribing speech locally…")
                            last_progress = progress
        except Exception as error:
            raise RuntimeError(
                "The audio could not be decoded or transcribed. "
                f"Details: {type(error).__name__}: {error}. "
                "Try recording again in a supported audio format."
            ) from error

        text = "".join(text_parts).strip()
        if not text:
            raise RuntimeError("No speech was detected in this recording.")
        return TranscriptionResult(
            text=text,
            language=info.language,
            language_probability=float(info.language_probability),
            model=self.model_name,
        )

    def transcribe_samples(
        self,
        audio: np.ndarray,
        language: TranscriptionLanguage,
        report_progress: ProgressCallback,
    ) -> TranscriptionResult:
        model = self._get_model(report_progress, local_files_only=True)
        if audio.ndim != 1 or audio.size < 4_800:
            raise RuntimeError("The utterance is too short to transcribe reliably.")
        if not np.isfinite(audio).all():
            raise RuntimeError("The microphone provided invalid audio samples.")
        report_progress(5, "Transcribing the utterance with local Whisper…")
        try:
            with self._inference_lock:
                segments, info = model.transcribe(
                    audio.astype(np.float32, copy=False),
                    language=language,
                    task="transcribe",
                    beam_size=1,
                    condition_on_previous_text=False,
                    vad_filter=False,
                )
                text = "".join(segment.text for segment in segments).strip()
        except Exception as error:
            raise RuntimeError(
                "Local Whisper could not decode this microphone utterance. "
                f"Details: {type(error).__name__}: {error}"
            ) from error
        if not text:
            raise RuntimeError("Whisper did not detect speech in that utterance.")
        return TranscriptionResult(
            text=text,
            language=info.language,
            language_probability=float(info.language_probability),
            model=self.model_name,
        )

    def _get_model(
        self,
        report_progress: ProgressCallback,
        *,
        local_files_only: bool = False,
    ) -> WhisperModel:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            report_progress(
                1,
                (
                    "Loading the cached local Whisper model…"
                    if local_files_only
                    else "Preparing the local Whisper model. First use may download the model "
                    "and requires internet."
                ),
            )
            try:
                from faster_whisper import WhisperModel
                from huggingface_hub import snapshot_download
                from huggingface_hub.utils import tqdm as HuggingFaceTqdm

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                last_progress = 5.0

                class DownloadProgress(HuggingFaceTqdm):
                    def __init__(self, *args: Any, **kwargs: Any) -> None:
                        self._aureon_description = kwargs.get("desc")
                        super().__init__(*args, **kwargs)

                    def update(self, n: int | float = 1) -> bool | None:
                        nonlocal last_progress
                        result = super().update(n)
                        if self._aureon_description == "Downloading bytes" and self.total:
                            downloaded = float(self.n)
                            total = float(self.total)
                            last_progress = max(
                                last_progress,
                                5.0 + min(1.0, downloaded / total) * 30.0,
                            )
                            report_progress(
                                last_progress,
                                "Downloading the local Whisper model "
                                f"({downloaded / 1_000_000:.0f} / {total / 1_000_000:.0f} MB).",
                            )
                        return result

                model_path = snapshot_download(
                    self.model_repository,
                    allow_patterns=[
                        "config.json",
                        "preprocessor_config.json",
                        "model.bin",
                        "tokenizer.json",
                        "vocabulary.*",
                    ],
                    cache_dir=str(self.cache_dir),
                    local_files_only=local_files_only,
                    tqdm_class=DownloadProgress,
                )
                if not isinstance(model_path, str):
                    raise RuntimeError("The Whisper model download returned an invalid path.")
                report_progress(32, "Loading the downloaded Whisper model into memory…")
                self._model = WhisperModel(
                    model_path,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
                report_progress(38, "Whisper model ready. Preparing the recording…")
            except Exception as error:
                if local_files_only:
                    message = (
                        "The local Whisper model is not fully cached. Prepare the offline "
                        f"voice models before starting a conversation. Details: {error}"
                    )
                else:
                    message = (
                        "Could not prepare the local Whisper model. The first download requires "
                        "internet; after it is cached, transcription runs offline. "
                        f"Details: {error}"
                    )
                raise RuntimeError(message) from error
        return self._model
