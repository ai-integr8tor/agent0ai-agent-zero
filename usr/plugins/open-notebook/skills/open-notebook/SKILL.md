---
name: open-notebook
description: >
  Open Notebook plugin meta-skill. Provides tool map, user journeys,
  first-time setup guidance, and cross-tool orchestration for the
  Open Notebook personal knowledge management plugin.
version: 1.1.0
tags: ["open-notebook", "plugin", "knowledge", "management", "orchestration"]
triggers:
  - open notebook
  - knowledge base
  - notebooks
  - sources
  - what notebooks do I have
  - show my knowledge
---

# Open Notebook — Plugin Meta-Skill

Open Notebook personal knowledge management plugin for Agent Zero.
Provides AI-powered notebooks, source management, name-based lookup, and podcast generation.

Use when the user mentions Open Notebook, knowledge base, notebooks, sources, or podcasts.

## Available Tools

| Tool | Purpose | Key Methods |
|------|---------|-------------|
| `opennotebook_browse` | Explore notebooks | `notebooks`, `notebook`, `tree` |
| `opennotebook_manage` | Connection, config, and notebook creation | `status`, `config`, `create` |
| `opennotebook_sources` | Manage content sources | `list`, `add`, `read`, `delete` |
| `opennotebook_notes` | Manage notes | `list`, `create`, `read`, `update`, `delete` |
| `opennotebook_query` | Name-based lookup | `find` |
| `opennotebook_podcasts` | Podcast generation | `profiles`, `generate`, `status`, `list`, `get`, `retry`, `delete` |

## User Journey Maps

### Explore Knowledge Base
1. `opennotebook_browse:notebooks` → see all notebooks (includes short ID column)
2. `opennotebook_browse:notebook` → inspect a specific notebook by full ID, or by name (case-insensitive, emoji-stripped)
3. `opennotebook_sources:list` → see sources in that notebook
4. `opennotebook_query:find` → look up specific items by name within a resolved notebook

### Research a Topic
1. Use the **open-notebook-research** skill for guided query workflow
2. If the user names a notebook, use that notebook first; if not, resolve an appropriate notebook by name or ID before searching
3. `opennotebook_query:find` → locate specific items by name
4. `opennotebook_notes:create` → save findings as a note

### Add Content (Updated Workflow)
1. If the user names a notebook, use that notebook first; otherwise use `opennotebook_browse:notebooks` to pick a notebook by name or ID
2. **Prepare Content**:
   - If the user provides a **URL** starting with `http://` or `https://`, pass it directly to the tool.
   - If the user provides a **local file path** (e.g., `/a0/usr/workdir/file.txt`, `document.pdf`), pass the path directly to the tool:
     - The tool **automatically detects** and **reads local files** with known extensions (.pdf, .doc, .docx, .txt, .md, .rtf, .odt, .epub, .html, .htm, .csv)
     - The file content is extracted and sent to the backend, not the file path itself
     - This is consistent across all tools: `opennotebook_sources:add`, `opennotebook_notes:create`, `opennotebook_notes:update`, and `opennotebook_podcasts:generate`
   - If the file path is invalid or the file doesn't exist, the tool returns a user-friendly error message.
3. `opennotebook_sources:add` → add content. The tool supports parameter aliases:
   - Use `notebook` OR `notebook_id`
   - Use `url` OR `content` (for URLs)
   - Use `source` OR `source_id` (for lookups)
4. **Tool Behavior**:
   - The tool detects if content is a URL (type `link`) or raw text (type `text`).
   - **Local file paths are automatically detected and read** - no manual file reading required.
5. **Confirmation Gate**: If enabled, the tool shows the detected type and preview. Retry using the exact confirmation format requested (handle both boolean and string confirmations).
6. **Async Processing**: Content is added immediately. Insight generation happens asynchronously (non-blocking), so you don't need to wait 3-4 minutes anymore.
7. `opennotebook_sources:list` → verify content was added

### Create a Podcast
1. Use the **open-notebook-podcast** skill for the full async workflow
2. `opennotebook_podcasts:profiles` → pick profiles
3. `opennotebook_podcasts:generate` → start generation (returns job_id)
4. Wait 3-5 min → `opennotebook_podcasts:status` → check progress
5. Repeat until complete → `opennotebook_podcasts:get` → retrieve episode

## First-Time Setup

1. `opennotebook_manage:status` → verify connection to port 5055
2. `opennotebook_browse:notebooks` → see existing notebooks
3. If empty → use `opennotebook_manage:create` to create your first notebook
4. `opennotebook_sources:add` → add content to your new notebook

## Workflow Notes

- **Parameter Aliases**: The `sources` tool accepts `notebook` (alias for `notebook_id`), `url` (alias for `content`), and `source` (alias for `source_id`).
- **Name Resolution**:
  - `browse` and `sources` tools support name-based lookup (case-insensitive, emoji-stripped).
  - `sources` tool supports short ID suffix matching (e.g., `abc12345` for `notebook:xyzabc12345`).
  - `browse` tool currently requires full ID or name match; use `browse:notebooks` to get the full short ID if needed.
- **Prefer** the notebook explicitly requested by the user over any default notebook.
- **Add-source confirmation flows** should not crash if the tool receives either a boolean-like or string-like confirmation value.
- **Insights** are now generated asynchronously; do not wait for them before proceeding.
- **create_if_missing**: When adding sources, you can use `create_if_missing: true` to automatically create a notebook if it doesn't exist. This follows safety patterns (respects read-only mode and confirmation gates).

## Error Guidance

| Error Scenario | Possible Cause | Resolution |
|----------------|----------------|------------|
| "Notebook not found" | Typo in name, or using short ID in browse, or notebook doesn't exist | Check spelling (case-insensitive), ensure emojis are stripped, or use the full ID from `browse:notebooks` table. If the notebook doesn't exist, use `opennotebook_manage:create` to create it, or use `create_if_missing: true` when adding sources to auto-create. |
| "Source add failed" | Invalid URL path, file not found, or API error | Verify the URL is reachable. For files, ensure the path is correct. Check `opennotebook_manage:status` for backend health. |
| "Confirmation required" | Read-only mode or confirmation gate enabled | Retry with `confirmed: true` or `confirmed: "yes"` as requested by the tool. Check `opennotebook_manage:config` if this is unexpected. |
| "Name resolution failed" | Multiple notebooks with similar names | Use the unique notebook ID instead of the name to disambiguate. |

## Plugin Configuration

Use `opennotebook_manage:config` to view settings:
- **API URL** — Open Notebook backend address
- **Read Only** — prevents write/delete operations
- **Confirmations** — requires confirmation before destructive ops

## Prerequisites

- Open Notebook backend running on port 5055
- Plugin enabled in Agent Zero
