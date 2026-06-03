from __future__ import annotations

import aiohttp

from helpers.api import ApiHandler, Request, Response
from plugins._kokoro_tts.helpers import migration, runtime


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        migration.ensure_migrated()

        cfg = runtime.get_config()
        remote_url = cfg.get("remote_url", "")

        remote_healthy = False
        remote_error = ""
        if remote_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{remote_url}/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        remote_healthy = resp.status == 200
            except Exception as e:
                remote_error = str(e)

        return {
            "plugin": "_kokoro_tts",
            "enabled": runtime.is_globally_enabled(),
            "config": cfg,
            "model": {
                "ready": remote_healthy,
                "loading": False,
            },
            "remote": {
                "url": remote_url,
                "healthy": remote_healthy,
                "error": remote_error,
            },
            "fallback": "Browser-native speechSynthesis remains the fallback when Kokoro is disabled.",
        }
