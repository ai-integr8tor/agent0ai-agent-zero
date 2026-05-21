"""Unit tests for checkpoint crash recovery module."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Add pipeline dir to path for direct test execution
_pipeline_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pipeline",
)
if _pipeline_dir not in sys.path:
    sys.path.insert(0, _pipeline_dir)

import checkpoint


class TestCheckpoint(unittest.TestCase):
    """Test suite for checkpoint save/load/clear/stale ops."""

    def setUp(self) -> None:
        """Create temp dir and patch STATE_DIR."""
        self.tmpdir = tempfile.mkdtemp()
        self.patcher = patch.object(
            checkpoint, "STATE_DIR", self.tmpdir
        )
        self.patcher.start()

    def tearDown(self) -> None:
        """Remove temp dir and stop patch."""
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self) -> None:
        """Round-trip: save a checkpoint then load it back."""
        processed = ["file1.md", "file2.md"]
        failed = [{"file": "bad.md", "error": "timeout"}]
        stats = {"pushed": 2, "failed": 1, "skipped": 0}

        result = checkpoint.save_checkpoint(
            worker_id=1, chunk_index=5, processed=processed,
            total=10, failed=failed, stats=stats,
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["worker_id"], 1)
        self.assertEqual(result["chunk_index"], 5)
        self.assertIn("last_checkpoint", result)

        loaded = checkpoint.load_checkpoint(1, 5)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["processed_files"], processed)
        self.assertEqual(loaded["stats"], stats)
        self.assertEqual(loaded["failed_files"], failed)

    def test_atomic_write(self) -> None:
        """Simulate crash: partial write leaves no valid file."""
        # Write a corrupt file directly to the checkpoint path
        cp_path = os.path.join(
            self.tmpdir, "worker_2_chunk_3.json"
        )
        with open(cp_path, "w") as f:
            f.write('{"broken json')

        loaded = checkpoint.load_checkpoint(2, 3)
        self.assertIsNone(loaded)

        # Verify save still works after corrupt file
        checkpoint.save_checkpoint(
            2, 3, ["a.md"], 5, [],
            {"pushed": 1, "failed": 0, "skipped": 0},
        )
        loaded = checkpoint.load_checkpoint(2, 3)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["processed_files"], ["a.md"])

    def test_clear_removes_file(self) -> None:
        """Verify clear_checkpoint deletes the file."""
        checkpoint.save_checkpoint(
            0, 0, ["x.md"], 1, [],
            {"pushed": 1, "failed": 0, "skipped": 0},
        )
        loaded = checkpoint.load_checkpoint(0, 0)
        self.assertIsNotNone(loaded)

        checkpoint.clear_checkpoint(0, 0)
        loaded = checkpoint.load_checkpoint(0, 0)
        self.assertIsNone(loaded)

        # Clearing non-existent should not raise
        checkpoint.clear_checkpoint(99, 99)

    def test_stale_detection(self) -> None:
        """Old checkpoint is detected as stale."""
        old_ts = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()
        cp_data = {
            "worker_id": 5,
            "chunk_index": 1,
            "processed_files": ["old.md"],
            "processed_count": 1,
            "total_files": 10,
            "failed_files": [],
            "stats": {"pushed": 1, "failed": 0, "skipped": 0},
            "last_checkpoint": old_ts,
        }
        cp_path = os.path.join(
            self.tmpdir, "worker_5_chunk_1.json"
        )
        with open(cp_path, "w") as f:
            json.dump(cp_data, f)

        stale = checkpoint.list_stale_checkpoints(ttl_hours=24)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["worker_id"], 5)

    def test_concurrent_workers(self) -> None:
        """Two workers with different IDs do not interfere."""
        checkpoint.save_checkpoint(
            1, 0, ["w1_a.md", "w1_b.md"], 10,
            [], {"pushed": 2, "failed": 0, "skipped": 0},
        )
        checkpoint.save_checkpoint(
            2, 0, ["w2_x.md"], 20,
            [{"file": "bad.md", "error": "err"}],
            {"pushed": 1, "failed": 1, "skipped": 0},
        )

        cp1 = checkpoint.load_checkpoint(1, 0)
        cp2 = checkpoint.load_checkpoint(2, 0)

        self.assertIsNotNone(cp1)
        self.assertIsNotNone(cp2)
        self.assertEqual(cp1["processed_files"], ["w1_a.md", "w1_b.md"])
        self.assertEqual(cp2["processed_files"], ["w2_x.md"])
        self.assertEqual(cp1["total_files"], 10)
        self.assertEqual(cp2["total_files"], 20)

        # Clear one does not affect the other
        checkpoint.clear_checkpoint(1, 0)
        self.assertIsNone(checkpoint.load_checkpoint(1, 0))
        self.assertIsNotNone(checkpoint.load_checkpoint(2, 0))


if __name__ == "__main__":
    unittest.main()
