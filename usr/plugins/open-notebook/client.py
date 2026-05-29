"""
Open Notebook Plugin - Shared HTTP Client

Provides a lazy-singleton httpx.AsyncClient instance shared across all tools.
Initialized on first call (not via agent_init hook).

Tools use this module to make HTTP requests:
    from plugin_root.client import get_client
    client = await get_client()
    response = await client.get(url)
"""

try:
    import httpx
except ImportError:
    httpx = None

# Module-level singleton — None until first call
_client = None

# Timeout configuration
_CONNECT_TIMEOUT = 5.0  # seconds
_READ_TIMEOUT = 30.0     # seconds


async def get_client():
    """Get or create the shared httpx.AsyncClient singleton.

    Returns a single AsyncClient instance with:
    - 5s connect timeout
    - 30s read timeout
    - Connection pooling enabled
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT,
                read=_READ_TIMEOUT,
                write=_READ_TIMEOUT,
                pool=_CONNECT_TIMEOUT,
            )
        )
    return _client


async def close_client() -> None:
    """Close the shared client instance (for cleanup if needed)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
