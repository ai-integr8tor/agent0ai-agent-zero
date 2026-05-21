"""KG Dreamer tool wrapper for Agent Zero.

Exposes dream operations via async tool methods compatible with
Agent Zero's tool pattern.
"""
import logging
from typing import Any, Dict, List, Optional

import sys
import os

_plugin_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_path not in sys.path:
    sys.path.insert(0, _plugin_path)

from orchestrator import DreamOrchestrator

logger = logging.getLogger(__name__)

VALID_OPERATIONS: List[str] = [
    "connect",
    "strengthen",
    "prune",
    "contradict",
    "pattern",
    "insight",
]


class KgDreamer:
    """Agent Zero tool wrapper for KG Dreamer operations.

    Provides async methods to run dream cycles, check status,
    and retrieve reports. Compatible with Agent Zero tool pattern.

    Attributes:
        _orchestrator: DreamOrchestrator instance (lazy loaded).
        _config_path: Path to configuration file.
    """

    def __init__(self, config_path: str = None) -> None:
        """Initialize KgDreamer tool.

        Args:
            config_path: Optional path to config YAML file.
        """
        self._config_path: Optional[str] = config_path
        self._orchestrator: Optional[DreamOrchestrator] = None

    def _get_orchestrator(self) -> DreamOrchestrator:
        """Get or create DreamOrchestrator instance (lazy loaded)."""
        if self._orchestrator is None:
            self._orchestrator = DreamOrchestrator(self._config_path)
        return self._orchestrator

    async def __call__(
        self, method: str, args: Dict[str, Any] = None, **kwargs
    ) -> Dict[str, Any]:
        """Route method calls to appropriate handler.

        Args:
            method: Method name to call (status, run_dream_cycle, etc.).
            args: Method arguments dict.
            **kwargs: Additional keyword arguments.

        Returns:
            Result dict with status key.
        """
        args = args or {}
        args.update(kwargs)

        method_map: Dict[str, callable] = {
            "status": self.status,
            "run_dream_cycle": self.run_dream_cycle,
            "run_operation": self.run_operation,
            "get_report": self.get_report,
        }

        if method not in method_map:
            return {
                "status": "error",
                "error": f"Unknown method: {method}. Valid methods: {list(method_map.keys())}",
            }

        try:
            return await method_map[method](**args)
        except Exception as exc:
            logger.error("Method %s failed: %s", method, exc)
            return {"status": "error", "error": str(exc), "method": method}

    async def status(self) -> Dict[str, Any]:
        """Get dream cycle status and last run information.

        Returns:
            Dict with status ('ok' or 'error'), last_run timestamp,
            operation states, and configuration paths.
        """
        try:
            orchestrator = self._get_orchestrator()
            status_info = orchestrator.get_status()
            return {"status": "ok", **status_info}
        except Exception as exc:
            logger.error("Failed to get status: %s", exc)
            return {"status": "error", "error": str(exc)}

    async def run_dream_cycle(
        self, dry_run: bool = True, operations: List[str] = None
    ) -> Dict[str, Any]:
        """Run full dream cycle with all or specified operations.

        Args:
            dry_run: If True, don't make changes, just report.
            operations: Optional list of specific operations to run.
                       If None, runs all enabled operations in order.

        Returns:
            Dream report dict with timestamp, results, and summary.
        """
        try:
            orchestrator = self._get_orchestrator()
            report = orchestrator.run_cycle(dry_run=dry_run, operations=operations)
            return {"status": "ok", **report}
        except Exception as exc:
            logger.error("Dream cycle failed: %s", exc)
            return {"status": "error", "error": str(exc), "dry_run": dry_run}

    async def run_operation(
        self, operation: str, dry_run: bool = True
    ) -> Dict[str, Any]:
        """Run a single dream operation.

        Args:
            operation: Operation name (connect, strengthen, prune,
                      contradict, pattern, insight).
            dry_run: If True, don't make changes, just report.

        Returns:
            Operation result dict with status.
        """
        if operation not in VALID_OPERATIONS:
            return {
                "status": "error",
                "error": f"Invalid operation: {operation}. Valid: {VALID_OPERATIONS}",
            }

        try:
            orchestrator = self._get_orchestrator()
            report = orchestrator.run_cycle(dry_run=dry_run, operations=[operation])

            op_result = report.get("operations", {}).get(operation, {})
            return {"status": "ok", "operation": operation, **op_result}
        except Exception as exc:
            logger.error("Operation %s failed: %s", operation, exc)
            return {"status": "error", "error": str(exc), "operation": operation}

    async def get_report(self, count: int = 5) -> Dict[str, Any]:
        """Get last N dream reports.

        Args:
            count: Number of reports to retrieve (default 5).

        Returns:
            Dict with status and list of report dicts.
        """
        if not isinstance(count, int) or count < 1:
            return {"status": "error", "error": "count must be a positive integer"}

        try:
            orchestrator = self._get_orchestrator()
            reports = orchestrator.get_reports(count=count)
            return {
                "status": "ok",
                "count": len(reports),
                "reports": reports,
            }
        except Exception as exc:
            logger.error("Failed to get reports: %s", exc)
            return {"status": "error", "error": str(exc)}


# Synchronous convenience methods for non-async usage
def get_dreamer_status(config_path: str = None) -> Dict[str, Any]:
    """Get dream cycle status synchronously.

    Args:
        config_path: Optional path to config YAML file.

    Returns:
        Status dict with last run info and operation states.
    """
    orchestrator = DreamOrchestrator(config_path)
    return orchestrator.get_status()


def run_dream_cycle_sync(
    dry_run: bool = True,
    operations: List[str] = None,
    config_path: str = None,
) -> Dict[str, Any]:
    """Run dream cycle synchronously.

    Args:
        dry_run: If True, don't make changes, just report.
        operations: Optional list of specific operations to run.
        config_path: Optional path to config YAML file.

    Returns:
        Dream report dict with timestamp, results, and summary.
    """
    orchestrator = DreamOrchestrator(config_path)
    return orchestrator.run_cycle(dry_run=dry_run, operations=operations)
