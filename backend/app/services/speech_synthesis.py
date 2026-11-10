from __future__ import annotations

import base64
import json
import platform
import re
import subprocess
import tempfile
from pathlib import Path

from app.schemas.languages import LanguageCode


class LocalSpeechSynthesizer:
    def voices(self) -> list[dict[str, str]]:
        system = platform.system()
        if system == "Darwin":
            return self._macos_voices()
        if system == "Linux":
            return self._linux_voices()
        if system == "Windows":
            return self._windows_voices()
        return []

    def synthesize(self, text: str, language: LanguageCode) -> bytes:
        voice = self._voice_for(language)
        if voice is None:
            raise RuntimeError(
                f"No installed offline speech voice supports {language}. "
                "Install a compatible local voice in your operating system before continuing."
            )
        if platform.system() == "Darwin":
            return self._synthesize_macos(text, voice["id"])
        if platform.system() == "Linux":
            result = subprocess.run(
                ["espeak-ng", "--stdout", "-v", voice["id"], text],
                capture_output=True,
                check=True,
                timeout=30,
            )
            return self._validate_wave(result.stdout)
        if platform.system() == "Windows":
            return self._synthesize_windows(text, voice["id"])
        raise RuntimeError(f"Offline speech synthesis is not configured for {platform.system()}.")

    @staticmethod
    def _voice_language(voice: dict[str, str]) -> str:
        return voice["language"].split("-", maxsplit=1)[0].split("_", maxsplit=1)[0].lower()

    def _voice_for(self, language: LanguageCode) -> dict[str, str] | None:
        matches = [voice for voice in self.voices() if self._voice_language(voice) == language]
        preferred_names = {
            "en": ("Samantha", "Alex", "Ava", "Allison", "Daniel", "Karen"),
            "ru": ("Milena",),
            "uz": (),
        }[language]
        for preferred_name in preferred_names:
            preferred_voice = next(
                (
                    voice
                    for voice in matches
                    if voice["id"].casefold() == preferred_name.casefold()
                    or voice["id"].casefold().startswith(f"{preferred_name.casefold()} (")
                ),
                None,
            )
            if preferred_voice is not None:
                return preferred_voice
        return next(
            (voice for voice in matches if not self._is_unnatural_fallback(voice["id"])),
            matches[0] if matches else None,
        )

    @staticmethod
    def _is_unnatural_fallback(voice_id: str) -> bool:
        voice_name = voice_id.partition(" (")[0].casefold()
        return voice_name in {
            "albert",
            "bad news",
            "bahh",
            "bells",
            "boing",
            "bubbles",
            "cellos",
            "fred",
            "good news",
            "grandma",
            "grandpa",
            "jester",
            "junior",
            "organ",
            "ralph",
            "rocko",
            "superstar",
            "trinoids",
            "wobble",
            "zarvox",
        }

    @staticmethod
    def _macos_voices() -> list[dict[str, str]]:
        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []
        voices: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            match = re.match(r"^\s*(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
            if match:
                voices.append(
                    {
                        "id": match.group(1).strip(),
                        "name": match.group(1).strip(),
                        "language": match.group(2).replace("_", "-").lower(),
                    }
                )
        return voices

    @staticmethod
    def _linux_voices() -> list[dict[str, str]]:
        try:
            result = subprocess.run(
                ["espeak-ng", "--voices"],
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []
        voices: list[dict[str, str]] = []
        for line in result.stdout.splitlines()[1:]:
            columns = line.split()
            if len(columns) >= 5:
                voices.append(
                    {"id": columns[4], "name": columns[4], "language": columns[1].lower()}
                )
        return voices

    @staticmethod
    def _windows_voices() -> list[dict[str, str]]:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.GetInstalledVoices() | ForEach-Object { "
            "@{id=$_.VoiceInfo.Name; name=$_.VoiceInfo.Name; "
            "language=$_.VoiceInfo.Culture.Name} } | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            )
            raw_voices = json.loads(result.stdout)
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
            return []
        if isinstance(raw_voices, dict):
            raw_voices = [raw_voices]
        if not isinstance(raw_voices, list):
            return []
        return [
            {"id": item["id"], "name": item["name"], "language": item["language"].lower()}
            for item in raw_voices
            if isinstance(item, dict)
            and all(isinstance(item.get(key), str) for key in ("id", "name", "language"))
        ]

    @staticmethod
    def _synthesize_macos(text: str, voice: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="aureon-tts-") as directory:
            source = Path(directory) / "speech.aiff"
            destination = Path(directory) / "speech.wav"
            subprocess.run(
                ["say", "-v", voice, "-o", str(source), text],
                capture_output=True,
                check=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "afconvert",
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16@24000",
                    str(source),
                    str(destination),
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            return LocalSpeechSynthesizer._validate_wave(destination.read_bytes())

    @staticmethod
    def _synthesize_windows(text: str, voice: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="aureon-tts-") as directory:
            destination = Path(directory) / "speech.wav"
            script_path = Path(directory) / "synthesize.ps1"
            encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
            encoded_voice = base64.b64encode(voice.encode("utf-8")).decode("ascii")
            encoded_path = base64.b64encode(str(destination).encode("utf-8")).decode("ascii")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$voice = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[0])); "
                "$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[1])); "
                "$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[2])); "
                "$s.SelectVoice($voice); $s.SetOutputToWaveFile($path); "
                "$s.Speak($text); $s.Dispose()"
            )
            script_path.write_text(script, encoding="utf-8")
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(script_path),
                    encoded_voice,
                    encoded_text,
                    encoded_path,
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            return LocalSpeechSynthesizer._validate_wave(destination.read_bytes())

    @staticmethod
    def _validate_wave(audio: bytes) -> bytes:
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise RuntimeError("The local speech engine returned an invalid WAV audio stream.")
        return audio
