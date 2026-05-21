"""Entity Resolution - 3-stage pipeline for finding and merging duplicates.

Uses string similarity blocking + LLM verification to resolve entity duplicates
in the Knowledge Graph. Implements Jaro-Winkler similarity and token overlap
for candidate generation, then validates with Qwen3.6-35B before merging.

Architecture:
    Stage 1: find_candidates() - String similarity blocking
    Stage 2: verify_candidates() - LLM verification (YES/NO judgment)
    Stage 3: merge_duplicates() - Merge confirmed pairs, keep higher-degree entity

KuzuDB-compatible Cypher ONLY - no CASE WHEN, no Neo4j-specific functions.
"""
import logging
import time
import json
from typing import Dict, List, Optional, Any, Tuple
from itertools import combinations

import requests

logger = logging.getLogger(__name__)


class EntityResolver:
    """Find and resolve duplicate entities using string similarity + LLM verification.
    
    Attributes:
        kg: KGClient instance for KG operations
        config: Configuration dict with thresholds and settings
        llm_url: URL for LLM verification endpoint
        llm_model: Model name for LLM verification
        audit_log: List of merge operations for auditing
    """
    
    def __init__(self, kg_client: Any, config: Optional[Dict] = None):
        """Initialize the entity resolver.
        
        Args:
            kg_client: KGClient instance for KG operations
            config: Optional configuration dict with keys:
                - string_threshold: Jaro-Winkler threshold (default 0.80)
                - token_threshold: Token overlap threshold (default 0.60)
                - llm_verify: Enable LLM verification (default True)
                - batch_size: LLM batch size for rate limiting (default 10)
                - llm_sleep: Seconds between LLM calls (default 0.5)
        """
        self.kg = kg_client
        self.config = config or {}
        self.llm_url = self.config.get(
            "llm_url", "http://192.168.1.250:11435/v1/chat/completions"
        )
        self.llm_model = self.config.get(
            "llm_model", "Qwen3.6-35B-A3B-MTP-UD-Q5_K_XL.gguf"
        )
        self.audit_log: List[Dict] = []
        self._llm_session = requests.Session()
    
    def find_candidates(
        self,
        entity_type: Optional[str] = None,
        similarity_threshold: float = 0.80,
    ) -> List[Dict]:
        """Stage 1: Find candidate duplicate pairs using string similarity.
        
        Uses Jaro-Winkler similarity and token overlap to find potential       duplicates. Groups by entity type first (blocking strategy) to reduce
        computational complexity.
        
        Args:
            entity_type: Filter by type (None = all types)
            similarity_threshold: Minimum Jaro-Winkler similarity (default 0.80)
        
        Returns:
            List of candidate dicts with keys:
                - name_a: First entity name
                - name_b: Second entity name
                - type: Entity type
                - similarity: Jaro-Winkler similarity score
                - token_overlap: Token overlap ratio
                - method: Detection method used
        """
        token_threshold = self.config.get("token_threshold", 0.60)
        
        logger.info(f"Finding candidates (type={entity_type}, threshold={similarity_threshold})")
        
        # Fetch entities from KG
        entities = self._fetch_entities(entity_type)
        
        if not entities:
            logger.warning("No entities found for resolution")
            return []
        
        logger.info(f"Loaded {len(entities)} entities for comparison")
        
        candidates = []
        
        # Group by type for blocking
        type_groups: Dict[str, List[Dict]] = {}
        for ent in entities:
            etype = ent.get("type", "unknown")
            type_groups.setdefault(etype, []).append(ent)
        
        # Compare within each type group
        for etype, group in type_groups.items():
            logger.debug(f"Processing type '{etype}' with {len(group)} entities")
            
            # Compare all pairs in this type
            for ent_a, ent_b in combinations(group, 2):
                name_a = ent_a.get("name", "")
                name_b = ent_b.get("name", "")
                
                if not name_a or not name_b or name_a == name_b:
                    continue
                
                # Calculate similarities
                jw_sim = self._jaro_winkler(name_a.lower(), name_b.lower())
                tok_overlap = self._token_overlap(name_a, name_b)
                
                # Check thresholds
                if jw_sim >= similarity_threshold or tok_overlap >= token_threshold:
                    method = "jaro_winkler" if jw_sim >= similarity_threshold else "token_overlap"
                    candidates.append({
                        "name_a": name_a,
                        "name_b": name_b,
                        "type": etype,
                        "similarity": round(jw_sim, 4),
                        "token_overlap": round(tok_overlap, 4),
                        "method": method,
                    })
        
        # Sort by combined score (weighted toward Jaro-Winkler)
        candidates.sort(
            key=lambda c: (c["similarity"] * 0.6 + c["token_overlap"] * 0.4),
            reverse=True,
        )
        
        logger.info(f"Found {len(candidates)} candidate pairs for verification")
        return candidates
    
    def verify_candidates(
        self,
        candidates: List[Dict],
        batch_size: int = 10,
    ) -> List[Dict]:
        """Stage 2: Verify candidates using LLM judgment.
        
        Sends each pair to Qwen3.6-35B for YES/NO verification with confidence
        scoring. Rate-limited with sleep between calls.
        
        Args:
            candidates: List from find_candidates()
            batch_size: Process N at a time (for progress reporting)
        
        Returns:
            List of verified duplicates with keys:
                - All keys from input candidate
                - llm_verdict: "YES" or "NO"
                - llm_confidence: 0.0-1.0 confidence score
                - llm_reasoning: Optional reasoning text
        """
        if not self.config.get("llm_verify", True):
            logger.info("LLM verification disabled, skipping")
            return [c for c in candidates if c.get("similarity", 0) > 0.95]
        
        verified = []
        llm_sleep = self.config.get("llm_sleep", 0.5)
        
        logger.info(f"Verifying {len(candidates)} candidates with LLM")
        
        for i, candidate in enumerate(candidates):
            if i > 0 and i % batch_size == 0:
                logger.debug(f"Processed {i}/{len(candidates)} candidates")
            
            result = self._llm_verify_pair(
                candidate["name_a"],
                candidate["name_b"],
                candidate["type"],
            )
            
            candidate_copy = candidate.copy()
            candidate_copy["llm_verdict"] = result["verdict"]
            candidate_copy["llm_confidence"] = result["confidence"]
            if result.get("reasoning"):
                candidate_copy["llm_reasoning"] = result["reasoning"]
            
            if result["verdict"] == "YES":
                verified.append(candidate_copy)
            
            # Rate limiting
            time.sleep(llm_sleep)
        
        logger.info(f"LLM verified {len(verified)} duplicates from {len(candidates)} candidates")
        return verified
    
    def merge_duplicates(
        self,
        duplicates: List[Dict],
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Stage 3: Merge confirmed duplicates in the KG.
        
        Keeps the entity with more connections as canonical. Absorbs
        relationships from the duplicate. Logs every merge to audit chain.
        
        Args:
            duplicates: Verified duplicate pairs from verify_candidates()
            dry_run: If True, report what would happen without executing
        
        Returns:
            Dict with keys:
                - merged: Count of successful merges
                - skipped: Count of skipped/invalid pairs
                - dry_run: Whether this was a dry run
                - details: List of per-merge detail dicts
                - audit_log: Full audit trail
        """
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made to KG")
        
        merged_count = 0
        skipped_count = 0
        details = []
        
        logger.info(f"Processing {len(duplicates)} duplicate pairs for merge")
        
        for dup in duplicates:
            name_a = dup["name_a"]
            name_b = dup["name_b"]
            entity_type = dup.get("type", "unknown")
            confidence = dup.get("llm_confidence", 0.8)
            
            # Get entity degrees to decide canonical
            degree_a = self._get_entity_degree(name_a)
            degree_b = self._get_entity_degree(name_b)
            
            if degree_a is None or degree_b is None:
                logger.warning(f"Could not get degrees for {name_a} or {name_b}, skipping")
                skipped_count += 1
                continue
            
            # Higher degree = canonical
            if degree_a >= degree_b:
                canonical_name, duplicate_name = name_a, name_b
                canonical_degree, duplicate_degree = degree_a, degree_b
            else:
                canonical_name, duplicate_name = name_b, name_a
                canonical_degree, duplicate_degree = degree_b, degree_a
            
            # Perform merge
            merge_result = self._merge_pair(
                canonical_name,
                duplicate_name,
                entity_type,
                dry_run=dry_run,
            )
            
            detail = {
                "canonical": canonical_name,
                "duplicate": duplicate_name,
                "type": entity_type,
                "canonical_degree": canonical_degree,
                "duplicate_degree": duplicate_degree,
                "confidence": confidence,
                "dry_run": dry_run,
                "result": merge_result,
            }
            details.append(detail)
            
            if merge_result.get("success"):
                merged_count += 1
                # Add to audit log
                self.audit_log.append({
                    "action": "merge",
                    "timestamp": time.isoformat(time.utcnow()) if hasattr(time, "isoformat") else str(time.time()),
                    "target_id": duplicate_name,
                    "metadata": {
                        "canonical": canonical_name,
                        "type": entity_type,
                        "confidence": confidence,
                    },
                })
            else:
                skipped_count += 1
        
        result = {
            "merged": merged_count,
            "skipped": skipped_count,
            "dry_run": dry_run,
            "details": details,
            "audit_log": self.audit_log,
        }
        
        logger.info(f"Completed: {merged_count} merged, {skipped_count} skipped (dry_run={dry_run})")
        return result
    
    def _fetch_entities(self, entity_type: Optional[str] = None) -> List[Dict]:
        """Fetch entities from KG using Cypher query.
        
        Args:
            entity_type: Optional filter by entity type
            
        Returns:
            List of entity dicts with name, type, mention_count
        """
        if entity_type:
            query = (
                f"MATCH (e:Entity) WHERE e.type = '{entity_type}' "
                "RETURN e.name AS name, e.type AS type, e.mention_count AS mention_count"
            )
        else:
            query = (
                "MATCH (e:Entity) "
                "RETURN e.name AS name, e.type AS type, e.mention_count AS mention_count"
            )
        
        try:
            rows = self.kg.query_cypher(query)
            return [
                {"name": r.get("name"), "type": r.get("type", "unknown"), "mention_count": r.get("mention_count", 0)}
                for r in rows
                if r.get("name")
            ]
        except Exception as e:
            logger.error(f"Failed to fetch entities: {e}")
            return []
    
    def _jaro_winkler(self, s1: str, s2: str) -> float:
        """Compute Jaro-Winkler similarity between two strings.
        
        Jaro similarity measures character matches and transpositions.
        Winkler adds prefix bonus for matching start characters.
        
        Args:
            s1: First string
            s2: Second string
            
        Returns:
            Similarity score 0.0-1.0
        """
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0
        
        # Jaro similarity
        len1, len2 = len(s1), len(s2)
        match_distance = (max(len1, len2) // 2) - 1
        
        s1_matches = [False] * len1
        s2_matches = [False] * len2
        
        matches = 0
        transpositions = 0
        
        # Find matches
        for i in range(len1):
            start = max(0, i - match_distance)
            end = min(len2, i + match_distance + 1)
            
            for j in range(start, end):
                if s2_matches[j] or s1[i] != s2[j]:
                    continue
                s1_matches[i] = s2_matches[j] = True
                matches += 1
                break
        
        if matches == 0:
            return 0.0
        
        # Count transpositions
        k = 0
        for i in range(len1):
            if not s1_matches[i]:
                continue
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
        
        jaro = ((matches / len1) + (matches / len2) + ((matches - transpositions / 2) / matches)) / 3.0
        
        # Winkler prefix bonus
        prefix_len = 0
        max_prefix = min(4, min(len1, len2))
        for i in range(max_prefix):
            if s1[i] == s2[i]:
                prefix_len += 1
            else:
                break
        
        p = 0.1  # Winkler scaling factor
        return jaro + (prefix_len * p * (1 - jaro))
    
    def _token_overlap(self, s1: str, s2: str) -> float:
        """Compute token overlap ratio between two strings.
        
        Tokenizes strings and calculates intersection/min(tokens_a, tokens_b).
        Catches cases like "Elastic Stack" vs "ELK Stack" (2/2 overlap).
        
        Args:
            s1: First string
            s2: Second string
            
        Returns:
            Overlap ratio 0.0-1.0
        """
        # Tokenize to lowercase words
        def tokenize(s: str) -> set:
            return set(w.lower() for w in s.split() if w.isalnum() or len(w) > 2)
        
        tokens_a = tokenize(s1)
        tokens_b = tokenize(s2)
        
        if not tokens_a or not tokens_b:
            return 0.0
        
        intersection = tokens_a & tokens_b
        return len(intersection) / min(len(tokens_a), len(tokens_b))
    
    def _llm_verify_pair(
        self,
        name_a: str,
        name_b: str,
        entity_type: str,
    ) -> Dict:
        """Ask LLM if two entities are the same real-world entity.
        
        Uses Qwen3.6-35B on Mediaserver for YES/NO verification.
        Checks reasoning_content first, falls back to content field.
        
        Args:
            name_a: First entity name
            name_b: Second entity name
            entity_type: Type of entities
            
        Returns:
            Dict with keys:
                - verdict: "YES" or "NO"
                - confidence: 0.0-1.0 score
                - reasoning: Optional explanation
        """
        prompt = f"""Are these the same real-world entity? Answer ONLY 'YES' or 'NO' followed by a confidence score 0-100.

Entity A: {name_a} (type: {entity_type})
Entity B: {name_b} (type: {entity_type})

Consider: Are these different names for the same thing, or genuinely different entities?
Examples:
- 'Elastic Stack' vs 'ELK Stack' → YES (same product suite)
- 'Elastic Security' vs 'Elastic SLED' → NO (different products)
- 'SLED' vs 'State, Local, and Education' → YES (same acronym)
- 'AI/ML' vs 'GenAI' → NO (related but different concepts)

Your response:"""
        
        try:
            response = self._llm_session.post(
                self.llm_url,
                json={
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.1,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract content - check reasoning_content first for Qwen models
            message = data.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "") or ""
            if not content:
                content = message.get("reasoning_content", "") or ""
            
            content = content.strip().lower()
            
            # Parse verdict
            verdict = "NO"
            if "yes" in content[:10]:  # Check first 10 chars
                verdict = "YES"
            
            # Parse confidence
            confidence = 0.8  # default
            import re
            # Look for number 0-100
            match = re.search(r'(\d{1,3})', content)
            if match:
                conf_val = int(match.group(1))
                if 0 <= conf_val <= 100:
                    confidence = conf_val / 100.0
            
            return {
                "verdict": verdict,
                "confidence": confidence,
                "reasoning": content[:200],  # truncate for brevity
            }
            
        except Exception as e:
            logger.warning(f"LLM verification failed for {name_a}/{name_b}: {e}")
            return {"verdict": "NO", "confidence": 0.0, "reasoning": f"error: {e}"}
    
    def _get_entity_degree(self, entity_name: str) -> Optional[int]:
        """Get relationship count for an entity.
        
        Uses Cypher count of edges connected to entity.
        
        Args:
            entity_name: Name of entity to check
            
        Returns:
            Degree (number of relationships) or None if not found
        """
        query = (
            f"MATCH (e:Entity)-[r]-() WHERE e.name = '{entity_name}' "
            "RETURN COUNT(r) AS degree"
        )
        
        try:
            rows = self.kg.query_cypher(query)
            if rows and len(rows) > 0:
                return rows[0].get("degree", 0)
            return 0
        except Exception as e:
            logger.error(f"Failed to get degree for {entity_name}: {e}")
            return None
    
    def _merge_pair(
        self,
        canonical_name: str,
        duplicate_name: str,
        entity_type: str,
        dry_run: bool = True,
    ) -> Dict:
        """Merge one pair of duplicates.
        
        Transfers all relationships from duplicate to canonical,
        then deletes the duplicate entity.
        
        Args:
            canonical_name: Name of entity to keep (higher degree)
            duplicate_name: Name of entity to merge/absorb
            entity_type: Type of both entities
            dry_run: If True, only report what would be done
            
        Returns:
            Dict with success status and details
        """
        if dry_run:
            return {
                "success": True,
                "action": "would_merge",
                "canonical": canonical_name,
                "duplicate": duplicate_name,
            }
        
        try:
            # Get relationships of duplicate
            rel_query = (
                f"MATCH (e:Entity)-[r]-(other) WHERE e.name = '{duplicate_name}' "
                "RETURN type(r) AS rel_type, other.name AS other_name"
            )
            rels = self.kg.query_cypher(rel_query)
            
            rels_transferred = 0
            
            # Create equivalent relationships from canonical
            for rel in rels:
                other_name = rel.get("other_name")
                if other_name and other_name != canonical_name:
                    create_query = (
                        f"MATCH (c:Entity) WHERE c.name = '{canonical_name}' "
                        f"MATCH (o:Entity) WHERE o.name = '{other_name}' "
                        "CREATE (c)-[:RELATED_TO]->(o)"
                    )
                    try:
                        self.kg.query_cypher(create_query)
                        rels_transferred += 1
                    except Exception:
                        pass  # Relationship may already exist
            
            # Delete duplicate entity
            # DETACH DELETE required by KuzuDB to remove nodes with relationships
            delete_query = f"MATCH (e:Entity) WHERE e.name = '{duplicate_name}' DETACH DELETE e"
            try:
                self.kg.query_cypher(delete_query)
            except Exception as e:
                logger.warning(f"Failed to delete duplicate {duplicate_name}: {e}")
                return {
                    "success": False,
                    "error": f"delete_failed: {e}",
                    "relationships_transferred": rels_transferred,
                }
            
            return {
                "success": True,
                "relationships_transferred": rels_transferred,
                "canonical": canonical_name,
                "duplicate_deleted": duplicate_name,
            }
            
        except Exception as e:
            logger.error(f"Merge failed for {canonical_name}/{duplicate_name}: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    def run(
        self,
        entity_type: Optional[str] = None,
        stage: str = "candidates",
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Run the full resolution pipeline or a single stage.
        
        Args:
            entity_type: Optional filter by entity type
            stage: Pipeline stage to run (candidates, verify, merge, or full)
            dry_run: Whether to simulate changes
            
        Returns:
            Pipeline results dict
        """
        result: Dict[str, Any] = {"stage": stage, "dry_run": dry_run}
        
        if stage == "candidates":
            candidates = self.find_candidates(entity_type)
            result["candidates"] = candidates
            result["count"] = len(candidates)
            
        elif stage == "verify":
            candidates = self.find_candidates(entity_type)
            verified = self.verify_candidates(candidates)
            result["verified"] = verified
            result["verified_count"] = len(verified)
            result["candidate_count"] = len(candidates)
            
        elif stage == "merge":
            candidates = self.find_candidates(entity_type)
            verified = self.verify_candidates(candidates)
            merge_result = self.merge_duplicates(verified, dry_run=dry_run)
            result.update(merge_result)
            
        elif stage == "full":
            # Run all 3 stages
            candidates = self.find_candidates(entity_type)
            verified = self.verify_candidates(candidates)
            merge_result = self.merge_duplicates(verified, dry_run=dry_run)
            result["candidates"] = candidates
            result["candidates_count"] = len(candidates)
            result["verified"] = verified
            result["verified_count"] = len(verified)
            result.update(merge_result)
            
        else:
            result = {"status": "error", "message": f"Unknown stage: {stage}"}
        
        return result
