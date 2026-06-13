"""Persistent TTS cache for static ByteRacer system messages."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import string
import subprocess
import uuid
from pathlib import Path
from typing import Iterable

from .i18n import DEFAULT_LOCALE, MESSAGES, normalize_locale, translate
from .tts_backends import generate_tts_wav


logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TTS_CACHE_DIR = PROJECT_DIR / ".venv" / "tts-cache"
# Kept separate from the static cache so LRU eviction can never delete the
# pre-generated static system messages.
DEFAULT_DYNAMIC_TTS_CACHE_DIR = PROJECT_DIR / ".venv" / "tts-cache-dynamic"
DEFAULT_DYNAMIC_CACHE_MAX_FILES = 256
CACHE_VERSION = 2


def get_tts_cache_dir(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("BYTERACER_TTS_CACHE_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_TTS_CACHE_DIR


def get_dynamic_tts_cache_dir(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("BYTERACER_TTS_DYNAMIC_CACHE_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_DYNAMIC_TTS_CACHE_DIR


def _template_has_fields(template: str) -> bool:
    formatter = string.Formatter()
    return any(field_name for _, field_name, _, _ in formatter.parse(template))


def is_static_message_key(key: str, locale: str | None = None) -> bool:
    locale = normalize_locale(locale)
    template = MESSAGES.get(locale, {}).get(key) or MESSAGES[DEFAULT_LOCALE].get(key)
    return bool(template) and not _template_has_fields(template)


def iter_static_messages(locales: Iterable[str] | None = None):
    selected_locales = list(locales or MESSAGES.keys())
    for locale in selected_locales:
        normalized_locale = normalize_locale(locale)
        catalog = MESSAGES.get(normalized_locale, {})
        for key, template in catalog.items():
            if _template_has_fields(template):
                continue
            yield normalized_locale, key, translate(key, normalized_locale)


def _cache_digest(
    text: str,
    lang: str,
    engine: str,
    voice: str | None,
    volume_percent: int,
    gain_db: int,
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "text": text,
        "lang": normalize_locale(lang),
        "engine": (engine or "piper").lower(),
        "voice": voice or "auto",
        "volume_percent": int(volume_percent),
        "gain_db": int(gain_db),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def cached_tts_path(
    text: str,
    lang: str,
    engine: str = "piper",
    voice: str | None = "auto",
    volume_percent: int = 100,
    gain_db: int = 0,
    cache_dir: str | Path | None = None,
) -> Path:
    digest = _cache_digest(text, lang, engine, voice, volume_percent, gain_db)
    return get_tts_cache_dir(cache_dir) / normalize_locale(lang) / f"{digest}.wav"


def generate_cached_tts_file(
    text: str,
    lang: str,
    engine: str = "piper",
    voice: str | None = "auto",
    volume_percent: int = 100,
    gain_db: int = 0,
    piper_data_dir: str | Path | None = None,
    supertonic_cache_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> Path | None:
    volume_percent = max(0, min(100, int(volume_percent)))
    gain_db = int(gain_db or 0)
    output_file = cached_tts_path(text, lang, engine, voice, volume_percent, gain_db, cache_dir)

    if output_file.exists() and output_file.stat().st_size > 44:
        return output_file

    output_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file = output_file.with_name(f".{output_file.stem}.{uuid.uuid4().hex}.raw.wav")
    adjusted_file = output_file.with_name(f".{output_file.stem}.{uuid.uuid4().hex}.wav")

    try:
        engine_used = generate_tts_wav(
            text,
            normalize_locale(lang),
            str(raw_file),
            engine=engine,
            voice=voice,
            data_dir=piper_data_dir,
            supertonic_cache_dir=supertonic_cache_dir,
            allow_fallback=False,
        )
        if not engine_used:
            return None

        play_file = raw_file
        if volume_percent != 100 or gain_db:
            sox = shutil.which("sox")
            if sox:
                result = subprocess.run(
                    [
                        sox,
                        str(raw_file),
                        str(adjusted_file),
                        "gain",
                        "-n",
                        "-3",
                        "vol",
                        str(volume_percent / 100.0),
                        "gain",
                        str(gain_db),
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    play_file = adjusted_file
                else:
                    logger.warning("Failed to adjust cached TTS volume: %s", result.stderr.strip())
            else:
                logger.warning("sox is unavailable; cached TTS volume/gain adjustment skipped")

        os.replace(play_file, output_file)
        return output_file
    except Exception as exc:
        logger.warning("Failed to generate cached TTS for %s: %s", lang, exc)
        return None
    finally:
        for path in (raw_file, adjusted_file):
            try:
                if path.exists() and path != output_file:
                    path.unlink()
            except OSError:
                pass


def _evict_dynamic_cache(cache_dir: Path, max_files: int) -> None:
    """Keep the dynamic cache bounded by deleting the least-recently-used files."""
    if max_files <= 0:
        return
    try:
        files = [p for p in cache_dir.rglob("*.wav") if not p.name.startswith(".")]
    except OSError:
        return
    if len(files) <= max_files:
        return
    try:
        files.sort(key=lambda p: p.stat().st_mtime)  # oldest first
    except OSError:
        return
    for path in files[: len(files) - max_files]:
        try:
            path.unlink()
        except OSError:
            pass


def generate_dynamic_cached_tts_file(
    text: str,
    lang: str,
    engine: str = "piper",
    voice: str | None = "auto",
    volume_percent: int = 100,
    gain_db: int = 0,
    piper_data_dir: str | Path | None = None,
    supertonic_cache_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    max_files: int = DEFAULT_DYNAMIC_CACHE_MAX_FILES,
) -> Path | None:
    """Content-addressed cache for *dynamic* strings (e.g. the spoken IP address).

    Same hashing as the static cache, but stored in a separate, LRU-bounded dir:
    a string is synthesised once, then reused on every later occurrence instead of
    re-running Piper. Returns the ready-to-play cached file, or None on failure.
    """
    cache_dir = get_dynamic_tts_cache_dir(cache_dir)
    output_file = generate_cached_tts_file(
        text,
        lang,
        engine=engine,
        voice=voice,
        volume_percent=volume_percent,
        gain_db=gain_db,
        piper_data_dir=piper_data_dir,
        supertonic_cache_dir=supertonic_cache_dir,
        cache_dir=cache_dir,
    )
    if output_file is not None:
        try:
            output_file.touch()  # bump mtime so reused entries survive eviction
        except OSError:
            pass
        _evict_dynamic_cache(cache_dir, max_files)
    return output_file


def pregenerate_static_tts(
    locales: Iterable[str] | None = None,
    engine: str = "piper",
    voice: str | None = "auto",
    volume_percent: int = 100,
    gain_db: int = 0,
    piper_data_dir: str | Path | None = None,
    supertonic_cache_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[int, int]:
    generated = 0
    failed = 0
    for lang, _key, text in iter_static_messages(locales):
        path = generate_cached_tts_file(
            text,
            lang,
            engine=engine,
            voice=voice,
            volume_percent=volume_percent,
            gain_db=gain_db,
            piper_data_dir=piper_data_dir,
            supertonic_cache_dir=supertonic_cache_dir,
            cache_dir=cache_dir,
        )
        if path:
            generated += 1
        else:
            failed += 1
    return generated, failed
