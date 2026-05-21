"""Entity health scoring and tiered memory assignment for KG.

Computes multi-dimensional health scores (0.0-1.0) for entities and
assigns memory tiers: hot, warm, cool, cold.

Scoring dimensions:
  - Connectivity (35%): relationship count normalized via log
  - Recency (20%): days since last_seen, exponential decay
  - Source Quality (20%): mention count + category richness
  - Freshness (15%): update frequency (first_seen vs last_seen)
  - Confidence (10%): entity confidence value
"""
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

from .kg_client import KGClient

logger = logging.getLogger(__name__)


class HealthScorer:
    """Compute health scores and memory tiers for KG entities."""

    TIER_THRESHOLDS: Dict[str, float] = {
        "hot": 0.7,
        "warm": 0.5,
        "cool": 0.3,
        "cold": 0.0,
    }

    WEIGHTS: Dict[str, float] = {
        "connectivity": 0.35,
        "recency": 0.20,
        "source_quality": 0.20,
        "freshness": 0.15,
        "confidence": 0.10,
    }

    def __init__(
        self,
        kg_client: KGClient,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize scorer with KG client and optional config.

        Args:
            kg_client: HTTP client for KG service.
            config: Optional overrides for thresholds and TTL.
        """
        self.kg = kg_client
        cfg = config or {}
        thresholds = cfg.get("health_scoring", {}).get("tier_thresholds", {})
        if thresholds:
            self.TIER_THRESHOLDS = {
                "hot": thresholds.get("hot", 0.7),
                "warm": thresholds.get("warm", 0.5),
                "cool": thresholds.get("cool", 0.3),
                "cold": 0.0,
            }
        ttl_hours = cfg.get("health_scoring", {}).get("cache_ttl_hours", 24)
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(hours=ttl_hours)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_entities(
        self,
        entity_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Score a batch of entities.

        Args:
            entity_type: Filter by entity type (None = all).
            limit: Max entities to score.
            offset: Pagination offset.

        Returns:
            Dict with scored entities, distribution, and metadata.
        """
        now = datetime.now(timezone.utc)

        # Fetch entities
        entities = self._fetch_entities(entity_type, limit, offset)
        if not entities:
            return {"status": "ok", "scored": 0, "entities": [],
                    "distribution": {}}

        # Fetch degrees and max_degree
        degree_map, max_degree = self._fetch_degrees()

        # Score each entity
        scored: List[Dict[str, Any]] = []
        for ent in entities:
            name = ent.get("name", "")
            degree = degree_map.get(name, 0)
            dims = self._compute_score(
                name=name,
                entity_type=ent.get("type", "unknown"),
                domain=ent.get("domain", ""),
                categories=ent.get("categories", ""),
                confidence=float(ent.get("confidence", 0.5)),
                mention_count=int(ent.get("mention_count", 0)),
                first_seen=ent.get("first_seen"),
                last_seen=ent.get("last_seen"),
                degree=degree,
                max_degree=max_degree,
            )
            dims["name"] = name
            dims["entity_type"] = ent.get("type", "unknown")
            dims["tier"] = self._assign_tier(dims["total"])
            scored.append(dims)

        # Update cache
        self._cache = scored
        self._cache_time = now

        distribution = self._calc_distribution(scored)
        return {
            "status": "ok",
            "scored": len(scored),
            "entities": scored,
            "distribution": distribution,
            "max_degree": max_degree,
        }

    def get_tier_distribution(self) -> Dict[str, int]:
        """Get count of entities in each tier (uses cache if fresh).

        Returns:
            Dict mapping tier name to entity count.
        """
        scored = self._get_cached()
        if scored is None:
            result = self.score_entities()
            scored = result.get("entities", [])
        return self._calc_distribution(scored)

    def get_critical_entities(
        self, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get entities with lowest health scores for cleanup review.

        Args:
            limit: Max entities to return.

        Returns:
            List of entity dicts sorted by score ascending.
        """
        scored = self._get_cached()
        if scored is None:
            result = self.score_entities()
            scored = result.get("entities", [])
        scored_sorted = sorted(scored, key=lambda e: e.get("total", 1.0))
        return scored_sorted[:limit]

    def clear_cache(self) -> None:
        """Force cache invalidation."""
        self._cache = None
        self._cache_time = None

    # ------------------------------------------------------------------
    # Scoring dimensions
    # ------------------------------------------------------------------

    def _compute_score(
        self,
        name: str,
        entity_type: str,
        domain: str,
        categories: str,
        confidence: float,
        mention_count: int,
        first_seen: Optional[str],
        last_seen: Optional[str],
        degree: int,
        max_degree: int,
    ) -> Dict[str, Any]:
        """Compute health score for a single entity.

        Returns:
            Dict with total score and per-dimension breakdown.
        """
        connectivity = self._score_connectivity(degree, max_degree)
        recency = self._score_recency(last_seen)
        source_quality = self._score_source_quality(mention_count, categories)
        freshness = self._score_freshness(first_seen, last_seen)
        confidence_score = self._score_confidence(confidence)

        total = (
            self.WEIGHTS["connectivity"] * connectivity
            + self.WEIGHTS["recency"] * recency
            + self.WEIGHTS["source_quality"] * source_quality
            + self.WEIGHTS["freshness"] * freshness
            + self.WEIGHTS["confidence"] * confidence_score
        )
        total = max(0.0, min(1.0, total))

        return {
            "total": round(total, 4),
            "connectivity": round(connectivity, 4),
            "recency": round(recency, 4),
            "source_quality": round(source_quality, 4),
            "freshness": round(freshness, 4),
            "confidence": round(confidence_score, 4),
        }

    def _score_connectivity(self, degree: int, max_degree: int) -> float:
        """Score based on relationship count. Weight: 35%.

        Uses log normalization: log(degree+1) / log(max_degree+1).
        Returns 0.0 when max_degree is 0.
        """
        if max_degree <= 0:
            return 0.0
        val = math.log(degree + 1) / math.log(max_degree + 1)
        return max(0.0, min(1.0, val))

    def _score_recency(self, last_seen: Optional[str]) -> float:
        """Score based on when entity was last seen. Weight: 20%.

        1.0 if less than 7 days, linear decay to 0.1 at 365 days, 0.0 if no last_seen.
        """
        if not last_seen:
            return 0.0
        try:
            dt = self._parse_datetime(last_seen)
            if dt is None:
                return 0.0
            now = datetime.now(timezone.utc)
            days = (now - dt).days
            if days < 0:
                return 1.0
            if days <= 7:
                return 1.0
            if days >= 365:
                return 0.1
            return 1.0 - (0.9 * (days - 7) / 358.0)
        except (ValueError, TypeError):
            logger.warning("Invalid last_seen value: %s", last_seen)
            return 0.0

    def _score_source_quality(
        self, mention_count: int, categories: str
    ) -> float:
        """Score based on mention count and category richness. Weight: 20%.

        mention_score = min(mention_count / 5, 1.0) * 0.5
        category_score = min(category_count / 5, 1.0) * 0.5
        """
        mention_score = min(mention_count / 5.0, 1.0) * 0.5
        cat_count = len(categories.split(",")) if categories else 0
        category_score = min(cat_count / 5.0, 1.0) * 0.5
        return max(0.0, min(1.0, mention_score + category_score))

    def _score_confidence(self, confidence: float) -> float:
        """Score based on entity confidence. Weight: 10%.

        Direct confidence value clamped to [0.0, 1.0].
        """
        return max(0.0, min(1.0, float(confidence)))

    def _score_freshness(
        self,
        first_seen: Optional[str],
        last_seen: Optional[str],
    ) -> float:
        """Score based on how often entity is updated. Weight: 15%.

        1.0 if updated within 7 days of first_seen (actively maintained),
        decays based on the update span relative to total lifetime.
        """
        if not first_seen or not last_seen:
            return 0.0
        try:
            dt_first = self._parse_datetime(first_seen)
            dt_last = self._parse_datetime(last_seen)
            if dt_first is None or dt_last is None:
                return 0.0
            now = datetime.now(timezone.utc)
            lifespan = (now - dt_first).days
            update_span = (dt_last - dt_first).days
            if lifespan <= 0:
                return 1.0
            ratio = update_span / lifespan
            return max(0.0, min(1.0, ratio))
        except (ValueError, TypeError):
            return 0.0

    def _assign_tier(self, score: float) -> str:
        """Assign memory tier based on total score.

        Args:
            score: Total health score in [0.0, 1.0].

        Returns:
            Tier string: hot, warm, cool, or cold.
        """
        if score >= self.TIER_THRESHOLDS["hot"]:
            return "hot"
        if score >= self.TIER_THRESHOLDS["warm"]:
            return "warm"
        if score >= self.TIER_THRESHOLDS["cool"]:
            return "cool"
        return "cold"

    # ------------------------------------------------------------------
    # Data fetching (KuzuDB-compatible Cypher)
    # ------------------------------------------------------------------

    def _fetch_entities(
        self,
        entity_type: Optional[str],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """Fetch entity properties from KG via Cypher.

        Uses simple MATCH/WHERE/RETURN - no CASE WHEN or rand().
        """
        if entity_type:
            query = (
                "MATCH (e:Entity) WHERE e.type = $type "
                "RETURN e.name AS name, e.type AS type, "
                "e.domain AS domain, e.categories AS categories, "
                "e.confidence AS confidence, e.mention_count AS mention_count, "
                "e.first_seen AS first_seen, e.last_seen AS last_seen "
                f"SKIP {offset} LIMIT {limit}"
            )
            rows = self.kg.query_cypher(query, {"type": entity_type})
        else:
            query = (
                "MATCH (e:Entity) "
                "RETURN e.name AS name, e.type AS type, "
                "e.domain AS domain, e.categories AS categories, "
                "e.confidence AS confidence, e.mention_count AS mention_count, "
                "e.first_seen AS first_seen, e.last_seen AS last_seen "
                f"SKIP {offset} LIMIT {limit}"
            )
            rows = self.kg.query_cypher(query)
        return rows

    def _fetch_degrees(self) -> Tuple[Dict[str, int], int]:
        """Fetch relationship counts per entity via Cypher.

        Returns:
            Tuple of (name->degree map, max_degree).
        """
        query = (
            "MATCH (e:Entity)-[r]-() "
            "WITH e.name AS name, count(r) AS degree "
            "RETURN name, degree "
            "ORDER BY degree DESC LIMIT 5000"
        )
        rows = self.kg.query_cypher(query)
        degree_map: Dict[str, int] = {}
        max_degree = 1  # floor at 1 to avoid division by zero
        for row in rows:
            name = row.get("name", "")
            deg = int(row.get("degree", 0))
            degree_map[name] = deg
            if deg > max_degree:
                max_degree = deg
        return degree_map, max_degree

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_datetime(ts: str) -> Optional[datetime]:
        """Parse ISO datetime string to timezone-aware datetime."""
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calc_distribution(
        scored: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Count entities in each tier.

        Args:
            scored: List of scored entity dicts with 'tier' key.

        Returns:
            Dict mapping tier name to count.
        """
        dist: Dict[str, int] = {"hot": 0, "warm": 0, "cool": 0, "cold": 0}
        for ent in scored:
            tier = ent.get("tier", "cold")
            dist[tier] = dist.get(tier, 0) + 1
        return dist

    def _get_cached(self) -> Optional[List[Dict[str, Any]]]:
        """Return cached scores if still within TTL."""
        if self._cache is None or self._cache_time is None:
            return None
        now = datetime.now(timezone.utc)
        if now - self._cache_time > self._cache_ttl:
            self._cache = None
            self._cache_time = None
            return None
        return self._cache

