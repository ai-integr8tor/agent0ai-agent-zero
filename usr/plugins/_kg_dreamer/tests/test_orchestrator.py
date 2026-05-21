"""Unit tests for DreamOrchestrator.

Tests config loading, run_cycle (dry-run, single operation, fault isolation),
and get_status. All external dependencies are mocked.
"""

import sys
import os
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure plugin root is importable
PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PLUGIN_DIR)

# Mock the helpers module BEFORE importing orchestrator, so we never touch
# _kg_pipeline or any real service.
import helpers as _helpers_mod


def _setup_mock_helpers():
    """Patch helpers module functions to return MagicMocks."""
    _helpers_mod.get_kg_client = MagicMock(return_value=MagicMock())
    _helpers_mod.get_audit_chain = MagicMock(return_value=MagicMock())
    _helpers_mod.get_health_scorer = MagicMock(return_value=MagicMock())


_setup_mock_helpers()

from orchestrator import DreamOrchestrator, OPERATION_ORDER


class TestDreamOrchestratorInit(unittest.TestCase):
    """Test DreamOrchestrator.__init__ and config loading."""

    @patch.object(DreamOrchestrator, "_ensure_directories")
    def test_init_loads_config_from_yaml(self, mock_dirs):
        """Init loads default_config.yaml and sets config dict."""
        orch = DreamOrchestrator()

        self.assertIsInstance(orch.config, dict)
        self.assertIn("dreamer", orch.config)
        # Verify the config has operations section
        ops = orch.config["dreamer"].get("operations", {})
        self.assertIn("connect", ops)
        self.assertIn("prune", ops)

    @patch.object(DreamOrchestrator, "_ensure_directories")
    def test_init_custom_config_path_missing_returns_empty(self, mock_dirs):
        """Init with non-existent config_path sets config to empty dict."""
        orch = DreamOrchestrator(config_path="/nonexistent/path.yaml")

        self.assertEqual(orch.config, {})

    @patch.object(DreamOrchestrator, "_ensure_directories")
    def test_init_sets_log_and_state_paths(self, mock_dirs):
        """Init sets log_dir and state_file from config."""
        orch = DreamOrchestrator()

        self.assertIsInstance(orch.log_dir, Path)
        self.assertIsInstance(orch.state_file, Path)


class TestDreamOrchestratorRunCycle(unittest.TestCase):
    """Test DreamOrchestrator.run_cycle with various configurations."""

    def setUp(self):
        """Create orchestrator with mocked dependencies."""
        # Patch _ensure_directories to avoid directory creation
        with patch.object(DreamOrchestrator, "_ensure_directories"):
            self.orch = DreamOrchestrator()

        self.mock_kg = MagicMock()
        self.mock_audit = MagicMock()
        self.mock_scorer = MagicMock()

        _helpers_mod.get_kg_client.return_value = self.mock_kg
        _helpers_mod.get_audit_chain.return_value = self.mock_audit
        _helpers_mod.get_health_scorer.return_value = self.mock_scorer

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_dry_run(self, mock_load_state, mock_save_state, mock_save_report):
        """Dry run cycle completes with dry_run=True in report."""
        # Mock all operations to return success
        with patch.object(self.orch, "_create_operation") as mock_create:
            mock_op = MagicMock()
            mock_op.execute.return_value = {"status": "ok", "candidates_found": 0}
            mock_create.return_value = mock_op

            report = self.orch.run_cycle(dry_run=True)

        self.assertTrue(report["dry_run"])
        self.assertIn("operations", report)
        self.assertIn("summary", report)
        self.assertEqual(report["summary"]["successful"], len(OPERATION_ORDER))
        self.assertEqual(report["summary"]["failed"], 0)

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_single_operation(self, mock_load_state, mock_save_state, mock_save_report):
        """Running a single operation only executes that operation."""
        with patch.object(self.orch, "_create_operation") as mock_create:
            mock_op = MagicMock()
            mock_op.execute.return_value = {"status": "ok"}
            mock_create.return_value = mock_op

            report = self.orch.run_cycle(dry_run=True, operations=["connect"])

        self.assertIn("connect", report["operations"])
        # Only 1 operation should be in the report
        self.assertEqual(len(report["operations"]), 1)
        self.assertEqual(report["summary"]["total_operations"], 1)

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_one_failure_doesnt_stop_others(self, mock_load_state, mock_save_state, mock_save_report):
        """When one operation fails, others still run and report contains all."""
        call_count = [0]
        def create_op(name):
            mock_op = MagicMock()
            if name == "prune":
                mock_op.execute.side_effect = RuntimeError("prune crashed")
            else:
                mock_op.execute.return_value = {"status": "ok"}
            return mock_op

        with patch.object(self.orch, "_create_operation", side_effect=create_op):
            report = self.orch.run_cycle(dry_run=True)

        ops = report["operations"]
        self.assertEqual(ops["prune"]["status"], "error")
        self.assertIn("prune crashed", ops["prune"]["error"])
        # All other operations should have succeeded
        for op_name in OPERATION_ORDER:
            if op_name != "prune":
                self.assertNotEqual(ops[op_name].get("status"), "error",
                                    f"{op_name} should not have errored")

        self.assertGreater(report["summary"]["successful"], 0)
        self.assertEqual(report["summary"]["failed"], 1)

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_unknown_operation_skipped(self, mock_load_state, mock_save_state, mock_save_report):
        """Unknown operation names are skipped with status='skipped'."""
        report = self.orch.run_cycle(dry_run=True, operations=["bogus_op"])

        self.assertEqual(report["operations"]["bogus_op"]["status"], "skipped")
        self.assertIn("Unknown operation", report["operations"]["bogus_op"]["error"])

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_saves_state_and_report(self, mock_load_state, mock_save_state, mock_save_report):
        """run_cycle calls _save_report and _save_state."""
        with patch.object(self.orch, "_create_operation") as mock_create:
            mock_op = MagicMock()
            mock_op.execute.return_value = {"status": "ok"}
            mock_create.return_value = mock_op

            self.orch.run_cycle(dry_run=True, operations=["connect"])

        mock_save_report.assert_called_once()
        mock_save_state.assert_called_once()

        # Verify state includes last_run timestamp
        saved_state = mock_save_state.call_args[0][0]
        self.assertIn("last_run", saved_state)
        self.assertIn("last_report_summary", saved_state)

    @patch.object(DreamOrchestrator, "_save_report")
    @patch.object(DreamOrchestrator, "_save_state")
    @patch.object(DreamOrchestrator, "_load_state", return_value={})
    def test_run_cycle_disabled_operation_skipped(self, mock_load_state, mock_save_state, mock_save_report):
        """When no specific operations given, disabled ops are skipped."""
        # Disable 'pattern' operation
        self.orch.config.setdefault("dreamer", {}).setdefault("operations", {})
        self.orch.config["dreamer"]["operations"]["pattern"] = {"enabled": False}

        with patch.object(self.orch, "_create_operation") as mock_create:
            mock_op = MagicMock()
            mock_op.execute.return_value = {"status": "ok"}
            mock_create.return_value = mock_op

            report = self.orch.run_cycle(dry_run=True)

        self.assertEqual(report["operations"]["pattern"]["status"], "skipped")
        self.assertEqual(report["operations"]["pattern"]["reason"], "disabled")


class TestDreamOrchestratorGetStatus(unittest.TestCase):
    """Test DreamOrchestrator.get_status."""

    def setUp(self):
        with patch.object(DreamOrchestrator, "_ensure_directories"):
            self.orch = DreamOrchestrator()

    def test_get_status_returns_operation_states(self):
        """get_status returns a dict with all OPERATION_ORDER entries."""
        with patch.object(self.orch, "_load_state", return_value={}):
            status = self.orch.get_status()

        self.assertIn("operations", status)
        for op_name in OPERATION_ORDER:
            self.assertIn(op_name, status["operations"])
            self.assertIn("enabled", status["operations"][op_name])

    def test_get_status_includes_last_run_from_state(self):
        """get_status includes last_run timestamp from state file."""
        state = {
            "last_run": "2026-05-20T12:00:00+00:00",
            "last_report_summary": {"successful": 5, "failed": 1, "total_operations": 6},
            "operation_results": {"connect": "ok", "prune": "error"},
        }
        with patch.object(self.orch, "_load_state", return_value=state):
            status = self.orch.get_status()

        self.assertEqual(status["last_run"], "2026-05-20T12:00:00+00:00")
        self.assertEqual(status["operations"]["connect"]["last_status"], "ok")
        self.assertEqual(status["operations"]["prune"]["last_status"], "error")

    def test_get_status_no_state_returns_none_last_run(self):
        """get_status with empty state returns None for last_run."""
        with patch.object(self.orch, "_load_state", return_value={}):
            status = self.orch.get_status()

        self.assertIsNone(status["last_run"])

    def test_get_status_includes_paths(self):
        """get_status includes config_path, log_dir, state_file."""
        with patch.object(self.orch, "_load_state", return_value={}):
            status = self.orch.get_status()

        self.assertIn("config_path", status)
        self.assertIn("log_dir", status)
        self.assertIn("state_file", status)


class TestDreamOrchestratorSaveReport(unittest.TestCase):
    """Test report saving and state persistence."""

    def setUp(self):
        with patch.object(DreamOrchestrator, "_ensure_directories"):
            import tempfile
            self.tmp_dir = tempfile.mkdtemp()
            self.orch = DreamOrchestrator()
            self.orch.log_dir = Path(self.tmp_dir) / "logs"
            self.orch.state_file = Path(self.tmp_dir) / "state" / "dreamer.json"

    def test_save_report_writes_json_file(self):
        """_save_report creates a valid JSON file in log_dir."""
        self.orch.log_dir.mkdir(parents=True, exist_ok=True)
        report = {"timestamp": "2026-05-20T12:00:00", "dry_run": True, "operations": {}}
        report_path = self.orch._save_report(report)

        self.assertTrue(report_path.exists())
        with open(report_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded["timestamp"], "2026-05-20T12:00:00")

    def test_save_state_writes_json_file(self):
        """_save_state creates a valid JSON state file."""
        state = {"last_run": "2026-05-20T12:00:00", "count": 42}
        self.orch._save_state(state)

        self.assertTrue(self.orch.state_file.exists())
        with open(self.orch.state_file) as f:
            loaded = json.load(f)
        self.assertEqual(loaded["last_run"], "2026-05-20T12:00:00")
        self.assertEqual(loaded["count"], 42)


class TestDreamOrchestratorCreateOperation(unittest.TestCase):
    """Test _create_operation creates the correct operation class."""

    def setUp(self):
        with patch.object(DreamOrchestrator, "_ensure_directories"):
            self.orch = DreamOrchestrator()

        self.mock_kg = MagicMock()
        self.mock_audit = MagicMock()
        self.mock_scorer = MagicMock()

        _helpers_mod.get_kg_client.return_value = self.mock_kg
        _helpers_mod.get_audit_chain.return_value = self.mock_audit
        _helpers_mod.get_health_scorer.return_value = self.mock_scorer

    def test_create_operation_connect(self):
        """_create_operation('connect') returns a ConnectOperation."""
        op = self.orch._create_operation("connect")
        from operations.connector import ConnectOperation
        self.assertIsInstance(op, ConnectOperation)

    def test_create_operation_prune(self):
        """_create_operation('prune') returns a PruneOperation."""
        op = self.orch._create_operation("prune")
        from operations.pruner import PruneOperation
        self.assertIsInstance(op, PruneOperation)

    def test_create_operation_unknown_raises(self):
        """_create_operation with unknown name raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.orch._create_operation("nonexistent")
        self.assertIn("Unknown operation", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
