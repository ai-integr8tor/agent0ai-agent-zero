"""
Open Notebook Plugin - Sources Tool

Manages knowledge sources within Open Notebook notebooks. Sources are the raw content
(URLs, files, text) that get processed, chunked, and embedded into a vector store
for retrieval and note-taking.

Methods:
    list   — List all sources in a notebook (table view with name, type, status, date)
    add    — Add a new source with auto-detected type (URL, file, or text)
    read   — Retrieve full content and metadata of a specific source by ID
    delete — Remove a source permanently (with optional confirmation gate)

Usage:
    First use `opennotebook_browse:notebooks` to get a notebook ID or name,
    then use `opennotebook_sources:list` to see sources in that notebook.
    Add sources with `opennotebook_sources:add`, then use
    `opennotebook_query:find` to locate specific items by name.
"""

from helpers.tool import Tool, Response

import asyncio
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
_MAX_SOURCES = 20
_MAX_CONTENT_CHARS = 2000  # Truncate long source content for readability

# Known file extensions for auto-detection of file-type sources
_FILE_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.md', '.rtf', '.odt', '.epub', '.html', '.htm', '.csv'}


def _detect_and_prepare(content: str, title: str, notebook_id: str) -> tuple:
    """Auto-detect source type from content and build form-encoded request data.

    Detection logic:
        - URL (http:// or https://) → type 'link', sets 'url' field
        - File path with known extension → type 'text', sets 'content' field
        - Everything else → type 'text', sets 'content' field (raw text)

    Args:
        content: The raw content string (URL, file path, or text).
        title: Optional title for the source (may be empty string).
        notebook_id: Target notebook ID.

    Returns:
        tuple: (source_type_string, request_data_dict) where request_data_dict
               is suitable for the ``data=`` parameter of httpx.post (form-encoded).
    """
    # Build base data dict with required fields
    # embed='true' triggers automatic vector embedding after processing
    # async_processing='true' so the source add returns immediately
    request_data = {
        "notebook_id": notebook_id,
        "title": title or "",
        "embed": "true",
        "async_processing": "true",
    }

    # Detect source type from content
    lower_content = content.lower()
    if lower_content.startswith(("http://", "https://")):
        source_type = "link"
        request_data["type"] = "link"
        request_data["url"] = content
    else:
        # Check if content looks like a file path with a known extension
        import os
        _, ext = os.path.splitext(content)
        if ext.lower() in _FILE_EXTENSIONS:
            source_type = "text"
            request_data["type"] = "text"
            request_data["content"] = content  # file path reference
        else:
            source_type = "text"
            request_data["type"] = "text"
            request_data["content"] = content  # raw text

    return source_type, request_data


class OpenNotebookSources(Tool):
    async def execute(self, **kwargs):
        """Route to the correct source method based on self.method.

        Supported methods: list, add, read, delete.
        Defaults to 'list' if no method is specified.

        Returns:
            Response: The result from the delegated method handler.
        """
        method = kwargs.get("action") or self.method or "list"

        if method == "list":
            # List all sources in a notebook — requires notebook_id
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            if notebook_id:
                try:
                    sys.modules.pop('shared', None)
                    from shared import resolve_notebook_id
                    notebook_id = await resolve_notebook_id(self.agent, notebook_id)
                except ValueError as e:
                    return Response(message=f"❌ **{e}**", break_loop=False)
            return await self._list(notebook_id)
        elif method == "add":
            # Add a new source — auto-detects type from content (URL, file, text)
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            if notebook_id:
                try:
                    sys.modules.pop('shared', None)
                    from shared import resolve_notebook_id
                    notebook_id = await resolve_notebook_id(self.agent, notebook_id)
                except ValueError as e:
                    return Response(message=f"❌ **{e}**", break_loop=False)
            content = kwargs.get("content", "") or kwargs.get("url", "")
            title = kwargs.get("title", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._add(notebook_id, content, title, confirmed)
        elif method == "read":
            # Read full source content — requires source_id
            notebook_id = kwargs.get("notebook_id", "") or kwargs.get("notebook", "")
            source_id = kwargs.get("source_id", "") or kwargs.get("source", "")
            return await self._read(source_id)
        elif method == "delete":
            # Delete a source permanently — requires source_id, optional confirmation
            source_id = kwargs.get("source_id", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._delete(source_id, confirmed)
        else:
            return Response(
                message=(
                    f"❌ **Unknown method '{method}'.**\n"
                    f"Available methods: `list`, `add`, `read`, `delete`.\n"
                    "Use `opennotebook_sources:list` to start browsing sources."
                ),
                break_loop=False,
            )

    async def _list(self, notebook_id: str) -> Response:
        """List all sources in a notebook in a markdown table.

        Args:
            notebook_id: The notebook to list sources from.

        Returns:
            Response: A markdown table of sources with name, type, processing status,
                      and date added, or an error/empty-state message with navigation hints.
        """
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.**\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to see sources."
                ),
                break_loop=False,
            )

        # Build API request — GET /api/sources filtered by notebook
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/sources"
        params = {"notebook_id": notebook_id, "limit": _MAX_SOURCES + 1}

        try:
            http_client = await client.get_client()
            response = await http_client.get(url, params=params)
            response.raise_for_status()
            sources = response.json()

            # Handle empty state — guide user to add their first source
            if not sources:
                return Response(
                    message=(
                        "📂 **No sources in this notebook yet.**\n"
                        "Use `opennotebook_sources:add` with a `notebook_id` and `content` "
                        "(URL, file path, or text) to add your first source."
                    ),
                    break_loop=False,
                )

            # Build markdown table of sources (capped at _MAX_SOURCES)
            lines = ["📂 **Sources**\n"]
            lines.append("| Name | Type | Status | Added |")
            lines.append("|------|------|--------|-------|")

            total = len(sources)
            for src in sources[:_MAX_SOURCES]:
                name = src.get("title") or "Untitled"
                source_type = get_asset_type(src)
                status = format_status(src.get("status"))
                created = format_date(src.get("created", ""))
                lines.append(f"| **{name}** | {source_type} | {status} | {created} |")

            # Indicate truncation when there are more sources than displayed
            if total > _MAX_SOURCES:
                remaining = total - _MAX_SOURCES
                lines.append(
                    f"\n...and {remaining} more sources. "
                    f"Use `opennotebook_query:find` to locate specific items by name."
                )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _add(self, notebook_id: str, content: str, title: str, confirmed: bool) -> Response:
        """Add a source to a notebook with auto-detected type.

        The content type is automatically detected from the input:
        - URLs (http:// or https://) → type 'link'
        - File paths with known extensions → type 'text' (file reference)
        - Everything else → type 'text' (plain text content)

        Args:
            notebook_id: Target notebook for the new source.
            content: The source content — a URL, file path, or text.
            title: Optional title for the source.
            confirmed: Whether the user has confirmed the addition.

        Returns:
            Response: Success message with source ID and detected type, or a
                      validation/confirmation/error message with guidance.
        """
        # Validate required notebook_id
        if not notebook_id:
            return Response(
                message=(
                    "❌ **Notebook ID required.**\n"
                    "Use `opennotebook_browse:notebooks` to list all notebooks and their IDs, "
                    "then pass the ID here to add a source."
                ),
                break_loop=False,
            )

        # Validate required content — must be a URL, file path, or text
        if not content or not content.strip():
            return Response(
                message=(
                    "❌ **Content required.**\n"
                    "Provide a URL (starts with http:// or https://), a file path, or text content.\n"
                    "Example: `opennotebook_sources:add` with `notebook_id` and `content='https://example.com'`."
                ),
                break_loop=False,
            )

        # Read-only mode prevents write operations
        if config.is_read_only(self.agent):
            return Response(
                message=(
                    "⚠️ **Plugin is in read-only mode.** Cannot add sources.\n"
                    "Use `opennotebook_config:settings` to check or change read-only mode."
                ),
                break_loop=False,
            )

        # Auto-detect content type and prepare request data
        content = content.strip()
        source_type, request_data = _detect_and_prepare(content, title, notebook_id)

        # Confirmation gate — show detected type and content preview before adding
        if config.needs_confirmation(self.agent) and not confirmed:
            return Response(
                message=(
                    f"⚠️ **Confirm adding source**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Detected Type | {source_type} |"
                    f"\n| Notebook | `{notebook_id}` |"
                    f"\n| Content Preview | {content[:100]}{'...' if len(content) > 100 else ''} |"
                    f"\n\nTo confirm, call again with `confirmed: true`."
                ),
                break_loop=False,
            )

        # Send request — POST /api/sources with form-encoded data
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/sources"

        try:
            http_client = await client.get_client()
            response = await http_client.post(url, data=request_data)
            response.raise_for_status()
            data = response.json()

            # Extract created source details from API response
            source_id = data.get("id", "unknown")
            source_title = data.get("title") or title or "Untitled"
            status = data.get("status", "unknown")

            # Start insight generation in the background (fire-and-forget)
            asyncio.create_task(self._generate_insight(source_id))

            # Build response with source details
            lines = [
                f"✅ **Source added successfully**",
                f"",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| ID | `{source_id}` |",
                f"| Title | {source_title} |",
                f"| Type | {source_type} |",
                f"| Status | {format_status(status)} |",
            ]

            lines.append(
                f"\n💡 Source is processing. Insights will be generated automatically. "
                f"Use `opennotebook_sources:list` to check processing status."
            )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _read(self, source_id: str) -> Response:
        """Read the full content and metadata of a specific source.

        Args:
            source_id: The unique ID of the source to retrieve.

        Returns:
            Response: Full source details including type, status, processing info,
                      embedded chunk count, and content (truncated if very long),
                      or a 404/error message with navigation hint.
        """
        if not source_id:
            return Response(
                message=(
                    "❌ **Source ID required.**\n"
                    "Use `opennotebook_sources:list` to see available sources and their IDs, "
                    "then pass the ID here to read the full source."
                ),
                break_loop=False,
            )

        # Fetch source details — GET /api/sources/{source_id}
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/sources/{source_id}"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)

            # Handle 404 — source may have been deleted or ID is wrong
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Source `{source_id}` not found.**\n"
                        "It may have been deleted. Use `opennotebook_sources:list` to see current sources."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()
            src = response.json()

            # Build metadata section with source details
            source_title = src.get("title") or "Untitled"
            source_type = get_asset_type(src)
            status = format_status(src.get("status"))
            created = format_date(src.get("created", ""))
            updated = format_date(src.get("updated", ""))
            chunks = src.get("embedded_chunks", 0)

            lines = [
                f"📓 **{source_title}**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| ID | `{src.get('id', '')}` |",
                f"| Type | {source_type} |",
                f"| Status | {status} |",
                f"| Created | {created} |",
                f"| Updated | {updated} |",
                f"| Chunks | {chunks} |",
            ]

            # Show processing error details if source failed to process
            proc_info = src.get("processing_info")
            if proc_info and isinstance(proc_info, dict) and status == "❌ failed":
                error_msg = proc_info.get("error", "") or proc_info.get("message", "")
                if error_msg:
                    lines.append(f"| Error | {error_msg[:200]} |")

            # Content section — truncated if exceeding display limit
            full_text = src.get("full_text")
            if full_text:
                lines.append(f"\n**Content:**\n")
                if len(full_text) > _MAX_CONTENT_CHARS:
                    # Truncate long content and suggest UI for full view
                    lines.append(full_text[:_MAX_CONTENT_CHARS])
                    lines.append(
                        f"\n...content truncated at {_MAX_CONTENT_CHARS} characters. "
                        f"Use the Open Notebook UI for the full content."
                    )
                else:
                    lines.append(full_text)
            else:
                # Content not yet available — source may still be processing
                lines.append(
                    "\n*Content not available or still processing. "
                    "Use `opennotebook_sources:list` to check the processing status.*"
                )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _delete(self, source_id: str, confirmed: bool) -> Response:
        """Delete a source permanently. Requires confirmation if confirmations are enabled.

        Args:
            source_id: The unique ID of the source to delete.
            confirmed: Whether the user has confirmed the deletion.

        Returns:
            Response: Deletion confirmation request, success message, or error.
        """
        if not source_id:
            return Response(
                message=(
                    "❌ **Source ID required.**\n"
                    "Use `opennotebook_sources:list` to see available sources and their IDs, "
                    "then pass the ID here to delete a source."
                ),
                break_loop=False,
            )

        # Read-only mode prevents destructive operations
        if config.is_read_only(self.agent):
            return Response(
                message=(
                    "⚠️ **Plugin is in read-only mode.** Cannot delete sources.\n"
                    "Use `opennotebook_config:settings` to check or change read-only mode."
                ),
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)

        # Confirmation gate — fetch source name first so user knows what they're deleting
        if config.needs_confirmation(self.agent) and not confirmed:
            try:
                http_client = await client.get_client()
                # Fetch source details to show in confirmation prompt
                response = await http_client.get(f"{api_url}/api/sources/{source_id}")
                if response.status_code == 200:
                    src = response.json()
                    source_title = src.get("title") or "Untitled"
                else:
                    source_title = source_id
            except Exception:
                source_title = source_id

            return Response(
                message=(
                    f"⚠️ **Confirm deletion**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Source | **{source_title}** |"
                    f"\n| ID | `{source_id}` |"
                    f"\n\nThis action cannot be undone. Call again with `confirmed: true` to proceed."
                ),
                break_loop=False,
            )

        # Execute deletion — DELETE /api/sources/{source_id}
        url = f"{api_url}/api/sources/{source_id}"

        try:
            http_client = await client.get_client()
            # Fetch source name before deleting for the success message
            source_title = source_id
            try:
                get_resp = await http_client.get(url)
                if get_resp.status_code == 200:
                    source_title = get_resp.json().get("title") or source_id
            except Exception:
                pass

            response = await http_client.delete(url)

            # Handle 404 — source already gone or never existed
            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Source `{source_id}` not found.** It may have already been deleted.\n"
                        "Use `opennotebook_sources:list` to see current sources."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()

            return Response(
                message=(
                    f"✅ **Source deleted:** {source_title}\n"
                    f"💡 Use `opennotebook_sources:list` to see remaining sources in the notebook."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _generate_insight(self, source_id: str) -> str:
        """Background task: embed source and generate insights after processing.

        Follows the same flow as the Open Notebook web app:
        1. Poll source status until processing is complete
        2. Trigger vector embedding via POST /api/embed
        3. Fetch available transformations and find the default
        4. Check for existing insights (skip if present)
        5. POST to generate an insight
        6. Poll until insight results are available

        This method never raises — all errors are silently handled
        so the source add operation always succeeds.

        Args:
            source_id: The ID of the newly created source.

        Returns:
            str: An informational note about the result,
                 or an empty string if nothing noteworthy to report.
        """
        api_url = config.get_api_url(self.agent)

        try:
            http_client = await client.get_client()

            # ── Step 1: Poll source status until ready ──────────────────
            # Source must finish processing before insights can be generated.
            # Poll every 3s, max 60 attempts (~3 minutes).
            status_url = f"{api_url}/api/sources/{source_id}/status"
            for attempt in range(60):
                try:
                    status_resp = await http_client.get(status_url)
                    if status_resp.status_code == 200:
                        status_data = status_resp.json()
                        current_status = status_data.get("status", "unknown")
                        if current_status not in ("pending", "processing"):
                            break
                except Exception:
                    pass
                await asyncio.sleep(3)
            else:
                # Timeout — source still processing
                return (
                    "⏳ **Source processing still in progress.** "
                    "Insight generation will need to be triggered later via the Open Notebook UI "
                    "once processing completes."
                )

            # Check if source ended in a failed state
            if current_status in ("failed", "error"):
                return (
                    f"⚠️ **Source processing failed** (status: {current_status}). "
                    f"Embedding and insight generation skipped."
                )

            # ── Step 2: Trigger automatic embedding ───────────────────
            # The POST /api/sources embed form field alone doesn't trigger
            # vector embedding. We must call POST /api/embed explicitly.
            try:
                embed_resp = await http_client.post(
                    f"{api_url}/api/embed",
                    json={"item_id": source_id, "item_type": "source"},
                )
                if embed_resp.status_code == 200:
                    embed_data = embed_resp.json()
                    # Embedding is async — just fire and move on
                else:
                    # Non-fatal — embedding can be triggered manually later
                    pass
            except Exception:
                pass  # Non-fatal — continue to insight generation

            # ── Step 3: Fetch transformations and find default ──────────
            transforms_url = f"{api_url}/api/transformations"
            transforms_resp = await http_client.get(transforms_url)
            transforms_resp.raise_for_status()
            transformations = transforms_resp.json()

            if not transformations:
                return (
                    "💡 No transformations configured for insight generation. "
                    "Configure transformations in the Open Notebook UI to enable automatic insights."
                )

            # Find the default transformation, or fall back to the first one
            default_transform = next(
                (t for t in transformations if t.get("apply_default")),
                transformations[0],
            )
            transformation_id = default_transform.get("id")
            transformation_name = default_transform.get("name", "Unnamed")

            # ── Step 3: Check for existing insights ─────────────────────
            insights_url = f"{api_url}/api/sources/{source_id}/insights"
            existing_resp = await http_client.get(insights_url)
            if existing_resp.status_code == 200:
                existing_insights = existing_resp.json()
                if existing_insights:
                    # Already have insights — no need to generate
                    summary = existing_insights[0].get("summary", "")
                    preview = summary[:300] + ("..." if len(summary) > 300 else "") if summary else ""
                    note = (
                        f"🧠 **Insight already exists** (transformation: {transformation_name})."
                    )
                    if preview:
                        note += f"\n> {preview}"
                    return note

            # ── Step 4: Generate insight via POST ────────────────────────
            gen_resp = await http_client.post(
                insights_url,
                json={"transformation_id": transformation_id},
            )
            gen_resp.raise_for_status()
            # API returns 202 Accepted (async processing)

            # ── Step 5: Poll for insight results ─────────────────────────
            # Poll every 2s, max 30 attempts (~60 seconds).
            insight_summary = ""
            for poll_attempt in range(30):
                await asyncio.sleep(2)
                try:
                    poll_resp = await http_client.get(insights_url)
                    if poll_resp.status_code == 200:
                        insights = poll_resp.json()
                        if insights:
                            # Extract the summary from the first completed insight
                            insight_summary = insights[0].get("summary", "")
                            break
                except Exception:
                    pass

            # ── Step 6: Build result note ────────────────────────────────
            if insight_summary:
                preview = insight_summary[:500]
                truncation = "..." if len(insight_summary) > 500 else ""
                return (
                    f"🧠 **Insight generated** (transformation: {transformation_name})\n"
                    f"\n> {preview}{truncation}"
                )
            else:
                return (
                    f"⏳ **Insight generation in progress** (transformation: {transformation_name}). "
                    f"The insight is being processed asynchronously. Check back with "
                    f"`opennotebook_sources:read` for the source `{source_id}`."
                )

        except Exception as e:
            # Never fail the add operation — just note the insight failure
            error_msg = str(e)[:200]
            return f"⚠️ **Insight generation failed:** {error_msg}"
