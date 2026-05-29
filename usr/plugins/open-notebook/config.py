"""
Open Notebook Plugin - Configuration Helpers

Provides typed access to plugin settings with sensible defaults.
All tools import from this module — never access config directly.
"""

from agent import Agent
from helpers import plugins

PLUGIN_NAME = "open-notebook"


def _get_config(agent: Agent) -> dict:
    """Get the plugin config dict."""
    return plugins.get_plugin_config(PLUGIN_NAME, agent=agent) or {}


def get_api_url(agent: Agent) -> str:
    """Get the configured Open Notebook API URL."""
    cfg = _get_config(agent)
    api_url = cfg.get("api_url")
    if api_url:
        return api_url

    import os
    env_url = os.environ.get("OPEN_NOTEBOOK_API_URL")
    if env_url:
        return env_url

    # Default to localhost for local/container-native setups; Docker Desktop users
    # can override via config or OPEN_NOTEBOOK_API_URL.
    return "http://localhost:5055"


def is_read_only(agent: Agent) -> bool:
    """Check if the plugin is in read-only mode."""
    return _get_config(agent).get("read_only", False)


def needs_confirmation(agent: Agent) -> bool:
    """Check if confirmations are enabled for destructive operations."""
    return _get_config(agent).get("confirmations", True)


