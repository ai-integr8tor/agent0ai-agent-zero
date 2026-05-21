"""Parallel chunk worker for distributed ingestion."""
import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from .kg_client import KGClient
from .ingester import Ingester
from .audit_chain import AuditChain
from . import checkpoint

logger = logging.getLogger(__name__)


class ParallelWorker:
    """Processes a chunk of files through parallel workers."""
    
    DOMAIN_MAP = {
        "blog": "context",
        "security-labs": "technology",
        "observability-labs": "technology",
        "customers": "work",
        "products": "technology",
        "industries": "work",
        "partners": "work",
        "competitive": "work",
        "what-is-glossary": "context",
        "ai-emerging": "technology",
        "training": "context",
        "pricing-licensing": "context",
    }
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.chunk_dir = config.get("chunk_dir", "/a0/usr/workdir/config")
        self.log_dir = config.get("log_dir", "/a0/usr/workdir/logs")
        self.timeout = config.get("timeout", 300)
        self.max_chars = config.get("max_chars", 30000)
        audit_cfg = config.get("audit", {})
        audit_dir = os.path.join(self.log_dir, "kg_audit")
        self.audit = AuditChain(
            audit_dir=audit_cfg.get("audit_dir", audit_dir),
            enabled=audit_cfg.get("enabled", True),
        )
    
    def _log(self, worker_id: int, msg: str) -> None:
        """Log message with worker ID."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [W{worker_id}] {msg}"
        logger.info(line)
        log_file = os.path.join(self.log_dir, f"kg_worker_{worker_id}.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as f:
            f.write(line + "\n")
    
    def get_processed_files(self) -> set:
        """Get already processed files from KG."""
        processed = set()
        try:
            data = self.kg.export_data()
            for doc in data.get("documents", []):
                sp = doc.get("source_path", "")
                if sp:
                    processed.add(os.path.basename(sp))
        except Exception as e:
            logger.warning(f"Could not fetch processed files: {e}")
        return processed
    
    def get_domain(self, filepath: str) -> str:
        """Map file directory to KG domain."""
        parts = filepath.split("/")
        for part in parts:
            if part in self.DOMAIN_MAP:
                return self.DOMAIN_MAP[part]
        return "context"
    
    def load_chunk(self, chunk_index: int) -> List[str]:
        """Load file list from chunk file."""
        chunk_file = os.path.join(
            self.chunk_dir, f"kg_chunk_{chunk_index}.txt"
        )
        if not os.path.exists(chunk_file):
            raise FileNotFoundError(
                f"Chunk file not found: {chunk_file}"
            )
        with open(chunk_file, "r") as f:
            return [line.strip() for line in f if line.strip()]
    
    def process_chunk(
        self, chunk_index: int, worker_id: int
    ) -> Dict[str, Any]:
        """Process a single chunk with crash recovery."""
        self._log(worker_id, f"Starting chunk {chunk_index}")
        resumed = False

        # Load existing checkpoint for resume
        cp = checkpoint.load_checkpoint(worker_id, chunk_index)
        checkpoint_processed: set = set()
        cp_failed: List[dict] = []
        cp_stats: Dict = {"pushed": 0, "failed": 0, "skipped": 0}

        if cp is not None:
            resumed = True
            checkpoint_processed = set(cp.get("processed_files", []))
            cp_failed = list(cp.get("failed_files", []))
            cp_stats = dict(cp.get("stats", cp_stats))
            self._log(
                worker_id,
                f"RESUMING from checkpoint: "
                f"{len(checkpoint_processed)} already done",
            )

        files = self.load_chunk(chunk_index)
        self._log(
            worker_id,
            f"Loaded {len(files)} files from chunk {chunk_index}",
        )

        processed = self.get_processed_files()
        self._log(
            worker_id,
            f"Found {len(processed)} already-processed in KG",
        )

        to_process = [
            f for f in files
            if os.path.basename(f) not in processed
            and os.path.basename(f) not in checkpoint_processed
            and os.path.exists(f) and os.path.getsize(f) > 100
        ]
        self._log(
            worker_id,
            f"After dedup: {len(to_process)} files to process",
        )

        if not to_process and not cp_failed:
            checkpoint.clear_checkpoint(worker_id, chunk_index)
            return {
                "status": "no_files", "processed": 0, "resumed": resumed,
            }

        pushed = cp_stats.get("pushed", 0)
        failed = cp_stats.get("failed", 0)
        skipped = cp_stats.get("skipped", 0)
        local_processed: List[str] = list(checkpoint_processed)
        failed_list: List[dict] = list(cp_failed)
        start_time = time.time()

        for i, fpath in enumerate(to_process, 1):
            try:
                with open(fpath, "r", encoding="utf-8",
                         errors="ignore") as f:
                    content = f.read()

                if len(content.strip()) < 100:
                    skipped += 1
                    continue

                # Apply token compression before truncation
                from .token_compressor import TokenCompressor
                if not hasattr(self, 'compressor'):
                    self.compressor = TokenCompressor(self.config)
                content = self.compressor.compress(content)

                if len(content) > self.max_chars:
                    content = content[:self.max_chars]
                    content += "\n\n[...truncated...]"

                rel_path = os.path.relpath(
                    fpath, "/a0/usr/workdir/"
                )
                domain = self.get_domain(rel_path)

                result = self.kg.add_content(
                    content, f"workdir/{rel_path}", domain
                )

                if "error" in result:
                    failed += 1
                    failed_list.append({
                        "file": os.path.basename(fpath),
                        "error": str(result["error"])[:100],
                    })
                else:
                    pushed += 1
                    local_processed.append(os.path.basename(fpath))
                    self.audit.append(
                        action="add",
                        target_type="document",
                        target_id=fpath,
                        source=f"parallel_worker:{worker_id}",
                        metadata={
                            "domain": domain,
                            "chunk": chunk_index,
                        },
                    )

                if i % 10 == 0:
                    stats = {
                        "pushed": pushed, "failed": failed,
                        "skipped": skipped,
                    }
                    checkpoint.save_checkpoint(
                        worker_id, chunk_index,
                        local_processed, len(files),
                        failed_list, stats,
                    )

                if i % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = pushed / (elapsed / 3600) if elapsed > 0 else 0
                    self._log(
                        worker_id,
                        f"[{i}/{len(to_process)}] "
                        f"pushed={pushed} failed={failed} "
                        f"skipped={skipped} | {rate:.1f}/h",
                    )

            except Exception as e:
                failed += 1
                failed_list.append({
                    "file": os.path.basename(fpath),
                    "error": str(e)[:100],
                })
                if failed <= 10:
                    self._log(
                        worker_id,
                        f"ERROR: {os.path.basename(fpath)} "
                        f"- {str(e)[:60]}",
                    )

            time.sleep(0.1)

        elapsed = time.time() - start_time
        self._log(
            worker_id,
            f"COMPLETE: {pushed} pushed, {failed} failed, "
            f"{skipped} skipped in {elapsed:.0f}s",
        )

        # Clear checkpoint only on clean completion
        if failed == 0:
            checkpoint.clear_checkpoint(worker_id, chunk_index)

        return {
            "status": "done",
            "processed": len(to_process),
            "pushed": pushed,
            "failed": failed,
            "skipped": skipped,
            "elapsed_seconds": round(elapsed, 1),
            "resumed": resumed,
        }
