"""STRENGTHEN operation for KG Dreamer.

Boosts weights of frequently-accessed relationships and decays
weights of unused pathways based on audit chain activity tracking.
"""
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StrengthenOperation:
    """Boost active relationships, decay dormant ones.

    Analyzes audit chain query history to identify recently-accessed
    entities. Relationships between frequently-accessed entities receive
    weight boosts, while unused relationships experience weight decay.

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for write operations.
        config: Operation configuration dict.
    """

    DEFAULT_BOOST_FACTOR: float = 1.2
    DEFAULT_DECAY_FACTOR: float = 0.95
    DEFAULT_MIN_QUERIES: int = 3
    DEFAULT_MAX_WEIGHT: float = 10.0
    DEFAULT_MIN_WEIGHT: float = 0.1
    RECENT_DAYS: int = 30
    DORMANT_DAYS: int = 90
    SECONDS_PER_DAY: int = 86400

    def __init__(
        self,
        kg_client: Any,
        audit_chain: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize StrengthenOperation.

        Args:
            kg_client: KG client with query_cypher() and update_relationship().
            audit_chain: Audit chain with append() and get_recent().
            config: Optional config overrides for boost_factor, decay_factor.
        """
        self.kg = kg_client
        self.audit = audit_chain
        cfg = config or {}

        self.boost_factor = float(
            cfg.get("boost_factor", self.DEFAULT_BOOST_FACTOR)
        )
        self.decay_factor = float(
            cfg.get("decay_factor", self.DEFAULT_DECAY_FACTOR)
        )
        self.min_queries = int(
            cfg.get("min_queries", self.DEFAULT_MIN_QUERIES)
        )
        self.max_weight = float(
            cfg.get("max_weight", self.DEFAULT_MAX_WEIGHT)
        )
        self.min_weight = float(
            cfg.get("min_weight", self.DEFAULT_MIN_WEIGHT)
        )

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute STRENGTHEN operation.

        Boosts weights of relationships between recently-accessed
        entities and decays weights of dormant relationships.

        Args:
            dry_run: If True, report changes without updating.

        Returns:
            Dict with boosted, decayed, total_updated counts,
            and details of each change.
        """
        relationships = self._get_relationships_with_weights()
        if not relationships:
            logger.info("No weighted relationships found.")
            return {
                "boosted": 0,
                "decayed": 0,
                "total_updated": 0,
                "dry_run": dry_run,
                "details": [],
            }

        recent_entities = self._get_recently_accessed_entities()
        dormant_entities = self._get_dormant_entities()

        boosted_count = 0
        decayed_count = 0
        details: List[Dict[str, Any]] = []

        for rel in relationships:
            result = self._process_relationship(
                rel, recent_entities, dormant_entities, dry_run
            )
            details.append(result)

            if result.get("action") == "boosted":
                boosted_count += 1
            elif result.get("action") == "decayed":
                decayed_count += 1

        total_updated = boosted_count + decayed_count

        logger.info(
            "STRENGTHEN completed: %d boosted, %d decayed, "
            "total %d (dry_run=%s)",
            boosted_count,
            decayed_count,
            total_updated,
            dry_run,
        )

        return {
            "boosted": boosted_count,
            "decayed": decayed_count,
            "total_updated": total_updated,
            "dry_run": dry_run,
            "details": details,
        }

    def _get_relationships_with_weights(self) -> List[Dict[str, Any]]:
        """Query KG for all relationships with weight property.

        Note: Current KG schema does not support weighted relationships.
        RELATES_TO edges only have rel_type, confidence, doc_id, created_at.
        This operation requires schema update to add 'weight' property.

        Returns:
            Empty list - weighted relationships not supported in current schema.
        """
        # Check if KG supports weighted relationships
        cypher = (
            "MATCH (e1:Entity)-[r:RELATES_TO]->(e2:Entity) "
            "WHERE r.weight IS NOT NULL "
            "RETURN e1.name AS source_name, e2.name AS target_name, "
            "r.rel_type AS rel_type, r.weight AS weight "
            "LIMIT 1"
        )

        try:
            rows = self.kg.query_cypher(cypher, {})
            if not rows:
                logger.warning(
                    "STRENGTHEN: KG schema does not support weighted relationships. "
                    "Please update KG schema to add 'weight' property to RELATES_TO edges."
                )
                return []  # Weighted relationships not supported

            # If we get here, weights exist - fetch all
            cypher = (
                "MATCH (e1:Entity)-[r:RELATES_TO]->(e2:Entity) "
                "WHERE r.weight IS NOT NULL "
                "RETURN e1.name AS source_name, e2.name AS target_name, "
                "r.rel_type AS rel_type, r.weight AS weight"
            )
            rows = self.kg.query_cypher(cypher, {})
            relationships: List[Dict[str, Any]] = [
                {
                    "source_name": r.get("source_name", ""),
                    "target_name": r.get("target_name", ""),
                    "rel_type": r.get("rel_type", "RELATES_TO"),
                    "weight": float(r.get("weight", 1.0)),
                }
                for r in rows
                if r.get("source_name") and r.get("target_name")
            ]
            logger.debug("Found %d weighted relationships", len(relationships))
            return relationships
        except Exception as exc:
            logger.error("Failed to query relationships: %s", exc)
            return []

    def _get_recently_accessed_entities(self) -> Dict[str, int]:
        """Read audit chain for entities accessed in last 30 days.

        Returns:
            Dict mapping entity names to access counts.
        """
        cutoff_time = time.time() - (
            self.RECENT_DAYS * self.SECONDS_PER_DAY
        )

        try:
            recent_entries = self.audit.get_recent(
                since=cutoff_time, action_filter="query"
            )

            entity_counts: Dict[str, int] = {}
            for entry in recent_entries:
                metadata = entry.get("metadata", {})
                entities = metadata.get("entities", [])
                target_id = entry.get("target_id", "")

                if isinstance(entities, list):
                    for entity in entities:
                        if entity and isinstance(entity, str):
                            entity_counts[entity] = (
                                entity_counts.get(entity, 0) + 1
                            )

                if target_id and isinstance(target_id, str):
                    entity_counts[target_id] = (
                        entity_counts.get(target_id, 0) + 1
                    )

            # Filter to entities with minimum queries
            filtered = {
                k: v for k, v in entity_counts.items()
                if v >= self.min_queries
            }
            logger.debug("Found %d recently-accessed entities", len(filtered))
            return filtered
        except Exception as exc:
            logger.error("Failed to get recent entities: %s", exc)
            return {}

    def _get_dormant_entities(self) -> List[str]:
        """Identify entities not queried in last 90 days.

        Returns:
            List of dormant entity names.
        """
        dormant_cutoff = time.time() - (
            self.DORMANT_DAYS * self.SECONDS_PER_DAY
        )
        recent_cutoff = time.time() - (
            self.RECENT_DAYS * self.SECONDS_PER_DAY
        )

        try:
            all_entities_query = (
                "MATCH (e:Entity) RETURN e.name AS name WHERE e.name IS NOT NULL"
            )
            all_rows = self.kg.query_cypher(all_entities_query, {})
            all_entities = {
                r.get("name")
                for r in all_rows if r.get("name")
            }

            recent_entries = self.audit.get_recent(
                since=recent_cutoff, action_filter="query"
            )
            recently_queried: set = set()
            for entry in recent_entries:
                metadata = entry.get("metadata", {})
                entities = metadata.get("entities", [])
                if isinstance(entities, list):
                    recently_queried.update(
                        e for e in entities if isinstance(e, str)
                    )
                target_id = entry.get("target_id", "")
                if isinstance(target_id, str):
                    recently_queried.add(target_id)

            # Entirely absent from recent queries
            dormant = list(all_entities - recently_queried)
            logger.debug("Found %d dormant entities", len(dormant))
            return dormant
        except Exception as exc:
            logger.error("Failed to get dormant entities: %s", exc)
            return []

    def _process_relationship(
        self,
        rel: Dict[str, Any],
        recent_entities: Dict[str, int],
        dormant_entities: List[str],
        dry_run: bool,
    ) -> Dict[str, Any]:
        """Process a single relationship for boost/decay.

        Args:
            rel: Relationship dict with source_name, target_name, weight.
            recent_entities: Map of recently-accessed entity names.
            dormant_entities: List of dormant entity names.
            dry_run: If True, don't apply changes.

        Returns:
            Dict with relationship details and action taken.
        """
        source = rel.get("source_name", "")
        target = rel.get("target_name", "")
        current_weight = rel.get("weight", 1.0)
        rel_type = rel.get("rel_type", "RELATED")
        rel_id = rel.get("rel_id")

        detail = {
            "source": source,
            "target": target,
            "rel_type": rel_type,
            "old_weight": current_weight,
            "new_weight": current_weight,
            "action": "none",
        }

        source_recent = source in recent_entities
        target_recent = target in recent_entities
        source_dormant = source in dormant_entities
        target_dormant = target in dormant_entities

        # Both entities recently accessed: boost
        if source_recent and target_recent:
            new_weight = min(current_weight * self.boost_factor, self.max_weight)
            detail["new_weight"] = round(new_weight, 3)
            detail["action"] = "boosted"
            detail["reason"] = "both_entities_active"

            if not dry_run:
                self._update_weight(source, target, rel_type, new_weight, rel_id)
                self._log_audit(source, target, rel_type, "boosted", detail)

        # Neither entity accessed recently: decay
        elif source_dormant and target_dormant:
            new_weight = max(current_weight * self.decay_factor, self.min_weight)
            detail["new_weight"] = round(new_weight, 3)
            detail["action"] = "decayed"
            detail["reason"] = "both_entities_dormant"

            if not dry_run:
                self._update_weight(source, target, rel_type, new_weight, rel_id)
                self._log_audit(source, target, rel_type, "decayed", detail)

        else:
            detail["reason"] = "no_change_needed"

        return detail

    def _update_weight(
        self,
        source: str,
        target: str,
        rel_type: str,
        new_weight: float,
        rel_id: Optional[Any] = None,
    ) -> bool:
        """Update relationship weight in KG via Cypher.

        Args:
            source: Source entity name.
            target: Target entity name.
            rel_type: Relationship type.
            new_weight: New weight value.
            rel_id: Optional relationship ID for precise targeting.

        Returns:
            True if update succeeded, False otherwise.
        """
        if rel_id is not None:
            cypher = (
                "MATCH ()-[r]->() WHERE id(r) = $rel_id "
                "SET r.weight = $weight"
            )
            params = {"rel_id": rel_id, "weight": new_weight}
        else:
            cypher = (
                "MATCH (e1:Entity {name: $source})-"""
                f"[r:{rel_type}]-(e2:Entity {{name: $target}}) "
                "SET r.weight = $weight"
            )
            params = {
                "source": source,
                "target": target,
                "weight": new_weight,
            }

        try:
            self.kg.query_cypher(cypher, params)
            logger.debug(
                "Updated weight %s->%s [%s]: %.3f",
                source, target, rel_type, new_weight
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to update weight for %s->%s: %s",
                source, target, exc
            )
            return False

    def _log_audit(
        self,
        source: str,
        target: str,
        rel_type: str,
        action: str,
        details: Dict[str, Any],
    ) -> None:
        """Log strengthen operation to audit chain.

        Args:
            source: Source entity name.
            target: Target entity name.
            rel_type: Relationship type.
            action: The action performed (boosted/decayed).
            details: Operation details dict.
        """
        try:
            self.audit.append(
                action=action,
                target_type="relationship",
                target_id=f"{source}->{target}:{rel_type}",
                source="kg_dreamer.operations.strengthener",
                metadata={
                    "source_entity": source,
                    "target_entity": target,
                    "relationship_type": rel_type,
                    "old_weight": details.get("old_weight"),
                    "new_weight": details.get("new_weight"),
                    "reason": details.get("reason"),
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
