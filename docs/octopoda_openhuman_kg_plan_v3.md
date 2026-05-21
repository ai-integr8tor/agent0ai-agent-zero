# Combined KG Enhancement Plan v3.1 — CC Approved (Final)

> **Sources:** Octopoda-OS v3.0.3 + OpenHuman v0.53.43
> **Date:** 2026-05-20
> **Status:** ✅ APPROVED WITH MODIFICATIONS — Council of Councils Review Complete
> **CC Confidence:** HIGH (with modifications)
> **Platform:** Agent Zero v2.1.0 (base v1.15), 35+ plugins

---

## Current State (Verified 2026-05-20)

### KG Service
| Metric | Value |
|---|---|
| Version | 6.0.0 (v6.1.0 analysis API) |
| **Entities** | **37,221** |
| **Relationships** | **123,086** |
| **Documents** | **11,012** |
| **Vectors** | **50,056** (LanceDB) |
| Backend | Neo4j on AICube (100.78.79.41:8010) |
| Embeddings | nomic-embed-text (AI Tower 192.168.1.246:11435) ✅ Operational |
| AICube Ollama | 100.78.79.41:11434 ⚠️ DOWN 65+ days (NOT used by this plan) |

### Entity Connectivity Distribution
| Tier | Connections | Count | % of Total |
|---|---|---|---|
| Isolated | 0 relationships | 42 | 0.1% |
| Single | 1 relationship | 1,409 | 3.8% |
| Low | 2-3 relationships | 9,508 | 25.5% |
| Medium | 4-10 relationships | 19,436 | 52.2% |
| High | 10+ relationships | 6,826 | 18.3% |

> **DATA CORRECTION:** Previous v2.0 plan claimed "73% isolated entities" — **INCORRECT**. Actual isolation is **0.1%**. Graph is healthy.

### Exact-Name Duplicate Candidates
Only 6 found: FastAPI, Python, Docker, vLLM, Ollama, CUDA (each appears 2x)

### CC Key Finding
Entity Resolution is about **semantic duplicates** (same concept, different names across sources), NOT exact-name duplicates. This is a hypothesis requiring validation before full build.

---

## Final Execution Order (CC-Approved)

| Day | Phase | Source | Deliverable | Owner | Est. Days |
|---|---|---|---|---|---|
| **1-2** | **Phase 2** | Octopoda | Crash Recovery Checkpoints | DevOps | 1.5 |
| **3** | **Phase 0-Spike** | OpenHuman | Entity Resolution Validation | KG Specialist | 1 |
| **4-5** | **Phase 1** | Octopoda | Append-Only Audit Log | DevOps | 2 |
| **6** | **Phase 1.5** | OpenHuman | Token Compression Pipeline | ML Engineer | 1.5 |
| **7-9** | **Phase 3** | Both | Health Scoring + Tiered Memory | KG Specialist | 3 |
| *Spike result ≥100 candidates* | **Phase 0** | OpenHuman | Full Entity Resolution Build | KG Specialist | 4 |
| *After Phase 0* | **Phase 5** | Both | Near-Duplicate Consolidation | ML Engineer | 1.5 |
| *Deferred indefinitely* | **Phase 6** | Octopoda | spaCy Pre-filter ($50/mo gate) | — | — |
| *Deferred to Agent Health* | **Phase 4** | Octopoda | Loop Detection | — | — |

> **Total committed:** 9.5 days | **Conditional:** 5.5 days (if spike passes) | **Max:** 15 days

### Decision Gate at Day 3
```
Phase 0 Validation Spike (Day 3):
  1. Sample 1,000 random entities from KG
  2. Generate embeddings via AI Tower nomic-embed-text
  3. Compute pairwise similarity within each entity type
  4. Count candidate pairs with cosine similarity ≥ 0.85
  
  Decision:
    ≥ 100 candidates → PROCEED to full Phase 0 build (Days 10-13)
    50-99 candidates → REVIEW with user before proceeding
    < 50 candidates → ABORT Phase 0 + Phase 5, move to other work
```

### Re-Ingestion Impact
| Phase | Re-Ingestion? | Details |
|---|---|---|
| Phase 2 | **No** | Checkpoint mechanism only |
| Phase 0-Spike | **No** | Read-only analysis on existing embeddings |
| Phase 1 | **No** | Append-only on future writes |
| Phase 1.5 | **No** for existing | Pipeline change going forward |
| Phase 3 | **No** | Read-only analysis endpoint |
| Phase 0 (full) | **Partial** | Reconciliation pass on existing entities. NOT re-scrape |
| Phase 5 | **No re-ingestion** | Modifies graph in-place |

---

## Phase 2: Crash Recovery Checkpoints (SHIPS FIRST)
**Priority:** P0 | **Score:** 9/10 | **Estimate:** 1.5 days | **Impact:** High
**Owner:** DevOps Engineer | **Source:** Octopoda

### Problem
`kg_parallel_worker.py` has no checkpoint. Worker crash = all progress lost.

### Solution
Atomic per-worker checkpoint files with processed file tracking.

### Files
| File | Action |
|---|---|
| `scripts/kg_checkpoint.py` | CREATE |
| `scripts/kg_parallel_worker.py` | MODIFY |
| `tests/unit/test_kg_checkpoint.py` | CREATE (5 tests) |
| `tests/integration/test_worker_crash_recovery.py` | CREATE (3 tests) |

### Design
- State dir: `/a0/usr/workdir/state/kg_checkpoints/`
- Atomic writes: temp file + `os.replace()`
- Checkpoint every 10 files
- Auto-resume on startup, auto-cleanup on success
- Stale detection at 24h TTL

### Acceptance Criteria
- [ ] Workers resume from checkpoint after crash
- [ ] 0 duplicate file processing
- [ ] Atomic writes verified
- [ ] All tests pass (80%+ coverage)

---

## Phase 0-Spike: Entity Resolution Validation
**Priority:** P0 (validation) | **Score:** 6/10 | **Estimate:** 1 day | **Impact:** Determines Phase 0 + Phase 5
**Owner:** KG Specialist | **Source:** OpenHuman

### Problem
We HYPOTHESIZE that 11K+ documents contain semantic duplicates (same concept, different names). This spike validates before committing 4 days of build.

### Approach
```
1. Export 1,000 random entities from KG (stratified by type)
2. Generate embeddings via AI Tower nomic-embed-text (:11435)
3. Compute pairwise cosine similarity within each entity type
4. Count candidate pairs ≥ 0.85 similarity
5. Manual review of top 20 candidates for accuracy
6. Report: candidate count, false positive rate, recommendation
```

### Files
| File | Action |
|---|---|
| `scripts/kg_resolution_spike.py` | CREATE (disposable spike script) |

### Deliverable
Written report with:
- Total candidate pairs found
- Sample of 20 candidates with manual review
- Estimated total duplicates across all 37K entities
- GO / NO-GO recommendation

---

## Phase 1: Append-Only Audit Log
**Priority:** P0 | **Score:** 8/10 | **Estimate:** 2 days | **Impact:** High
**Owner:** DevOps Engineer | **Source:** Octopoda

### Design
- Append-only JSONL at `/a0/usr/workdir/logs/kg_audit/audit.jsonl`
- Event schema: timestamp, action, target_type, target_id, source, content_hash, entity_count, rel_count
- Backup: rsync to AITower every 4 hours
- Rollback: `KG_AUDIT_ENABLED=false`

### Files
| File | Action |
|---|---|
| `scripts/kg_audit_chain.py` | CREATE |
| `scripts/kg_parallel_worker.py` | MODIFY |
| `scripts/kg_ingest.py` | MODIFY |
| `scripts/kg_elastic_ingest.py` | MODIFY |
| `scripts/kg_audit_backup.py` | CREATE |
| `tests/unit/test_kg_audit_chain.py` | CREATE (8 tests) |

### Acceptance Criteria
- [ ] 100% audit coverage of `/api/v1/add` calls
- [ ] `verify_integrity()` returns valid
- [ ] Backup to AITower every 4 hours
- [ ] Rollback tested

---

## Phase 1.5: Token Compression Pipeline
**Priority:** P1 | **Score:** 8/10 | **Estimate:** 1.5 days | **Impact:** High (cost savings)
**Owner:** ML Engineer | **Source:** OpenHuman TokenJuice

### Problem
Raw content sent to LLM. OpenHuman achieves 80% token reduction via pre-processing.

### Solution
Compress content BEFORE LLM extraction:
1. HTML → Markdown
2. Strip boilerplate (nav, footer, cookie banners)
3. URL shortening (drop query params)
4. Whitespace normalization
5. Non-ASCII removal (preserve CJK)
6. Line deduplication
7. Truncate to 30K chars

### Files
| File | Action |
|---|---|
| `scripts/kg_token_compressor.py` | CREATE |
| `scripts/kg_parallel_worker.py` | MODIFY |
| `scripts/kg_ingest.py` | MODIFY |
| `tests/unit/test_token_compressor.py` | CREATE |

### Success Metrics
| Metric | Target |
|---|---|
| Token reduction | ≥ 40% |
| Content preservation | 100% meaningful content |
| Processing speed | < 50ms/file |

---

## Phase 3: Entity Health Scoring + Tiered Memory
**Priority:** P1 | **Score:** 8/10 | **Estimate:** 3 days | **Impact:** High
**Owner:** KG Specialist | **Source:** Both

### OpenHuman Integration: 4-Tier Memory
| Tier | Criteria | Behavior |
|---|---|---|
| Hot | < 7 days, ≥ 5 rels | Prioritized in queries |
| Warm | < 30 days, ≥ 2 rels | Normal priority |
| Cool | < 90 days, any connectivity | Lower priority |
| Cold | > 90 days OR isolated | Minimal priority |

### Scoring
Connectivity (35%), Recency (20%), Source Quality (20%), Community (15%), Confidence (10%)

### Endpoint
`GET /analysis/health?tier=hot&warm&cool&cold&min_score=0&limit=50`

### Prerequisites
- Neo4j version check via `CALL dbms.components()`
- Index audit on `Entity.name`, `Entity.type`, `created_at`

---

## Phase 0 (Conditional): Full Entity Resolution Build
**Priority:** P1 (conditional) | **Score:** 6/10 | **Estimate:** 4 days | **Impact:** Conditional
**Owner:** KG Specialist | **Source:** OpenHuman
**TRIGGER:** Spike finds ≥ 100 semantic duplicate candidates

### Full Build
- Resolution pipeline between extraction and KG write
- Canonical entity schema with aliases and multi-source provenance
- Reconciliation pass over all 37K existing entities
- Uses LanceDB vectors for similarity search
- Logs every merge to audit trail (Phase 1)

---

## Phase 5 (Conditional): Near-Duplicate Consolidation
**Priority:** P2 (conditional) | **Score:** 6/10 | **Estimate:** 1.5 days
**Owner:** ML Engineer | **Source:** Both
**TRIGGER:** Phase 0 completes successfully
**DEPENDENCY:** Phase 0 + Phase 1

---

## Deferred
| Phase | Reason |
|---|---|
| Phase 6 (spaCy) | ROI gate raised to $50/month. Defer indefinitely. |
| Phase 4 (Loop Detection) | Agent framework work, not KG. Separate initiative. |

---

## CC Decision Summary

| Phase | Score | Status |
|---|---|---|
| Phase 2 (Crash Recovery) | 9/10 | ✅ SHIPS FIRST |
| Phase 1 (Audit Log) | 8/10 | ✅ APPROVED |
| Phase 1.5 (Token Compression) | 8/10 | ✅ APPROVED |
| Phase 3 (Health Scoring) | 8/10 | ✅ APPROVED |
| Phase 0-Spike (Validation) | — | ✅ REQUIRED GATE |
| Phase 0 (Entity Resolution) | 6/10 | ⚠️ CONDITIONAL on spike |
| Phase 5 (Consolidation) | 6/10 | ⚠️ CONDITIONAL on Phase 0 |
| Phase 6 (spaCy) | 3/10 | ❌ DEFERRED ($50/mo gate) |

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Phase 0 hypothesis wrong (few semantic duplicates) | Validation spike before full build |
| Entity resolution false merges | Dry-run, manual review, threshold tuning |
| Token compression drops content | A/B test extraction quality on 100 files |
| Audit log corruption | 4-hour rsync backup to AITower |
| Health scoring timeout | Cache daily, 5-second SLA |

## Rollback Triggers

| Trigger | Action |
|---|---|
| Entity resolution false merge rate > 2% | Lower threshold, add manual review |
| Token compression drops extraction > 5% | Disable, investigate |
| Audit corruption > 1 incident | Disable, restore from backup |
| Health query > 10s | Disable endpoint |

---

## Appendix: Source Attribution

| Phase | Source | Adapted Concept |
|---|---|---|
| Phase 2 | Octopoda snapshots | Crash recovery checkpoints |
| Phase 0-Spike | OpenHuman Neoortex | Entity resolution validation approach |
| Phase 1 | Octopoda audit-v2 | Append-only audit trail |
| Phase 1.5 | OpenHuman TokenJuice | Token compression pipeline |
| Phase 3 | Both | Health scoring (Octopoda) + Tiered memory (OpenHuman) |
| Phase 0 | OpenHuman Neoortex | Cross-source entity resolution |
| Phase 5 | Both | Consolidation (Octopoda) + semantic dedup (OpenHuman) |

## Appendix: CC Review Details

- **TC v2.0 Review:** `/a0/usr/workdir/docs/octopoda_tc_review.md`
- **CC v3.0 Review:** Council of Councils (technology-architecture + business-leadership)
- **CC Verdict:** Approved with Modifications (HIGH confidence)
- **Key CC Changes Applied:**
  1. Phase 2 reordered to first (immediate value, low risk)
  2. Phase 0 validation spike added (1-day gate before 4-day build)
  3. Phase 6 deferred (ROI gate raised to $50/month)
  4. Phase 0 and Phase 5 made conditional on spike results
  5. Data correction: 0.1% isolation vs claimed 73%
  6. AICube Ollama outage confirmed irrelevant (AI Tower operational)
