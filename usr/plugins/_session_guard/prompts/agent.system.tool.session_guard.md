# Session Guard - Enforcement Notice

This plugin monitors `code_execution_tool` calls in session 0 and enforces protection against long-running operations.

## Risk Categories

| Score | Category | Action |
|-------|----------|--------|
| 0 | Safe | Allow execution |
| 1-24 | Low | Log but allow |
| 25-49 | Medium | Warn in console |
| 50-79 | High | Redirect to session 1-9 |
| 80+ | Critical | Block or redirect based on mode |

## High-Risk Indicators (Blocked/Redirected)

- **KG Pipeline Operations**: `kg_pipeline`, `elastic_ingest`, `knowledge_ingest`
- **Bulk Operations**: `batch`, `bulk`, `multi_*`, `concurrent`
- **Long-running Loops**: `while True`, unbounded iterations
- **Long Sleep**: `sleep > 60s` (15pts), `sleep > 300s` (30pts)
- **Large Code**: >5000 chars or >6 lines
- **Async Aggregation**: `asyncio.gather`, `asyncio.wait`
- **Subprocess**: `subprocess.*`, `Popen`
- **File Scans**: `glob`, `os.walk`, `Path.rglob`

## Safe Patterns (Always Allowed in Session 0)

Basic shell commands: `ls`, `grep`, `cat`, `head`, `tail`, `ps`, `curl`, `docker ps`, `whoami`, `pwd`, `echo`, `git status`, etc.

## Policy

Long-running operations (30+ seconds expected runtime) **MUST** use a dedicated subagent with `dedicated_context=false` instead of `code_execution_tool` session 0. The session guard will enforce this policy automatically.

Current mode: `{enforcement_mode}` (tuning for {tuning_period_days} days before enforcement)
