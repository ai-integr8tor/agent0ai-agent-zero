"""
Open Notebook Plugin - Health Check Extension

Fires before every opennotebook_* tool execution.
Sends a quick /health ping to detect connectivity issues.
Sets context.data["on_unhealthy"] flag if unhealthy, but does NOT block execution.
"""

import time
import httpx
from helpers.extension import Extension

import sys
from pathlib import Path

# Add plugin root to path for imports
_plugin_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

import config
import telemetry

# Health check budget
_HEALTH_TIMEOUT = 0.4  # 400ms
_MIN_CHECK_INTERVAL = 30  # Don't check more than once per 30s


class HealthCheckExtension(Extension):
    async def execute(self, **kwargs):
        """Run before opennotebook_* tool execution."""
        tool_name = kwargs.get("tool_name", "")

        # Only run for opennotebook tools
        if not tool_name.startswith("opennotebook_"):
            return

        agent = self.agent
        if not agent:
            return

        # Rate-limit health checks
        context_data = agent.context.data
        last_check = context_data.get("on_last_health_check", 0)
        now = time.monotonic()
        if now - last_check < _MIN_CHECK_INTERVAL:
            return

        context_data["on_last_health_check"] = now

        # Quick health ping
        api_url = config.get_api_url(agent)
        health_url = f"{api_url}/health"

        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as quick_client:
                response = await quick_client.get(health_url)
                if response.status_code == 200:
                    context_data["on_unhealthy"] = False
                    telemetry.set_unhealthy(False)
                else:
                    context_data["on_unhealthy"] = True
                    context_data["on_unhealthy_since"] = now
                    telemetry.set_unhealthy(True)
        except Exception:
            context_data["on_unhealthy"] = True
            context_data["on_unhealthy_since"] = now
            telemetry.set_unhealthy(True)
