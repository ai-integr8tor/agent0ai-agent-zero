### opennotebook_sources:
manage research sources in Open Notebook notebooks

**Methods:**

- `list` — List all sources in a notebook. Shows name, type, processing status, and date added.
- `add` — Add a new source to a notebook. Auto-detects content type: URL (http/https) → File (known extension) → Text (default).
- `read` — Read the full content and metadata of a specific source.
- `delete` — Remove a source from Open Notebook. Requires confirmation if confirmations are enabled.

**Parameters:**
- `notebook_id` (string, required for list/add) — The notebook to work with; notebook names may be accepted when the tool resolves them
- `source_id` (string, required for read/delete) — The source ID
- `content` (string, required for add) — URL, file path, or text content to add
- `title` (string, optional for add) — Custom title for the source
- `confirmed` (string, "true"/"false") — Set to "true" to confirm add/delete operations

**Auto-detection cascade:** URL → File → Text (default)
- Starts with `http://` or `https://` → detected as URL
- Has known extension (.pdf, .doc, .txt, .md, etc.) → detected as File
- Everything else → treated as Text content

**When to use:**
- User says "what sources are in this notebook?" → use `list`
- User says "add this article/URL/text" → use `add`
- User says "show me what's in this source" → use `read`
- User says "remove/delete this source" → use `delete`

**Important:** Sources need processing time after being added. Use `opennotebook_sources:list` to check processing status.

usage:
~~~json
{
    "thoughts": ["User wants to add a source..."],
    "headline": "Adding source to notebook",
    "tool_name": "opennotebook_sources",
    "tool_args": {
        "method": "add",
        "notebook_id": "notebook-id",
        "content": "https://example.com/article"
    }
}
~~~
