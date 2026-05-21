"""Tests for AuditChain append-only audit trail."""
import json
import os
import shutil
import time
import unittest
from datetime import date, datetime, timedelta, timezone

import sys
sys.path.insert(0, "/a0/usr/plugins/_kg_pipeline")
from pipeline.audit_chain import AuditChain


class TestAuditChain(unittest.TestCase):
    """Unit tests for AuditChain."""

    def setUp(self) -> None:
        """Create temp audit directory for each test."""
        self.audit_dir = f"/tmp/test_audit_{os.getpid()}"
        os.makedirs(self.audit_dir, exist_ok=True)

    def tearDown(self) -> None:
        """Remove temp audit directory after each test."""
        shutil.rmtree(self.audit_dir, ignore_errors=True)

    def _make_chain(self, enabled: bool = True) -> AuditChain:
        """Create an AuditChain pointing at the test directory."""
        return AuditChain(self.audit_dir, enabled=enabled)

    def _read_events(self) -> list:
        """Read all events from today's audit file."""
        today = date.today().isoformat()
        filepath = os.path.join(self.audit_dir, f"kg_audit_{today}.jsonl")
        events = []
        if not os.path.exists(filepath):
            return events
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def test_append_creates_file(self) -> None:
        """Append an event and verify the file exists with valid JSON."""
        chain = self._make_chain()
        chain.append(
            action="add",
            target_type="document",
            target_id="/test/file.md",
            source="test:test",
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "add")
        self.assertEqual(events[0]["target_type"], "document")
        self.assertEqual(events[0]["target_id"], "/test/file.md")
        self.assertEqual(events[0]["source"], "test:test")
        self.assertIn("timestamp", events[0])

    def test_append_multiple_events(self) -> None:
        """Append 5 events and verify all present."""
        chain = self._make_chain()
        for i in range(5):
            chain.append(
                action="add",
                target_type="document",
                target_id=f"/test/file{i}.md",
                source="test:test",
                metadata={"index": i},
            )
        events = self._read_events()
        self.assertEqual(len(events), 5)
        for i, ev in enumerate(events):
            self.assertEqual(ev["target_id"], f"/test/file{i}.md")

    def test_query_by_action(self) -> None:
        """Append mixed events, query by action='add'."""
        chain = self._make_chain()
        chain.append(action="add", target_type="entity",
                     target_id="e1", source="test")
        chain.append(action="update", target_type="entity",
                     target_id="e2", source="test")
        chain.append(action="add", target_type="document",
                     target_id="d1", source="test")
        chain.append(action="delete", target_type="entity",
                     target_id="e3", source="test")

        adds = chain.query(action="add")
        self.assertEqual(len(adds), 2)
        self.assertTrue(all(e["action"] == "add" for e in adds))

    def test_query_by_source(self) -> None:
        """Append events from different sources, filter by source."""
        chain = self._make_chain()
        chain.append(action="add", target_type="document",
                     target_id="d1", source="ingester")
        chain.append(action="add", target_type="document",
                     target_id="d2", source="elastic")
        chain.append(action="add", target_type="document",
                     target_id="d3", source="ingester")

        results = chain.query(source="ingester")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(e["source"] == "ingester" for e in results))

    def test_query_by_since(self) -> None:
        """Append events, query only those after a specific time."""
        chain = self._make_chain()
        chain.append(action="add", target_type="document",
                     target_id="d1", source="test")
        time.sleep(0.05)
        cutoff = datetime.now(timezone.utc).isoformat()
        time.sleep(0.05)
        chain.append(action="add", target_type="document",
                     target_id="d2", source="test")
        chain.append(action="add", target_type="document",
                     target_id="d3", source="test")

        results = chain.query(since=cutoff)
        self.assertGreaterEqual(len(results), 2)
        for ev in results:
            self.assertGreaterEqual(ev["timestamp"], cutoff)

    def test_disabled_is_noop(self) -> None:
        """enabled=False: no files should be created."""
        noop_dir = f"/tmp/test_audit_noop_{os.getpid()}"
        chain = AuditChain(noop_dir, enabled=False)
        chain.append(
            action="add", target_type="document",
            target_id="x", source="test",
        )
        self.assertFalse(os.path.exists(noop_dir))
        results = chain.query()
        self.assertEqual(results, [])
        stats = chain.get_stats()
        self.assertEqual(stats["total_events"], 0)
        shutil.rmtree(noop_dir, ignore_errors=True)

    def test_stats(self) -> None:
        """Append events and verify stats counts."""
        chain = self._make_chain()
        chain.append(action="add", target_type="document",
                     target_id="d1", source="test")
        chain.append(action="add", target_type="document",
                     target_id="d2", source="test")
        chain.append(action="update", target_type="entity",
                     target_id="e1", source="test")

        stats = chain.get_stats()
        self.assertEqual(stats["total_events"], 3)
        self.assertEqual(stats["events_by_action"]["add"], 2)
        self.assertEqual(stats["events_by_action"]["update"], 1)
        self.assertEqual(stats["file_count"], 1)
        self.assertGreater(stats["total_size_bytes"], 0)

    def test_daily_rotation(self) -> None:
        """Append events to different dates, verify separate files."""
        chain = self._make_chain()

        # Write to today
        chain.append(action="add", target_type="document",
                     target_id="today.md", source="test")

        # Manually write to a different date file
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yesterday_file = os.path.join(
            self.audit_dir, f"kg_audit_{yesterday}.jsonl"
        )
        with open(yesterday_file, "a") as f:
            f.write(json.dumps({
                "timestamp": yesterday + "T00:00:00Z",
                "action": "add",
                "target_type": "document",
                "target_id": "yesterday.md",
                "source": "test",
                "metadata": {},
            }) + "\n")

        stats = chain.get_stats()
        self.assertEqual(stats["file_count"], 2)
        self.assertEqual(stats["total_events"], 2)

        # Query should find both
        all_events = chain.query(limit=10)
        self.assertEqual(len(all_events), 2)


if __name__ == "__main__":
    unittest.main()
