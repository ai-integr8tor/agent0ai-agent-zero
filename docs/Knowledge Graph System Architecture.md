# Knowledge Graph System Architecture

## System Overview

Agent Zero's Knowledge Graph is a persistent, structured knowledge system that stores entities, relationships, and documents in a graph database. It serves as the long-term memory and structured recall layer for all agent operations.

**Current Scale:**
- 36,768 entities
- 123,952 relationships
- 11,025 documents
- 50,121 vector embeddings
- 7 entity types across 5 domains

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent Zero Framework                         │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   kg_tools       │    │  _kg_pipeline    │    │   FAISS Index    │  │
│  │   (query-side)   │    │  (batch-side)    │    │   (short-term)   │  │
│  │                  │    │                  │    │                  │  │
│  │  kg_search       │    │  ingest          │    │  Memory recall   │  │
│  │  kg_insights     │    │  bulk_ingest     │    │  Pattern match   │  │
│  │  kg_query        │    │  elastic_ingest  │    │  Session context │  │
│  │  kg_hubs         │    │  parallel_ingest │    │                  │  │
│  │  kg_communities  │    │  health          │    └─────────────────┘  │
│  │  kg_surprises    │    │  resolve_entities│                        │
│  │  kg_bridges      │    │  audit           │                        │
│  └────────┬────────┘    └────────┬────────┘                        │
│           │                      │                                 │
│           ▼                      ▼                                 │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    KG Service (AICube:8010)                   │  │
│  │                                                              │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │  │
│  │  │ KuzuDB   │  │ LanceDB  │  │ Entity   │  │ Analysis │    │  │
│  │  │ (Graph)  │  │ (Vectors)│  │ Extract  │  │ Engine   │    │  │
│  │  │          │  │          │  │ (LLM)    │  │          │    │  │
│  │  │ 37K ents │  │ 50K vecs │  │          │  │ Orphans  │    │  │
│  │  │ 124K rels│  │          │  │          │  │ Hubs     │    │  │
│  │  └──────────┘  └──────────┘  └──────────┘  │ Communi. │    │  │
│  │                                             │ Bridges  │    │  │
│  │                                             │ Surprises│    │  │
│  │                                             └──────────┘    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Supporting Services                        │  │
│  │                                                              │  │
│  │  Qwen3.6-35B (Mediaserver)  │  nomic-embed (AI Tower GPU2)  │  │
│  │  Entity verification         │  Vector embeddings            │  │
│  │  Content summarization       │  Semantic search              │  │
│  │  Token compression           │  Similarity scoring           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. Ingestion Flow (Writing to KG)

```
Source Content (MD files, Elastic KB, Knowledge dirs)
       │
       ▼
┌─────────────────────────────────────────┐
│         Token Compressor                 │
│  ┌───────────┐  ┌────────────────────┐   │
│  │ Regex     │  │ LLM (Mediaserver)  │   │
│  │ strip     │→ │ summarize if >30K  │   │
│  │ boilerplate│ │ smart truncate     │   │
│  └───────────┘  └────────────────────┘   │
│         ↓                                │
│  ┌───────────────────────────────┐       │
│  │ Content Hash Cache (7-day)    │       │
│  │ Skip re-compressing unchanged │       │
│  └───────────────────────────────┘       │
└─────────────────────────────────────────┘
       │
       ▼ (~29-70% token reduction)
┌─────────────────────────────────────────┐
│         KG Service /api/v1/add           │
│  ┌───────────────────────────────────┐  │
│  │  LLM Entity Extraction           │  │
│  │  Content → entities + rels        │  │
│  │  (runs on AICube)                 │  │
│  └───────────────────────────────────┘  │
│         ↓                                │
│  ┌───────────────────────────────────┐  │
│  │  KuzuDB Write (graph store)       │  │
│  │  + LanceDB Write (vector index)   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│         Audit Chain                      │
│  Append-only JSONL: action, source, count │
│  One file per day, 90-day retention       │
│  /a0/usr/workdir/logs/kg_audit/           │
└─────────────────────────────────────────┘
```

### 2. Query Flow (Reading from KG)

```
User asks question / Agent needs context
       │
       ▼
┌─────────────────────────────────────────┐
│         kg_tools plugin (per chat turn)   │
│  ┌───────────────┐  ┌───────────────────┐│
│  │ kg_search     │  │ kg_insights       ││
│  │ (semantic)    │  │ (cross-domain)    ││
│  └───────────────┘  └───────────────────┘│
│  ┌───────────────┐  ┌───────────────────┐│
│  │ kg_hubs       │  │ kg_communities    ││
│  │ (key entities)│  │ (clusters)        ││
│  └───────────────┘  └───────────────────┘│
│  ┌───────────────┐  ┌───────────────────┐│
│  │ kg_surprises  │  │ kg_bridges        ││
│  │ (unexpected)  │  │ (connectors)      ││
│  └───────────────┘  └───────────────────┘│
└─────────────────────────────────────────┘
       │
       ▼ Results injected into agent context
       │
┌─────────────────────────────────────────┐
│         FAISS Memory (session layer)     │
│  Short-term patterns, user preferences   │
│  30-day rolling window                   │
└─────────────────────────────────────────┘
```

### 3. Batch Processing Flow

```
Scheduled tasks (cron)
       │
       ├→ kg_pipeline:ingest (knowledge dirs)
       ├→ kg_pipeline:elastic_ingest (Elastic KB)
       ├→ kg_pipeline:parallel_ingest (chunked)
       ├→ kg_pipeline:enrich (domain enrichment)
       ├→ kg_pipeline:audit (quality audit)
       ├→ kg_pipeline:connect_orphans (reconnection)
       ├→ kg_pipeline:health (health scoring)
       └→ kg_pipeline:resolve_entities (dedup)
       │
       ▼
┌─────────────────────────────────────────┐
│  Crash Recovery Checkpoints              │
│  Atomic state saves every 10 files       │
│  Resume on crash, skip processed files   │
│  /a0/usr/workdir/state/kg_checkpoints/   │
└─────────────────────────────────────────┘
```

---

## Data Model

### Entity Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | Entity name (normalized) |
| `type` | enum | technology, product, concept, person, organization, service, event, location |
| `domain` | string | technology, work, personal, context |
| `categories` | string | Comma-separated tags |
| `confidence` | float | Extraction confidence (0.0-1.0) |
| `mention_count` | int | Times mentioned across sources |
| `first_seen` | datetime | First extraction timestamp |
| `last_seen` | datetime | Most recent extraction timestamp |

### Entity Types and Distribution

| Type | Count | % of Total | Examples |
|------|-------|------------|----------|
| technology | ~9,700 | 26% | Docker, Kubernetes, AI/ML |
| product | ~9,000 | 24% | Elasticsearch, Elastic Security |
| concept | ~6,700 | 18% | SIEM, SLED, Observability |
| person | ~4,500 | 12% | Engineers, authors, leaders |
| organization | ~3,900 | 11% | Elastic, AWS, Forrester |
| service | ~1,260 | 3% | Gmail, AWS Lambda |
| event | ~900 | 2% | Elastic{ON}, conferences |
| location | ~755 | 2% | Cities, regions, data centers |

### Relationships

Entities are connected via typed relationships extracted from content:
- `RELATED_TO` — General association
- `MENTIONED_IN` — Entity appears in document
- `PART_OF` — Hierarchical containment
- `USES` / `USED_BY` — Technology dependency
- `COMPETES_WITH` — Competitive relationship

---

## Pipeline Modules

### _kg_pipeline Plugin Structure

```
usr/plugins/_kg_pipeline/
├── plugin.yaml                  # Plugin manifest
├── default_config.yaml          # All configuration
├── README.md                    # Full documentation
│
├── pipeline/                    # Core processing modules
│   ├── kg_client.py            # HTTP client (retries, circuit breaker)
│   ├── ingester.py             # File ingestion (single, bulk, directory)
│   ├── elastic_ingester.py     # Elastic KB specific ingestion
│   ├── parallel_worker.py      # Chunk-based parallel processing
│   ├── checkpoint.py           # Crash recovery (atomic state saves)
│   ├── audit_chain.py          # Write provenance (JSONL per day)
│   ├── token_compressor.py     # Content compression (regex + LLM + cache)
│   ├── health_scorer.py        # Entity quality scoring (5 dimensions)
│   ├── entity_resolver.py      # Deduplication (string + LLM)
│   ├── auditor.py              # Retrieval quality audit
│   ├── enricher.py             # Domain enrichment
│   ├── orphan_connector.py     # Orphan entity reconnection
│   ├── extractor.py            # Entity extraction
│   ├── knowledge_archiver.py   # File archival
│   └── knowledge_ingester.py   # Knowledge dir ingestion
│
├── tools/                       # Agent-facing tools
│   └── kg_pipeline.py          # Tool routes (14 methods)
│
├── tests/                       # Test suite (88 tests)
│   ├── test_checkpoint.py       # 5 tests
│   ├── test_audit_chain.py      # 8 tests
│   ├── test_token_compressor.py # 21 tests
│   ├── test_health_scorer.py    # 18 tests
│   └── test_entity_resolver.py  # 36 tests
│
└── prompts/                     # Agent prompt templates
    └── agent.system.tool.kg_pipeline.md
```

### Tool Methods

| Method | Purpose |
|--------|---------|
| `status` | KG service health + entity/rel counts |
| `ingest` | Single file or directory ingestion |
| `bulk_ingest` | Bulk ingestion with dedup |
| `elastic_ingest` | Elastic KB ingestion |
| `parallel_ingest` | Parallel chunk processing |
| `connect_orphans` | Reconnect isolated entities |
| `enrich` | Domain/category enrichment |
| `audit` | Retrieval quality audit |
| `knowledge_ingest` | Knowledge directory ingestion |
| `gdrive_upload` | Export to Google Drive |
| `health` | Entity health scores + tier distribution |
| `resolve_entities` | Entity deduplication pipeline |

---

## Infrastructure

| Component | Location | Technology |
|-----------|----------|------------|
| **KG Service** | AICube (100.78.79.41:8010) | KuzuDB + LanceDB + LLM extraction |
| **Entity Extraction LLM** | KG Service (embedded) | Configurable LLM via Spark |
| **Verification LLM** | Mediaserver (192.168.1.250:11435) | Qwen3.6-35B MoE GGUF Q5 |
| **Embedding Service** | AI Tower GPU2 (192.168.1.246:11435) | nomic-embed-text (768-dim) |
| **Agent Framework** | Agent Zero container | Python 3.13, Flask, Alpine.js |
| **Short-term Memory** | Agent Zero container | FAISS index (30-day window) |

---

## Health Scoring System

### 5-Dimension Scoring

| Dimension | Weight | Formula |
|-----------|--------|---------|
| Connectivity | 35% | log(degree+1) / log(max_degree+1) |
| Recency | 20% | 1.0 if <7d → 0.1 at 365d |
| Source Quality | 20% | min(mentions/5,1.0)*0.5 + min(categories/5,1.0)*0.5 |
| Freshness | 15% | Update frequency vs entity lifespan |
| Confidence | 10% | Direct extraction confidence |

### Memory Tiers

| Tier | Threshold | Meaning |
|------|-----------|---------|
| **Hot** | ≥0.70 | Actively used, high connectivity |
| **Warm** | ≥0.50 | Moderately connected, recent |
| **Cool** | ≥0.30 | Low connectivity, aging |
| **Cold** | <0.30 | Isolated, stale, archival candidate |

---

## Entity Resolution Pipeline

### 3-Stage Deduplication

```
Stage 1: STRING BLOCKING
  Group by entity type
  Jaro-Winkler similarity ≥ 0.80
  Token overlap ≥ 0.60
  Sliding window (sorted names, window=50)
       ↓
Stage 2: LLM VERIFICATION
  Qwen3.6-35B on Mediaserver
  "Are these the same entity? YES/NO + confidence"
  Checks reasoning_content first (Qwen reasoning models)
  0.5s rate limiting between calls
       ↓
Stage 3: SAFE MERGE
  Keep higher-degree entity as canonical
  Transfer relationships from duplicate
  DETACH DELETE (KuzuDB requirement)
  Log every merge to audit chain
  Dry-run default (no accidental merges)
```

### Merge Statistics
- 504 entities merged (37,240 → 36,768)
- 83 case/format variants + 421 plural/punctuation variants
- 72,000+ false positives correctly rejected
- Zero errors

---

## Configuration

```yaml
# KG Service connection
kg_service_url: "http://100.78.79.41:8010"
batch_size: 50
timeout: 300
max_retries: 3

# Audit trail
audit:
  enabled: true
  retention_days: 90

# Content compression
compression:
  enabled: true
  llm_enabled: true
  llm_threshold_chars: 30000
  llm_max_output_tokens: 4096
  cache_enabled: true
  cache_ttl_days: 7

# Health scoring
health_scoring:
  enabled: true
  cache_ttl_hours: 24
  tier_thresholds: { hot: 0.7, warm: 0.5, cool: 0.3 }

# Entity resolution
entity_resolution:
  enabled: true
  string_threshold: 0.80
  llm_verify: true
  dry_run_default: true
```

---

## Testing

```bash
cd /a0/usr/plugins/_kg_pipeline
python3 -m pytest tests/ -v
# 88 tests, ~0.3s execution time
```

All tests must pass before any changes are merged.

---

*Last updated: 2026-05-20*
*Part of Agent Zero Knowledge Graph system*