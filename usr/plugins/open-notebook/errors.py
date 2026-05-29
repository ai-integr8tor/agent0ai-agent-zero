"""
Open Notebook Plugin - Shared Error Handler

Translates HTTP and httpx exceptions into human-readable messages.
All tools route errors through these functions — never expose raw
status codes or Python tracebacks to the agent.
"""
try:
    import httpx
except ImportError:
    httpx = None  # lazy-loaded at runtime


# --- HTTP status code mappings ---

_STATUS_MESSAGES: dict[int, str] = {
    400: "Bad request — the data sent to Open Notebook was invalid.",
    401: "Authentication required — check your Open Notebook credentials.",
    403: "Permission denied — you don't have access to this resource.",
    404: "Resource not found — the requested item may have been deleted or the ID is incorrect.",
    409: "Conflict — the resource already exists or has been modified by another operation.",
    422: "Validation error — the request data didn't match the expected format.",
    429: "Rate limited — too many requests. Wait a moment and try again.",
    500: "Open Notebook server error — the service is experiencing issues.",
    502: "Bad gateway — Open Notebook may be starting up or misconfigured.",
    503: "Service unavailable — Open Notebook is temporarily unreachable or under maintenance.",
    504: "Gateway timeout — the request took too long on the server side.",
}


def format_timeout(operation: str) -> str:
    """Format a timeout error with operation context."""
    return (
        f"❌ **Timeout** while trying to {operation}.\n"
        "Open Notebook didn't respond within the expected time.\n"
        "\n**Suggested next steps:**\n"
        "- Check if Open Notebook is running and responsive\n"
        "- Verify the API URL in plugin settings\n"
        "- Try again in a few seconds"
    )


def format_connection_error() -> str:
    """Format a connection refused / unreachable error."""
    return (
        "❌ **Connection failed** — unable to reach Open Notebook.\n"
        "\n**Suggested next steps:**\n"
        "- Verify Open Notebook is running (check Docker status)\n"
        "- Check the API URL in plugin settings\n"
        "- Ensure the network allows connections to the configured host and port"
    )


def format_http_error(error) -> str:
    """Format an HTTP status error (4xx / 5xx) with specific guidance."""
    status_code = error.response.status_code
    message = _STATUS_MESSAGES.get(
        status_code,
        f"Unexpected HTTP error occurred."
    )

    # Try to extract the actual error detail from the API response
    api_detail = ""
    try:
        body = error.response.json()
        api_detail = body.get("detail", "")
    except Exception:
        pass

    # Use warning emoji for service-level issues (5xx), error for client issues (4xx)
    icon = "⚠️" if status_code >= 500 else "❌"

    result = f"{icon} **{message}"
    if api_detail:
        result += f"\n\n**Details:** {api_detail}"
    result += (
        f"\n\n**Suggested next steps:**\n"
        f"- Double-check the resource ID or parameters you provided\n"
        f"- Try the operation again in a moment\n"
        f"- If the problem persists, check Open Notebook logs for details"
    )
    return result


def format_unexpected(error: Exception) -> str:
    """Format an unexpected / unknown error (catch-all)."""
    return (
        f"❌ **Unexpected error** — something went wrong that wasn't anticipated.\n"
        f"\n**Suggested next steps:**\n"
        f"- Try the operation again\n"
        f"- Check if Open Notebook is running normally\n"
        f"- If this keeps happening, report it as a bug"
    )
