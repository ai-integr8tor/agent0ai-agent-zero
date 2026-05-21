# KG Dreamer Plugin

Autonomous background intelligence for the Knowledge Graph. Makes the KG proactive instead of passive.

## Overview

KG Dreamer runs 6 dream operations every 6 hours to:
- Discover hidden connections between entities
- Strengthen important pathways, decay unused ones
- Archive stale cold-tier entities
- Detect contradictions across sources
- Discover unnamed entity clusters
- Generate proactive insights using LLM

## Architecture

```
_kg_dreamer/
├── plugin.yaml              # depends: _kg_pipeline
├── default_config.yaml      # schedule, LLM endpoint, thresholds
├── orchestrator.py           # Dream cycle runner (353 lines)
├── operations/
│   ├── connector.py          # CONNECT: implied relationships (218 lines)
│   ├── strengthener.py       # STRENGTHEN: pathway weights (403 lines)
│   ├── pruner.py             # PRUNE: cold entity archival (354 lines)
│   ├── contradiction.py      # CONTRADICT: conflict detection (476 lines)
│   ├── patterns.py           # PATTERN: cluster discovery (232 lines)
│   └── insights.py           # INSIGHT: LLM observations (369 lines)
├── tools/
│   └── kg_dreamer.py         # Agent Zero tool (211 lines)
├── helpers/
│   └── __init__.py           # Cross-plugin imports
└── tests/
    ├── test_connector.py     # 15 tests
    ├── test_pruner.py         # 15 tests
    └── test_orchestrator.py   # 18 tests
```

## Dream Operations

| Operation | What It Does | Priority |
|---|---|---|
| **CONNECT** | Find entities sharing documents with no direct relationship, create IMPLIED_RELATION edges | P0 |
| **STRENGTHEN** | Boost weights on frequently-accessed pathways, decay dormant ones | P1 |
| **PRUNE** | Archive cold-tier entities (>180 days, <0.1 health score) | P0 |
| **CONTRADICT** | Detect conflicting entity properties across sources via LLM | P1 |
| **PATTERN** | Discover unnamed entity clusters, suggest parent concepts via LLM | P2 |
| **INSIGHT** | Generate proactive observations using graph statistics + LLM | P2 |

## Tool Methods

```
kg_dreamer:status                      → Check dream cycle status
kg_dreamer:run_dream_cycle             → Run all operations
kg_dreamer:run_operation operation=connect  → Run single operation
kg_dreamer:get_report count=5           → Get last N dream reports
```

## LLM Usage

All LLM operations use Qwen3.6-35B on Mediaserver (192.168.1.250:11435) — free, local, no cloud costs.

## Dependencies

- `_kg_pipeline` plugin (KGClient, AuditChain, HealthScorer)
- KG service on AICube (100.78.79.41:8010)
- Qwen3.6-35B on Mediaserver for LLM operations

## Stats

- **14 Python files**
- **3,605 lines of code**
- **48 tests, 100% pass rate**
- **0 cloud API calls**
