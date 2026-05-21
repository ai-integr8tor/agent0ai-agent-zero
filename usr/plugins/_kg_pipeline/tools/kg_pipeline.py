"""KG Pipeline Tool - Consolidated batch operations for Knowledge Graph.

Provides tool methods for:
- status: Check KG service health and counts
- ingest: Single file or directory ingestion
- bulk_ingest: Bulk ingestion with deduplication
- elastic_ingest: Elastic KB ingestion with domain mapping
- parallel_ingest: Parallel chunk worker processing
- connect_orphans: Connect orphan entities via LLM
- enrich: Entity enrichment with domain/categories
- audit: Retrieval quality auditing
- extract: Entity extraction from files
"""
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any

# Add plugin root to path for helper imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from helpers.tool import Tool, Response
from pipeline import (
    KGClient,
    Ingester,
    ElasticIngester,
    ParallelWorker,
    OrphanConnector,
    KGExtractor,
    EntityEnricher,
    KGAuditor,
    HealthScorer,
    EntityResolver,
)
from pipeline.gdrive import KGDriveUploader
import importlib.util

logger = logging.getLogger(__name__)


def _load_config() -> Dict[str, Any]:
    """Load config from plugin default_config.yaml."""
    config_path = Path(__file__).parent.parent / "default_config.yaml"
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {
            "kg_service_url": "http://100.78.79.41:8010",
            "batch_size": 50,
            "timeout": 300,
            "log_dir": "/a0/usr/workdir/logs",
        }


def _get_client() -> KGClient:
    """Create a KG HTTP client from config."""
    cfg = _load_config()
    return KGClient(
        base_url=cfg.get("kg_service_url", "http://100.78.79.41:8010"),
        timeout=cfg.get("timeout", 300),
        max_retries=cfg.get("max_retries", 3),
        retry_delay=cfg.get("retry_delay", 1.0),
    )


class KgPipeline(Tool):
    """KG Pipeline batch operations tool for Agent Zero."""

    async def execute(self, **kwargs) -> Response:
        """Route to sub-method based on self.method."""
        method = self.method or kwargs.get("method", "status")
        cfg = _load_config()

        try:
            if method == "status":
                result = self._status()
            elif method == "ingest":
                result = self._ingest(cfg, **kwargs)
            elif method == "bulk_ingest":
                result = self._bulk_ingest(cfg, **kwargs)
            elif method == "elastic_ingest":
                result = self._elastic_ingest(cfg, **kwargs)
            elif method == "parallel_ingest":
                result = self._parallel_ingest(cfg, **kwargs)
            elif method == "connect_orphans":
                result = self._connect_orphans(cfg, **kwargs)
            elif method == "enrich":
                result = self._enrich(cfg, **kwargs)
            elif method == "audit":
                result = self._audit(cfg, **kwargs)
            elif method == "extract":
                result = self._extract(cfg, **kwargs)
            elif method == "retry_failed":
                result = self._retry_failed(cfg, **kwargs)
            elif method == "knowledge_ingest":
                return Response(message=json.dumps(self._knowledge_ingest(cfg, **kwargs)), break_loop=False)
            elif method == "gdrive_upload":
                result = self._gdrive_upload(cfg, **kwargs)
            elif method == "health":
                result = self._health(cfg, **kwargs)
            elif method == "resolve_entities":
                result = self._resolve_entities(cfg, **kwargs)
            else:
                result = {"status": "error", "message": f"Unknown method: {method}"}
        except Exception as e:
            logger.error(f"Method {method} failed: {e}")
            result = {"status": "error", "message": str(e)}

        msg = json.dumps(result, indent=2) if isinstance(result, dict) else str(result)
        return Response(message=msg, break_loop=False)

    def _status(self) -> Dict[str, Any]:
        """Check KG service health and document counts."""
        client = _get_client()
        health = client.health_check()
        kg_status = client.get_status()
        return {
            "status": "ok",
            "service": {
                "healthy": health.get("status") == "ok",
                "version": health.get("version"),
            },
            "documents": kg_status.get("documents", 0),
            "entities": kg_status.get("entities", 0),
            "relationships": kg_status.get("relationships", 0),
        }

    def _ingest(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Ingest a file or directory into KG."""
        filepath = kwargs.get("filepath")
        directory = kwargs.get("directory")
        if not filepath and not directory:
            return {"status": "error", "message": "Provide filepath or directory"}

        client = _get_client()
        ingester = Ingester(client, cfg)
        if filepath:
            return ingester.ingest_file(filepath)
        return ingester.ingest_directory(
            directory,
            limit=kwargs.get("limit"),
            resume=kwargs.get("resume", False),
            force_reingest=kwargs.get("force_reingest", False),
        )

    def _bulk_ingest(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Bulk ingest files from a directory."""
        directory = kwargs.get("directory", "")
        pattern = kwargs.get("pattern", "**/*.md")
        dry_run = kwargs.get("dry_run", False)
        if not directory:
            return {"status": "error", "message": "directory required"}

        client = _get_client()
        ingester = Ingester(client, cfg)

        # Dedup check via export
        kg_paths = set()
        try:
            export = client.export_data()
            docs = export.get("data", {}).get("docs", [])
            kg_paths = {doc.get("path", "") for doc in docs}
        except Exception:
            pass

        import glob
        files = glob.glob(os.path.join(directory, pattern), recursive=True)
        pushed, failed, skipped = ingester.bulk_ingest(
            files, kg_paths=kg_paths, dry_run=dry_run
        )
        return {
            "status": "done",
            "files_total": len(files),
            "pushed": pushed,
            "failed": failed,
            "skipped": skipped,
        }

    def _elastic_ingest(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Ingest Elastic KB files into KG."""
        client = _get_client()
        elastic = ElasticIngester(client, cfg)
        files = elastic.collect_files(kwargs.get("category"))

        kg_paths = set()
        if not kwargs.get("skip_export_check", False):
            try:
                export = client.export_data()
                docs = export.get("data", {}).get("docs", [])
                kg_paths = {doc.get("path", "") for doc in docs}
            except Exception:
                pass

        pushed, failed, skipped = elastic.ingest_files(
            files, kg_paths=kg_paths, dry_run=kwargs.get("dry_run", False)
        )
        return {
            "status": "done",
            "files_total": len(files),
            "pushed": pushed,
            "failed": failed,
            "skipped": skipped,
        }

    def _parallel_ingest(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Process a single chunk via parallel worker."""
        chunk = kwargs.get("chunk")
        worker_id = kwargs.get("worker_id", 1)
        if chunk is None:
            return {"status": "error", "message": "chunk required"}

        client = _get_client()
        worker = ParallelWorker(client, cfg)
        return worker.process_chunk(chunk, worker_id)

    def _connect_orphans(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Connect orphan entities to hub entities."""
        if kwargs.get("reset", False):
            client = _get_client()
            connector = OrphanConnector(client, cfg)
            connector.reset()
            return {"status": "reset"}

        client = _get_client()
        connector = OrphanConnector(client, cfg)
        return connector.run(
            batch_size=kwargs.get("batch_size", 5),
            max_batches=kwargs.get("max_batches"),
            dry_run=kwargs.get("dry_run", False),
        )

    def _enrich(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Enrich entities with domain and categories."""
        client = _get_client()
        enricher = EntityEnricher(client, cfg)
        return enricher.run_enrichment(
            limit=kwargs.get("limit"),
            offset=kwargs.get("offset"),
            dry_run=kwargs.get("dry_run", False),
        )

    def _audit(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Run retrieval audit."""
        client = _get_client()
        auditor = KGAuditor(client, cfg)
        report = auditor.run_audit(sample=kwargs.get("sample", True))

        if kwargs.get("save_report", True):
            path = auditor.save_report()
            report["report_path"] = path
        return report

    def _extract(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Extract entities from a file."""
        filepath = kwargs.get("filepath", "")
        if not filepath:
            return {"status": "error", "message": "filepath required"}

        client = _get_client()
        extractor = KGExtractor(client, cfg)
        return extractor.extract_from_file(filepath)
        
    def _retry_failed(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Retry docs that failed during worker ingestion."""
        import glob as glob_mod
        log_dir = cfg.get("log_dir", "/a0/usr/workdir/logs")
        failed_files = set()
        for log_path in glob_mod.glob(os.path.join(log_dir, "kg_worker_*.log")):
            with open(log_path) as f:
                for line in f:
                    if "FAILED:" in line:
                        fname = line.split("FAILED:")[-1].strip().split(" - ")[0].strip()
                        failed_files.add(fname)
        if not failed_files:
            return {"status": "ok", "message": "No failed files found", "retried": 0}
        elastic_dir = cfg.get("elastic_kb_dir", "/a0/usr/workdir/elastic_kb")
        to_retry = []
        for fpath in glob_mod.glob(os.path.join(elastic_dir, "**/*.md"), recursive=True):
            if os.path.basename(fpath) in failed_files:
                to_retry.append(fpath)
        if not to_retry:
            return {"status": "ok", "failed_names": len(failed_files), "found": 0, "message": "Failed files not found on disk"}
        client = _get_client()
        ingester = Ingester(client, cfg)
        pushed, failed, skipped = ingester.bulk_ingest(to_retry)
        return {
            "status": "done",
            "failed_names": len(failed_files),
            "found_on_disk": len(to_retry),
            "pushed": pushed,
            "still_failed": failed,
            "skipped": skipped,
        }
    

    def _knowledge_ingest(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Knowledge file ingestion with state tracking, archiving, and janitor."""
        import os, sys
        os.chdir("/a0/usr/workdir")
        spec = importlib.util.spec_from_file_location(
            "knowledge_ingester", 
            "/a0/usr/plugins/_kg_pipeline/pipeline/knowledge_ingester.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        
        if kwargs.get("status_only"):
            # Status check mode
            import requests
            try:
                r = requests.get(f"{mod.KG_SERVICE}/status", timeout=5)
                svc = r.json()
            except Exception as e:
                svc = {"error": str(e)}
            state = mod.load_state()
            done = sum(1 for v in state.values() if v.get("status") == "done")
            failed = sum(1 for v in state.values() if v.get("status") == "failed")
            return {
                "status": "ok",
                "service": svc,
                "state": {"done": done, "failed": failed, "total": len(state)}
            }
        
        # Run ingestion
        limit = kwargs.get("limit", 100)
        resume = kwargs.get("resume", True)
        force_reingest = kwargs.get("force_reingest", False)
        
        # Monkey-patch argparse to avoid sys.argv parsing
        import argparse
        original_parse = argparse.ArgumentParser.parse_args
        argparse.ArgumentParser.parse_args = lambda self, args=None, namespace=None: argparse.Namespace(
            limit=limit, resume=resume, force_reingest=force_reingest, status=False
        )
        try:
            mod.main()
        finally:
            argparse.ArgumentParser.parse_args = original_parse
        
        # Load final state
        state = mod.load_state()
        done = sum(1 for v in state.values() if v.get("status") == "done")
        failed = sum(1 for v in state.values() if v.get("status") == "failed")
        return {
            "status": "done",
            "processed": done,
            "failed": failed,
            "total_in_state": len(state)
        }

    def _gdrive_upload(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Upload KG export to Google Drive."""
        client = _get_client()
        uploader = KGDriveUploader(client, cfg)
        return uploader.upload_export(kwargs.get("filepath", ""))

    def _health(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Get entity health scores and tier distribution."""
        client = _get_client()
        scorer = HealthScorer(client, cfg)

        action = kwargs.get("action", "score")
        if action == "distribution":
            return {
                "status": "ok",
                "distribution": scorer.get_tier_distribution(),
            }
        if action == "critical":
            entities = scorer.get_critical_entities(
                limit=kwargs.get("limit", 50)
            )
            return {"status": "ok", "critical": entities}

        # Default: score entities
        entity_type = kwargs.get("entity_type")
        limit = kwargs.get("limit", 1000)
        offset = kwargs.get("offset", 0)
        result = scorer.score_entities(
            entity_type=entity_type, limit=limit, offset=offset
        )

        min_score = kwargs.get("min_score", 0.0)
        sort = kwargs.get("sort", "desc")
        entities = result.get("entities", [])
        if min_score > 0:
            entities = [e for e in entities if e.get("total", 0) >= min_score]
        entities.sort(
            key=lambda e: e.get("total", 0),
            reverse=(sort == "desc"),
        )
        result["entities"] = entities
        result["filtered_count"] = len(entities)
        return result

    def _resolve_entities(self, cfg: Dict, **kwargs) -> Dict[str, Any]:
        """Resolve entity duplicates using string similarity + LLM verification.
        
        Args:
            entity_type: Optional filter by entity type
            stage: Pipeline stage (candidates, verify, merge, full)
            dry_run: If True, report without executing merges
        
        Returns:
            Dict with resolution results
        """
        entity_type = kwargs.get("entity_type")
        stage = kwargs.get("stage", "candidates")
        dry_run = kwargs.get("dry_run", True)
        
        client = _get_client()
        resolver = EntityResolver(client, cfg)
        return resolver.run(entity_type=entity_type, stage=stage, dry_run=dry_run)
