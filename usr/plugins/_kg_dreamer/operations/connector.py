"""CONNECT operation for KG Dreamer.

Finds entities that share documents but have no direct relationship,
creating IMPLIED_RELATION edges between them.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConnectOperation:
    """Create implied relationships between co-occurring entities.

    Entities that appear together in multiple documents likely have
    a semantic relationship. This operation finds such pairs and
    creates IMPLIED_RELATION edges with weights proportional to
    co-occurrence frequency.

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for write operations.
        config: Operation configuration dict.
    """

    DEFAULT_MIN_SHARED_DOCS: int = 2
    DEFAULT_MAX_CANDIDATES: int = 500
    DEFAULT_RELATIONSHIP_TYPE: str = "IMPLIED_RELATION"

    def __init__(
        self,
        kg_client: Any,
        audit_chain: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ConnectOperation.

        Args:
            kg_client: KG client with query_cypher() and create_relationship().
            audit_chain: Audit chain with append() method.
            config: Optional config overrides for min_shared_docs,
                   max_candidates, relationship_type.
        """
        self.kg = kg_client
        self.audit = audit_chain
        cfg = config or {}

        self.min_shared_docs = cfg.get(
            "min_shared_docs", self.DEFAULT_MIN_SHARED_DOCS
        )
        self.max_candidates = cfg.get(
            "max_candidates", self.DEFAULT_MAX_CANDIDATES
        )
        self.relationship_type = cfg.get(
            "relationship_type", self.DEFAULT_RELATIONSHIP_TYPE
        )

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute CONNECT operation.

        Finds entity pairs that co-occur in documents and creates
        IMPLIED_RELATION relationships.

        Args:
            dry_run: If True, report candidates without creating edges.

        Returns:
            Dict with candidates_found, connections_made, dry_run flag,
            and details of each connection.
        """
        candidates = self._find_candidates()
        if not candidates:
            logger.info("No connection candidates found.")
            return {
                "candidates_found": 0,
                "connections_made": 0,
                "dry_run": dry_run,
                "details": [],
            }

        connections: List[Dict[str, Any]] = []
        connections_made = 0

        for candidate in candidates[: self.max_candidates]:
            detail = self._process_candidate(candidate, dry_run)
            connections.append(detail)
            if detail.get("created"):
                connections_made += 1

        logger.info(
            "CONNECT completed: %d candidates, %d connections (dry_run=%s)",
            len(candidates),
            connections_made,
            dry_run,
        )

        return {
            "candidates_found": len(candidates),
            "connections_made": connections_made,
            "dry_run": dry_run,
            "details": connections,
        }

    def _find_candidates(self) -> List[Dict[str, Any]]:
        """Query KG for entity pairs in same domain with shared categories.

        Finds entities of same type in same domain that share categories
        but don't have a direct RELATES_TO relationship.

        Returns:
            List of candidate dicts with e1_name, e2_name, type1,
            type2, and shared_categories count.
        """
        # Find pairs in same domain/type with overlapping categories
        cypher = (
            "MATCH (e1:Entity), (e2:Entity) "
            "WHERE e1.name < e2.name "
            "AND e1.domain = e2.domain "
            "AND e1.categories IS NOT NULL "
            "AND e2.categories IS NOT NULL "
            "WITH e1, e2, "
            "split(e1.categories, ',') AS c1, "
            "split(e2.categories, ',') AS c2 "
            "WITH e1, e2, c1, c2, "
            "size([x IN c1 WHERE x IN c2]) AS shared_count "
            "WHERE shared_count >= $min_shared "
            "AND NOT EXISTS { MATCH (e1)-[:RELATES_TO]-(e2) } "
            "RETURN e1.name AS e1_name, e2.name AS e2_name, "
            "e1.type AS type1, e2.type AS type2, shared_count, "
            "e1.domain AS domain"
        )

        try:
            rows = self.kg.query_cypher(
                cypher, {"min_shared": self.min_shared_docs}
            )
            candidates: List[Dict[str, Any]] = [
                {
                    "e1_name": r.get("e1_name", ""),
                    "e2_name": r.get("e2_name", ""),
                    "type1": r.get("type1", "unknown"),
                    "type2": r.get("type2", "unknown"),
                    "shared_docs": int(r.get("shared_count", 0)),
                    "domain": r.get("domain", "unknown"),
                }
                for r in rows
                if r.get("e1_name") and r.get("e2_name")
            ]
            logger.debug("Found %d connection candidates", len(candidates))
            return candidates
        except Exception as exc:
            logger.error("Failed to query candidates: %s", exc)
            return []

    def _process_candidate(
        self, candidate: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Process a single candidate pair.

        Args:
            candidate: Dict with e1_name, e2_name, shared_docs.
            dry_run: If True, don't create the relationship.

        Returns:
            Dict with connection details and created status.
        """
        e1 = candidate.get("e1_name", "")
        e2 = candidate.get("e2_name", "")
        weight = candidate.get("shared_docs", 0)

        detail = {
            "e1": e1,
            "e2": e2,
            "type1": candidate.get("type1", "unknown"),
            "type2": candidate.get("type2", "unknown"),
            "weight": weight,
            "created": False,
        }

        if dry_run:
            detail["status"] = "would_create"
            self._log_audit(e1, e2, weight, dry_run=True)
            return detail

        try:
            # Create relationship via KG client
            success = self.kg.create_relationship(
                source_name=e1, target_name=e2, rel_type=self.relationship_type
            )
            if success:
                detail["created"] = True
                detail["status"] = "created"
                self._log_audit(e1, e2, weight, dry_run=False)
            else:
                detail["status"] = "failed"
                logger.warning("Failed to create relationship %s -> %s", e1, e2)
        except Exception as exc:
            detail["status"] = "error"
            detail["error"] = str(exc)
            logger.error("Error creating relationship %s -> %s: %s", e1, e2, exc)

        return detail

    def _log_audit(
        self, e1: str, e2: str, weight: int, dry_run: bool
    ) -> None:
        """Log connection to audit chain.

        Args:
            e1: Source entity name.
            e2: Target entity name.
            weight: Relationship weight (shared docs count).
            dry_run: Whether this was a dry run.
        """
        try:
            self.audit.append(
                action="add" if not dry_run else "dry_run",
                target_type="relationship",
                target_id=f"{e1}->{e2}:{self.relationship_type}",
                source="kg_dreamer.operations.connector",
                metadata={
                    "source_entity": e1,
                    "target_entity": e2,
                    "relationship_type": self.relationship_type,
                    "weight": weight,
                    "dry_run": dry_run,
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
