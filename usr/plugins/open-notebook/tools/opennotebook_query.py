"""
Open Notebook Plugin - Query Tool

Provides name-based lookup for sources and notes within Open Notebook notebooks.

Methods:
    find   — Look up a specific source or note by name within a notebook.
             Uses fuzzy name matching for flexible lookups.

Usage:
    First use `opennotebook_browse:notebooks` to get a notebook ID or name,
    then use `opennotebook_query:find` to locate specific items by name within that notebook.
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

class OpenNotebookQuery(Tool):
    async def execute(self, **kwargs):
        """Route to the correct query method based on self.method.

        Supported methods: find.
        Defaults to 'find' if no method is specified.

        Returns:
            Response: The result from the delegated method handler.
        """
        method = kwargs.get("action") or self.method or "find"

        if method == "find":
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            if notebook_id:
                try:
                    sys.modules.pop('shared', None)
                    from shared import resolve_notebook_id
                    notebook_id = await resolve_notebook_id(self.agent, notebook_id)
                except ValueError as e:
                    return Response(message=f"❌ **{e}**", break_loop=False)
            name = kwargs.get("name", "")
            return await self._find(notebook_id, name)
        else:
            return Response(
                message=(
                    f"❌ **Unknown method '{method}'.**\n"
                    f"Available method: `find`.\n"
                    "Use `opennotebook_query:find` with a `notebook_id` and `name` to look up items."
                ),
                break_loop=False,
            )

    async def _find(self, notebook_id: str, name: str) -> Response:
        """Find a specific source or note by name within a notebook.

        Uses case-insensitive fuzzy matching — the search term can be a substring
        of the actual name, or vice versa.

        Args:
            notebook_id: The notebook to search within (required — find is notebook-scoped).
            name: The name or identifier to search for.

        Returns:
            Response: A table of matching items with type, name, ID, and status,
                      or a not-found message with alternative search suggestions.
        """
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.** Find is notebook-scoped.\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to search within a specific notebook."
                ),
                break_loop=False,
            )

        # Validate required name parameter
        if not name:
            return Response(
                message=(
                    "❌ **Name required.**\n"
                    "Provide the name or partial name to search for. "
                    "Use `opennotebook_sources:list` to browse all sources in the notebook."
                ),
                break_loop=False,
            )

        # Fetch all sources in this notebook for local fuzzy matching
        api_url = config.get_api_url(self.agent)

        try:
            http_client = await client.get_client()

            # Search sources in this notebook — GET /api/sources filtered by notebook
            sources_url = f"{api_url}/api/sources"
            source_response = await http_client.get(
                sources_url, params={"notebook_id": notebook_id, "limit": 100}
            )
            source_response.raise_for_status()
            sources = source_response.json()

            # Also fetch notes in this notebook for fuzzy matching
            notes_url = f"{api_url}/api/notes"
            note_response = await http_client.get(
                notes_url, params={"notebook_id": notebook_id}
            )
            note_response.raise_for_status()
            notes = note_response.json()

            # Filter by name similarity — case-insensitive substring matching
            name_lower = name.lower()
            matches = []
            for src in sources:
                title = (src.get("title") or "").lower()
                # Bidirectional substring match for flexibility
                if name_lower in title or title in name_lower:
                    matches.append({
                        "type": "source",
                        "name": src.get("title") or "Untitled",
                        "id": src.get("id", ""),
                        "status": src.get("status", ""),
                    })

            # Also match notes by name
            for note in notes:
                note_title = (note.get("title") or note.get("name") or "").lower()
                if name_lower in note_title or note_title in name_lower:
                    matches.append({
                        "type": "note",
                        "name": note.get("title") or note.get("name") or "Untitled",
                        "id": note.get("id", ""),
                        "status": note.get("status", ""),
                    })

            # Handle no matches — suggest broader search alternatives
            if not matches:
                return Response(
                    message=(
                        f"🔍 **No item found matching '{name}' in this notebook.**\n"
                        "Try a different name, or use `opennotebook_browse:notebook` to browse the notebook contents."
                    ),
                    break_loop=False,
                )

            # Build results table with matched items
            lines = [f"🔍 **Found {len(matches)} match(es)**\n"]
            lines.append("| Type | Name | ID | Status |")
            lines.append("|------|------|----|--------|")

            for m in matches:
                status = m.get("status", "") or "completed"
                lines.append(f"| {m['type']} | **{m['name']}** | `{m['id']}` | {status} |")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, f"{api_url}/api/sources"), break_loop=False)
