"""Text-to-speech backend helpers shared by app and maintenance scripts."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PIPER_DATA_DIR = PROJECT_DIR / ".venv" / "piper-voices"
DEFAULT_SUPERTONIC_CACHE_DIR = PROJECT_DIR / ".venv" / "supertonic-cache"
PICO_SUPPORTED_LANGS = {"en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"}
PIPER_DEFAULT_VOICES = {
    "en-US": "en_US-lessac-medium",
    "en-GB": "en_GB-alan-medium",
    "fr-FR": "fr_FR-siwis-medium",
    "de-DE": "de_DE-thorsten-medium",
    "es-ES": "es_ES-davefx-medium",
    "it-IT": "it_IT-riccardo-x_low",
}
SUPERTONIC_DEFAULT_VOICE = "M1"
SUPERTONIC_VOICES = {
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
}
SUPERTONIC_LANGS = {
    "en",
    "ko",
    "ja",
    "ar",
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "et",
    "fi",
    "fr",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "lt",
    "lv",
    "nl",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sv",
    "tr",
    "uk",
    "vi",
    "na",
}
LOCALE_TO_SUPERTONIC_LANG = {
    "en-US": "en",
    "en-GB": "en",
    "fr-FR": "fr",
    "de-DE": "de",
    "es-ES": "es",
    "it-IT": "it",
}


def get_piper_data_dir(value: str | None = None) -> Path:
    configured = value or os.environ.get("BYTERACER_PIPER_DATA_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_PIPER_DATA_DIR


def get_supertonic_cache_dir(value: str | None = None) -> Path:
    configured = value or os.environ.get("SUPERTONIC_CACHE_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_SUPERTONIC_CACHE_DIR


def piper_voice_for_language(lang: str, configured_voice: str | None = None) -> str:
    if configured_voice and configured_voice != "auto":
        return configured_voice
    return PIPER_DEFAULT_VOICES.get(lang, PIPER_DEFAULT_VOICES["en-US"])


def supertonic_voice_for_language(lang: str, configured_voice: str | None = None) -> str:
    voice = (configured_voice or "").upper()
    if voice in SUPERTONIC_VOICES:
        return voice
    return SUPERTONIC_DEFAULT_VOICE


def supertonic_lang_for_locale(lang: str) -> str:
    if lang in LOCALE_TO_SUPERTONIC_LANG:
        return LOCALE_TO_SUPERTONIC_LANG[lang]

    short_lang = (lang or "").split("-", 1)[0].lower()
    if short_lang in SUPERTONIC_LANGS:
        return short_lang

    return "na"


def piper_voice_available(voice: str, data_dir: Path) -> bool:
    return (data_dir / f"{voice}.onnx").exists()


def _supertonic_executable(python_executable: str | None = None) -> str | None:
    python_bin = Path(python_executable or sys.executable).resolve()
    bin_dir = python_bin.parent
    candidates = [
        bin_dir / ("supertonic.exe" if os.name == "nt" else "supertonic"),
        bin_dir / "supertonic",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return shutil.which("supertonic")


def generate_pico_wav(text: str, lang: str, output_file: str) -> bool:
    if lang not in PICO_SUPPORTED_LANGS:
        logger.warning("Pico language %s is unsupported; falling back to en-US", lang)
        lang = "en-US"

    pico2wave = shutil.which("pico2wave")
    if not pico2wave:
        logger.error("pico2wave executable not found")
        return False

    result = subprocess.run(
        [pico2wave, "-l", lang, "-w", output_file, text],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("pico2wave failed: %s", result.stderr.strip())
        return False
    return True


def generate_piper_wav(
    text: str,
    lang: str,
    output_file: str,
    voice: str | None = None,
    data_dir: str | Path | None = None,
    python_executable: str | None = None,
) -> bool:
    voice_name = piper_voice_for_language(lang, voice)
    voice_dir = get_piper_data_dir(str(data_dir) if data_dir else None)

    if not piper_voice_available(voice_name, voice_dir):
        logger.warning("Piper voice %s is missing from %s", voice_name, voice_dir)
        return False

    python_bin = python_executable or sys.executable
    result = subprocess.run(
        [
            python_bin,
            "-m",
            "piper",
            "--data-dir",
            str(voice_dir),
            "-m",
            voice_name,
            "-f",
            output_file,
            "--",
            text,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        logger.error("Piper failed: %s", result.stderr.strip())
        return False
    return True


def generate_supertonic_wav(
    text: str,
    lang: str,
    output_file: str,
    voice: str | None = None,
    cache_dir: str | Path | None = None,
    python_executable: str | None = None,
) -> bool:
    supertonic = _supertonic_executable(python_executable)
    if not supertonic:
        logger.error("Supertonic executable not found")
        return False

    voice_name = supertonic_voice_for_language(lang, voice)
    lang_code = supertonic_lang_for_locale(lang)
    resolved_cache_dir = get_supertonic_cache_dir(str(cache_dir) if cache_dir else None)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["SUPERTONIC_CACHE_DIR"] = str(resolved_cache_dir)
    env.setdefault("SUPERTONIC_INTRA_OP_THREADS", "2")
    env.setdefault("SUPERTONIC_INTER_OP_THREADS", "1")

    result = subprocess.run(
        [
            supertonic,
            "tts",
            text,
            "-o",
            output_file,
            "--voice",
            voice_name,
            "--lang",
            lang_code,
            "--steps",
            "5",
        ],
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
    )
    if result.returncode != 0:
        logger.error("Supertonic failed: %s", result.stderr.strip())
        return False
    return True


def generate_tts_wav(
    text: str,
    lang: str,
    output_file: str,
    engine: str = "piper",
    voice: str | None = None,
    data_dir: str | Path | None = None,
    supertonic_cache_dir: str | Path | None = None,
    allow_fallback: bool = True,
) -> str | None:
    engine = (engine or "piper").lower()

    if engine in {"piper", "auto"}:
        if generate_piper_wav(text, lang, output_file, voice=voice, data_dir=data_dir):
            return "piper"
        if not allow_fallback:
            return None
        logger.warning("Piper TTS failed")

    if engine in {"supertonic", "auto"}:
        if generate_supertonic_wav(
            text,
            lang,
            output_file,
            voice=voice,
            cache_dir=supertonic_cache_dir,
        ):
            return "supertonic"
        if not allow_fallback:
            return None
        logger.warning("Supertonic TTS failed")

    if engine in {"pico", "piper", "supertonic", "auto"}:
        if engine != "pico":
            logger.warning("Falling back to pico2wave for TTS")
        return "pico" if generate_pico_wav(text, lang, output_file) else None

    logger.error("Unsupported TTS engine: %s", engine)
    return None
