### opennotebook_notes:
manage notes in your Open Notebook knowledge base

**Methods:**

- `list` — List all notes in a notebook. Shows title, type, created and updated dates.
- `create` — Create a new note with title and content.
- `read` — Read the full content of a specific note.
- `update` — Update a note's title or content. No confirmation required.
- `delete` — Remove a note. Requires confirmation if confirmations are enabled.

**Parameters:**
- `notebook_id` (string, required for list/create) — The notebook to work with; notebook names may be accepted when the tool resolves them internally
- `note_id` (string, required for read/update/delete) — The note ID
- `title` (string, optional) — Note title
- `content` (string, required for create, optional for update) — Note body content
- `confirmed` (string, "true"/"false") — Set to "true" to confirm delete operations

**Collaborative note creation:**
When the user says "note this down", "make a note about X", or "remember this", capture their conversational content as the note body. Don't ask for structured input — compose the note from what they've said.

**When to use:**
- User says "show my notes" or "what notes do I have?" → use `list`
- User says "note this down" or "make a note" → use `create` with their content
- User says "show me note X" or "read my note" → use `read`
- User says "update/change note X" → use `update`
- User says "delete/remove note X" → use `delete`

**Important:** Notes are user-created content. Always confirm before deleting or significantly modifying user notes.

usage:
~~~json
{
    "thoughts": ["User wants to create a note..."],
    "headline": "Creating note",
    "tool_name": "opennotebook_notes",
    "tool_args": {
        "method": "create",
        "notebook_id": "notebook-id",
        "title": "My Note Title",
        "content": "The note content goes here"
    }
}
~~~
