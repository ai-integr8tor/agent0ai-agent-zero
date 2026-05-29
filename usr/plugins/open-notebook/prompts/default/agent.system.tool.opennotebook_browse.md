### opennotebook_browse:
browse and explore Open Notebook knowledge bases

**Methods:**

- `notebooks` — List all notebooks with name, source count, note count, and last updated date. Use for an overview of available knowledge bases.
- `notebook` — Get details for a specific notebook by ID. Name-based lookup may also be supported and resolved internally. Shows description, creation date, source/note counts, and archive status.
- `tree` — Show a hierarchical view of all notebooks with their source and note counts.

**When to use:**
- User asks "what notebooks do I have?" or "show my knowledge bases" → use `notebooks`
- User asks "what's in my knowledge base?" or "what's available?" → start with `notebooks` overview
- User asks about a specific notebook or says "tell me about notebook X" → use `notebook` with the notebook ID, or the notebook name when name-based lookup is supported
- User asks "show me everything" or "what does my knowledge base look like?" → use `tree`

**Parameters:**
- `notebook_id` (string, required for `notebook` method) — The notebook ID to retrieve details for; name-based lookup may be accepted and resolved internally

usage:
~~~json
{
    "thoughts": [
        "User wants to see their notebooks...",
    ],
    "headline": "Listing notebooks",
    "tool_name": "opennotebook_browse",
    "tool_args": {
        "method": "notebooks"
    }
}
~~~

~~~json
{
    "thoughts": [
        "User wants details on a specific notebook...",
    ],
    "headline": "Getting notebook details",
    "tool_name": "opennotebook_browse",
    "tool_args": {
        "method": "notebook",
        "notebook_id": "notebook-id-here"
    }
}
~~~

~~~json
{
    "thoughts": [
        "User wants a bird's eye view of everything...",
    ],
    "headline": "Showing knowledge base tree",
    "tool_name": "opennotebook_browse",
    "tool_args": {
        "method": "tree"
    }
}
~~~
