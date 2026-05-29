"""
Open Notebook Plugin - Notes Tool

Manages notes within Open Notebook notebooks. Notes are user-created text entries
that can be attached to notebooks for personal observations, summaries, or annotations.

Methods:
    list   — List all notes in a notebook (table view with title, type, dates)
    create — Add a new human-authored note to a notebook
    read   — Retrieve full content of a specific note by ID
    update — Modify an existing note's title and/or content
    delete — Remove a note (with optional confirmation gate)

Usage:
    First use `opennotebook_browse:notebooks` to get a notebook ID or name,
    then use `opennotebook_notes:list` with that value to see notes.
"""

from helpers.tool import Tool, Response

import sys
from pathlib import Path

# Add plugin root to path for shared imports (config, client, errors)
_plugin_root = str(Path(__file__).resolve().parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

import config
import client
import errors
sys.modules.pop('shared', None)
from shared import format_date, format_status, get_asset_type, handle_error

# Limits for display — prevents overwhelming output
_MAX_NOTES = 20

class OpenNotebookNotes(Tool):
    async def execute(self, **kwargs):
        """Route to the correct note method based on self.method.

        Supported methods: list, create, read, update, delete.
        Defaults to 'list' if no method is specified.

        Returns:
            Response: The result from the delegated method handler.
        """
        method = kwargs.get("action") or self.method or "list"

        if method == "list":
            # List all notes in a notebook — requires notebook_id
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            if notebook_id:
                try:
                    sys.modules.pop('shared', None)
                    from shared import resolve_notebook_id
                    notebook_id = await resolve_notebook_id(self.agent, notebook_id)
                except ValueError as e:
                    return Response(message=f"❌ **{e}**", break_loop=False)
            return await self._list(notebook_id)
        elif method == "create":
            # Create a new note — requires notebook_id, content, optional title
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            if notebook_id:
                try:
                    sys.modules.pop('shared', None)
                    from shared import resolve_notebook_id
                    notebook_id = await resolve_notebook_id(self.agent, notebook_id)
                except ValueError as e:
                    return Response(message=f"❌ **{e}**", break_loop=False)
            title = kwargs.get("title", "")
            content = kwargs.get("content", "")
            return await self._create(notebook_id, title, content)
        elif method == "read":
            # Read a single note by ID — requires note_id
            note_id = kwargs.get("note_id", "")
            return await self._read(note_id)
        elif method == "update":
            # Update an existing note — requires note_id, at least one of title/content
            note_id = kwargs.get("note_id", "")
            title = kwargs.get("title", "")
            content = kwargs.get("content", "")
            return await self._update(note_id, title, content)
        elif method == "delete":
            # Delete a note — requires note_id, optional confirmation
            note_id = kwargs.get("note_id", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._delete(note_id, confirmed)
        else:
            return Response(
                message=(
                    f"❌ **Unknown method '{method}'.**\n"
                    f"Available methods: `list`, `create`, `read`, `update`, `delete`.\n"
                    "Use `opennotebook_notes:list` to start browsing notes."
                ),
                break_loop=False,
            )

    async def _list(self, notebook_id: str) -> Response:
        """List all notes in a notebook in a markdown table.

        Args:
            notebook_id: The notebook to list notes from.

        Returns:
            Response: A markdown table of notes with title, type, created/updated dates,
                      or an error/empty-state message with navigation hints.
        """
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.**\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to see notes."
                ),
                break_loop=False,
            )

        # Build API request — GET /api/notes filtered by notebook
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notes"
        params = {"notebook_id": notebook_id}

        try:
            http_client = await client.get_client()
            response = await http_client.get(url, params=params)
            response.raise_for_status()
            notes = response.json()

            # Handle empty state — guide user to create their first note
            if not notes:
                return Response(
                    message=(
                        "📂 **No notes in this notebook yet.**\n"
                        "Use `opennotebook_notes:create` with a `notebook_id`, `title`, and `content` "
                        "to add your first note."
                    ),
                    break_loop=False,
                )

            # Build markdown table of notes (capped at _MAX_NOTES)
            lines = ["📂 **Notes**\n"]
            lines.append("| Title | Type | Created | Updated |")
            lines.append("|-------|------|---------|---------|")

            total = len(notes)
            for note in notes[:_MAX_NOTES]:
                title = note.get("title") or "Untitled"
                note_type = note.get("note_type") or "human"
                created = format_date(note.get("created", ""))
                updated = format_date(note.get("updated", ""))
                lines.append(f"| **{title}** | {note_type} | {created} | {updated} |")

            # Indicate truncation when there are more notes than displayed
            if total > _MAX_NOTES:
                remaining = total - _MAX_NOTES
                lines.append(
                    f"\n...and {remaining} more notes. "
                    f"Use `opennotebook_query:find` to locate specific items by name."
                )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _create(self, notebook_id: str, title: str, content: str) -> Response:
        """Create a new human-authored note in a notebook.

        Args:
            notebook_id: Target notebook for the new note.
            title: Optional title for the note.
            content: Required text content for the note.

        Returns:
            Response: Success message with note ID and title, or a validation error
                      with guidance on what to provide.
        """
        # Validate required notebook_id
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.**\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to create a note."
                ),
                break_loop=False,
            )

        # Validate required content — title is optional but content is mandatory
        if not content or not content.strip():
            return Response(
                message=(
                    "❌ **Content required.**\n"
                    "Provide `content` (the note text). You can also optionally provide a `title`.\n"
                    "Example: `opennotebook_notes:create` with `notebook_id`, `content='My note text'`."
                ),
                break_loop=False,
            )

        # Read-only mode prevents write operations
        if config.is_read_only(self.agent):
            return Response(
                message=(
                    "⚠️ **Plugin is in read-only mode.** Cannot create notes.\n"
                    "Use `opennotebook_config:settings` to check or change read-only mode."
                ),
                break_loop=False,
            )

        # Build API request — POST /api/notes with note_type 'human'
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notes"

        body = {
            "content": content.strip(),
            "note_type": "human",
            "notebook_id": notebook_id,
        }
        # Title is optional — only include if provided
        if title and title.strip():
            body["title"] = title.strip()

        try:
            http_client = await client.get_client()
            response = await http_client.post(url, json=body)
            response.raise_for_status()
            data = response.json()

            # Extract created note details from API response
            note_id = data.get("id", "unknown")
            note_title = data.get("title") or title or "Untitled"

            return Response(
                message=(
                    f"✅ **Note created successfully**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| ID | `{note_id}` |"
                    f"\n| Title | {note_title} |"
                    f"\n\n💡 Use `opennotebook_notes:read` with `note_id='{note_id}'` to view the full note, "
                    f"or `opennotebook_notes:list` to see all notes in this notebook."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _read(self, note_id: str) -> Response:
        """Read the full content of a specific note.

        Args:
            note_id: The unique ID of the note to retrieve.

        Returns:
            Response: Full note details including title, type, dates, and content,
                      or a 404/error message with navigation hint.
        """
        if not note_id:
            return Response(
                message=(
                    "❌ **Note ID required.**\n"
                    "Use `opennotebook_notes:list` to see available notes and their IDs, "
                    "then pass the ID here to read the full note."
                ),
                break_loop=False,
            )

        # Fetch note details — GET /api/notes/{note_id}
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notes/{note_id}"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)

            # Handle 404 — note may have been deleted or ID is wrong
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Note `{note_id}` not found.**\n"
                        "It may have been deleted. Use `opennotebook_notes:list` to see current notes."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()
            note = response.json()

            # Build detailed note view with metadata and full content
            lines = [
                f"📓 **{note.get('title') or 'Untitled'}**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| ID | `{note.get('id', '')}` |",
                f"| Type | {note.get('note_type', 'human')} |",
                f"| Created | {format_date(note.get('created', ''))} |",
                f"| Updated | {format_date(note.get('updated', ''))} |",
                f"\n**Content:**\n",
                note.get("content") or "*Empty note.*",
            ]

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _update(self, note_id: str, title: str, content: str) -> Response:
        """Update an existing note's title and/or content.

        This is a non-destructive operation (no confirmation gate needed).
        At least one of title or content must be provided.

        Args:
            note_id: The unique ID of the note to update.
            title: New title (optional — leave empty to keep current).
            content: New content (optional — leave empty to keep current).

        Returns:
            Response: Success message with updated note details, or a validation error.
        """
        if not note_id:
            return Response(
                message=(
                    "❌ **Note ID required.**\n"
                    "Use `opennotebook_notes:list` to see available notes and their IDs, "
                    "then pass the ID here to update a note."
                ),
                break_loop=False,
            )

        # Read-only mode prevents write operations
        if config.is_read_only(self.agent):
            return Response(
                message=(
                    "⚠️ **Plugin is in read-only mode.** Cannot update notes.\n"
                    "Use `opennotebook_config:settings` to check or change read-only mode."
                ),
                break_loop=False,
            )

        # Require at least one field to update — reject empty update requests
        if not title and not content:
            return Response(
                message=(
                    "❌ **Provide at least a `title` or `content` to update.**\n"
                    "Use `opennotebook_notes:read` to check current values before updating."
                ),
                break_loop=False,
            )

        # Build API request — PUT /api/notes/{note_id} with only changed fields
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notes/{note_id}"

        body = {}
        if title:
            body["title"] = title
        if content:
            body["content"] = content

        try:
            http_client = await client.get_client()
            response = await http_client.put(url, json=body)

            # Handle 404 — note may have been deleted
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Note `{note_id}` not found.**\n"
                        "It may have been deleted. Use `opennotebook_notes:list` to see current notes."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()
            data = response.json()

            # Display updated note details
            note_title = data.get("title") or "Untitled"
            updated = format_date(data.get("updated", ""))

            return Response(
                message=(
                    f"✅ **Note updated**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Title | {note_title} |"
                    f"\n| Updated | {updated} |"
                    f"\n\n💡 Use `opennotebook_notes:read` with `note_id='{note_id}'` to verify changes."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _delete(self, note_id: str, confirmed: bool) -> Response:
        """Delete a note permanently. Requires confirmation if confirmations are enabled.

        Args:
            note_id: The unique ID of the note to delete.
            confirmed: Whether the user has confirmed the deletion.

        Returns:
            Response: Deletion confirmation request, success message, or error.
        """
        if not note_id:
            return Response(
                message=(
                    "❌ **Note ID required.**\n"
                    "Use `opennotebook_notes:list` to see available notes and their IDs, "
                    "then pass the ID here to delete a note."
                ),
                break_loop=False,
            )

        # Read-only mode prevents destructive operations
        if config.is_read_only(self.agent):
            return Response(
                message=(
                    "⚠️ **Plugin is in read-only mode.** Cannot delete notes.\n"
                    "Use `opennotebook_config:settings` to check or change read-only mode."
                ),
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)

        # Confirmation gate — fetch note name first so user knows what they're deleting
        if config.needs_confirmation(self.agent) and not confirmed:
            try:
                http_client = await client.get_client()
                # Fetch note details to show in confirmation prompt
                response = await http_client.get(f"{api_url}/api/notes/{note_id}")
                if response.status_code == 200:
                    note_title = response.json().get("title") or "Untitled"
                else:
                    note_title = note_id
            except Exception:
                note_title = note_id

            return Response(
                message=(
                    f"⚠️ **Confirm deletion**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Note | **{note_title}** |"
                    f"\n| ID | `{note_id}` |"
                    f"\n\nThis action cannot be undone. Call again with `confirmed: true` to proceed."
                ),
                break_loop=False,
            )

        # Execute deletion — DELETE /api/notes/{note_id}
        url = f"{api_url}/api/notes/{note_id}"

        try:
            http_client = await client.get_client()
            # Fetch note name before deleting for the success message
            note_title = note_id
            try:
                get_resp = await http_client.get(url)
                if get_resp.status_code == 200:
                    note_title = get_resp.json().get("title") or note_id
            except Exception:
                pass

            response = await http_client.delete(url)

            # Handle 404 — note already gone or never existed
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Note `{note_id}` not found.** It may have already been deleted.\n"
                        "Use `opennotebook_notes:list` to see current notes."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()

            return Response(
                message=(
                    f"✅ **Note deleted:** {note_title}\n"
                    f"💡 Use `opennotebook_notes:list` to see remaining notes in the notebook."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

