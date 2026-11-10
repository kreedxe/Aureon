import io
from pathlib import Path
from wave import open as open_wave

from app.services.speech_synthesis import LocalSpeechSynthesizer


def test_english_prefers_named_voice_with_locale_suffix(monkeypatch) -> None:
    synthesizer = LocalSpeechSynthesizer()
    voices = [
        {"id": "Albert", "name": "Albert", "language": "en-us"},
        {
            "id": "Samantha (English (US))",
            "name": "Samantha (English (US))",
            "language": "en-us",
        },
    ]
    monkeypatch.setattr(synthesizer, "voices", lambda: voices)

    assert synthesizer._voice_for("en") == voices[1]


def test_english_fallback_skips_novelty_voices(monkeypatch) -> None:
    synthesizer = LocalSpeechSynthesizer()
    voices = [
        {"id": "Albert", "name": "Albert", "language": "en-us"},
        {"id": "Kathy", "name": "Kathy", "language": "en-us"},
    ]
    monkeypatch.setattr(synthesizer, "voices", lambda: voices)

    assert synthesizer._voice_for("en") == voices[1]


def test_macos_speech_conversion_keeps_voice_audio_at_24khz(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        commands.append(command)
        if command[0] == "afconvert":
            Path(command[-1]).write_bytes(_wave_bytes())

    monkeypatch.setattr("app.services.speech_synthesis.subprocess.run", fake_run)

    result = LocalSpeechSynthesizer._synthesize_macos("Hello there.", "Samantha")

    assert commands[1][commands[1].index("-d") + 1] == "LEI16@24000"
    assert result[:4] == b"RIFF"


def _wave_bytes() -> bytes:
    output = io.BytesIO()
    with open_wave(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 24)
    return output.getvalue()
