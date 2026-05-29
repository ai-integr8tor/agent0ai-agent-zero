"""Open Notebook Reverse Proxy API.

Proxies all requests from the frontend through Agent Zero's API port
so remote clients can reach the Open Notebook backend without
direct access to localhost:5055.

Frontend calls: POST /api/plugins/open-notebook/proxy
Body: { "method": "GET", "path": "/api/notebooks", "body": null, "headers": {} }

GET mode (for audio/binary): /api/plugins/open-notebook/proxy?__audio=1&path=/api/podcasts/episodes/.../audio
"""

import json as json_mod
import os
from typing import Any, Dict

import httpx
from flask import request as flask_request
from helpers.api import ApiHandler, Request, Response

# Backend URL from env or default
ON_API_URL = os.environ.get("OPEN_NOTEBOOK_API_URL", "http://host.docker.internal:5055")


class ProxyHandler(ApiHandler):
    """Reverse proxy for the Open Notebook backend service."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    async def process(self, input: dict, request: Request) -> dict | Response:
        # GET mode: binary proxy for audio files
        if request.method == "GET":
            return await self._handle_binary_proxy(request)

        # POST mode: JSON proxy
        return await self._handle_json_proxy(input)

    async def _handle_binary_proxy(self, request: Request) -> Response:
        """Handle GET requests for binary content (audio files, etc.)."""
        path = request.args.get("path", "/")
        target_url = ON_API_URL.rstrip("/") + "/" + path.lstrip("/")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(target_url)

            content_type = resp.headers.get("content-type", "application/octet-stream")
            return Response(
                response=resp.content,
                status=resp.status_code,
                mimetype=content_type,
            )
        except httpx.ConnectError:
            return Response(
                response=json_mod.dumps({"ok": False, "error": "Backend unreachable"}),
                status=502,
                mimetype="application/json",
            )
        except Exception as e:
            return Response(
                response=json_mod.dumps({"ok": False, "error": str(e)}),
                status=500,
                mimetype="application/json",
            )

    async def _handle_json_proxy(self, input: dict) -> dict | Response:
        """Handle POST requests for JSON API calls."""
        method = input.get("method", "GET").upper()
        path = input.get("path", "/")
        body = input.get("body")
        extra_headers = input.get("headers", {})

        # Build target URL
        target_url = ON_API_URL.rstrip("/") + "/" + path.lstrip("/")

        # Build headers
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers)

        # Build kwargs for httpx
        kwargs: Dict[str, Any] = {
            "method": method,
            "url": target_url,
            "headers": headers,
            "timeout": 30.0,
        }

        if body is not None and method in ("POST", "PUT", "PATCH"):
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            elif isinstance(body, str):
                kwargs["content"] = body
            else:
                kwargs["content"] = json_mod.dumps(body)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(**kwargs)

            # Try to parse JSON
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    data = resp.json()
                    return Response(
                        response=json_mod.dumps({
                            "_proxy_status": resp.status_code,
                            "_proxy_content_type": content_type,
                            "data": data,
                        }),
                        status=200,
                        mimetype="application/json",
                    )
                except Exception:
                    pass

            # Return raw content for non-JSON responses
            return Response(
                response=json_mod.dumps({
                    "_proxy_status": resp.status_code,
                    "_proxy_content_type": content_type,
                    "data": resp.text,
                }),
                status=200,
                mimetype="application/json",
            )

        except httpx.ConnectError:
            return Response(
                response=json_mod.dumps({
                    "ok": False,
                    "error": "Open Notebook backend unreachable on " + ON_API_URL,
                }),
                status=502,
                mimetype="application/json",
            )
        except Exception as e:
            return Response(
                response=json_mod.dumps({
                    "ok": False,
                    "error": f"Proxy error: {str(e)}",
                }),
                status=500,
                mimetype="application/json",
            )
