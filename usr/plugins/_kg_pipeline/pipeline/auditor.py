"""Retrieval audit helper for KG quality measurement."""
import os
import json
import random
import logging
from datetime import datetime, timedelta
from collections import Counter
from typing import Dict, List, Optional, Any

from .kg_client import KGClient

logger = logging.getLogger(__name__)


class KGAuditor:
    """Audit the Knowledge Graph for quality metrics."""
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.report = {
            "timestamp": datetime.now().isoformat(),
            "health": {},
            "entity_stats": {},
            "retrieval_precision": {},
            "staleness": {},
            "gaps": {},
            "recommendations": []
        }
    
    def check_health(self) -> bool:
        """Check KG service health."""
        try:
            health = self.kg.health_check()
            self.report["health"] = {
                "status": health.get("status"),
                "version": health.get("version"),
                "vectors": health.get("vectors_count"),
            }
            return True
        except Exception as e:
            self.report["health"]["error"] = str(e)
            return False
    
    def analyze_entities(self, sample_size: int = 500) -> None:
        """Analyze entity coverage and tag quality."""
        try:
            result = self.kg.get_entities(limit=1)
            total = result.get("total", 0)
            
            # Sample entities
            entities = []
            if total > 0:
                sample_offsets = [random.randint(0, max(0, total - sample_size)) 
                                 for _ in range(min(10, total // 50))]
                for offset in sample_offsets:
                    batch = self.kg.get_entities(offset=offset, limit=50)
                    entities.extend(batch.get("entities", []))
            
            # Analyze
            no_tags = single_tag = multi_tag = rich_tag = 0
            cat_counter = Counter()
            domain_counter = Counter()
            
            now = datetime.now()
            stale_count = 0
            stale_threshold = timedelta(days=30)
            
            for e in entities:
                cats = (e.get("categories", "") or "").strip()
                cat_list = [c.strip() for c in cats.split(",") if c.strip()]
                
                if len(cat_list) == 0:
                    no_tags += 1
                elif len(cat_list) == 1:
                    single_tag += 1
                elif len(cat_list) == 2:
                    multi_tag += 1
                else:
                    rich_tag += 1
                
                for c in cat_list:
                    cat_counter[c] += 1
                domain_counter[e.get("domain", "unknown")] += 1
                
                # Staleness
                last_seen = e.get("last_seen")
                if last_seen:
                    try:
                        ls = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                        if now - ls.replace(tzinfo=None) > stale_threshold:
                            stale_count += 1
                    except:
                        pass
            
            self.report["entity_stats"] = {
                "total": total,
                "sampled": len(entities),
                "tag_coverage": {
                    "no_tags": no_tags,
                    "no_tags_pct": round(no_tags / len(entities) * 100, 1) if entities else 0,
                    "single_tag": single_tag,
                    "single_tag_pct": round(single_tag / len(entities) * 100, 1) if entities else 0,
                    "multi_tag": multi_tag,
                    "multi_tag_pct": round(multi_tag / len(entities) * 100, 1) if entities else 0,
                    "rich_tag_3plus": rich_tag,
                    "rich_tag_pct": round(rich_tag / len(entities) * 100, 1) if entities else 0,
                },
                "top_categories": cat_counter.most_common(20),
                "domain_distribution": dict(domain_counter),
                "stale_entities": stale_count,
                "stale_pct": round(stale_count / len(entities) * 100, 1) if entities else 0
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze entities: {e}")
    
    def test_retrieval_precision(self, sample: bool = True) -> None:
        """Test retrieval precision@10 with domain-specific queries."""
        test_queries = [
            {"query": "docker container orchestration", "expected": ["technology", "devops", "docker"]},
            {"query": "large language model inference", "expected": ["technology", "ai-ml", "llm"]},
            {"query": "vector database search engine", "expected": ["technology", "database"]},
            {"query": "sales territory pipeline", "expected": ["work", "sales", "territory"]},
            {"query": "state government education SLED", "expected": ["work", "sled", "government"]},
            {"query": "self-hosting home lab", "expected": ["personal", "home-lab"]},
            {"query": "bookmark web tutorial", "expected": ["personal", "bookmark"]},
            {"query": "open source AI tools", "expected": ["technology", "ai-ml", "open-source"]},
            {"query": "security authentication encryption", "expected": ["technology", "security"]},
            {"query": "monitoring observability logging", "expected": ["technology", "monitoring", "devops"]},
        ]
        
        if not sample:
            # Full test with more queries
            test_queries.extend([
                {"query": "python programming framework", "expected": ["technology", "programming"]},
                {"query": "cloud AWS serverless", "expected": ["technology", "cloud", "aws"]},
            ])
        
        precision_scores = []
        query_results = []
        
        for tq in test_queries:
            try:
                result = self.kg.search(tq["query"], limit=10)
                entities = result.get("entities", [])
                
                relevant = sum(1 for e in entities 
                               if any(exp in str(e.get("domain", "")).lower() 
                                      or str(e.get("categories", "")).lower()
                                      for exp in tq["expected"]))
                
                precision = relevant / max(len(entities), 1)
                precision_scores.append(precision)
                
                query_results.append({
                    "query": tq["query"],
                    "precision": round(precision, 3),
                    "relevant": relevant,
                    "total": len(entities)
                })
                
            except Exception as e:
                query_results.append({"query": tq["query"], "error": str(e)})
        
        avg_p = sum(precision_scores) / len(precision_scores) if precision_scores else 0
        self.report["retrieval_precision"] = {
            "avg_precision_at_10": round(avg_p, 3),
            "queries_tested": len(query_results),
            "per_query": query_results
        }
    
    def check_gaps(self) -> None:
        """Detect gaps: orphan entities, missing relationships."""
        try:
            orphans = self.kg.get_orphans(limit=100)
            
            # Sample entities for low-confidence check
            sample = self.kg.get_entities(limit=100)
            entities = sample.get("entities", [])
            
            low_confidence = [e for e in entities if e.get("confidence", 1.0) < 0.5]
            no_domain = [e for e in entities if not e.get("domain")]
            
            self.report["gaps"] = {
                "orphan_count": len(orphans),
                "low_confidence": len(low_confidence),
                "no_domain": len(no_domain)
            }
            
        except Exception as e:
            logger.error(f"Failed to check gaps: {e}")
    
    def generate_recommendations(self) -> None:
        """Generate recommendations based on audit results."""
        recs = []
        
        # Retrieval-based
        avg_p10 = self.report.get("retrieval_precision", {}).get("avg_precision_at_10", 0)
        if avg_p10 < 0.3:
            recs.append({"priority": "HIGH", "area": "Retrieval",
                        "finding": f"Low precision@10 ({avg_p10:.3f})",
                        "action": "Consider pruning stale entities"})
        elif avg_p10 < 0.6:
            recs.append({"priority": "MEDIUM", "area": "Retrieval",
                        "finding": f"Moderate precision@10 ({avg_p10:.3f})",
                        "action": "Review tag quality"})
        
        # Staleness
        stale_pct = self.report.get("entity_stats", {}).get("stale_pct", 0)
        if stale_pct > 20:
            recs.append({"priority": "HIGH", "area": "Staleness",
                        "finding": f"{stale_pct}% entities are stale",
                        "action": "Archive or re-tag stale entities"})
        
        self.report["recommendations"] = recs
    
    def run_audit(self, sample: bool = True) -> Dict[str, Any]:
        """Run full audit."""
        if not self.check_health():
            return {"status": "error", "message": "KG service not healthy"}
        
        self.analyze_entities(sample_size=200 if sample else 500)
        self.test_retrieval_precision(sample=sample)
        self.check_gaps()
        self.generate_recommendations()
        
        return self.report
    
    def save_report(self, path: Optional[str] = None) -> str:
        """Save audit report to file."""
        if path is None:
            log_dir = self.config.get("log_dir", "/a0/usr/workdir/logs")
            audit_dir = os.path.join(log_dir, "kg_audit")
            os.makedirs(audit_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(audit_dir, f"kg_audit_{ts}.json")
        
        with open(path, "w") as f:
            json.dump(self.report, f, indent=2, default=str)
        
        return path
