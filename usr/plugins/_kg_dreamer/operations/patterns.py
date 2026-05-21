"""PATTERN operation for KG Dreamer.

Discovers unnamed entity clusters and suggests parent concepts using
community detection and LLM-assisted concept generation.
"""
import logging
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class PatternOperation:
    """Discover unnamed entity clusters and suggest parent concepts.

    Analyzes the knowledge graph to find groups of entities that are
densely connected within communities but lack a unifying parent concept.
Uses LLM to suggest appropriate parent concepts and categories.

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for write operations.
        config: Operation configuration dict.
    """

    DEFAULT_MIN_CLUSTER_SIZE: int = 3
    DEFAULT_MAX_CLUSTERS: int = 50
    DEFAULT_LLM_TIMEOUT: int = 120
    DEFAULT_LLM_MAX_TOKENS: int = 4096

    def __init__(
        self, kg_client: Any, audit_chain: Any, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Initialize PatternOperation.

        Args:
            kg_client: KG client with query_cypher(), create_entity(), link_entity().
            audit_chain: Audit chain with append() method.
            config: Optional config for min_cluster_size, max_clusters, llm settings.
        """
        self.kg = kg_client
        self.audit = audit_chain
        cfg = config or {}
        self.min_cluster_size = int(cfg.get("min_cluster_size", self.DEFAULT_MIN_CLUSTER_SIZE))
        self.max_clusters = int(cfg.get("max_clusters", self.DEFAULT_MAX_CLUSTERS))
        self.llm_endpoint = cfg.get(
            "llm_endpoint", "http://192.168.1.250:11435/v1/chat/completions"
        )
        self.llm_timeout = int(cfg.get("llm_timeout", self.DEFAULT_LLM_TIMEOUT))
        self.llm_max_tokens = int(cfg.get("llm_max_tokens", self.DEFAULT_LLM_MAX_TOKENS))

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute PATTERN operation."""
        clusters = self._find_clusters()
        if not clusters:
            logger.info("No entity clusters found for pattern analysis.")
            return {"clusters_analyzed": 0, "patterns_found": 0, "patterns": [], "dry_run": dry_run}
        patterns: List[Dict[str, Any]] = []
        patterns_found = 0
        for cluster in clusters[: self.max_clusters]:
            pattern = self._analyze_cluster(cluster, dry_run)
            if pattern:
                patterns.append(pattern)
                if pattern.get("suggested_parent"):
                    patterns_found += 1
        logger.info(
            "PATTERN: %d clusters analyzed, %d patterns found (dry_run=%s)",
            len(clusters), patterns_found, dry_run
        )
        if not dry_run and patterns_found > 0:
            self._log_audit("pattern_discovery", len(clusters), patterns)
        return {"clusters_analyzed": len(clusters), "patterns_found": patterns_found, "patterns": patterns, "dry_run": dry_run}

    def _find_clusters(self) -> List[Dict[str, Any]]:
        """Query KG for groups of densely connected entities."""
        cypher = "MATCH (e:Entity) RETURN e.name AS name, e.type AS etype, labels(e) AS labels"
        try:
            rows = self.kg.query_cypher(cypher, {})
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                etype = r.get("etype", "unknown")
                if etype not in by_type:
                    by_type[etype] = []
                by_type[etype].append({"name": r.get("name", ""), "type": etype, "labels": r.get("labels", [])})
            clusters: List[Dict[str, Any]] = []
            for etype, entities in by_type.items():
                if len(entities) >= self.min_cluster_size:
                    if not self._has_parent(entities):
                        clusters.append({"entities": entities, "type": etype, "size": len(entities)})
            logger.debug("Found %d unnamed entity clusters", len(clusters))
            return clusters
        except Exception as exc:
            logger.error("Failed to query entity clusters: %s", exc)
            return []

    def _has_parent(self, entities: List[Dict[str, Any]]) -> bool:
        """Check if entities already share a common parent concept.

        Note: Current KG schema does not support Concept nodes or
        BELONGS_TO relationships. This method is currently a no-op
        to allow pattern discovery to proceed.
        """
        # Concept nodes and BELONGS_TO not supported in current KG schema
        # Return False to allow pattern analysis of all entities
        return False

    def _analyze_cluster(self, cluster: Dict[str, Any], dry_run: bool) -> Optional[Dict[str, Any]]:
        """Analyze a cluster and suggest parent concept via LLM."""
        entities = cluster.get("entities", [])
        if not entities:
            return None
        names = [e.get("name", "") for e in entities if e.get("name")]
        types = list(set(e.get("type", "unknown") for e in entities))
        suggestion = self._suggest_parent(names, types)
        if not suggestion:
            return None
        pattern = {
            "entities": names[:20], "suggested_parent": suggestion.get("concept_name", ""),
            "category": suggestion.get("category", "unknown"),
            "confidence": suggestion.get("confidence", 0.0), "reasoning": suggestion.get("reasoning", ""),
        }
        if not dry_run and suggestion.get("concept_name"):
            pattern["created"] = self._create_parent(
                suggestion["concept_name"], suggestion.get("category", "concept"), names, suggestion.get("reasoning", "")
            )
        return pattern

    def _suggest_parent(self, names: List[str], types: List[str]) -> Optional[Dict[str, Any]]:
        """Call LLM to suggest parent concept name and category."""
        names_str = ", ".join(names[:15])
        types_str = ", ".join(types)
        prompt = (
            f"Given these related entities, suggest a parent concept name and category.\n\n"
            f"Entities: {names_str}\nTypes: {types_str}\n\n"
            "Format: CONCEPT_NAME | CATEGORY | CONFIDENCE (0-1) | REASONING\n\n"
            "Example:\n"
            "Cloud Security Solutions | concept | 0.85 | These entities all relate to security products in cloud environments"
        )
        try:
            response = self._call_llm(prompt)
            return self._parse_response(response)
        except Exception as exc:
            logger.error("LLM suggestion failed: %s", exc)
            return None

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Call LLM endpoint for concept suggestion."""
        payload = {
            "model": "qwen3.6:35b",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a knowledge graph analyst specializing in taxonomy and concept discovery. Suggest clear, concise parent concepts.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.llm_max_tokens,
            "temperature": 0.3,
            "stream": False,
        }
        response = requests.post(self.llm_endpoint, json=payload, timeout=self.llm_timeout)
        response.raise_for_status()
        return response.json()

    def _parse_response(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse LLM response for concept suggestion. Tries reasoning_content first."""
        choices = response.get("choices", [])
        if not choices:
            logger.warning("Empty choices in LLM response")
            return None
        message = choices[0].get("message", {})
        text = message.get("reasoning_content", "") or message.get("content", "")
        if not text:
            logger.warning("Empty LLM message content")
            return None
        text = str(text).strip()
        match = re.search(r"^([^|]+)\s*\|\s*([^|]+)\s*\|\s*([0-9.]+)\s*\|\s*(.+)$", text, re.MULTILINE | re.DOTALL)
        if match:
            try:
                return {
                    "concept_name": match.group(1).strip(), "category": match.group(2).strip(),
                    "confidence": max(0.0, min(1.0, float(match.group(3).strip()))),
                    "reasoning": match.group(4).strip()[:500],
                }
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse concept pattern: %s", exc)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if lines:
            return {"concept_name": lines[0][:100], "category": "suggested_concept", "confidence": 0.5, "reasoning": text[:500]}
        return None

    def _create_parent(self, name: str, category: str, children: List[str], reasoning: str) -> bool:
        """Create parent concept entity and link children."""
        try:
            props = {
                "name": name, "type": category, "source": "kg_dreamer_patterns",
                "description": reasoning[:500], "auto_generated": True,
            }
            if not self.kg.create_entity(props):
                logger.warning("Failed to create concept: %s", name)
                return False
            for child in children:
                self.kg.link_entity(source_name=name, target_name=child, rel_type="CONTAINS", properties={"auto_generated": True})
            logger.debug("Created parent '%s' with %d children", name, len(children))
            return True
        except Exception as exc:
            logger.error("Failed to create parent concept: %s", exc)
            return False

    def _log_audit(self, action: str, count: int, patterns: List[Dict[str, Any]]) -> None:
        """Log pattern operation to audit chain."""
        try:
            self.audit.append(
                action=action, target_type="knowledge_graph", target_id="pattern_analysis",
                source="kg_dreamer.operations.patterns",
                metadata={
                    "cluster_count": count, "patterns_found": len(patterns),
                    "min_cluster_size": self.min_cluster_size, "patterns": patterns[:5],
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
