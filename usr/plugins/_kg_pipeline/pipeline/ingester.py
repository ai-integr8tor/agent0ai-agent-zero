"""File ingestion helper combining single and bulk ingest logic."""
import os
import json
import time
import glob
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

from .kg_client import KGClient
from .audit_chain import AuditChain

logger = logging.getLogger(__name__)


class Ingester:
    """Handles single file and bulk ingestion to KG."""
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.state_file = config.get("ingest_state_file")
        self.log_dir = config.get("log_dir", "/a0/usr/workdir/logs")
        self.max_file_size_kb = config.get("max_file_size_kb", 50)
        self.min_file_size_kb = config.get("min_file_size_kb", 2)
        audit_cfg = config.get("audit", {})
        audit_dir = os.path.join(self.log_dir, "kg_audit")
        self.audit = AuditChain(
            audit_dir=audit_cfg.get("audit_dir", audit_dir),
            enabled=audit_cfg.get("enabled", True),
        )
    
    def _log(self, msg: str) -> None:
        """Log message with timestamp."""
        ts = datetime.utcnow().isoformat()
        line = f"[{ts}] {msg}"
        logger.info(msg)
        log_file = os.path.join(self.log_dir, "kg_ingest.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as f:
            f.write(line + "\n")
    
    def _load_state(self) -> Dict:
        """Load ingestion state from file."""
        if self.state_file and os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
        return {}
    
    def _save_state(self, state: Dict) -> None:
        """Save ingestion state to file."""
        if self.state_file:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
    
    @staticmethod
    def detect_domain(filepath: str) -> str:
        """Detect domain from file path."""
        p = filepath.lower()
        if any(x in p for x in [
            "work", "sales", "territory", "deal", "pipeline", "sled"
        ]):
            return "work"
        elif any(x in p for x in [
            "personal", "life", "home", "bookmark"
        ]):
            return "personal"
        elif any(x in p for x in [
            "infra", "model", "docker", "server", "system", "framework"
        ]):
            return "technology"
        return "context"
    
    def _should_process_file(self, filepath: str, state: Dict,
                            resume: bool = False) -> bool:
        """Check if file should be processed."""
        if not filepath.endswith(".md"):
            return False
        
        size_kb = os.path.getsize(filepath) / 1024
        if size_kb > self.max_file_size_kb or size_kb < self.min_file_size_kb:
            return False
        
        # Skip archived
        if "_archived" in filepath:
            return False
        
        if resume and filepath in state:
            stored = state[filepath].get("mtime", 0)
            if stored == os.path.getmtime(filepath):
                return False
        
        return True
    
    def ingest_file(self, filepath: str, domain: Optional[str] = None
                   ) -> Dict[str, Any]:
        """Ingest a single file into KG."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            
            if len(content.strip()) < 200:
                return {"status": "skipped", "reason": "too_short"}
            
            # Apply token compression before truncation
            from .token_compressor import TokenCompressor
            if not hasattr(self, 'compressor'):
                self.compressor = TokenCompressor(self.config)
            content = self.compressor.compress(content)
            
            full_content = f"Source: {filepath}\n\n{content[:8000]}"
            domain = domain or self.detect_domain(filepath)
            
            start = time.time()
            result = self.kg.add_content(full_content, filepath, domain)
            elapsed = time.time() - start
            self.audit.append(
                action="add",
                target_type="document",
                target_id=filepath,
                source="ingester.ingest_file",
                metadata={
                    "entities": result.get("entities", 0),
                    "domain": domain,
                    "elapsed": round(elapsed, 1),
                },
            )
            return {
                "status": "done",
                "entities": result.get("entities", 0),
                "relationships": result.get("relationships", 0),
                "domain": result.get("domain", domain),
                "elapsed": round(elapsed, 1)
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    
    def ingest_directory(self, knowledge_dir: str, limit: Optional[int] = None,
                         resume: bool = False, force_reingest: bool = False
                         ) -> Dict[str, Any]:
        """Ingest all files from a directory."""
        state = {} if force_reingest else self._load_state()
        
        files = []
        for root, dirs, filenames in os.walk(knowledge_dir):
            dirs[:] = [d for d in dirs if d != "_archived"]
            for fn in filenames:
                fp = os.path.join(root, fn)
                if self._should_process_file(fp, state, resume):
                    files.append((fp, os.path.getsize(fp) / 1024))
        
        files.sort(key=lambda x: x[1])
        if limit:
            files = files[:limit]
        
        self._log(f"Found {len(files)} files to process")
        
        total_ents = 0
        total_rels = 0
        done_count = 0
        fail_count = 0
        
        for i, (fp, size_kb) in enumerate(files):
            self._log(f"[{i+1}/{len(files)}] Processing: {fp}")
            result = self.ingest_file(fp)
            state[fp] = {
                "status": result["status"],
                **result,
                "mtime": os.path.getmtime(fp),
                "timestamp": datetime.utcnow().isoformat()
            }
            self._save_state(state)
            
            if result["status"] == "done":
                total_ents += result.get("entities", 0)
                total_rels += result.get("relationships", 0)
                done_count += 1
                self.audit.append(
                    action="add",
                    target_type="document",
                    target_id=fp,
                    source="ingester.ingest_directory",
                    metadata={
                        "entities": result.get("entities", 0),
                        "domain": result.get("domain", ""),
                    },
                )
            elif result["status"] == "failed":
                fail_count += 1
        
        # Run janitor
        if done_count > 0:
            try:
                self.kg.janitor(passes=["normalize", "orphans"])
                self.audit.append(
                    action="janitor",
                    target_type="entity",
                    target_id="all",
                    source="ingester.ingest_directory",
                    metadata={"passes": ["normalize", "orphans"]},
                )
            except Exception as e:
                logger.warning(f"Janitor failed: {e}")
        
        return {
            "files_processed": done_count,
            "files_failed": fail_count,
            "entities_added": total_ents,
            "relationships_added": total_rels
        }
    
    def bulk_ingest(self, file_list: List[str], kg_paths: set = None,
                   dry_run: bool = False) -> Tuple[int, int, int]:
        """Bulk ingest files with deduplication."""
        kg_paths = kg_paths or set()
        pushed, failed, skipped = 0, 0, 0
        
        kg_basenames = {p.split("/")[-1].replace(".md", "") for p in kg_paths}
        
        for i, filepath in enumerate(file_list, 1):
            rel_path = filepath.lstrip("/")
            basename = os.path.basename(filepath).replace(".md", "")
            
            if rel_path in kg_paths or basename in kg_basenames:
                skipped += 1
                continue
            
            try:
                with open(filepath) as f:
                    content = f.read()
                
                if len(content.strip()) < 100:
                    skipped += 1
                    continue
                
                # Apply token compression before truncation
                from .token_compressor import TokenCompressor
                if not hasattr(self, 'compressor'):
                    self.compressor = TokenCompressor(self.config)
                content = self.compressor.compress(content)
                
                # Truncate large files
                if len(content) > 30000:
                    content = content[:30000] + "\n\n[...truncated...]"
                
                domain = self.detect_domain(filepath)
                
                if dry_run:
                    pushed += 1
                    continue
                
                result = self.kg.add_content(content, rel_path, domain)
                
                if "error" in result:
                    failed += 1
                else:
                    pushed += 1
                    self.audit.append(
                        action="add",
                        target_type="document",
                        target_id=filepath,
                        source="ingester.bulk_ingest",
                        metadata={"domain": domain},
                    )
            except Exception as e:
                failed += 1
                logger.error(f"Failed to process {filepath}: {e}")
            
            time.sleep(0.3)
        
        return pushed, failed, skipped
