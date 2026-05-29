"""
Open Notebook Plugin - Browse Tool

Provides notebook discovery: list, details, and tree view.
Use this tool to explore what notebooks exist and what they contain.

Methods:
    notebooks — List all notebooks (table view)
    notebook  — Get details for a single notebook by ID or name when supported
    tree      — Show hierarchical overview of all notebooks
"""

from helpers.tool import Tool, Response

import sys
from pathlib import Path

# Add plugin root to path for imports
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

# Limits
_MAX_NOTEBOOKS = 20   # Maximum notebooks shown in list view
_MAX_TREE_ITEMS = 50  # Threshold for compact vs full tree view

class OpenNotebookBrowse(Tool):
    async def execute(self, **kwargs):
        """Route to the requested browse method."""
        method = kwargs.get("action") or self.method or "notebooks"

        if method == "notebooks":
            return await self._notebooks()
        elif method == "notebook":
            notebook_id = kwargs.get("notebook_id", "")
            return await self._notebook(notebook_id)
        elif method == "tree":
            return await self._tree()
        else:
            return Response(
                message=(
                    f"❌ **Unknown method '{method}'.**\n"
                    "Available methods: `notebooks`, `notebook`, `tree`.\n"
                    "💡 Use `opennotebook_browse:notebooks` to list all notebooks, "
                    "or `opennotebook_browse:tree` for a hierarchical overview."
                ),
                break_loop=False,
            )

    async def _notebooks(self) -> Response:
        """List all notebooks with name, source count, note count, and last updated.

        Returns a markdown table of all notebooks. If no notebooks exist,
        suggests creating one in the Open Notebook UI.
        """
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notebooks"

        try:
            # Fetch all notebooks from the API
            http_client = await client.get_client()
            response = await http_client.get(url)
            response.raise_for_status()
            notebooks = response.json()

            # Handle empty state
            if not notebooks:
                return Response(
                    message=(
                        "📂 **No notebooks found.**\n"
                        "Create a new notebook in the Open Notebook UI, "
                        "then use `opennotebook_browse:notebooks` to see it here.\n"
                        "💡 Use `opennotebook_sources:add` to add content to a notebook."
                    ),
                    break_loop=False,
                )

            # Build markdown table of notebooks
            lines = ["📂 **Notebooks**\n"]
            lines.append("| ID | Name | Sources | Notes | Updated |")
            lines.append("|----|------|---------|-------|---------|")

            total = len(notebooks)
            for nb in notebooks[:_MAX_NOTEBOOKS]:
                name = nb.get("name", "Untitled")
                nb_id = nb.get('id', '')
                short_id = nb_id.split(':')[-1][-8:] if nb_id else 'N/A'
                source_count = nb.get("source_count", 0)
                note_count = nb.get("note_count", 0)
                updated = format_date(nb.get("updated", ""))
                lines.append(f"| `{short_id}` | **{name}** | {source_count} | {note_count} | {updated} |")

            lines.append("\n💡 Use the full notebook ID with `opennotebook_sources:list` or `opennotebook_sources:add`.")

            # Indicate if results were truncated
            if total > _MAX_NOTEBOOKS:
                remaining = total - _MAX_NOTEBOOKS
                lines.append(f"\n...and {remaining} more")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _notebook(self, notebook_id: str) -> Response:
        """Get details for a specific notebook by ID or name.

        Returns a key-value table with notebook metadata including
        source/note counts, dates, and archive status. Notebook lookup is
        resolved through the shared notebook resolver for consistent behavior.
        """
        # Validate required parameter
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.**\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to see details."
                ),
                break_loop=False,
            )

        # Resolve notebook names / partial IDs through the shared helper for consistent behavior
        try:
            sys.modules.pop('shared', None)
            from shared import resolve_notebook_id
            notebook_id = await resolve_notebook_id(self.agent, notebook_id)
        except ValueError as e:
            return Response(message=f"❌ **{e}**", break_loop=False)
        except Exception as e:
            api_url = config.get_api_url(self.agent)
            return Response(message=handle_error(e, f"{api_url}/api/notebooks"), break_loop=False)

        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notebooks/{notebook_id}"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)

            # Handle not found
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Notebook `{notebook_id}` not found.**\n"
                        "The notebook may have been deleted or the ID is incorrect.\n"
                        "💡 Use `opennotebook_browse:notebooks` to see all available notebooks."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()
            nb = response.json()

            # Build detail table
            lines = [
                f"📓 **{nb.get('name', 'Untitled')}**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| ID | `{nb.get('id', '')}` |",
                f"| Description | {nb.get('description', 'No description')} |",
                f"| Sources | {nb.get('source_count', 0)} |",
                f"| Notes | {nb.get('note_count', 0)} |",
                f"| Created | {format_date(nb.get('created', ''))} |",
                f"| Updated | {format_date(nb.get('updated', ''))} |",
                f"| Archived | {'Yes' if nb.get('archived') else 'No'} |",
            ]

            # Add navigation hints based on content
            src_count = nb.get('source_count', 0)
            note_count = nb.get('note_count', 0)
            hints = []
            if src_count > 0:
                hints.append(f"Use `opennotebook_sources:list` with this notebook ID to see its sources.")
            if note_count > 0:
                hints.append(f"Use `opennotebook_notes:list` with this notebook ID to see its notes.")
            if hints:
                lines.append(f"\n💡 {' | '.join(hints)}")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _tree(self) -> Response:
        """Show hierarchical view of all notebooks with source and note counts.

        Automatically switches between compact and full tree view based
        on the total number of items across all notebooks.
        """
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/notebooks"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)
            response.raise_for_status()
            notebooks = response.json()

            # Handle empty state
            if not notebooks:
                return Response(
                    message=(
                        "📂 **No notebooks found.**\n"
                        "Create a new notebook in the Open Notebook UI, "
                        "then use `opennotebook_browse:tree` to see the overview.\n"
                        "💡 Use `opennotebook_browse:notebooks` for a table view."
                    ),
                    break_loop=False,
                )

            # Count total items to decide compact vs full view
            total_items = sum(
                1 + nb.get("source_count", 0) + nb.get("note_count", 0)
                for nb in notebooks
            )

            lines = ["📁 **Knowledge Base Tree**\n"]

            if total_items > _MAX_TREE_ITEMS:
                # Compact view — too many items for full tree
                for nb in notebooks:
                    name = nb.get("name", "Untitled")
                    src = nb.get("source_count", 0)
                    notes = nb.get("note_count", 0)
                    lines.append(f"📂 **{name}** — {src} sources, {notes} notes")
                lines.append(
                    "\n💡 Use `opennotebook_browse:notebook` with a specific notebook ID "
                    "to expand and see its details."
                )
            else:
                # Full tree with source and note breakdown
                for nb in notebooks:
                    name = nb.get("name", "Untitled")
                    src = nb.get("source_count", 0)
                    notes = nb.get("note_count", 0)
                    lines.append(f"📂 **{name}** ({src} sources, {notes} notes)")
                    if src > 0:
                        lines.append(f"  └── 📄 {src} source(s)")
                    if notes > 0:
                        lines.append(f"  └── 📝 {notes} note(s)")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

