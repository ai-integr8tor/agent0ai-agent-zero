"""Elastic KB ingestion helper."""
import os
import time
import glob
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

from .kg_client import KGClient
from .ingester import Ingester
from .audit_chain import AuditChain

logger = logging.getLogger(__name__)


class ElasticIngester:
    """Ingests Elastic KB files into KG with domain mapping."""
    
    DOMAIN_MAP = {
        "products": "technology",
        "pricing-licensing": "work",
        "competitive": "work",
        "customers": "work",
        "blog": "context",
        "security-labs": "technology",
        "observability-labs": "technology",
        "industries": "work",
        "partners": "work",
        "ai-emerging": "technology",
        "training": "context",
        "what-is-glossary": "context",
    }
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.elastic_kb_dir = config.get("elastic_kb_dir", "/a0/usr/workdir/elastic_kb")
        self.log_dir = config.get("log_dir", "/a0/usr/workdir/logs")
        audit_cfg = config.get("audit", {})
        audit_dir = os.path.join(self.log_dir, "kg_audit")
        self.audit = AuditChain(
            audit_dir=audit_cfg.get("audit_dir", audit_dir),
            enabled=audit_cfg.get("enabled", True),
        )
    
    def _log(self, msg: str, level: str = "INFO") -> None:
        """Log message with timestamp."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        logger.info(msg)
        log_file = os.path.join(self.log_dir, "kg_elastic_ingest.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as f:
            f.write(line + "\n")
    
    def determine_domain(self, filepath: str) -> str:
        """Determine domain from file path using category mapping."""
        rel = os.path.relpath(filepath, self.elastic_kb_dir)
        category = rel.split("/")[0] if "/" in rel else rel
        return self.DOMAIN_MAP.get(category, "context")
    
    def collect_files(self, category: Optional[str] = None) -> List[str]:
        """Collect all .md files from Elastic KB directory."""
        files = []
        pattern = os.path.join(self.elastic_kb_dir, "**", "*.md")
        for filepath in sorted(glob.glob(pattern, recursive=True)):
            if category:
                rel = os.path.relpath(filepath, self.elastic_kb_dir)
                if not rel.startswith(category):
                    continue
            files.append(filepath)
        return files
    
    def ingest_files(self, file_list: List[str], kg_paths: set = None,
                    dry_run: bool = False) -> Tuple[int, int, int]:
        """Ingest Elastic KB files with deduplication."""
        kg_paths = kg_paths or set()
        pushed, failed, skipped = 0, 0, 0
        
        kg_basenames = {p.split("/")[-1].replace(".md", "") for p in kg_paths}
        start_time = time.time()
        
        for i, filepath in enumerate(file_list, 1):
            rel_path = os.path.relpath(filepath, self.elastic_kb_dir)
            basename = os.path.basename(filepath).replace(".md", "")
            
            if rel_path in kg_paths or basename in kg_basenames:
                skipped += 1
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8") as f:
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
                    content = content[:30000] + "\n\n[... Content truncated ...]"
                
                domain = self.determine_domain(filepath)
                
                if dry_run:
                    pushed += 1
                    if i % 100 == 0:
                        self._log(f"[{i}/{len(file_list)}] WOULD process {filepath}")
                    continue
                
                source = f"elastic_kb/{rel_path}"
                result = self.kg.add_content(content, source, domain)
                
                if "error" in result:
                    failed += 1
                    if i % 100 == 0:
                        self._log(f"[{i}/{len(file_list)}] FAILED: {filepath}")
                else:
                    pushed += 1
                    self.audit.append(
                        action="add",
                        target_type="document",
                        target_id=filepath,
                        source="elastic_ingester.ingest_files",
                        metadata={
                            "domain": domain,
                            "elastic_source": source,
                        },
                    )
                
                if i % 100 == 0 or i == len(file_list):
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    self._log(f"[{i}/{len(file_list)}] pushed={pushed} failed={failed} "
                             f"skipped={skipped} | {rate:.1f}/s")
                
            except Exception as e:
                failed += 1
                if failed <= 10:
                    self._log(f"[{i}/{len(file_list)}] ERROR: {filepath} - {e}", "ERROR")
            
            time.sleep(0.2)
        
        return pushed, failed, skipped
