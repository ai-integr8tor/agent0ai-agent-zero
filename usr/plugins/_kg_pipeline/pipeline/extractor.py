"""Entity extraction helper."""
import os
import re
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

from .kg_client import KGClient

logger = logging.getLogger(__name__)


class KGExtractor:
    """Extracts entities and relationships using LLM."""
    
    LLM_TIMEOUT = 120
    MAX_CONTENT_LENGTH = 4000
    
    DOMAIN_PATHS = {
        "work": ["work/", "sales/", "sled/", "deals/", "territory/"],
        "personal": ["personal/", "life/", "home/", "bookmark/"],
        "technology": ["system/", "infra/", "docker/", "framework/", "model/"],
        "context": ["context/", "ideas/", "testing/", "archive/"]
    }
    
    # Common entity aliases for normalization
    ENTITY_ALIASES = {
        "MSU": "Michigan State University",
        "U of M": "University of Michigan",
        "OSU": "Ohio State University",
        "MWO": "MechWarrior Online",
        "A0": "Agent Zero",
        "Elastic": "Elastic",
    }
    
    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.session = requests.Session()
        self.llm_url = config.get("llm_api_url", "http://192.168.1.245:8000/v1")
        self.llm_model = config.get("llm_model", "default")
    
    def detect_domain(self, filepath: str) -> str:
        """Detect domain from file path."""
        rel_path = filepath.lower()
        for domain, paths in self.DOMAIN_PATHS.items():
            for prefix in paths:
                if prefix in rel_path:
                    return domain
        return "context"
    
    def canonicalize(self, name: str) -> str:
        """Normalize entity name."""
        return self.ENTITY_ALIASES.get(name.strip(), name.strip())
    
    def _build_extraction_prompt(self, content: str, filename: str,
                                  domain: str) -> str:
        """Build extraction prompt for LLM."""
        domain_desc = {
            "work": "SLED sales - accounts, contacts, competitors, deals",
            "personal": "Personal - books, recipes, games, interests",
            "technology": "Agent Zero system, AI models, infrastructure",
            "context": "Learning notes, ideas, testing"
        }.get(domain, "General knowledge")
        
        return f"""Extract entities and relationships from this {domain} domain file.

DOMAIN: {domain} - {domain_desc}
SOURCE: {filename}

TEXT CONTENT:
{content[:self.MAX_CONTENT_LENGTH]}

Output ONLY valid JSON:
{{
  "entities": [
    {{"name": "exact name", "type": "EntityType", "confidence": 0.8}}
  ],
  "relationships": [
    {{"subject": "name", "type": "REL_TYPE", "object": "name", "confidence": 0.8}}
  ]
}}

RULES:
1. Extract ONLY entities explicitly mentioned
2. Use EXACT names from text (no paraphrasing)
3. Every relationship must connect two extracted entities
4. Confidence: 1.0=explicit, 0.8=strongly implied, 0.7=likely"""
    
    def extract_with_llm(self, content: str, filename: str,
                         domain: str) -> Dict[str, Any]:
        """Extract entities using local LLM."""
        prompt = self._build_extraction_prompt(content, filename, domain)
        
        try:
            response = self.session.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 8000
                },
                timeout=self.LLM_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            raw_content = result['choices'][0]['message']['content']
            
            parsed = self._extract_json_from_text(raw_content)
            if parsed:
                return parsed
            
            return {"entities": [], "relationships": []}
            
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {"entities": [], "relationships": []}
    
    def _extract_json_from_text(self, text: str) -> Optional[Dict]:
        """Extract JSON from LLM response."""
        try:
            return json.loads(text.strip())
        except:
            pass
        
        for marker in ['```json', '```']:
            if marker in text:
                try:
                    block = text.split(marker)[1].split('```')[0]
                    return json.loads(block.strip())
                except:
                    continue
        
        import re

        brace_pattern = re.compile(r'\{[^{}]*"entities"[^{}]*\}', re.DOTALL)
        match = brace_pattern.search(text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
        
        return None
    
    def extract_from_file(self, filepath: str) -> Dict[str, Any]:
        """Extract entities from a single file."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            if len(content) < 50:
                return {"status": "skipped", "reason": "too_short"}
            
            domain = self.detect_domain(filepath)
            filename = os.path.basename(filepath)
            
            extraction = self.extract_with_llm(content, filename, domain)
            
            return {
                "status": "done",
                "filename": filename,
                "domain": domain,
                "entities": extraction.get("entities", []),
                "relationships": extraction.get("relationships", [])
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
