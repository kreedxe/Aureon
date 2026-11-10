from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import onnxruntime
from platformdirs import user_cache_dir

logger = logging.getLogger(__name__)


class SileroVoiceActivityDetector:
    model_url = (
        "https://raw.githubusercontent.com/snakers4/silero-vad/master/"
        "src/silero_vad/data/silero_vad.onnx"
    )
    sample_rate = 16_000
    frame_samples = 512
    context_samples = 64

    def __init__(self) -> None:
        self.model_path = Path(user_cache_dir("Aureon", "Aureon")) / "voice" / "silero_vad.onnx"
        self._session: onnxruntime.InferenceSession | None = None
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.context_samples), dtype=np.float32)
        self._lock = threading.Lock()

    @property
    def cached(self) -> bool:
        return self.model_path.is_file() and self.model_path.stat().st_size > 1_000_000

    def load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            if not self.cached:
                raise RuntimeError(
                    "The local Silero VAD model is missing. Prepare the offline voice models "
                    "before starting a conversation."
                )
            options = onnxruntime.SessionOptions()
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            self._session = onnxruntime.InferenceSession(
                str(self.model_path),
                providers=["CPUExecutionProvider"],
                sess_options=options,
            )
            self._state.fill(0)
            self._context.fill(0)

    def download_and_load(self, progress: Callable[[float, str], None]) -> None:
        if not self.cached:
            import httpx

            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.model_path.with_suffix(".onnx.download")
            try:
                with httpx.stream(
                    "GET",
                    self.model_url,
                    follow_redirects=True,
                    timeout=60,
                ) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as model_file:
                        for chunk in response.iter_bytes():
                            model_file.write(chunk)
                if temporary_path.stat().st_size <= 1_000_000:
                    raise RuntimeError("The downloaded Silero VAD model is unexpectedly small.")
                temporary_path.replace(self.model_path)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
        progress(90, "Loading the local Silero voice detector…")
        self.load()

    def reset(self) -> None:
        with self._lock:
            self._state.fill(0)
            self._context.fill(0)

    def probability(self, pcm_frame: np.ndarray) -> float:
        if pcm_frame.shape != (self.frame_samples,):
            raise ValueError(f"VAD expects exactly {self.frame_samples} mono samples per frame.")
        if not np.isfinite(pcm_frame).all():
            raise ValueError("VAD received non-finite audio samples.")
        if self._session is None:
            self.load()
        with self._lock:
            if self._session is None:
                raise RuntimeError("The local Silero voice detector is not loaded.")
            framed_audio = np.concatenate(
                (self._context[0], pcm_frame.astype(np.float32, copy=False))
            )[None, :]
            outputs = self._session.run(
                None,
                {
                    "input": framed_audio,
                    "state": self._state,
                    "sr": np.asarray(self.sample_rate, dtype=np.int64),
                },
            )
            scores, state = outputs
            self._state = state
            self._context[0] = framed_audio[0, -self.context_samples :]
        return float(np.asarray(scores).reshape(-1)[0])
