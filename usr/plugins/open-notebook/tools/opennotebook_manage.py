"""
Open Notebook Plugin - Manage Tool

Provides connection status checking and configuration display.
Methods: status, config
"""

import time
from helpers.tool import Tool, Response

# Import plugin modules using relative paths from plugin root
import sys
from pathlib import Path

# Add plugin root to path for imports
_plugin_root = str(Path(__file__).resolve().parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

import config
import client
import errors
sys.modules.pop('shared', None)
from shared import format_date, format_status, get_asset_type, handle_error


class OpenNotebookManage(Tool):
    async def execute(self, **kwargs):
        method = kwargs.get("action") or self.method or "status"

        if method == "status":
            return await self._status()
        elif method == "config":
            return await self._config()
        else:
            return Response(
                message=f"❌ Unknown method '{method}'. Available: status, config",
                break_loop=False,
            )

    async def _status(self) -> Response:
        """Check connection to Open Notebook via /health endpoint."""
        api_url = config.get_api_url(self.agent)
        health_url = f"{api_url}/health"

        try:
            start = time.monotonic()
            http_client = await client.get_client()
            response = await http_client.get(health_url)
            elapsed = time.monotonic() - start

            if response.status_code == 200:
                data = response.json()
                return Response(
                    message=(
                        f"✅ **Open Notebook is connected**\n"
                        f"\n"
                        f"| Detail | Value |\n"
                        f"|--------|-------|\n"
                        f"| Status | Connected |\n"
                        f"| Response Time | {elapsed:.2f}s |\n"
                        f"| API URL | `{api_url}` |\n"
                    ) + (
                        f"| Version | {data.get('version', 'unknown')} |\n"
                        if isinstance(data, dict) and 'version' in data
                        else ""
                    ),
                    break_loop=False,
                )
            else:
                return Response(
                    message=(
                        f"⚠️ **Open Notebook is reachable but unhealthy**\n"
                        f"\n"
                        f"| Detail | Value |\n"
                        f"|--------|-------|\n"
                        f"| Status | Unhealthy |\n"
                        f"| Response Time | {elapsed:.2f}s |\n"
                        f"| API URL | `{api_url}` |\n"
                        f"\n"
                        f"**Suggested next steps:**\n"
                        f"- Check Open Notebook logs for errors\n"
                        f"- Try again in a moment\n"
                    ),
                    break_loop=False,
                )

        except Exception as e:
            # Route through error translator
            import httpx
            if isinstance(e, httpx.TimeoutException):
                msg = errors.format_timeout("check Open Notebook health")
            elif isinstance(e, httpx.ConnectError):
                msg = errors.format_connection_error()
            else:
                msg = errors.format_unexpected(e)
            # Append configured URL for troubleshooting
            msg += f"\n**Configured API URL:** `{api_url}`"
            return Response(message=msg, break_loop=False)

    async def _config(self) -> Response:
        """Display current plugin configuration."""
        # Placeholder — full implementation in Story 1.4
        return Response(
            message=(
                f"⚙️ **Open Notebook Plugin Configuration**\n"
                f"\n"
                f"| Setting | Value |\n"
                f"|---------|-------|\n"
                f"| API URL | `{config.get_api_url(self.agent)}` |\n"
                f"| Read Only | {'Yes 🔒' if config.is_read_only(self.agent) else 'No ✏️'} |\n"
                f"| Confirmations | {'On ✅' if config.needs_confirmation(self.agent) else 'Off ⚠️'} |\n"
            ),
            break_loop=False,
        )
