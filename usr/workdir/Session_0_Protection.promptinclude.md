# Session 0 Protection (ENFORCED BY ARCHITECTURE)

> **This rule is enforced by the `_session_guard` plugin. Violations are auto-redirected, not merely logged.**

---

## CONSTRAINT

**Session 0 is for SHORT commands only (<30 seconds). ALL long-running processes MUST be delegated to `call_subordinate` or use session ≥1.**

This is not advisory. This is not a suggestion. The `_session_guard` plugin intercepts `code_execution_tool` calls in session 0 and automatically redirects high-risk commands.

## AUTOMATIC INTERVENTION

When the `_session_guard` plugin detects a potentially long-running command in session 0, it will:
1. **Auto-redirect** the command to a new session (1, 2, 3...)
2. **Log** the intervention with reasoning
3. **Continue** execution — no container lockup possible

## What Triggers Auto-Redirect (Risk Score ≥30)

| Pattern | Risk Score |
|---------|------------|
| KG pipeline / elastic_ingest / knowledge_ingest | +25 |
| LLM distillation, bulk/batch processing | +25 |
| `while True` loops | +50 |
| `sleep > 300` seconds | +30 |
| `asyncio.gather`, subprocess calls | +20 |
| Code length > 5000 chars | +40 |
| Code > 18 lines | +30 |

## What's Safe in Session 0 (Score 0)

- Status checks: `ls`, `ps`, `ss`, `curl`, `docker ps`, `whoami`, `pwd`
- File reads: `cat`, `grep`, `head`, `tail`, `find`, `stat`
- Short Python snippets (<6 lines, <5000 chars, <30s runtime)
- Configuration reads and simple queries

## Delegation Pattern (ALWAYS Use for Long Tasks)

Instead of:
```json
{"tool_name": "code_execution_tool", "tool_args": {"runtime": "python", "session": 0, "code": "bulk_process_all_files()"}}
```

Use:
```json
{"tool_name": "call_subordinate", "tool_args": {"profile": "developer", "message": "Run bulk_process_all_files.py and return results.", "reset": true}}
```

## Enforcement Timeline

| Phase | Mode | Behavior |
|-------|------|----------|
| Week 1 (current) | `warn` | Log warnings, allow execution |
| Week 2+ | `redirect` | Auto-redirect to session 1+ for score ≥30 |
| Emergency | `block` | Prevent execution entirely for score ≥50 |

## Why This Exists

Multiple container lockups occurred because long-running processes (KG ingest, LLM distillation, bulk file processing) were executed in session 0, starving the main agent process of resources. Advisory rules in the system prompt and behaviour_adjustment failed to prevent violations.

**"The guardrail, not the sign, prevents the fall."**

## Plugin Files

| File | Purpose |
|------|---------|
| `/a0/usr/plugins/_session_guard/plugin.yaml` | Manifest (`always_enabled: true`) |
| `/a0/usr/plugins/_session_guard/default_config.yaml` | Config (thresholds, patterns, mode) |
| `/a0/usr/plugins/_session_guard/extensions/python/tool_execute_before/_10_session_guard.py` | Main extension |
| `/a0/usr/workdir/logs/session_guard.log` | Intervention log (JSON lines) |
| `/a0/usr/workdir/logs/session_guard_stats.json` | Statistics |
