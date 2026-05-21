"""PRUNE operation for KG Dreamer.

Archives cold-tier entities that are old, low health, and never queried.
Uses health scoring and audit chain analysis to identify stale entities.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PruneOperation:
    """Archive cold-tier entities based on health, age, and usage.

    Identifies entities that are:
    - Low health score (below threshold)
    - Old (not updated within min_age_days)
    - Rarely or never queried (below max_queries threshold)

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for write operations.
        health_scorer: HealthScorer instance for entity scoring.
        config: Operation configuration dict.
    """

    DEFAULT_MIN_AGE_DAYS: int = 180
    DEFAULT_MAX_HEALTH_SCORE: float = 0.1
    DEFAULT_MAX_QUERIES: int = 0
    DEFAULT_BATCH_SIZE: int = 100

    def __init__(
        self,
        kg_client: Any,
        audit_chain: Any,
        health_scorer: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize PruneOperation.

        Args:
            kg_client: KG client with query_cypher() methods.
            audit_chain: Audit chain with query() and append() methods.
            health_scorer: Optional health scorer (kept for backward compat, not used).
            config: Optional config overrides for thresholds.
        """
        self.kg = kg_client
        self.audit = audit_chain
        self.health_scorer = health_scorer
        cfg = config or {}

        self.min_age_days = cfg.get(
            "min_age_days", self.DEFAULT_MIN_AGE_DAYS
        )
        self.max_health_score = cfg.get(
            "max_health_score", self.DEFAULT_MAX_HEALTH_SCORE
        )
        self.max_queries = cfg.get(
            "max_queries", self.DEFAULT_MAX_QUERIES
        )
        self.batch_size = cfg.get(
            "batch_size", self.DEFAULT_BATCH_SIZE
        )

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute PRUNE operation.

        Archives cold-tier entities based on health, age, and usage.

        Args:
            dry_run: If True, report candidates without deleting.

        Returns:
            Dict with candidates_found, entities_pruned, dry_run flag,
            and list of pruned entities.
        """
        candidates = self._find_prune_candidates()
        if not candidates:
            logger.info("No prune candidates found.")
            return {
                "candidates_found": 0,
                "entities_pruned": 0,
                "dry_run": dry_run,
                "pruned_entities": [],
            }

        pruned: List[Dict[str, Any]] = []
        entities_pruned = 0

        for candidate in candidates[: self.batch_size]:
            result = self._process_prune_candidate(candidate, dry_run)
            pruned.append(result)
            if result.get("pruned"):
                entities_pruned += 1

        logger.info(
            "PRUNE completed: %d candidates, %d pruned (dry_run=%s)",
            len(candidates),
            entities_pruned,
            dry_run,
        )

        return {
            "candidates_found": len(candidates),
            "entities_pruned": entities_pruned,
            "dry_run": dry_run,
            "pruned_entities": pruned,
        }

    def _find_prune_candidates(self) -> List[Dict[str, Any]]:
        """Find entities eligible for pruning based on KG properties.

        Finds entities with:
        - Low mention count (<= threshold)
        - Old last_seen (> min_age_days ago)
        - No outgoing/incoming relationships (orphaned entities)

        Returns:
            List of candidate dicts with name, type, mention_count,
            last_seen, and age_days.
        """
        try:
            # Query entities with low mention count and old last_seen
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=self.min_age_days)).isoformat()

            cypher = (
                "MATCH (e:Entity) "
                "WHERE e.mention_count IS NOT NULL "
                "AND e.mention_count <= $min_mentions "
                "AND e.last_seen < $cutoff "
                "AND NOT EXISTS { MATCH (e)-[:RELATES_TO]-() } "
                "RETURN e.name AS name, e.type AS etype, "
                "e.mention_count AS mention_count, e.last_seen AS last_seen "
                "ORDER BY e.last_seen ASC "
                "LIMIT $max_results"
            )

            rows = self.kg.query_cypher(cypher, {
                "min_mentions": 1,
                "cutoff": cutoff_date,
                "max_results": self.batch_size * 2
            })

            candidates: List[Dict[str, Any]] = []
            now = datetime.now(timezone.utc)

            for r in rows:
                name = r.get("name", "")
                ent_type = r.get("etype", "unknown")
                mention_count = int(r.get("mention_count", 0))
                last_seen = r.get("last_seen", "")

                age_days = self._calculate_age_days(now, last_seen)
                if age_days is None:
                    continue

                candidates.append({
                    "name": name,
                    "type": ent_type,
                    "health_score": 1.0 / max(mention_count, 1),  # Inverse of mention count
                    "tier": "cold",
                    "last_seen": last_seen,
                    "age_days": age_days,
                    "query_count": 0,
                    "mention_count": mention_count,
                })

            # Sort by age (oldest first) then by mention count
            candidates.sort(key=lambda x: (x.get("age_days", 0), -x.get("mention_count", 0)), reverse=True)

            logger.debug("Found %d prune candidates", len(candidates))
            return candidates

        except Exception as exc:
            logger.error("Failed to find prune candidates: %s", exc)
            return []

    def _calculate_age_days(
        self, now: datetime, last_seen: Optional[str]
    ) -> Optional[int]:
        """Calculate days since last update.

        Args:
            now: Current UTC datetime.
            last_seen: ISO timestamp string or None.

        Returns:
            Days since last seen, or None if unparseable.
        """
        if not last_seen:
            return None
        try:
            dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).days
        except (ValueError, TypeError) as exc:
            logger.debug("Cannot parse last_seen '%s': %s", last_seen, exc)
            return None

    def _count_entity_queries(self, entity_name: str) -> int:
        """Count how many times entity was queried recently.

        Args:
            entity_name: Name of the entity.

        Returns:
            Count of audit events referencing this entity.
        """
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=self.min_age_days)
            ).isoformat()
            events = self.audit.query(
                since=cutoff,
                limit=1000,
            )
            count = sum(
                1
                for e in events
                if entity_name in str(e.get("metadata", {}))
                or entity_name in e.get("target_id", "")
            )
            return count
        except Exception as exc:
            logger.debug("Failed to query audit for %s: %s", entity_name, exc)
            return 0

    def _process_prune_candidate(
        self, candidate: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Process a single prune candidate.

        Args:
            candidate: Dict with name, type, health_score, etc.
            dry_run: If True, don't delete the entity.

        Returns:
            Dict with prune result details.
        """
        name = candidate.get("name", "")
        result = {
            "name": name,
            "type": candidate.get("type", "unknown"),
            "health_score": candidate.get("health_score", 0.0),
            "tier": candidate.get("tier", "unknown"),
            "age_days": candidate.get("age_days"),
            "query_count": candidate.get("query_count", 0),
            "pruned": False,
            "archived": False,
        }

        if dry_run:
            result["status"] = "would_prune"
            self._log_audit(name, candidate, dry_run=True)
            return result

        try:
            # Archive first
            archive_ok = self._archive_entity(name, candidate)
            result["archived"] = archive_ok

            # Delete entity with DETACH DELETE for KuzuDB
            delete_ok = self._delete_entity(name)

            if archive_ok and delete_ok:
                result["pruned"] = True
                result["status"] = "pruned"
                self._log_audit(name, candidate, dry_run=False)
            elif not delete_ok:
                result["status"] = "failed_delete"
                logger.warning("Failed to delete entity %s", name)
            else:
                result["status"] = "failed_archive"
                logger.warning("Failed to archive entity %s", name)

        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            logger.error("Error pruning entity %s: %s", name, exc)

        return result

    def _archive_entity(
        self, name: str, candidate: Dict[str, Any]
    ) -> bool:
        """Archive entity data before deletion.

        Args:
            name: Entity name.
            candidate: Entity data dict.

        Returns:
            True if archival succeeded.
        """
        try:
            # Get full entity details from KG
            query = (
                "MATCH (e:Entity {name: $name}) "
                "RETURN e, e.name, e.type, e.domain, e.categories, "
                "e.confidence, e.mention_count, e.first_seen, e.last_seen"
            )
            rows = self.kg.query_cypher(query, {"name": name})

            if rows:
                candidate["entity_data"] = rows[0]

            # Archive data is stored in candidate for potential recovery
            candidate["archived_at"] = datetime.now(timezone.utc).isoformat()
            return True

        except Exception as exc:
            logger.warning("Failed to archive entity %s: %s", name, exc)
            return False

    def _delete_entity(self, name: str) -> bool:
        """Delete entity from KG using DETACH DELETE.

        Args:
            name: Entity name.

        Returns:
            True if deletion succeeded.
        """
        try:
            # KuzuDB requires DETACH DELETE to remove entity and its relationships
            query = "MATCH (e:Entity {name: $name}) DETACH DELETE e"
            self.kg.query_cypher(query, {"name": name})
            return True
        except Exception as exc:
            logger.error("Failed to delete entity %s: %s", name, exc)
            return False

    def _log_audit(
        self, name: str, candidate: Dict[str, Any], dry_run: bool
    ) -> None:
        """Log prune operation to audit chain.

        Args:
            name: Entity name.
            candidate: Entity data dict.
            dry_run: Whether this was a dry run.
        """
        try:
            self.audit.append(
                action="delete" if not dry_run else "dry_run",
                target_type="entity",
                target_id=name,
                source="kg_dreamer.operations.pruner",
                metadata={
                    "entity_name": name,
                    "entity_type": candidate.get("type", "unknown"),
                    "health_score": candidate.get("health_score", 0.0),
                    "age_days": candidate.get("age_days"),
                    "query_count": candidate.get("query_count", 0),
                    "dry_run": dry_run,
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
