### opennotebook_query:
look up sources and notes by name

**Methods:** `find`

**Key params:**
- `name` (string) — item name to locate
- `notebook_id` (string) — scope to notebook (required, but notebook names may be accepted when the tool resolves them internally)

usage:
~~~json
{
    "tool_name": "opennotebook_query",
    "tool_args": {
        "method": "find",
        "notebook_id": "notebook-id-or-name",
        "name": "item name or partial name"
    }
}
~~~
