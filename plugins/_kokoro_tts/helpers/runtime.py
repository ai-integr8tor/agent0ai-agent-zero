from __future__ import annotations

import asyncio
import base64
from typing import Any

import aiohttp

from helpers import plugins
from helpers.print_style import PrintStyle
from plugins._kokoro_tts.helpers import migration


PLUGIN_NAME = "_kokoro_tts"
DEFAULT_CONFIG = {
    "voice": "am_onyx+am_echo",
    "speed": 1.1,
    "remote_url": "http://ares.moon-dragon.us:18890",
    "response_format": "mp3",
}

VALID_FORMATS = {"wav", "mp3", "opus", "flac"}
MIME_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "flac": "audio/flac",
}

_remote_healthy: bool | None = None


def normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    if not isinstance(config, dict):
        return normalized

    voice = str(config.get("voice", normalized["voice"]) or "").strip()
    if voice:
        normalized["voice"] = voice

    try:
        speed = float(config.get("speed", normalized["speed"]))
        if speed > 0:
            normalized["speed"] = speed
    except (TypeError, ValueError):
        pass

    remote_url = str(config.get("remote_url", normalized["remote_url"]) or "").strip()
    if remote_url:
        normalized["remote_url"] = remote_url.rstrip("/")

    response_format = str(config.get("response_format", normalized["response_format"]) or "").strip().lower()
    if response_format in VALID_FORMATS:
        normalized["response_format"] = response_format

    return normalized


def get_config() -> dict[str, Any]:
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    return normalize_config(config)


def is_globally_enabled() -> bool:
    migration.ensure_migrated()
    return plugins.determined_toggle_from_paths(
        True, reversed(plugins.get_plugin_roots(PLUGIN_NAME))
    )


async def preload(config: dict[str, Any] | None = None):
    return await _preload()


async def _preload():
    global _remote_healthy
    try:
        cfg = get_config()
        remote_url = cfg.get("remote_url", DEFAULT_CONFIG["remote_url"])
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{remote_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                _remote_healthy = resp.status == 200
        if _remote_healthy:
            PrintStyle.standard("Kokoro TTS remote API is healthy.")
        else:
            PrintStyle.error(f"Kokoro TTS remote API unhealthy: status {resp.status}")
    except Exception as e:
        _remote_healthy = False
        PrintStyle.error(f"Kokoro TTS remote API check failed: {e}")


async def is_downloading() -> bool:
    return False


async def is_downloaded() -> bool:
    if _remote_healthy is None:
        await _preload()
    return _remote_healthy is True


async def synthesize_sentences(
    sentences: list[str], config: dict[str, Any] | None = None
) -> tuple[str, str]:
    cfg = normalize_config(config or get_config())
    return await _synthesize_sentences(
        sentences,
        voice=str(cfg["voice"]),
        speed=float(cfg["speed"]),
        remote_url=str(cfg["remote_url"]),
        response_format=str(cfg["response_format"]),
    )


async def _synthesize_sentences(
    sentences: list[str],
    *,
    voice: str,
    speed: float,
    remote_url: str,
    response_format: str,
) -> tuple[str, str]:
    text = " ".join(s.strip() for s in sentences if s.strip())
    if not text:
        return "", MIME_TYPES.get(response_format, "audio/mpeg")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{remote_url}/v1/audio/speech",
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": voice,
                    "response_format": response_format,
                    "speed": speed,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                audio_bytes = await resp.read()
                mime_type = MIME_TYPES.get(response_format, "audio/mpeg")
                return base64.b64encode(audio_bytes).decode("utf-8"), mime_type
    except Exception as e:
        PrintStyle.error(f"Error in remote Kokoro TTS synthesis: {e}")
        raise
