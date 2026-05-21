"""Unit tests for PruneOperation.

Tests candidate filtering by health/age/queries, dry-run behavior,
DETACH DELETE usage, batch size limits, and audit logging.
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call, patch

# Ensure plugin dir is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from operations.pruner import PruneOperation


# Fixed "now" so age calculations are deterministic
FIXED_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

# Real fromisoformat for patching
_real_fromisoformat = datetime.fromisoformat


def _make_entity(
    name: str,
    health: float = 0.05,
    days_ago: int = 200,
    entity_type: str = "concept",
    tier: str = "cold",
) -> dict:
    """Build a score_entities() result dict for one entity."""
    last_seen = (FIXED_NOW - timedelta(days=days_ago)).isoformat()
    return {
        "name": name,
        "total": health,
        "last_seen": last_seen,
        "entity_type": entity_type,
        "tier": tier,
    }


def _make_cypher_row(
    name: str,
    mention_count: int = 1,
    days_ago: int = 200,
    entity_type: str = "concept",
) -> dict:
    """Build a query_cypher() result row for one entity."""
    last_seen = (FIXED_NOW - timedelta(days=days_ago)).isoformat()
    return {
        "name": name,
        "etype": entity_type,
        "mention_count": mention_count,
        "last_seen": last_seen,
    }


def _patch_datetime(mock_dt):
    """Configure a mocked datetime to work with PruneOperation.

    Sets now() to FIXED_NOW and preserves fromisoformat().
    """
    mock_dt.now.return_value = FIXED_NOW
    mock_dt.fromisoformat = _real_fromisoformat


class TestPruneOperationInit(unittest.TestCase):
    """Test PruneOperation.__init__ with various configs."""

    def test_init_with_defaults_populates_defaults(self):
        """Init with no config uses default thresholds."""
        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        op = PruneOperation(kg, audit, scorer)

        self.assertIs(op.kg, kg)
        self.assertIs(op.audit, audit)
        self.assertIs(op.health_scorer, scorer)
        self.assertEqual(op.min_age_days, 180)
        self.assertAlmostEqual(op.max_health_score, 0.1)
        self.assertEqual(op.max_queries, 0)
        self.assertEqual(op.batch_size, 100)

    def test_init_with_custom_config_overrides_defaults(self):
        """Config dict overrides all default values."""
        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        cfg = {
            "min_age_days": 90,
            "max_health_score": 0.3,
            "max_queries": 5,
            "batch_size": 25,
        }
        op = PruneOperation(kg, audit, scorer, cfg)

        self.assertEqual(op.min_age_days, 90)
        self.assertAlmostEqual(op.max_health_score, 0.3)
        self.assertEqual(op.max_queries, 5)
        self.assertEqual(op.batch_size, 25)


class TestPruneOperationDryRun(unittest.TestCase):
    """Test dry-run mode: no deletes executed."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.scorer = MagicMock()
        self.op = PruneOperation(self.kg, self.audit, self.scorer)

    def test_execute_dry_run_no_deletes(self):
        """Dry run never calls query_cypher with DETACH DELETE."""
        self.scorer.score_entities.return_value = {
            "entities": [_make_entity("OldEntity", health=0.01, days_ago=300)]
        }
        self.audit.query.return_value = []
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["entities_pruned"], 0)
        for call_item in self.kg.query_cypher.call_args_list:
            query = call_item[0][0] if call_item[0] else ""
            self.assertNotIn("DETACH DELETE", str(query))

    @patch("operations.pruner.datetime")
    def test_execute_dry_run_marks_candidates_as_would_prune(self, mock_dt):
        """Dry run returns status='would_prune' for each candidate."""
        _patch_datetime(mock_dt)

        self.kg.query_cypher.return_value = [
            _make_cypher_row("Stale", mention_count=1, days_ago=250)
        ]
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["pruned_entities"][0]["status"], "would_prune")
        self.assertFalse(result["pruned_entities"][0]["pruned"])


class TestPruneOperationFiltering(unittest.TestCase):
    """Test filtering logic: health, age, and query count."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.scorer = MagicMock()
        self.op = PruneOperation(self.kg, self.audit, self.scorer)

    @patch("operations.pruner.datetime")
    def test_execute_filters_by_health_score_high_health_excluded(self, mock_dt):
        """Entity with high mention_count (high health) is excluded by Cypher query."""
        _patch_datetime(mock_dt)

        op = PruneOperation(self.kg, self.audit, self.scorer, {"max_health_score": 0.1})
        # Cypher query handles filtering; only the low-health entity qualifies
        self.kg.query_cypher.return_value = [
            _make_cypher_row("LowHealth", mention_count=1, days_ago=300)
        ]
        result = op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["pruned_entities"][0]["name"], "LowHealth")

    @patch("operations.pruner.datetime")
    def test_execute_filters_by_age_too_recent_excluded(self, mock_dt):
        """Entity with recent last_seen is excluded by Cypher query."""
        _patch_datetime(mock_dt)

        op = PruneOperation(self.kg, self.audit, self.scorer, {"min_age_days": 180})
        # Cypher query handles filtering; only the old entity qualifies
        self.kg.query_cypher.return_value = [
            _make_cypher_row("OldEnough", mention_count=1, days_ago=250)
        ]
        result = op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["pruned_entities"][0]["name"], "OldEnough")

    @patch("operations.pruner.datetime")
    def test_execute_filters_by_query_count_queried_entity_excluded(self, mock_dt):
        """Entity queried more than max_queries times is excluded."""
        _patch_datetime(mock_dt)

        op = PruneOperation(self.kg, self.audit, self.scorer, {"max_queries": 0})
        self.scorer.score_entities.return_value = {
            "entities": [
                _make_entity("NeverQueried", health=0.01, days_ago=300),
            ]
        }
        # audit.query returns a match for NeverQueried -> query_count=1 > max_queries=0
        self.audit.query.return_value = [
            {"metadata": {"entity": "NeverQueried"}, "target_id": "NeverQueried"}
        ]
        result = op.execute(dry_run=True)

        # NeverQueried should be excluded since query_count(1) > max_queries(0)
        self.assertEqual(result["candidates_found"], 0)

    def test_execute_no_candidates_returns_empty_result(self):
        """When scorer returns no entities, result has zero candidates."""
        self.scorer.score_entities.return_value = {"entities": []}
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 0)
        self.assertEqual(result["entities_pruned"], 0)
        self.assertEqual(result["pruned_entities"], [])

    def test_execute_scorer_error_returns_empty_result(self):
        """When scorer raises, no crash and candidates_found is 0."""
        self.scorer.score_entities.side_effect = RuntimeError("scorer down")
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 0)
        self.assertEqual(result["entities_pruned"], 0)


class TestPruneOperationLiveRun(unittest.TestCase):
    """Test live execution: DETACH DELETE, archival, and error handling."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.scorer = MagicMock()
        self.op = PruneOperation(self.kg, self.audit, self.scorer)

    @patch("operations.pruner.datetime")
    def test_execute_live_uses_detach_delete(self, mock_dt):
        """Live run issues DETACH DELETE Cypher for each pruned entity."""
        _patch_datetime(mock_dt)

        self.kg.query_cypher.side_effect = [
            [_make_cypher_row("DeadEntity", mention_count=1, days_ago=300)],  # find
            [{"e": "data"}],  # archive
            None,  # delete (DETACH DELETE)
        ]
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["entities_pruned"], 1)
        delete_calls = [
            c for c in self.kg.query_cypher.call_args_list
            if "DETACH DELETE" in (c[0][0] if c[0] else "")
        ]
        self.assertEqual(len(delete_calls), 1)
        # Entity name is passed via params, not inline in query
        delete_params = delete_calls[0][0][1] if len(delete_calls[0][0]) > 1 else delete_calls[0][1]
        self.assertEqual(delete_params.get("name"), "DeadEntity")

    @patch("operations.pruner.datetime")
    def test_execute_live_delete_failure_marks_error(self, mock_dt):
        """When DETACH DELETE query fails, status is 'failed_delete'."""
        _patch_datetime(mock_dt)

        self.kg.query_cypher.side_effect = [
            [_make_cypher_row("StuckEntity", mention_count=1, days_ago=300)],  # find
            [{"e": "data"}],  # archive
            RuntimeError("delete failed"),  # delete raises
        ]
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["entities_pruned"], 0)
        self.assertEqual(result["pruned_entities"][0]["status"], "failed_delete")


class TestPruneOperationBatchSize(unittest.TestCase):
    """Test batch_size limits the number of processed candidates."""

    @patch("operations.pruner.datetime")
    def test_execute_respects_batch_size(self, mock_dt):
        """Only batch_size candidates are processed even if more qualify."""
        _patch_datetime(mock_dt)

        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        op = PruneOperation(kg, audit, scorer, {"batch_size": 2})

        kg.query_cypher.return_value = [
            _make_cypher_row(f"E{i}", mention_count=1, days_ago=300) for i in range(10)
        ]
        result = op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 10)
        self.assertEqual(len(result["pruned_entities"]), 2)


class TestPruneOperationAuditLog(unittest.TestCase):
    """Test audit chain logging for prune operations."""

    @patch("operations.pruner.datetime")
    def test_execute_dry_run_logs_action_dry_run(self, mock_dt):
        """Dry run calls audit.append with action='dry_run'."""
        _patch_datetime(mock_dt)

        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        op = PruneOperation(kg, audit, scorer)

        kg.query_cypher.return_value = [
            _make_cypher_row("Ghost", mention_count=1, days_ago=250)
        ]
        op.execute(dry_run=True)

        audit.append.assert_called_once()
        kwargs = audit.append.call_args[1]
        self.assertEqual(kwargs["action"], "dry_run")
        self.assertEqual(kwargs["target_type"], "entity")
        self.assertEqual(kwargs["target_id"], "Ghost")
        self.assertEqual(kwargs["source"], "kg_dreamer.operations.pruner")
        self.assertEqual(kwargs["metadata"]["entity_name"], "Ghost")
        self.assertTrue(kwargs["metadata"]["dry_run"])

    @patch("operations.pruner.datetime")
    def test_execute_live_logs_action_delete(self, mock_dt):
        """Successful live prune logs action='delete'."""
        _patch_datetime(mock_dt)

        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        op = PruneOperation(kg, audit, scorer)

        kg.query_cypher.side_effect = [
            [_make_cypher_row("Gone", mention_count=1, days_ago=250)],  # find
            [{"e": "data"}],  # archive
            None,  # delete (DETACH DELETE)
        ]
        op.execute(dry_run=False)

        kwargs = audit.append.call_args[1]
        self.assertEqual(kwargs["action"], "delete")
        self.assertFalse(kwargs["metadata"]["dry_run"])


class TestPruneOperationSorting(unittest.TestCase):
    """Test that candidates are sorted by last_seen (oldest first)."""

    @patch("operations.pruner.datetime")
    def test_candidates_sorted_lowest_health_first(self, mock_dt):
        """Prune candidates ordered by last_seen ascending (oldest first)."""
        _patch_datetime(mock_dt)

        kg = MagicMock()
        audit = MagicMock()
        scorer = MagicMock()
        op = PruneOperation(kg, audit, scorer, {"batch_size": 3})

        # Return rows in non-sorted order; code sorts by age descending
        kg.query_cypher.return_value = [
            _make_cypher_row("Recent", mention_count=1, days_ago=200),
            _make_cypher_row("Oldest", mention_count=1, days_ago=400),
            _make_cypher_row("Middle", mention_count=1, days_ago=300),
        ]
        result = op.execute(dry_run=True)

        names = [e["name"] for e in result["pruned_entities"]]
        self.assertEqual(names, ["Oldest", "Middle", "Recent"])


if __name__ == "__main__":
    unittest.main()
