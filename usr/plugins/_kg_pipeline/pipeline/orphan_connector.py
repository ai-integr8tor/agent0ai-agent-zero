"""Orphan entity connector using LLM to suggest connections."""
import os
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import requests

from .kg_client import KGClient

logger = logging.getLogger(__name__)


@dataclass
class OrphanEntity:
    """Represents an orphan entity from KG."""
    id: str
    name: str
    type: str
    domain: str
    confidence: float
    degree: int


@dataclass
class InferredRelationship:
    """Represents LLM-inferred relationship."""
    source_name: str
    target_name: str
    relation: str
    confidence: float
    reasoning: str


@dataclass
class ConnectorState:
    """Tracks processing state for resume capability."""
    total_orphans: int = 0
    processed_count: int = 0
    connected_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    last_batch_time: Optional[str] = None
    processed_ids: set = field(default_factory=set)
    failed_ids: set = field(default_factory=set)
    
    def to_dict(self) -> Dict:
        return {
            "total_orphans": self.total_orphans,
            "processed_count": self.processed_count,
            "connected_count": self.connected_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "last_batch_time": self.last_batch_time,
            "processed_ids": list(self.processed_ids),
            "failed_ids": list(self.failed_ids),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ConnectorState":
        state = cls(
            total_orphans=data.get("total_orphans", 0),
            processed_count=data.get("processed_count", 0),
            connected_count=data.get("connected_count", 0),
            failed_count=data.get("failed_count", 0),
            skipped_count=data.get("skipped_count", 0),
            last_batch_time=data.get("last_batch_time"),
        )
        state.processed_ids = set(data.get("processed_ids", []))
        state.failed_ids = set(data.get("failed_ids", []))
        return state


class OrphanConnector:
    """Connects orphan entities to hub entities via LLM."""
    
    LLM_TIMEOUT = 60
    CONFIDENCE_THRESHOLD = 0.7
    MIN_HUB_DEGREE = 5
    BATCH_SIZE = 5
    RATE_LIMIT_DELAY = 2.0
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.state_file = config.get("orphan_state_file",
            "/a0/usr/workdir/state/kg_orphan_state.json")
        self.session = requests.Session()
        self.llm_url = config.get("llm_api_url", "http://192.168.1.245:8000/v1")
        self.llm_model = config.get("llm_model", "default")
    
    def _load_state(self) -> ConnectorState:
        """Load state from file."""
        if self.state_file and os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    return ConnectorState.from_dict(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
        return ConnectorState()
    
    def _save_state(self, state: ConnectorState) -> None:
        """Save state to file."""
        if self.state_file:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
    
    def infer_relationships(self, orphans: List[OrphanEntity],
                           hubs: List[Dict]) -> List[InferredRelationship]:
        """Use LLM to infer relationships between orphans and hubs."""
        orphan_list = "\n".join(
            f"- Name: '{o.name}', Type: {o.type}"
            for o in orphans
        )
        hub_list = "\n".join(
            f"- Name: '{h['name']}', Type: {h['type']}"
            for h in hubs[:50]
        )
        
        prompt = f"""You are a knowledge graph relationship inference engine.
Suggest logical relationships between ORPHAN entities and HUB entities.

ORPHANS (low connectivity):
{orphan_list}

HUBS (well-connected):
{hub_list}

For each orphaned entity, propose 1-3 logical connections.

INSTRUCTIONS:
1. Only suggest semantically meaningful relationships
2. Use specific terms (e.g., "mentioned_in", "part_of", "related_to")
3. Assign confidence 0.0-1.0 based on semantic strength
4. Provide brief reasoning

Return ONLY JSON:
{{"relationships": [
{{"source_name": "...", "target_name": "...", "relation": "...",
 "confidence": 0.85, "reasoning": "..."}}
]}}"""
        
        try:
            response = self.session.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
                timeout=self.LLM_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"].get("content", "")
            
            parsed = self._extract_json(content)
            if not parsed:
                return []
            
            relationships = []
            for rel_data in parsed.get("relationships", []):
                if rel_data.get("confidence", 0) >= self.CONFIDENCE_THRESHOLD:
                    relationships.append(InferredRelationship(
                        source_name=rel_data["source_name"],
                        target_name=rel_data["target_name"],
                        relation=rel_data["relation"],
                        confidence=rel_data["confidence"],
                        reasoning=rel_data.get("reasoning", ""),
                    ))
            return relationships
            
        except Exception as e:
            logger.error(f"LLM inference failed: {e}")
            return []
    
    def _extract_json(self, content: str) -> Optional[Dict]:
        """Extract JSON from LLM response."""
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass
        
        import re

        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{.*"relationships".*\}',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match.strip())
                except:
                    continue
        return None
    
    def process_batch(self, orphans: List[OrphanEntity],
                     hubs: List[Dict], state: ConnectorState,
                     dry_run: bool = False) -> tuple:
        """Process a batch of orphans."""
        if not orphans or not hubs:
            return 0, 0, 0
        
        inferred = self.infer_relationships(orphans, hubs)
        time.sleep(self.RATE_LIMIT_DELAY)
        
        connected = 0
        failed = 0
        
        for rel in inferred:
            if rel.source_name in state.processed_ids:
                continue
            
            if dry_run:
                logger.info(f"[DRY RUN] Would connect: {rel.source_name} -> {rel.target_name}")
                connected += 1
            else:
                success = self.kg.create_relationship(
                    source_name=rel.source_name,
                    target_name=rel.target_name,
                    rel_type=rel.relation
                )
                if success:
                    connected += 1
                else:
                    failed += 1
                    state.failed_ids.add(rel.source_name)
        
        for orphan in orphans:
            state.processed_ids.add(orphan.id)
        
        return len(orphans), connected, failed
    
    def run(self, batch_size: int = 5, max_batches: Optional[int] = None,
            dry_run: bool = False) -> Dict[str, Any]:
        """Main processing loop."""
        state = self._load_state()
        
        # Fetch orphans and hubs
        orphan_data = self.kg.get_orphans(limit=5000)
        hubs = self.kg.get_hubs(top_n=50, min_degree=self.MIN_HUB_DEGREE)
        
        if not orphan_data:
            return {"status": "no_orphans"}
        
        # Convert to OrphanEntity
        orphans = [
            OrphanEntity(
                id=item["id"],
                name=item["name"],
                type=item.get("type", ""),
                domain=item.get("domain", ""),
                confidence=item.get("confidence", 0),
                degree=item.get("degree", 0),
            )
            for item in orphan_data
        ]
        
        state.total_orphans = len(orphans)
        
        # Filter already processed
        to_process = [
            o for o in orphans
            if o.id not in state.processed_ids and o.id not in state.failed_ids
        ]
        
        logger.info(f"Processing {len(to_process)} orphans")
        
        batches_processed = 0
        for i in range(0, len(to_process), batch_size):
            if max_batches and batches_processed >= max_batches:
                break
            
            batch = to_process[i:i + batch_size]
            processed, connected, failed = self.process_batch(batch, hubs, state, dry_run)
            
            state.processed_count += processed
            state.connected_count += connected
            state.failed_count += failed
            state.last_batch_time = datetime.utcnow().isoformat()
            batches_processed += 1
            
            self._save_state(state)
            time.sleep(self.RATE_LIMIT_DELAY)
        
        return {
            "status": "done",
            "total_orphans": state.total_orphans,
            "processed": state.processed_count,
            "connected": state.connected_count,
            "failed": state.failed_count,
        }
    
    def reset(self) -> bool:
        """Reset state file."""
        if self.state_file and os.path.exists(self.state_file):
            os.remove(self.state_file)
            logger.info(f"State file reset: {self.state_file}")
        return True
