"""Tests for HealthScorer entity health scoring and tiered memory."""
import math
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Add plugin dir to path so `pipeline` package is importable
_plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from pipeline.health_scorer import HealthScorer


def _make_scorer(config: dict = None) -> HealthScorer:
    """Create a HealthScorer with a mock KG client."""
    mock_client = MagicMock()
    return HealthScorer(mock_client, config), mock_client


def _recent_dt(days_ago: int = 0) -> str:
    """Return ISO datetime string for N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


class TestScoreConnectivity(unittest.TestCase):
    """Tests for _score_connectivity dimension."""

    def test_score_connectivity_high(self) -> None:
        """Entity with degree=50 vs max=100 should be ~0.92."""
        scorer, _ = _make_scorer()
        result = scorer._score_connectivity(degree=50, max_degree=100)
        expected = math.log(51) / math.log(101)
        self.assertAlmostEqual(result, expected, places=3)
        self.assertGreater(result, 0.85)
        self.assertLess(result, 1.0)

    def test_score_connectivity_zero(self) -> None:
        """Entity with degree=0 should return 0.0."""
        scorer, _ = _make_scorer()
        result = scorer._score_connectivity(degree=0, max_degree=100)
        self.assertEqual(result, 0.0)

    def test_score_connectivity_max_zero(self) -> None:
        """When max_degree is 0, return 0.0 (avoid div-by-zero)."""
        scorer, _ = _make_scorer()
        result = scorer._score_connectivity(degree=0, max_degree=0)
        self.assertEqual(result, 0.0)


class TestScoreRecency(unittest.TestCase):
    """Tests for _score_recency dimension."""

    def test_score_recency_recent(self) -> None:
        """Entity seen within 7 days should return 1.0."""
        scorer, _ = _make_scorer()
        result = scorer._score_recency(_recent_dt(3))
        self.assertEqual(result, 1.0)

    def test_score_recency_stale(self) -> None:
        """Entity last seen 365+ days ago should return ~0.1."""
        scorer, _ = _make_scorer()
        result = scorer._score_recency(_recent_dt(400))
        self.assertAlmostEqual(result, 0.1, places=2)

    def test_score_recency_none(self) -> None:
        """Entity with no last_seen should return 0.0."""
        scorer, _ = _make_scorer()
        result = scorer._score_recency(None)
        self.assertEqual(result, 0.0)

    def test_score_recency_empty_string(self) -> None:
        """Entity with empty last_seen should return 0.0."""
        scorer, _ = _make_scorer()
        result = scorer._score_recency("")
        self.assertEqual(result, 0.0)


class TestScoreSourceQuality(unittest.TestCase):
    """Tests for _score_source_quality dimension."""

    def test_score_source_quality_high(self) -> None:
        """High mention_count + rich categories should score high."""
        scorer, _ = _make_scorer()
        result = scorer._score_source_quality(
            mention_count=10, categories="devops,docker,cloud,infra,ci-cd"
        )
        # mention_score = min(10/5, 1.0) * 0.5 = 0.5
        # category_score = min(5/5, 1.0) * 0.5 = 0.5
        self.assertAlmostEqual(result, 1.0, places=2)

    def test_score_source_quality_low(self) -> None:
        """Low mentions + no categories should score low."""
        scorer, _ = _make_scorer()
        result = scorer._score_source_quality(mention_count=0, categories="")
        self.assertEqual(result, 0.0)


class TestAssignTier(unittest.TestCase):
    """Tests for _assign_tier."""

    def test_assign_tier_hot(self) -> None:
        """Score >= 0.7 should be 'hot'."""
        scorer, _ = _make_scorer()
        self.assertEqual(scorer._assign_tier(0.85), "hot")
        self.assertEqual(scorer._assign_tier(0.7), "hot")

    def test_assign_tier_warm(self) -> None:
        """Score >= 0.5 and < 0.7 should be 'warm'."""
        scorer, _ = _make_scorer()
        self.assertEqual(scorer._assign_tier(0.6), "warm")
        self.assertEqual(scorer._assign_tier(0.5), "warm")

    def test_assign_tier_cool(self) -> None:
        """Score >= 0.3 and < 0.5 should be 'cool'."""
        scorer, _ = _make_scorer()
        self.assertEqual(scorer._assign_tier(0.4), "cool")
        self.assertEqual(scorer._assign_tier(0.3), "cool")

    def test_assign_tier_cold(self) -> None:
        """Score < 0.3 should be 'cold'."""
        scorer, _ = _make_scorer()
        self.assertEqual(scorer._assign_tier(0.2), "cold")
        self.assertEqual(scorer._assign_tier(0.0), "cold")


class TestComputeScore(unittest.TestCase):
    """Tests for _compute_score full scoring."""

    def test_compute_score_returns_dimensions(self) -> None:
        """Verify all 5 dimensions present in result."""
        scorer, _ = _make_scorer()
        result = scorer._compute_score(
            name="TestEntity",
            entity_type="technology",
            domain="tech",
            categories="a,b,c",
            confidence=0.9,
            mention_count=5,
            first_seen=_recent_dt(30),
            last_seen=_recent_dt(1),
            degree=10,
            max_degree=100,
        )
        for dim in ["total", "connectivity", "recency",
                    "source_quality", "freshness", "confidence"]:
            self.assertIn(dim, result, f"Missing dimension: {dim}")
        self.assertGreaterEqual(result["total"], 0.0)
        self.assertLessEqual(result["total"], 1.0)


class TestTierDistribution(unittest.TestCase):
    """Tests for get_tier_distribution."""

    def test_tier_distribution(self) -> None:
        """Mock entities and verify distribution counts."""
        scorer, mock_client = _make_scorer()
        mock_client.query_cypher.side_effect = [
            # _fetch_entities response
            [
                {"name": "A", "type": "tech", "domain": "x",
                 "categories": "a", "confidence": 0.9,
                 "mention_count": 5, "first_seen": _recent_dt(10),
                 "last_seen": _recent_dt(1)},
                {"name": "B", "type": "tech", "domain": "x",
                 "categories": "", "confidence": 0.3,
                 "mention_count": 0, "first_seen": _recent_dt(200),
                 "last_seen": _recent_dt(100)},
                {"name": "C", "type": "tech", "domain": "x",
                 "categories": "a,b,c,d,e", "confidence": 1.0,
                 "mention_count": 10, "first_seen": _recent_dt(5),
                 "last_seen": _recent_dt(1)},
            ],
            # _fetch_degrees response
            [
                {"name": "A", "degree": 5},
                {"name": "B", "degree": 1},
                {"name": "C", "degree": 50},
            ],
        ]
        dist = scorer.get_tier_distribution()
        self.assertEqual(set(dist.keys()), {"hot", "warm", "cool", "cold"})
        total = sum(dist.values())
        self.assertEqual(total, 3)


class TestCriticalEntities(unittest.TestCase):
    """Tests for get_critical_entities."""

    def test_critical_entities(self) -> None:
        """Verify lowest-scored entities returned first."""
        scorer, mock_client = _make_scorer()
        mock_client.query_cypher.side_effect = [
            [
                {"name": "Good", "type": "tech", "domain": "x",
                 "categories": "a,b,c", "confidence": 1.0,
                 "mention_count": 10, "first_seen": _recent_dt(2),
                 "last_seen": _recent_dt(0)},
                {"name": "Bad", "type": "tech", "domain": "x",
                 "categories": "", "confidence": 0.2,
                 "mention_count": 0, "first_seen": _recent_dt(300),
                 "last_seen": _recent_dt(200)},
            ],
            [
                {"name": "Good", "degree": 50},
                {"name": "Bad", "degree": 0},
            ],
        ]
        critical = scorer.get_critical_entities(limit=10)
        self.assertGreater(len(critical), 0)
        self.assertEqual(critical[0]["name"], "Bad")
        self.assertLess(critical[0]["total"], critical[-1]["total"])


class TestCacheInvalidation(unittest.TestCase):
    """Tests for cache mechanism."""

    def test_cache_invalidation(self) -> None:
        """Score, cache, clear, re-score — cache is properly invalidated."""
        scorer, mock_client = _make_scorer()
        mock_client.query_cypher.side_effect = [
            # First score_entities call
            [{"name": "X", "type": "tech", "domain": "x",
              "categories": "a", "confidence": 0.5,
              "mention_count": 1, "first_seen": _recent_dt(10),
              "last_seen": _recent_dt(1)}],
            [{"name": "X", "degree": 5}],
            # After cache clear, score_entities again
            [{"name": "Y", "type": "tech", "domain": "x",
              "categories": "b", "confidence": 0.8,
              "mention_count": 3, "first_seen": _recent_dt(5),
              "last_seen": _recent_dt(0)}],
            [{"name": "Y", "degree": 10}],
        ]

        # First scoring
        result1 = scorer.score_entities()
        self.assertEqual(result1["scored"], 1)
        self.assertEqual(result1["entities"][0]["name"], "X")

        # Cache should be populated
        self.assertIsNotNone(scorer._cache)

        # Clear cache
        scorer.clear_cache()
        self.assertIsNone(scorer._cache)

        # Re-score with different data
        result2 = scorer.score_entities()
        self.assertEqual(result2["scored"], 1)
        self.assertEqual(result2["entities"][0]["name"], "Y")


class TestScoreRanges(unittest.TestCase):
    """Verify all scores are within [0.0, 1.0]."""

    def test_all_scores_in_range(self) -> None:
        """Extreme inputs should still produce valid scores."""
        scorer, _ = _make_scorer()
        result = scorer._compute_score(
            name="Extreme",
            entity_type="test",
            domain="x",
            categories="",
            confidence=0.0,
            mention_count=0,
            first_seen=None,
            last_seen=None,
            degree=0,
            max_degree=100,
        )
        for key, val in result.items():
            self.assertGreaterEqual(val, 0.0, f"{key} below 0.0")
            self.assertLessEqual(val, 1.0, f"{key} above 1.0")


if __name__ == "__main__":
    unittest.main()
