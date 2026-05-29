---
name: open-notebook-research
description: >
  Query and research your Open Notebook knowledge base using name-based
  lookup with fuzzy matching.
version: 1.1.0
tags: ["research", "query", "find", "knowledge", "lookup"]
triggers:
  - find source
  - research topic
  - find note
  - query notebook
  - look up source
  - open notebook research
---

# Research & Lookup — Name-Based Search Skill

Look up specific sources and notes in your Open Notebook knowledge base by name.
Use when you need to find a specific item or check if content exists.

## Method: find — Lookup by Name

Finds a specific source or note by name within a notebook. Uses fuzzy matching.

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

**Tips:**
- The name match is case-insensitive and supports partial matches
- You can pass a notebook name instead of an ID — it will be resolved automatically
- Results include both sources and notes

## Research Workflow

1. `opennotebook_browse:notebooks` → identify the right notebook
2. `opennotebook_query:find` → look up items by name
3. `opennotebook_sources:read` → read full source content if needed
4. `opennotebook_notes:create` → save findings as a note

## Cross-Tool Navigation

- Want to explore a notebook? → `opennotebook_browse:notebook` for details
- Found an interesting source? → `opennotebook_sources:read` for full content
- Want to save a finding? → `opennotebook_notes:create` to capture it

## Honest Boundaries

Always acknowledge when items are not found:
- "No item matching 'X' was found in this notebook."
- Suggest browsing all sources with `opennotebook_sources:list`.
