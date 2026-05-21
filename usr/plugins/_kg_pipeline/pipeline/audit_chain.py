"""Append-only audit trail for KG write operations.

Provides write provenance tracking for all KG mutations (entity adds,
relationship creates, janitor runs) with daily JSONL files.

Upgrade path: Hash chaining (SHA-256 chain linking events) documented
but not implemented per TC decision. See comments in append().
"""
import json
import os
import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditChain:
    """Append-only audit trail for KG write operations."""

    def __init__(self, audit_dir: str, enabled: bool = True):
        """Initialize audit chain.

        Args:
            audit_dir: Directory for audit JSONL files (one per day).
            enabled: Set False to disable audit (all calls become no-ops).
        """
        self.audit_dir = audit_dir
        self.enabled = enabled
        if self.enabled:
            os.makedirs(self.audit_dir, exist_ok=True)

    def _today_file(self) -> str:
        """Get the JSONL file path for today."""
        today = date.today().isoformat()
        return os.path.join(self.audit_dir, f"kg_audit_{today}.jsonl")

    def _file_for_date(self, dt: date) -> str:
        """Get the JSONL file path for a specific date."""
        return os.path.join(
            self.audit_dir, f"kg_audit_{dt.isoformat()}.jsonl"
        )

    def append(
        self,
        action: str,
        target_type: str,
        target_id: str,
        source: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Append an audit event to today's JSONL file.

        Args:
            action: One of 'add', 'update', 'delete', 'merge', 'janitor'.
            target_type: One of 'entity', 'relationship', 'document'.
            target_id: Source path or document ID.
            source: Module/function that triggered the write.
            metadata: Optional dict with entity_count, rel_count, domain.
        """
        if not self.enabled:
            return

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "source": source,
            "metadata": metadata or {},
        }
        # Upgrade path: add hash chaining here:
        #   event["prev_hash"] = self._last_hash()
        #   event["hash"] = self._hash_event(event)

        filepath = self._today_file()
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error("Audit write failed: %s", exc)

    def query(
        self,
        action: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Query audit events with optional filters.

        Args:
            action: Filter by action type.
            source: Filter by source module.
            since: ISO timestamp to filter from.
            limit: Max results to return.

        Returns:
            List of matching audit events (newest first within limit).
        """
        if not self.enabled:
            return []

        results: List[Dict] = []
        files = sorted(
            f for f in os.listdir(self.audit_dir)
            if f.startswith("kg_audit_") and f.endswith(".jsonl")
        )
        # Read files in reverse chronological order
        for filename in reversed(files):
            filepath = os.path.join(self.audit_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if action and event.get("action") != action:
                            continue
                        if source and event.get("source") != source:
                            continue
                        if since and event.get("timestamp", "") < since:
                            continue
                        results.append(event)
                        if len(results) >= limit:
                            return results
            except OSError:
                continue
        return results

    def get_stats(self) -> Dict:
        """Get audit statistics.

        Returns:
            Dict with total_events, events_by_action, file_count,
            total_size_bytes, and file_details list.
        """
        if not self.enabled or not os.path.isdir(self.audit_dir):
            return {
                "enabled": self.enabled,
                "total_events": 0,
                "events_by_action": {},
                "file_count": 0,
                "total_size_bytes": 0,
                "file_details": [],
            }

        total_events = 0
        by_action: Dict[str, int] = {}
        total_size = 0
        details: List[Dict] = []

        for filename in sorted(os.listdir(self.audit_dir)):
            if not (filename.startswith("kg_audit_")
                    and filename.endswith(".jsonl")):
                continue
            filepath = os.path.join(self.audit_dir, filename)
            size = os.path.getsize(filepath)
            total_size += size
            count = 0
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                            count += 1
                            act = event.get("action", "unknown")
                            by_action[act] = by_action.get(act, 0) + 1
                        except json.JSONDecodeError:
                            count += 1
            except OSError:
                pass
            total_events += count
            details.append({
                "file": filename,
                "events": count,
                "size_bytes": size,
            })

        return {
            "enabled": self.enabled,
            "total_events": total_events,
            "events_by_action": by_action,
            "file_count": len(details),
            "total_size_bytes": total_size,
            "file_details": details,
        }
