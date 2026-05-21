"""Entity enrichment helper for retroactive enrichment and history enrichment."""
import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests

from .kg_client import KGClient


logger = logging.getLogger(__name__)


class EntityEnricher:
    """Enriches entities with domain and categories using LLM."""
    
    LLM_TIMEOUT = 60
    
    VALID_DOMAINS = ["technology", "work", "personal", "platform"]
    KG_DOMAIN = "agent-history"
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.llm_url = config.get("llm_api_url", "http://192.168.1.245:8000/v1")
        self.llm_model = config.get("llm_model", "default")
        self.state_file = config.get("enrichment_state_file",
            "/a0/usr/workdir/logs/kg_enrichment_state.json")
        self.log_dir = config.get("log_dir", "/a0/usr/workdir/logs")
        self.session = requests.Session()
    
    def _log(self, msg: str, level: str = "INFO") -> None:
        """Log message with timestamp."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        logger.info(msg)
        log_file = os.path.join(self.log_dir, "kg_enrichment.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as f:
            f.write(line + "\n")
    
    def _load_state(self) -> Dict:
        """Load enrichment state."""
        if self.state_file and os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
        return {
            "phase": None,
            "offset": 0,
            "total_processed": 0,
            "total_updated": 0,
            "total_skipped": 0,
            "total_errors": 0
        }
    
    def _save_state(self, state: Dict) -> None:
        """Save enrichment state."""
        if self.state_file:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
    
    def _infer_categories(self, name: str, etype: str, current_domain: str,
                          current_cats: str) -> Dict[str, str]:
        """Use LLM to infer domain and categories."""
        prompt = f"""Assign the BEST domain and categories to this entity.

Entity: "{name}"
Type: {etype}
Current domain: {current_domain}
Current categories: {current_cats or "(none)"}

Available domains: technology, work, personal, platform

RULES:
- Assign exactly ONE domain
- Assign 3-6 specific categories
- Normalize: lowercase, hyphens not underscores
- Prefer specific over generic categories

Return ONLY JSON:
{{"domain": "technology", "categories": "ai-ml,llm,inference"}}"""
        
        try:
            response = self.session.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200
                },
                timeout=self.LLM_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Strip markdown fences
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                content = "\n".join(lines).strip()
            
            parsed = json.loads(content)
            return {
                "domain": parsed.get("domain", current_domain),
                "categories": parsed.get("categories", current_cats)
            }
            
        except Exception as e:
            logger.error(f"LLM enrichment failed: {e}")
            return {"domain": current_domain, "categories": current_cats}
    
    def enrich_entity(self, entity_id: str, name: str, etype: str,
                      current_domain: str, current_cats: str,
                      dry_run: bool = False) -> bool:
        """Enrich a single entity."""
        result = self._infer_categories(name, etype, current_domain, current_cats)
        new_domain = result["domain"]
        new_cats = result["categories"]
        
        # Validate domain
        if new_domain not in self.VALID_DOMAINS:
            new_domain = current_domain
        
        if dry_run:
            self._log(f"[DRY-RUN] {name}: {current_domain}/{current_cats} -> {new_domain}/{new_cats}")
            return True
        
        try:
            self.kg.update_entity(entity_id, {
                "domain": new_domain,
                "categories": new_cats
            })
            self._log(f"Updated '{name}': {new_domain}/{new_cats}")
            return True
        except Exception as e:
            logger.error(f"Update failed for '{name}': {e}")
            return False
    
    def run_enrichment(self, limit: Optional[int] = None, offset: Optional[int] = None,
                       dry_run: bool = False) -> Dict[str, Any]:
        """Run retroactive enrichment."""
        state = self._load_state()
        if offset is None:
            offset = state.get("offset", 0)
        
        self._log(f"Starting enrichment offset={offset} limit={limit}")
        
        # Fetch untagged entities via Cypher
        try:
            rows = self.kg.query_cypher(
                "MATCH (e:Entity) WHERE e.categories IS NULL OR e.categories = '' "
                "RETURN e.name, e.type, e.id, e.domain, e.categories "
                f"SKIP {offset} LIMIT {limit or 50}"
            )
        except Exception as e:
            # Fallback to REST API
            result = self.kg.get_entities(offset=offset, limit=limit or 50)
            rows = result.get("entities", [])
        
        processed = updated = skipped = errors = 0
        
        for entity in rows[:limit or len(rows)]:
            if isinstance(entity, dict):
                name = entity.get("e.name", entity.get("name", ""))
                eid = entity.get("e.id", entity.get("id", ""))
                etype = entity.get("e.type", entity.get("type", ""))
                current_domain = entity.get("e.domain", entity.get("domain", ""))
                current_cats = entity.get("e.categories", entity.get("categories", "")) or ""
            else:
                continue
            
            if not name or not eid:
                skipped += 1
                continue
            
            try:
                success = self.enrich_entity(
                    eid, name, etype, current_domain, current_cats, dry_run
                )
                if success:
                    updated += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error enriching {name}: {e}")
            
            processed += 1
            time.sleep(2.0)  # Rate limiting
        
        state["total_processed"] = processed
        state["total_updated"] = updated
        state["total_skipped"] = skipped
        state["total_errors"] = errors
        state["offset"] = offset + processed
        self._save_state(state)
        
        return {
            "status": "done",
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors
        }
    
    def get_historical_context(self, insight_bank: Optional[Dict] = None) -> str:
        """Get historical context for distill (from kg_history_enrich.py)."""
        try:
            sections = []
            
            # Top recurring entities
            rows = self.kg.query_cypher(
                'MATCH (e:Entity) WHERE e.domain = $domain '
                'RETURN e.name, e.type, e.mention_count '
                'ORDER BY e.mention_count DESC LIMIT 10',
                {"domain": self.KG_DOMAIN}
            )
            if rows:
                sections.append("## Historical Knowledge Graph Topics")
                for r in rows[:8]:
                    name = r.get("e.name", "?")
                    etype = r.get("e.type", "?")
                    sections.append(f"- {name} ({etype})")
            
            return "\n".join(sections) if sections else ""
        except Exception:
            return ""
    
    def enrich_insight_bank(self, insight_bank: Dict) -> List[str]:
        """Query KG for patterns that should be promoted (from kg_history_enrich.py)."""
        try:
            rows = self.kg.query_cypher(
                'MATCH (e:Entity) WHERE e.domain = $domain AND e.mention_count > 1 '
                'RETURN e.name, e.type, e.mention_count '
                'ORDER BY e.mention_count DESC LIMIT 20',
                {"domain": self.KG_DOMAIN}
            )
            promotions = []
            for r in rows:
                name = r.get("e.name", "")
                mentions = r.get("e.mention_count", 0)
                etype = r.get("e.type", "")
                if mentions >= 2 and name:
                    promotions.append(f"{name} ({etype}, seen {mentions}x)")
            return promotions
        except Exception:
            return []
