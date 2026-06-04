# Development Priority Rule (MANDATORY)

> **Created:** 2026-06-03
> **Source:** User directive

---

## THE RULE

**When adding ANY new functionality to the Agent Zero platform, always follow this priority order:**

| Priority | Approach | When to Use |
|----------|----------|-------------|
| **1. PLUGIN FIRST** | Create a plugin in `/a0/usr/plugins/<name>/` | Default choice for ALL new features. Bundles tools, extensions, prompts, API endpoints, config. Self-contained, survives updates. |
| **2. SKILL SECOND** | Create a skill in `/a0/usr/skills/<name>/` with `SKILL.md` | When the feature is instructional guidance or reusable instructions rather than executable code. |
| **3. PATCH LAST** | Modify core framework files (`/a0/agent.py`, `/a0/models.py`, etc.) | LAST RESORT only when plugin/skill approaches are technically impossible. Must be documented and tracked. |

## Why This Order

| Approach | Survives Updates | Self-Contained | Discoverable | Maintainable |
|----------|----------------|---------------|--------------|-------------|
| **Plugin** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Easy |
| **Skill** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Easy |
| **Patch** | ❌ No | ❌ No | ❌ No | ❌ Fragile |

## Examples

| Feature | Correct Approach | Why |
|---------|-----------------|-----|
| Session guard (intercept tool calls) | **Plugin** (`_session_guard`) | Needs extension hook + config + prompts |
| Backup automation | **Plugin** (`_backup_manager`) | Needs tools + pipeline + helpers |
| KG pipeline scripts | **Plugin** (`_kg_pipeline`) | Needs tools + config + helpers |
| Meeting intelligence docs | **Skill** (`meeting-intelligence`) | Instructional guidance |
| LLM response format fix | **Patch** | Core framework bug, no plugin hook available |

## Plugin Structure Reference
```
/a0/usr/plugins/<name>/
├── plugin.yaml                    # Manifest (always_enabled: true for system plugins)
├── default_config.yaml            # Configuration
├── tools/                         # Agent tools
│   └── my_tool.py
├── extensions/python/<hook_point>/ # Lifecycle extensions
│   └── _10_my_extension.py
├── prompts/                       # Prompt fragments
│   └── agent.system.tool.my_tool.md
├── api/                           # Web UI endpoints (optional)
│   └── my_endpoint.py
└── helpers/                       # Internal helpers (optional)
    └── my_helper.py
```

## Extension Filename Uniqueness (MANDATORY)

**ALL extension files MUST have UNIQUE filenames across the ENTIRE framework.**

The framework (`/a0/helpers/extension.py` → `_get_extension_classes()`) deduplicates extensions by **filename only**. If two plugins have extensions with the same filename, only the **first** is kept — all others are **silently dropped** with no warning.

```
❌ WRONG: _10_force_subagent.py          (same name = deduplication collision)
✅ RIGHT: _10_force_subagent__plugin_name.py  (unique per plugin)
```

**Pattern:** `_<priority>_<descriptive_name>__<plugin_name>.py`

Before creating ANY extension:
1. `find /a0/ -path '*/<hook_point>/<your_filename>' -not -path '*__pycache__*'`
2. If ANY other plugin has the same filename, RENAME YOURS
3. Test with ACTUAL tool calls, not just file existence checks

## Enforcement

Before implementing ANY new feature, ask:
1. **Can this be a plugin?** → Yes? → Make it a plugin.
2. **Can this be a skill?** → Yes? → Make it a skill.
3. **Must this patch core code?** → Document WHY in the commit message.
