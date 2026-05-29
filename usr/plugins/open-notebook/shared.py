"""
Open Notebook Plugin - Shared Helpers

Common utilities used across all tool files: date formatting,
status formatting, error handling, and asset type detection.
"""

try:
    import httpx
except ImportError:
    httpx = None
from errors import format_timeout, format_connection_error, format_http_error, format_unexpected


def format_date(date_str: str) -> str:
    """Format ISO date string to 'YYYY-MM-DD HH:MM'."""
    if not date_str:
        return "unknown"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return date_str


def format_status(status) -> str:
    """Format processing status with emoji for visual scanning."""
    if not status:
        return "✅ completed"
    status = str(status).lower()
    if status in ("completed", "done", "finished"):
        return "✅ completed"
    elif status in ("processing", "in_progress", "running"):
        return "⏳ processing"
    elif status in ("pending", "queued", "waiting"):
        return "⏳ pending"
    elif status in ("failed", "error"):
        return "❌ failed"
    return status


def get_asset_type(source: dict) -> str:
    """Extract display-friendly source type from nested asset data."""
    asset = source.get("asset")
    if isinstance(asset, dict):
        asset_type = asset.get("type", "")
        if asset_type:
            return asset_type
    return "text"


def handle_error(error: Exception, url: str) -> str:
    """Route errors through the error translator with user-friendly messages."""
    if isinstance(error, httpx.TimeoutException):
        return format_timeout("fetch from Open Notebook")
    elif isinstance(error, httpx.ConnectError):
        return format_connection_error()
    elif isinstance(error, httpx.HTTPStatusError):
        return format_http_error(error)
    else:
        return format_unexpected(error)


async def resolve_notebook_id(agent, notebook_id_or_name: str) -> str:
    """Resolve a notebook name or partial ID to a full notebook ID.
    
    If the value already looks like a full ID (starts with 'notebook:'), return it as-is.
    Otherwise, fetch all notebooks and search by name (case-insensitive, emoji-stripped).
    Returns the full ID string, or raises ValueError if not found.
    """
    import re
    from pathlib import Path
    import sys
    _plugin_root = str(Path(__file__).resolve().parent.parent)
    if _plugin_root not in sys.path:
        sys.path.insert(0, _plugin_root)
    import config
    import client
    
    if not notebook_id_or_name:
        raise ValueError("Notebook ID or name is required")
    
    # Already a full ID
    if notebook_id_or_name.startswith("notebook:"):
        return notebook_id_or_name
    
    # Fetch all notebooks and search by name
    api_url = config.get_api_url(agent)
    url = f"{api_url}/api/notebooks"
    http_client = await client.get_client()
    response = await http_client.get(url)
    response.raise_for_status()
    all_notebooks = response.json()
    
    search_term = notebook_id_or_name.lower()
    for nb in all_notebooks:
        # Strip emoji for matching
        clean_name = re.sub(r'[\U00010000-\U0010ffff]', '', nb.get('name', '')).strip().lower()
        nb_id = nb.get('id', '')
        # Match on clean name or short ID suffix
        short_id = nb_id.split(':')[-1] if nb_id else ''
        if (search_term in clean_name or clean_name in search_term or 
            short_id == search_term or short_id.endswith(search_term)):
            return nb_id
    
    raise ValueError(f"No notebook found matching '{notebook_id_or_name}'")
