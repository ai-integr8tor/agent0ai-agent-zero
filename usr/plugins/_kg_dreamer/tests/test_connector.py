"""Unit tests for ConnectOperation.

Tests candidate detection, relationship creation, dry-run behavior,
max_candidates enforcement, and audit logging.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, call, patch

# Ensure plugin root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from operations.connector import ConnectOperation


class TestConnectOperationInit(unittest.TestCase):
    """Test ConnectOperation.__init__ with various configs."""

    def test_init_with_defaults_populates_defaults(self):
        """Init with no config uses DEFAULT_MIN_SHARED_DOCS=2, DEFAULT_MAX_CANDIDATES=500."""
        kg = MagicMock()
        audit = MagicMock()
        op = ConnectOperation(kg, audit)

        self.assertIs(op.kg, kg)
        self.assertIs(op.audit, audit)
        self.assertEqual(op.min_shared_docs, 2)
        self.assertEqual(op.max_candidates, 500)
        self.assertEqual(op.relationship_type, "IMPLIED_RELATION")

    def test_init_with_custom_config_overrides_defaults(self):
        """Config dict overrides all default values."""
        kg = MagicMock()
        audit = MagicMock()
        cfg = {
            "min_shared_docs": 5,
            "max_candidates": 10,
            "relationship_type": "CO_OCCURS",
        }
        op = ConnectOperation(kg, audit, cfg)

        self.assertEqual(op.min_shared_docs, 5)
        self.assertEqual(op.max_candidates, 10)
        self.assertEqual(op.relationship_type, "CO_OCCURS")


class TestConnectOperationDryRun(unittest.TestCase):
    """Test dry-run mode: no writes to KG."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.op = ConnectOperation(self.kg, self.audit)

    def test_execute_dry_run_returns_zero_connections_made(self):
        """When candidates exist but dry_run=True, connections_made stays 0."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "Alpha", "e2_name": "Beta", "type1": "org", "type2": "tech", "shared_docs": 3},
        ]
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["connections_made"], 0)
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["status"], "would_create")
        self.assertFalse(result["details"][0]["created"])

    def test_execute_dry_run_never_calls_create_relationship(self):
        """Dry run must not call kg.create_relationship at all."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "A", "e2_name": "B", "type1": "x", "type2": "y", "shared_docs": 4},
        ]
        self.op.execute(dry_run=True)

        self.kg.create_relationship.assert_not_called()

    def test_execute_live_run_calls_create_relationship(self):
        """Live run with successful create_relationship increments connections_made."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "A", "e2_name": "B", "type1": "x", "type2": "y", "shared_docs": 4},
        ]
        self.kg.create_relationship.return_value = True
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["connections_made"], 1)
        self.assertTrue(result["details"][0]["created"])
        self.assertEqual(result["details"][0]["status"], "created")
        self.kg.create_relationship.assert_called_once_with(
            source_name="A", target_name="B", rel_type="IMPLIED_RELATION"
        )


class TestConnectOperationCandidateDetection(unittest.TestCase):
    """Test candidate finding and filtering logic."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.op = ConnectOperation(self.kg, self.audit)

    def test_execute_finds_shared_docs_from_cypher_results(self):
        """Multiple candidates returned from query are all processed."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "X", "e2_name": "Y", "type1": "a", "type2": "b", "shared_docs": 3},
            {"e1_name": "P", "e2_name": "Q", "type1": "c", "type2": "d", "shared_docs": 5},
        ]
        self.kg.create_relationship.return_value = True
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["candidates_found"], 2)
        self.assertEqual(result["connections_made"], 2)
        self.assertEqual(len(result["details"]), 2)

    def test_execute_respects_max_candidates_limit(self):
        """Only the first max_candidates entries are processed."""
        cfg = {"max_candidates": 2}
        op = ConnectOperation(self.kg, self.audit, cfg)

        rows = [
            {"e1_name": f"E{i}", "e2_name": f"F{i}", "type1": "t", "type2": "t", "shared_docs": 3}
            for i in range(10)
        ]
        self.kg.query_cypher.return_value = rows
        self.kg.create_relationship.return_value = True
        result = op.execute(dry_run=False)

        self.assertEqual(result["candidates_found"], 10)
        self.assertEqual(len(result["details"]), 2)
        self.assertEqual(result["connections_made"], 2)

    def test_execute_no_candidates_returns_empty_result(self):
        """When query returns empty list, result has zero candidates."""
        self.kg.query_cypher.return_value = []
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 0)
        self.assertEqual(result["connections_made"], 0)
        self.assertEqual(result["details"], [])

    def test_execute_filters_candidates_with_missing_names(self):
        """Rows with empty/missing e1_name or e2_name are filtered out."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "", "e2_name": "Beta", "type1": "a", "type2": "b", "shared_docs": 3},
            {"e1_name": "Alpha", "e2_name": "", "type1": "a", "type2": "b", "shared_docs": 3},
            {"e1_name": "Valid", "e2_name": "Pair", "type1": "a", "type2": "b", "shared_docs": 4},
        ]
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 1)
        self.assertEqual(result["details"][0]["e1"], "Valid")
        self.assertEqual(result["details"][0]["e2"], "Pair")

    def test_execute_cypher_query_error_returns_empty_candidates(self):
        """When kg.query_cypher raises, candidates_found is 0 and no crash."""
        self.kg.query_cypher.side_effect = Exception("connection refused")
        result = self.op.execute(dry_run=True)

        self.assertEqual(result["candidates_found"], 0)
        self.assertEqual(result["connections_made"], 0)

    def test_execute_live_create_failure_marks_detail_as_failed(self):
        """When create_relationship returns False, detail status is 'failed'."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "A", "e2_name": "B", "type1": "x", "type2": "y", "shared_docs": 3},
        ]
        self.kg.create_relationship.return_value = False
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["connections_made"], 0)
        self.assertEqual(result["details"][0]["status"], "failed")
        self.assertFalse(result["details"][0]["created"])


class TestConnectOperationAuditLog(unittest.TestCase):
    """Test audit chain logging behavior."""

    def setUp(self):
        self.kg = MagicMock()
        self.audit = MagicMock()
        self.op = ConnectOperation(self.kg, self.audit)

    def test_execute_dry_run_logs_to_audit_chain(self):
        """Dry run calls audit.append with action='dry_run' and correct metadata."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "Foo", "e2_name": "Bar", "type1": "x", "type2": "y", "shared_count": 7},
        ]
        self.op.execute(dry_run=True)

        self.audit.append.assert_called_once()
        call_kwargs = self.audit.append.call_args[1]
        self.assertEqual(call_kwargs["action"], "dry_run")
        self.assertEqual(call_kwargs["target_type"], "relationship")
        self.assertEqual(call_kwargs["target_id"], "Foo->Bar:IMPLIED_RELATION")
        self.assertEqual(call_kwargs["source"], "kg_dreamer.operations.connector")
        self.assertEqual(call_kwargs["metadata"]["weight"], 7)
        self.assertTrue(call_kwargs["metadata"]["dry_run"])

    def test_execute_live_run_logs_action_add(self):
        """Live run with successful creation logs action='add'."""
        self.kg.query_cypher.return_value = [
            {"e1_name": "Cat", "e2_name": "Dog", "type1": "x", "type2": "y", "shared_docs": 5},
        ]
        self.kg.create_relationship.return_value = True
        self.op.execute(dry_run=False)

        call_kwargs = self.audit.append.call_args[1]
        self.assertEqual(call_kwargs["action"], "add")
        self.assertFalse(call_kwargs["metadata"]["dry_run"])

    def test_audit_append_failure_does_not_crash(self):
        """If audit.append raises, the operation still completes successfully."""
        self.audit.append.side_effect = RuntimeError("audit broken")
        self.kg.query_cypher.return_value = [
            {"e1_name": "A", "e2_name": "B", "type1": "x", "type2": "y", "shared_docs": 3},
        ]
        self.kg.create_relationship.return_value = True
        result = self.op.execute(dry_run=False)

        self.assertEqual(result["connections_made"], 1)


class TestConnectOperationRelationshipType(unittest.TestCase):
    """Test custom relationship type is passed through correctly."""

    def test_custom_relationship_type_used_in_create(self):
        """Configured relationship_type propagates to create_relationship and audit."""
        kg = MagicMock()
        audit = MagicMock()
        op = ConnectOperation(kg, audit, {"relationship_type": "CO_OCCURS"})

        kg.query_cypher.return_value = [
            {"e1_name": "A", "e2_name": "B", "type1": "x", "type2": "y", "shared_docs": 3},
        ]
        kg.create_relationship.return_value = True
        result = op.execute(dry_run=False)

        kg.create_relationship.assert_called_once_with(
            source_name="A", target_name="B", rel_type="CO_OCCURS"
        )
        audit_kwargs = audit.append.call_args[1]
        self.assertIn("CO_OCCURS", audit_kwargs["target_id"])


if __name__ == "__main__":
    unittest.main()
