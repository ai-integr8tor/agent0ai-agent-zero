from typing import Any

import models

try:
    from exa_py import Exa
except ImportError:
    Exa = None  # type: ignore[assignment,misc]

NUM_RESULTS = 10


def _get_client() -> Any:
    if Exa is None:
        raise ImportError("exa-py is required for Exa search: pip install exa-py")
    api_key = models.get_api_key("exa")
    if not api_key or api_key == "None":
        raise RuntimeError("EXA_API_KEY is not set")
    client = Exa(api_key=api_key)
    client.headers["x-exa-integration"] = "agent-zero"
    return client


def is_available() -> bool:
    """Return True if an Exa API key is configured."""
    key = models.get_api_key("exa")
    return bool(key and key != "None" and Exa is not None)


async def search(query: str) -> list[dict[str, str]]:
    """Search the web via Exa and return a list of result dicts.

    Each dict contains 'title', 'url', and 'content' keys to match the
    format expected by SearchEngine.format_result_searxng().
    """
    client = _get_client()
    response = client.search_and_contents(
        query,
        num_results=NUM_RESULTS,
        highlights=True,
    )
    results = []
    for item in response.results:
        highlights = getattr(item, "highlights", None) or []
        content = " ".join(highlights) if highlights else (getattr(item, "text", "") or "")
        results.append({
            "title": getattr(item, "title", "") or "",
            "url": getattr(item, "url", "") or "",
            "content": content,
        })
    return results
