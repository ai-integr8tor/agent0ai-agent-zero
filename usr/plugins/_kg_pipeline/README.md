# _kg_pipeline Plugin

**Knowledge Graph Batch Pipeline** — Consolidated batch operations for Agent Zero's Knowledge Graph system.

## Overview

This plugin provides the complete ingestion, quality, and maintenance pipeline for the Knowledge Graph:

- **Ingestion**: Single file, bulk, Elastic KB, and parallel chunk-based ingestion
- **Crash Recovery**: Atomic checkpoint saves for worker resilience
- **Audit Trail**: Append-only JSONL write provenance
- **Token Compression**: Regex + LLM summarization + content cache
- **Health Scoring**: 5-dimension entity quality scoring with tier assignment
- **Entity Resolution**: String similarity + LLM verification deduplication
- **Quality Audit**: Retrieval precision and entity coverage measurement
- **Enrichment**: Entity enrichment and orphan connection

## Structure

```
/a0/usr/plugins/_kg_pipeline/
├── plugin.yaml                     # Plugin metadata
├── default_config.yaml             # All configuration
├── README.md                       # This file
│
├── pipeline/
│   ├── __init__.py                # Package exports
│   ├── kg_client.py               # Shared HTTP client for KG service
│   ├── ingester.py                # Single/bulk file ingestion
│   ├── elastic_ingester.py        # Elastic KB ingestion
│   ├── parallel_worker.py         # Chunk-based parallel processing
│   ├── checkpoint.py              # Crash recovery checkpoints
│   ├── audit_chain.py             # Append-only write provenance
│   ├── token_compressor.py        # Regex + LLM content compression
│   ├── health_scorer.py           # Entity health scoring + tiers
│   ├── entity_resolver.py         # String + LLM entity dedup
│   ├── orphan_connector.py        # Orphan entity connection
│   ├── extractor.py               # Entity extraction
│   ├── enricher.py                # Entity enrichment
│   ├── auditor.py                 # Retrieval quality audit
│   ├── knowledge_archiver.py      # KG file archival
│   ├── knowledge_ingester.py      # Knowledge directory ingestion
│   ├── gdrive.py                  # Google Drive upload
│   └── phase2_ingest.py           # Phase 2 ingestion
│
├── tools/
│   ├── __init__.py
│   └── kg_pipeline.py             # Main tool with sub-methods
│
├── tests/
│   ├── __init__.py
│   ├── test_checkpoint.py         # 5 tests
│   ├── test_audit_chain.py        # 8 tests
│   ├── test_token_compressor.py   # 21 tests
│   ├── test_health_scorer.py      # 18 tests
│   └── test_entity_resolver.py    # 36 tests
│
└── prompts/
    └── agent.system.tool.kg_pipeline.md
```

## Tool Methods

| Method | Description | Source |
|--------|-------------|--------|
| `status` | Check KG service health and counts | Existing |
| `ingest` | Ingest single file or directory | Existing |
| `bulk_ingest` | Bulk ingest with deduplication | Existing |
| `elastic_ingest` | Elastic KB ingestion | Existing |
| `parallel_ingest` | Chunk-based parallel processing | Existing |
| `connect_orphans` | Connect orphan entities | Existing |
| `enrich` | Enrich entities with domain/categories | Existing |
| `audit` | Retrieval quality audit | Existing |
| `knowledge_ingest` | Knowledge directory ingestion | Existing |
| `gdrive_upload` | Export KG to Google Drive | Existing |
| `health` | Entity health scores and tier distribution | **New** |
| `resolve_entities` | Entity resolution (candidates/verify/merge) | **New** |

## Pipeline Modules Added (2026-05-20)

### checkpoint.py — Crash Recovery
Atomic checkpoint saves for parallel workers. On crash, workers resume from last checkpoint instead of restarting.

- `save_checkpoint()`, `load_checkpoint()`, `clear_checkpoint()`, `list_stale_checkpoints()`
- Atomic writes via `os.replace()`, 24h stale detection
- Integrated into `parallel_worker.py`

### audit_chain.py — Write Provenance
Append-only JSONL audit trail for all KG write operations.

- `append()`, `query()`, `get_stats()`
- One file per day: `kg_audit_YYYY-MM-DD.jsonl`
- Kill switch: `audit.enabled: false` → all calls become no-ops
- Integrated into `ingester.py`, `elastic_ingester.py`, `parallel_worker.py`

### token_compressor.py — Content Compression
Reduces token usage by stripping boilerplate, LLM summarization, and caching.

- Regex: social buttons, bylines, whitespace, URL tracking params, duplicate lines
- LLM: Qwen3.6-35B on Mediaserver for files >30K chars
- Cache: MD5-based content hash cache with 7-day TTL
- Smart truncate: entity-aware paragraph selection
- ~29% reduction on Elastic blog content, ~40%+ on large files

### health_scorer.py — Entity Quality Scoring
Multi-dimensional health scoring with memory tier assignment.

- 5 dimensions: Connectivity (35%), Recency (20%), Source Quality (20%), Freshness (15%), Confidence (10%)
- Tiers: hot (≥0.7), warm (≥0.5), cool (≥0.3), cold (<0.3)
- 24h cache, KuzuDB-compatible Cypher

### entity_resolver.py — Entity Deduplication
3-stage pipeline for finding and merging duplicate entities.

- Stage 1: String blocking (Jaro-Winkler + token overlap)
- Stage 2: LLM verification (Qwen3.6-35B on Mediaserver)
- Stage 3: Safe merge (higher-degree canonical, DETACH DELETE, audit logging)
- Dry-run default, KuzuDB-compatible

## Configuration

All settings in `default_config.yaml`:

```yaml
kg_service_url: "http://100.78.79.41:8010"

audit:
  enabled: true
  retention_days: 90

compression:
  enabled: true
  llm_enabled: true
  llm_threshold_chars: 30000
  cache_enabled: true
  cache_ttl_days: 7

health_scoring:
  enabled: true
  cache_ttl_hours: 24
  tier_thresholds: { hot: 0.7, warm: 0.5, cool: 0.3 }

entity_resolution:
  enabled: true
  string_threshold: 0.80
  llm_verify: true
  dry_run_default: true
```

## Testing

```bash
cd /a0/usr/plugins/_kg_pipeline
python3 -m pytest tests/ -v
```

88 tests across 5 test files. All must pass before any merge to main.

## Dependencies

- `requests` — KG service HTTP client
- `numpy` — Health scoring calculations
- LLM endpoint: Qwen3.6-35B on Mediaserver (192.168.1.250:11435)

## License

Part of Agent Zero system.
