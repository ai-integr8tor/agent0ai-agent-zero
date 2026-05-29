### opennotebook_manage:
manage Open Notebook plugin connection status and configuration
usage:
~~~json
{
    "thoughts": [
        "Need to check Open Notebook connection...",
    ],
    "headline": "Checking Open Notebook status",
    "tool_name": "opennotebook_manage",
    "tool_args": {
        "method": "status"
    }
}
~~~

**Methods:**

- `status` — Check if Open Notebook is reachable and healthy. Use when you need to verify connectivity or troubleshoot connection issues.
- `config` — Display current plugin configuration (API URL, read-only mode, confirmation settings). Use when the user wants to see or verify their settings.

**When to use:**
- User asks "is Open Notebook connected?" or "check connection" → use `status`
- User asks "what are my settings?" or "show configuration" → use `config`
- Before performing any operation that requires Open Notebook connectivity → use `status` to verify
