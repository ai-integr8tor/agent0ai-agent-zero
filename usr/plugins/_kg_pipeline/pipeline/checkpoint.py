"""Crash recovery checkpoints for KG pipeline workers.

Provides atomic save/load/clear operations for worker state,
enabling resume-after-crash for parallel ingestion chunks.
"""
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_DIR = "/a0/usr/workdir/state/kg_checkpoints"
CHECKPOINT_PATTERN = "worker_{worker_id}_chunk_{chunk_index}.json"
STALE_TTL_HOURS = 24


def _checkpoint_path(worker_id: int, chunk_index: int) -> str:
    """Return absolute path for a worker checkpoint file."""
    filename = CHECKPOINT_PATTERN.format(
        worker_id=worker_id, chunk_index=chunk_index
    )
    return os.path.join(STATE_DIR, filename)


def _ensure_state_dir() -> None:
    """Create state directory if it does not exist."""
    os.makedirs(STATE_DIR, exist_ok=True)


def save_checkpoint(
    worker_id: int,
    chunk_index: int,
    processed: List[str],
    total: int,
    failed: List[dict],
    stats: Dict,
) -> Dict:
    """Atomically save a checkpoint for a worker chunk.

    Writes to a temp file first, then uses os.replace() for
    POSIX-atomic rename. Returns the saved checkpoint dict.

    Args:
        worker_id: Worker identifier (0-based).
        chunk_index: Chunk index being processed.
        processed: List of basenames successfully pushed.
        total: Total files in this chunk.
        failed: List of {file, error} dicts.
        stats: Dict with pushed/failed/skipped counts.

    Returns:
        The full checkpoint dictionary that was persisted.
    """
    _ensure_state_dir()
    now = datetime.now(timezone.utc).isoformat()
    checkpoint = {
        "worker_id": worker_id,
        "chunk_index": chunk_index,
        "processed_files": processed,
        "processed_count": len(processed),
        "total_files": total,
        "failed_files": failed,
        "stats": stats,
        "last_checkpoint": now,
    }
    target = _checkpoint_path(worker_id, chunk_index)
    tmp_path = target + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(checkpoint, fh, indent=2)
        os.replace(tmp_path, target)
    except OSError as exc:
        logger.error("Checkpoint write failed W%d C%d: %s",
                     worker_id, chunk_index, exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return checkpoint


def load_checkpoint(worker_id: int, chunk_index: int) -> Optional[Dict]:
    """Load a checkpoint for a worker chunk.

    Returns None if no checkpoint exists or the file is corrupt.

    Args:
        worker_id: Worker identifier.
        chunk_index: Chunk index.

    Returns:
        Checkpoint dict, or None if not found / invalid.
    """
    target = _checkpoint_path(worker_id, chunk_index)
    if not os.path.exists(target):
        return None
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Corrupt checkpoint W%d C%d, ignoring: %s",
            worker_id, chunk_index, exc,
        )
        return None


def clear_checkpoint(worker_id: int, chunk_index: int) -> None:
    """Remove a checkpoint file after successful completion.

    Silently succeeds if the file does not exist.

    Args:
        worker_id: Worker identifier.
        chunk_index: Chunk index.
    """
    target = _checkpoint_path(worker_id, chunk_index)
    try:
        if os.path.exists(target):
            os.remove(target)
            logger.info("Checkpoint cleared W%d C%d",
                        worker_id, chunk_index)
    except OSError as exc:
        logger.warning("Could not clear checkpoint W%d C%d: %s",
                       worker_id, chunk_index, exc)


def list_stale_checkpoints(
    ttl_hours: int = STALE_TTL_HOURS,
) -> List[Dict]:
    """Return checkpoints older than the given TTL.

    Scans state directory, loads each checkpoint, and returns
    those whose last_checkpoint timestamp exceeds ttl_hours.

    Args:
        ttl_hours: Age threshold in hours (default 24).

    Returns:
        List of checkpoint dicts that are stale.
    """
    _ensure_state_dir()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    stale: List[Dict] = []

    for fname in os.listdir(STATE_DIR):
        if not fname.startswith("worker_") or not fname.endswith(".json"):
            continue
        fpath = os.path.join(STATE_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ts_str = data.get("last_checkpoint", "")
            if not ts_str:
                stale.append(data)
                continue
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                stale.append(data)
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning("Skipping unreadable checkpoint: %s", fname)

    return stale
