import wave
from io import StringIO
from pathlib import Path
from typing import Any

import faster_whisper
import huggingface_hub
from pytest import MonkeyPatch

from app.services.transcription import LocalWhisperTranscriber


def test_model_download_reports_byte_progress(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    progress_updates: list[tuple[float, str]] = []
    model_arguments: list[tuple[str, dict[str, Any]]] = []

    def fake_snapshot_download(repository: str, **kwargs: Any) -> str:
        assert repository == "Systran/faster-whisper-small"
        progress_class = kwargs["tqdm_class"]
        progress = progress_class(
            total=100_000_000,
            desc="Downloading bytes",
            unit="B",
            file=StringIO(),
        )
        progress.update(50_000_000)
        progress.close()
        return str(tmp_path)

    class FakeWhisperModel:
        def __init__(self, model_path: str, **kwargs: Any) -> None:
            model_arguments.append((model_path, kwargs))

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        "app.services.transcription.user_cache_dir",
        lambda *_args: str(tmp_path),
    )

    transcriber = LocalWhisperTranscriber()
    transcriber._get_model(lambda progress, message: progress_updates.append((progress, message)))

    download_updates = [
        (progress, message)
        for progress, message in progress_updates
        if "Downloading the local Whisper model" in message
    ]
    assert download_updates
    assert download_updates[-1][0] == 20
    assert "50 / 100 MB" in download_updates[-1][1]
    assert model_arguments[0][0] == str(tmp_path)
    assert model_arguments[0][1]["local_files_only"] is True


def test_faster_whisper_decoder_reads_wav_audio(tmp_path: Path) -> None:
    from faster_whisper.audio import decode_audio

    recording_path = tmp_path / "silence.wav"
    with wave.open(str(recording_path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16_000)
        recording.writeframes(bytes(32_000))

    decoded_audio = decode_audio(str(recording_path))

    assert len(decoded_audio) == 16_000
    assert decoded_audio.min() == decoded_audio.max() == 0
