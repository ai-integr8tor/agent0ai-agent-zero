"""Shared KG service HTTP client."""
import json
import time
import logging
from typing import Dict, List, Optional, Any
import requests

logger = logging.getLogger(__name__)


class KGClient:
    """HTTP client for KG service communication."""
    
    def __init__(self, base_url: str, timeout: int = 300, 
                 max_retries: int = 3, retry_delay: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.session = requests.Session()
    
    def _request(self, method: str, endpoint: str, 
                 **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    r = self.session.get(url, timeout=self.timeout, **kwargs)
                else:
                    r = self.session.request(method, url, timeout=self.timeout, **kwargs)
                r.raise_for_status()
                return r.json() if r.text else {}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise
        return {}
    
    def health_check(self) -> Dict[str, Any]:
        """Check KG service health."""
        return self._request("GET", "/health")
    
    def add_content(self, content: str, source_path: str,
                    domain: str = "context") -> Dict[str, Any]:
        """Add content with entity extraction."""
        return self._request("POST", "/api/v1/add",
            json={"content": content, "source_path": source_path, "domain": domain})
    
    def search(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search entities/relationships."""
        return self._request("POST", "/api/v1/search",
            json={"query": query, "limit": limit})
    
    def get_entities(self, offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        """List entities."""
        return self._request("GET", "/api/v1/entities",
            params={"offset": offset, "limit": limit})
    
    def export_data(self) -> Dict[str, Any]:
        """Export all data."""
        return self._request("GET", "/api/v1/export")
    
    def get_hubs(self, top_n: int = 50, min_degree: int = 5) -> List[Dict]:
        """Get hub entities."""
        r = self._request("GET", "/api/v1/graph/hubs",
            params={"top_n": top_n, "min_degree": min_degree})
        return r.get("hubs", [])
    
    def get_orphans(self, limit: int = 1000) -> List[Dict]:
        """Get orphan entities."""
        r = self._request("GET", "/api/v1/analysis/orphans",
            params={"limit": limit})
        return r.get("orphans", [])
    
    def get_communities(self) -> Dict[str, Any]:
        """Detect communities."""
        return self._request("GET", "/api/v1/analysis/communities")
    
    def get_bridges(self) -> Dict[str, Any]:
        """Find bridge nodes."""
        return self._request("GET", "/api/v1/analysis/bridges")
    
    def janitor(self, passes: List[str] = None, 
                dry_run: bool = False) -> Dict[str, Any]:
        """Run cleanup/maintenance."""
        passes = passes or ["normalize", "orphans"]
        return self._request("POST", "/api/v1/janitor",
            json={"passes": passes, "dry_run": dry_run})
    
    def query_cypher(self, query: str, params: Dict = None) -> List[Dict]:
        """Execute Cypher query."""
        r = self._request("POST", "/api/v1/query",
            json={"query": query, "params": params or {}})
        return r.get("rows", [])
    
    def update_entity(self, entity_id: str, data: Dict) -> Dict[str, Any]:
        """Update entity."""
        return self._request("PUT", f"/api/v1/entities/{entity_id}",
            json=data)
    
    def create_relationship(self, source_name: str, target_name: str,
                          rel_type: str) -> bool:
        """Create relationship between entities."""
        try:
            self._request("POST", "/api/v1/relationships",
                json={"source_name": source_name, "target_name": target_name,
                      "rel_type": rel_type})
            return True
        except Exception as e:
            logger.error(f"Failed to create relationship: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        return self._request("GET", "/api/v1/status")
