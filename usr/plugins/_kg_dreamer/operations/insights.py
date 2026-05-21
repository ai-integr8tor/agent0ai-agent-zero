"""INSIGHT operation for KG Dreamer.

Generates proactive observations from graph patterns using LLM analysis.
Creates actionable insights for sales teams based on KG statistics.
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import requests

logger = logging.getLogger(__name__)


class InsightOperation:
    """Generate proactive observations from graph patterns using LLM.

    Analyzes KG statistics, recent activity, and contradictions to generate
    novel, actionable insights. Tracks insight novelty to avoid repetition.

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for operations.
        config: Operation configuration dict.
    """

    DEFAULT_MAX_INSIGHTS: int = 10
    DEFAULT_MIN_NOVELTY: float = 0.6
    DEFAULT_LLM_TIMEOUT: int = 120
    DEFAULT_LLM_MAX_TOKENS: int = 4096
    RECENT_DAYS: int = 7
    STATE_DIR: str = "/a0/usr/plugins/_kg_dreamer/state"
    LOG_DIR: str = "/a0/usr/plugins/_kg_dreamer/logs"

    def __init__(
        self, kg_client: Any, audit_chain: Any, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Initialize InsightOperation.

        Args:
            kg_client: KG client with query_cypher() and status() methods.
            audit_chain: Audit chain with query(), append(), get_recent().
            config: Optional config for max_insights, min_novelty, llm settings.
        """
        self.kg = kg_client
        self.audit = audit_chain
        cfg = config or {}
        self.max_insights = int(cfg.get("max_insights", self.DEFAULT_MAX_INSIGHTS))
        self.min_novelty = float(cfg.get("min_novelty", self.DEFAULT_MIN_NOVELTY))
        self.llm_endpoint = cfg.get(
            "llm_endpoint", "http://192.168.1.250:11435/v1/chat/completions"
        )
        self.llm_timeout = int(cfg.get("llm_timeout", self.DEFAULT_LLM_TIMEOUT))
        self.llm_max_tokens = int(cfg.get("llm_max_tokens", self.DEFAULT_LLM_MAX_TOKENS))
        self.state_file = os.path.join(self.STATE_DIR, "insights_state.json")
        os.makedirs(self.STATE_DIR, exist_ok=True)
        os.makedirs(self.LOG_DIR, exist_ok=True)

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute INSIGHT operation."""
        stats = self._gather_stats()
        if not stats:
            return {"insights_generated": 0, "insights": [], "dry_run": dry_run}
        raw_insights = self._generate_insights(stats)
        if not raw_insights:
            return {"insights_generated": 0, "insights": [], "dry_run": dry_run}
        filtered = self._filter_by_novelty(raw_insights)
        self._save_to_log(filtered, dry_run)
        if not dry_run:
            self._update_state(filtered)
            self._log_audit("insight_generation", len(filtered), stats)
        logger.info(
            "INSIGHT: %d generated, %d novel (dry_run=%s)",
            len(raw_insights), len(filtered), dry_run
        )
        return {"insights_generated": len(filtered), "insights": filtered, "dry_run": dry_run}

    def _gather_stats(self) -> Optional[Dict[str, Any]]:
        """Gather comprehensive statistics from KG and audit chain."""
        try:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "recent_entities": self._get_recent_entities(),
                "top_hubs": self._get_top_hubs(),
                "recent_connections": self._get_recent_connections(),
                "contradictions": self._get_contradictions(),
                "type_distribution": self._get_type_distribution(),
            }
        except Exception as exc:
            logger.error("Failed to gather stats: %s", exc)
            return None

    def _get_recent_entities(self) -> List[Dict[str, Any]]:
        """Get recently seen entities from KG.

        Uses last_seen property to find entities recently updated.
        """
        try:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=self.RECENT_DAYS)).isoformat()
            cypher = (
                "MATCH (e:Entity) "
                "WHERE e.last_seen >= $cutoff "
                "AND e.first_seen IS NOT NULL "
                "RETURN e.name AS name, e.type AS etype, e.first_seen, e.last_seen, "
                "e.mention_count AS mention_count "
                "ORDER BY e.last_seen DESC LIMIT 20"
            )
            rows = self.kg.query_cypher(cypher, {"cutoff": cutoff_date})
            entities = [
                {
                    "name": r.get("name", ""),
                    "type": r.get("etype", "unknown"),
                    "added_at": r.get("e.first_seen", ""),
                    "updated_at": r.get("e.last_seen", ""),
                    "mention_count": int(r.get("mention_count", 0)),
                }
                for r in rows if r.get("name")
            ]
            return entities
        except Exception as exc:
            logger.debug("Failed to get recent entities: %s", exc)
            return []

    def _get_top_hubs(self) -> List[Dict[str, Any]]:
        """Query KG for top connected entities (hubs)."""
        cypher = (
            "MATCH (e:Entity)-[r]-(other) WITH e, count(r) AS cc "
            "ORDER BY cc DESC LIMIT 20 RETURN e.name AS name, e.type AS etype, cc"
        )
        try:
            rows = self.kg.query_cypher(cypher, {})
            return [
                {"name": r.get("name", ""), "type": r.get("etype", "unknown"), "connections": int(r.get("cc", 0))}
                for r in rows if r.get("name")
            ][:10]
        except Exception as exc:
            logger.debug("Failed to get top hubs: %s", exc)
            return []

    def _get_recent_connections(self) -> List[Dict[str, Any]]:
        """Get recently created RELATES_TO connections from KG.

        Uses created_at property on relationships to find recent connections.
        """
        try:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=self.RECENT_DAYS)).isoformat()
            cypher = (
                "MATCH (e1:Entity)-[r:RELATES_TO]->(e2:Entity) "
                "WHERE r.created_at >= $cutoff "
                "RETURN e1.name AS e1, e2.name AS e2, "
                "r.rel_type AS rel_type, r.created_at AS created_at, "
                "r.confidence AS confidence "
                "ORDER BY r.created_at DESC LIMIT 20"
            )
            rows = self.kg.query_cypher(cypher, {"cutoff": cutoff_date})
            connections = [
                {
                    "e1": r.get("e1", ""),
                    "e2": r.get("e2", ""),
                    "rel_type": r.get("rel_type", "RELATES_TO"),
                    "confidence": float(r.get("confidence", 0.0)),
                    "created_at": r.get("created_at", ""),
                }
                for r in rows if r.get("e1") and r.get("e2")
            ]
            return connections
        except Exception as exc:
            logger.debug("Failed to get recent connections: %s", exc)
            return []

    def _get_contradictions(self) -> List[Dict[str, Any]]:
        """Get count of contradictions from CONTRADICT operation."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.RECENT_DAYS * 2)).timestamp()
            entries = self.audit.get_recent(since=cutoff, action_filter="contradiction_scan")
            contradictions = []
            for entry in entries:
                metadata = entry.get("metadata", {})
                if "contradictions_found" in metadata:
                    contradictions.append({
                        "count": metadata.get("contradictions_found", 0),
                        "entities_checked": metadata.get("entities_checked", 0),
                        "timestamp": entry.get("timestamp", ""),
                    })
            return contradictions[-5:]
        except Exception as exc:
            logger.debug("Failed to get contradictions: %s", exc)
            return []

    def _get_type_distribution(self) -> Dict[str, int]:
        """Get entity type distribution from KG."""
        cypher = "MATCH (e:Entity) RETURN e.type AS etype, count(e) AS cnt ORDER BY cnt DESC"
        try:
            rows = self.kg.query_cypher(cypher, {})
            distribution = {}
            for r in rows:
                etype = r.get("etype", "unknown")
                cnt = int(r.get("cnt", 0))
                if etype and cnt > 0:
                    distribution[etype] = cnt
            return distribution
        except Exception as exc:
            logger.debug("Failed to get type distribution: %s", exc)
            return {}

    def _generate_insights(self, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Call LLM to generate insights from graph statistics."""
        try:
            response = self._call_llm(self._build_prompt(stats))
            return self._parse_response(response)
        except Exception as exc:
            logger.error("LLM insight generation failed: %s", exc)
            return []

    def _build_prompt(self, stats: Dict[str, Any]) -> str:
        """Build LLM prompt for insight generation."""
        lines = [
            "You are analyzing a Knowledge Graph for a sales team at Elastic (SLED division - State/Local Government and Education).",
            f"Generate up to {self.max_insights} novel, actionable insights.",
            "Focus on: market trends, competitive intelligence, account opportunities, technology shifts.",
            "Each insight should be specific, actionable, and non-obvious.",
        ]
        recent = stats.get("recent_entities", [])
        if recent:
            lines.extend(["", "Recent Entity Additions (last 7 days):"] + [f"  - {e['name']} ({e['type']})" for e in recent[:10]])
        hubs = stats.get("top_hubs", [])
        if hubs:
            lines.extend(["", "Top Connected Entities (hubs):"] + [f"  - {h['name']} ({h['type']}): {h['connections']} connections" for h in hubs[:8]])
        connections = stats.get("recent_connections", [])
        if connections:
            lines.extend(["", "Recent Relationship Discoveries:"])
            lines.extend([f"  - {c['e1']} <-> {c['e2']}" for c in connections[:8]])
        contradictions = stats.get("contradictions", [])
        if contradictions:
            total_contra = sum(c.get("count", 0) for c in contradictions)
            lines.extend(["", f"Data Quality: {total_contra} contradictions detected recently"])
        type_dist = stats.get("type_distribution", {})
        if type_dist:
            lines.extend(["", "Entity Type Distribution:"])
            lines.extend([f"  - {t}: {c}" for t, c in list(type_dist.items())[:10]])
        lines.extend([
            "",
            "Format for each insight (one per line):",
            "INSIGHT: <concise description> | RELEVANCE: <domain> | CONFIDENCE: <0.0-1.0>",
            "",
            "Example:",
            "INSIGHT: Three universities recently added observability platforms, suggesting a shift toward modern IT monitoring | RELEVANCE: market trend | CONFIDENCE: 0.75",
        ])
        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Call LLM endpoint for insight generation."""
        payload = {
            "model": "qwen3.6:35b",
            "messages": [
                {"role": "system", "content": "You are a strategic sales analyst specializing in public sector technology trends. Generate insights that sales teams can act on."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.llm_max_tokens,
            "temperature": 0.4,
            "stream": False,
        }
        resp = requests.post(self.llm_endpoint, json=payload, timeout=self.llm_timeout)
        resp.raise_for_status()
        return resp.json()

    def _parse_response(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse LLM response for insights. Tries reasoning_content first."""
        choices = response.get("choices", [])
        if not choices:
            logger.warning("Empty choices in LLM response")
            return []
        message = choices[0].get("message", {})
        text = message.get("reasoning_content", "") or message.get("content", "")
        if not text:
            logger.warning("Empty LLM message content")
            return []
        text = str(text).strip()
        insights = []
        pattern = r"INSIGHT:\s*(.+?)\s*\|\s*RELEVANCE:\s*(\w+)\s*\|\s*CONFIDENCE:\s*([0-9.]+)"
        for match in re.findall(pattern, text, re.IGNORECASE)[: self.max_insights]:
            try:
                insight_text = match[0].strip()
                domain = match[1].strip().lower()
                confidence = max(0.0, min(1.0, float(match[2])))
                if insight_text and len(insight_text) > 10:
                    insights.append({
                        "text": insight_text[:500],
                        "domain": domain,
                        "confidence": confidence,
                        "novel": True,
                        "hash": self._compute_hash(insight_text),
                    })
            except (ValueError, IndexError) as exc:
                logger.debug("Failed to parse insight: %s", exc)
        if not insights:
            for line in text.split("\n"):
                line = line.strip()
                if line.lower().startswith("insight:"):
                    text_part = line[8:].strip()
                    if text_part and len(text_part) > 20:
                        insights.append({
                            "text": text_part[:500], "domain": "general",
                            "confidence": 0.5, "novel": True,
                            "hash": self._compute_hash(text_part),
                        })
        return insights[: self.max_insights]

    def _compute_hash(self, text: str) -> str:
        """Compute hash for insight text to track novelty."""
        normalized = text.lower().strip().replace(" ", "")
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _filter_by_novelty(self, insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter insights by novelty against previously generated."""
        previous = self._load_previous_hashes()
        filtered = []
        for insight in insights:
            h = insight.get("hash", "")
            if h and h not in previous:
                insight["novel"] = True
                filtered.append(insight)
            else:
                insight["novel"] = False
                if insight.get("confidence", 0) >= self.min_novelty:
                    filtered.append(insight)
        return filtered

    def _load_previous_hashes(self) -> Set[str]:
        """Load hashes of previously generated insights."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                    return set(state.get("insight_hashes", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Failed to load state: %s", exc)
        return set()

    def _update_state(self, insights: List[Dict[str, Any]]) -> None:
        """Update state file with new insight hashes."""
        try:
            previous = self._load_previous_hashes()
            new_hashes = {i["hash"] for i in insights if i.get("hash") and i.get("novel")}
            all_hashes = previous | new_hashes
            state = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "insight_hashes": list(all_hashes)[-100:],
                "total_insights_generated": len(all_hashes),
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except OSError as exc:
            logger.warning("Failed to update state: %s", exc)

    def _save_to_log(self, insights: List[Dict[str, Any]], dry_run: bool) -> None:
        """Save insights to log file."""
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(self.LOG_DIR, f"insights_{timestamp}.json")
            with open(filepath, "w") as f:
                json.dump({
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "dry_run": dry_run,
                    "insight_count": len(insights),
                    "insights": insights,
                }, f, indent=2)
            logger.debug("Saved %d insights to %s", len(insights), filepath)
        except OSError as exc:
            logger.warning("Failed to save insights: %s", exc)

    def _log_audit(self, action: str, count: int, stats: Dict[str, Any]) -> None:
        """Log insight operation to audit chain."""
        try:
            self.audit.append(
                action=action,
                target_type="knowledge_graph",
                target_id="insight_analysis",
                source="kg_dreamer.operations.insights",
                metadata={
                    "insight_count": count,
                    "recent_entities": len(stats.get("recent_entities", [])),
                    "recent_hubs": len(stats.get("top_hubs", [])),
                    "recent_connections": len(stats.get("recent_connections", [])),
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
