"""Dream cycle orchestrator for KG Dreamer.

Runs all enabled dream operations in sequence, manages state,
and produces dream reports.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Support both Agent Zero plugin namespace and standalone execution
from pathlib import Path
import sys

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from helpers import get_audit_chain, get_health_scorer, get_kg_client
from operations.connector import ConnectOperation
from operations.contradiction import ContradictionOperation
from operations.insights import InsightOperation
from operations.patterns import PatternOperation
from operations.pruner import PruneOperation
from operations.strengthener import StrengthenOperation

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH: str = "/a0/usr/plugins/_kg_dreamer/default_config.yaml"

OPERATION_ORDER: List[str] = [
    "connect",
    "strengthen",
    "prune",
    "contradict",
    "pattern",
    "insight",
]


class DreamOrchestrator:
    """Orchestrates the dream cycle across all enabled operations.

    Manages configuration, state, and execution of dream operations.
    Produces dream reports and maintains operation history.

    Attributes:
        config_path: Path to YAML configuration file.
        config: Parsed configuration dict.
        log_dir: Directory for dream reports.
        state_file: Path to JSON state file.
        _kg_client: KG client instance (lazy loaded).
        _audit_chain: Audit chain instance (lazy loaded).
        _health_scorer: Health scorer instance (lazy loaded).
    """

    def __init__(self, config_path: str = None) -> None:
        """Initialize DreamOrchestrator.

        Args:
            config_path: Path to config YAML file. Uses default if None.
        """
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config: Dict[str, Any] = self._load_config()
        self.log_dir: Path = Path(
            self.config.get("dreamer", {}).get(
                "log_dir", "/a0/usr/workdir/logs/kg_dreams"
            )
        )
        self.state_file: Path = Path(
            self.config.get("dreamer", {}).get(
                "state_file", "/a0/usr/workdir/state/kg_dreamer_state.json"
            )
        )

        self._kg_client: Any = None
        self._audit_chain: Any = None
        self._health_scorer: Any = None

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create log_dir if it doesn't exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file.

        Returns:
            Parsed configuration dict.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.debug("Loaded config from %s", self.config_path)
            return config or {}
        except FileNotFoundError:
            logger.error("Config file not found: %s", self.config_path)
            return {}
        except yaml.YAMLError as exc:
            logger.error("Failed to parse config: %s", exc)
            return {}

    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON state file.

        Returns:
            State dict or empty dict if file doesn't exist.
        """
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.debug("Loaded state from %s", self.state_file)
            return state
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse state file: %s", exc)
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save state to JSON state file.

        Args:
            state: State dict to save.
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            logger.debug("Saved state to %s", self.state_file)
        except OSError as exc:
            logger.error("Failed to save state: %s", exc)

    def _save_report(self, report: Dict[str, Any]) -> Path:
        """Save dream report to log directory.

        Args:
            report: Report dict to save.

        Returns:
            Path to saved report file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = self.log_dir / f"dream_report_{timestamp}.json"

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Saved dream report to %s", report_path)
            return report_path
        except OSError as exc:
            logger.error("Failed to save report: %s", exc)
            return Path()

    def _get_kg_client(self) -> Any:
        """Get or create KG client instance (lazy loaded)."""
        if self._kg_client is None:
            self._kg_client = get_kg_client(self.config)
        return self._kg_client

    def _get_audit_chain(self) -> Any:
        """Get or create audit chain instance (lazy loaded)."""
        if self._audit_chain is None:
            self._audit_chain = get_audit_chain(self.config)
        return self._audit_chain

    def _get_health_scorer(self) -> Any:
        """Get or create health scorer instance (lazy loaded)."""
        if self._health_scorer is None:
            self._health_scorer = get_health_scorer(self.config)
        return self._health_scorer

    def _is_operation_enabled(self, op_name: str) -> bool:
        """Check if an operation is enabled in config.

        Args:
            op_name: Name of the operation (e.g., 'connect').

        Returns:
            True if operation is enabled, False otherwise.
        """
        ops_config = self.config.get("dreamer", {}).get("operations", {})
        op_config = ops_config.get(op_name, {})
        return op_config.get("enabled", True)

    def _get_operation_config(self, op_name: str) -> Dict[str, Any]:
        """Get configuration for a specific operation.

        Args:
            op_name: Name of the operation.

        Returns:
            Operation configuration dict.
        """
        ops_config = self.config.get("dreamer", {}).get("operations", {})
        return ops_config.get(op_name, {})

    def _create_operation(self, op_name: str) -> Any:
        """Create operation instance by name.

        Args:
            op_name: Name of the operation to create.

        Returns:
            Operation instance.

        Raises:
            ValueError: If operation name is unknown.
        """
        op_config = self._get_operation_config(op_name)
        kg_client = self._get_kg_client()
        audit_chain = self._get_audit_chain()

        if op_name == "connect":
            return ConnectOperation(kg_client, audit_chain, op_config)
        if op_name == "strengthen":
            return StrengthenOperation(kg_client, audit_chain, op_config)
        if op_name == "prune":
            health_scorer = self._get_health_scorer()
            return PruneOperation(kg_client, audit_chain, health_scorer, op_config)
        if op_name == "contradict":
            return ContradictionOperation(kg_client, audit_chain, op_config)
        if op_name == "pattern":
            return PatternOperation(kg_client, audit_chain, op_config)
        if op_name == "insight":
            return InsightOperation(kg_client, audit_chain, op_config)

        raise ValueError(f"Unknown operation: {op_name}")

    def run_cycle(
        self, dry_run: bool = False, operations: List[str] = None
    ) -> Dict[str, Any]:
        """Run dream cycle with all or specified operations.

        Args:
            dry_run: If True, don't make changes, just report.
            operations: Optional list of specific operations to run.
                       If None, runs all enabled operations in order.

        Returns:
            Dream report dict with timestamp, results, and summary.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        operations_to_run = operations or OPERATION_ORDER

        logger.info(
            "Starting dream cycle: dry_run=%s, operations=%s",
            dry_run,
            operations_to_run,
        )

        results: Dict[str, Any] = {}
        successful: int = 0
        failed: int = 0

        for op_name in operations_to_run:
            if op_name not in OPERATION_ORDER:
                logger.warning("Unknown operation: %s, skipping", op_name)
                results[op_name] = {
                    "status": "skipped",
                    "error": f"Unknown operation: {op_name}",
                }
                failed += 1
                continue

            if not operations and not self._is_operation_enabled(op_name):
                logger.info("Operation disabled: %s, skipping", op_name)
                results[op_name] = {"status": "skipped", "reason": "disabled"}
                continue

            try:
                operation = self._create_operation(op_name)
                op_result = operation.execute(dry_run=dry_run)
                results[op_name] = op_result
                successful += 1
                logger.info(
                    "Operation %s completed: %s", op_name, op_result.get("status", "ok")
                )
            except Exception as exc:
                logger.error("Operation %s failed: %s", op_name, exc)
                results[op_name] = {"status": "error", "error": str(exc)}
                failed += 1

        report = {
            "timestamp": timestamp,
            "dry_run": dry_run,
            "operations": results,
            "summary": {
                "total_operations": len(operations_to_run),
                "successful": successful,
                "failed": failed,
            },
        }

        self._save_report(report)

        state = self._load_state()
        state["last_run"] = timestamp
        state["last_report_summary"] = report["summary"]
        state["operation_results"] = {
            name: res.get("status", "unknown") for name, res in results.items()
        }
        self._save_state(state)

        logger.info(
            "Dream cycle completed: %d successful, %d failed", successful, failed
        )
        return report

    def get_status(self) -> Dict[str, Any]:
        """Get current dream cycle status.

        Returns:
            Status dict with last run info and operation states.
        """
        state = self._load_state()
        dreamer_config = self.config.get("dreamer", {})
        ops_config = dreamer_config.get("operations", {})

        op_states = {}
        for op_name in OPERATION_ORDER:
            op_config = ops_config.get(op_name, {})
            op_states[op_name] = {
                "enabled": op_config.get("enabled", True),
                "last_status": state.get("operation_results", {}).get(op_name),
            }

        return {
            "last_run": state.get("last_run"),
            "last_report_summary": state.get("last_report_summary"),
            "operations": op_states,
            "config_path": str(self.config_path),
            "log_dir": str(self.log_dir),
            "state_file": str(self.state_file),
        }

    def get_reports(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get last N dream reports.

        Args:
            count: Number of reports to retrieve (default 5).

        Returns:
            List of report dicts, sorted newest first.
        """
        try:
            report_files = sorted(self.log_dir.glob("dream_report_*.json"), reverse=True)
            reports = []
            for report_path in report_files[:count]:
                with open(report_path, "r", encoding="utf-8") as f:
                    reports.append(json.load(f))
            return reports
        except OSError as exc:
            logger.error("Failed to load reports: %s", exc)
            return []
