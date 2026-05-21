"""CONTRADICTION operation for KG Dreamer.

Detects entities with conflicting property values across multiple
source documents using LLM-based contradiction analysis.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

import requests

logger = logging.getLogger(__name__)


class ContradictionOperation:
    """Detect property contradictions across multiple sources.

    Identifies entities that have different values for the same
    property across source documents, then uses LLM analysis to
    determine if the differences represent genuine contradictions
    or semantically equivalent variants.

    Attributes:
        kg_client: HTTP client for KG service.
        audit_chain: Append-only audit trail for operations.
        config: Operation configuration dict.
        llm_endpoint: URL for LLM contradiction analysis.
    """

    DEFAULT_PROPERTY_FIELDS: List[str] = ["description", "type", "category"]
    DEFAULT_MIN_CONFIDENCE: float = 0.7
    DEFAULT_LLM_TIMEOUT: int = 60
    DEFAULT_LLM_MAX_TOKENS: int = 4096
    DEFAULT_BATCH_SIZE: int = 10

    CONTRADICTION_PATTERN: str = r"\bCONTRADICTION\b"
    CONSISTENT_PATTERN: str = r"\bCONSISTENT\b"

    def __init__(
        self,
        kg_client: Any,
        audit_chain: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ContradictionOperation.

        Args:
            kg_client: KG client with query_cypher() and get_entity() methods.
            audit_chain: Audit chain with append() method.
            config: Optional config for property_fields, min_confidence,
                   llm_endpoint, llm_timeout, llm_max_tokens.
        """
        self.kg = kg_client
        self.audit = audit_chain
        cfg = config or {}

        self.property_fields: List[str] = cfg.get(
            "property_fields", self.DEFAULT_PROPERTY_FIELDS
        )
        self.min_confidence: float = float(
            cfg.get("min_confidence", self.DEFAULT_MIN_CONFIDENCE)
        )
        self.llm_endpoint: str = cfg.get(
            "llm_endpoint",
            "http://192.168.1.250:11435/v1/chat/completions",
        )
        self.llm_timeout: int = int(
            cfg.get("llm_timeout", self.DEFAULT_LLM_TIMEOUT)
        )
        self.llm_max_tokens: int = int(
            cfg.get("llm_max_tokens", self.DEFAULT_LLM_MAX_TOKENS)
        )
        self.batch_size: int = int(
            cfg.get("batch_size", self.DEFAULT_BATCH_SIZE)
        )

    def execute(self, dry_run: bool = True) -> Dict[str, Any]:
        """Execute CONTRADICTION operation.

        Searches for entities with multiple sources, analyzes property
        consistency using LLM, and reports detected contradictions.

        Args:
            dry_run: If True, report findings without side effects.

        Returns:
            Dict with checked count, contradictions_found count,
            contradictions list, and dry_run flag.
        """
        entities = self._get_multi_source_entities()
        if not entities:
            logger.info("No multi-source entities found.")
            return {
                "checked": 0,
                "contradictions_found": 0,
                "contradictions": [],
                "dry_run": dry_run,
            }

        contradictions: List[Dict[str, Any]] = []
        checked_count = 0

        for entity in entities:
            entity_contradictions = self._check_entity_properties(
                entity, dry_run
            )
            contradictions.extend(entity_contradictions)
            checked_count += 1

        contradictions_found = len(contradictions)

        logger.info(
            "CONTRADICTION completed: %d entities checked, "
            "%d contradictions found (dry_run=%s)",
            checked_count,
            contradictions_found,
            dry_run,
        )

        # Log to audit chain even in dry_run to track analysis
        if not dry_run:
            self._log_audit("contradiction_scan", checked_count, contradictions)

        return {
            "checked": checked_count,
            "contradictions_found": contradictions_found,
            "contradictions": contradictions,
            "dry_run": dry_run,
        }

    def _get_multi_source_entities(self) -> List[Dict[str, Any]]:
        """Query KG for entities with potential contradictions.

        Finds entities with same name but different types or domains,
        indicating potential data quality issues.

        Returns:
            List of entity dicts with name, type, domain, and variation count.
        """
        # Find entities with same name but different types
        cypher = (
            "MATCH (e1:Entity), (e2:Entity) "
            "WHERE e1.name = e2.name "
            "AND e1.id <> e2.id "
            "AND (e1.type <> e2.type OR e1.domain <> e2.domain) "
            "RETURN DISTINCT e1.name AS name, e1.type AS etype1, "
            "e2.type AS etype2, e1.domain AS domain1, e2.domain AS domain2, "
            "count(e1) AS occurrence"
        )

        try:
            rows = self.kg.query_cypher(cypher, {})
            # Aggregate by entity name
            seen: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                name = r.get("name", "")
                if not name:
                    continue
                if name not in seen:
                    seen[name] = {
                        "name": name,
                        "type": r.get("etype1", "unknown"),
                        "domain": r.get("domain1", "unknown"),
                        "types": set(),
                        "domains": set(),
                        "variation_count": 0,
                    }
                seen[name]["types"].add(r.get("etype1", "unknown"))
                seen[name]["types"].add(r.get("etype2", "unknown"))
                seen[name]["domains"].add(r.get("domain1", "unknown"))
                seen[name]["domains"].add(r.get("domain2", "unknown"))
                seen[name]["variation_count"] = len(seen[name]["types"]) + len(seen[name]["domains"])

            # Convert sets to lists for serialization
            entities: List[Dict[str, Any]] = [
                {
                    "name": v["name"],
                    "type": v["type"],
                    "domain": v["domain"],
                    "types": list(v["types"]),
                    "domains": list(v["domains"]),
                    "variation_count": v["variation_count"],
                }
                for v in seen.values()
                if v["variation_count"] >= 2
            ]

            logger.debug("Found %d multi-variant entities", len(entities))
            return entities
        except Exception as exc:
            logger.error("Failed to query multi-source entities: %s", exc)
            return []

    def _get_entity_property_values(
        self, entity_name: str, field: str
    ) -> List[Dict[str, Any]]:
        """Get property values for an entity.

        Args:
            entity_name: The entity to query.
            field: The property field to retrieve.

        Returns:
            List of dicts with value and entity info.
        """
        # Get entity property directly
        # Current KG schema doesn't track source documents per property
        cypher = (
            f"MATCH (e:Entity {{name: $name}}) "
            f"WHERE e.{field} IS NOT NULL "
            f"RETURN e.{field} AS value, e.type AS etype, "
            f"e.domain AS domain LIMIT 1"
        )

        try:
            rows = self.kg.query_cypher(cypher, {"name": entity_name})
            values: List[Dict[str, Any]] = []
            for r in rows:
                val = r.get("value")
                if val is not None and str(val).strip():
                    values.append({
                        "value": str(val),
                        "source": f"type={r.get('etype', 'unknown')}, domain={r.get('domain', 'unknown')}",
                    })
            return values
        except Exception as exc:
            logger.error(
                "Failed to get property values for %s.%s: %s",
                entity_name, field, exc
            )
            return []

    def _check_entity_properties(
        self, entity: Dict[str, Any], dry_run: bool
    ) -> List[Dict[str, Any]]:
        """Check all configured properties for contradictions.

        Args:
            entity: Entity dict with name and type.
            dry_run: If True, don't create flags.

        Returns:
            List of detected contradictions for this entity.
        """
        entity_name = entity.get("name", "")
        entity_type = entity.get("type", "unknown")
        contradictions: List[Dict[str, Any]] = []

        for field in self.property_fields:
            values = self._get_entity_property_values(entity_name, field)
            if len(values) < 2:
                continue

            # Compare each pair of values
            for i in range(len(values)):
                for j in range(i + 1, len(values)):
                    val_a = values[i]
                    val_b = values[j]

                    # Skip identical values
                    if val_a["value"] == val_b["value"]:
                        continue

                    result = self._analyze_contradiction(
                        entity_name, entity_type, field,
                        val_a["value"], val_b["value"]
                    )

                    if result.get("is_contradiction"):
                        confidence = result.get("confidence", 0.5)
                        if confidence >= self.min_confidence:
                            contradiction = {
                                "entity": entity_name,
                                "entity_type": entity_type,
                                "field": field,
                                "value_a": val_a["value"],
                                "value_b": val_b["value"],
                                "source_a": val_a["doc_id"],
                                "source_b": val_b["doc_id"],
                                "source_a_title": val_a["doc_title"],
                                "source_b_title": val_b["doc_title"],
                                "confidence": confidence,
                                "explanation": result.get("explanation", ""),
                            }
                            contradictions.append(contradiction)

                            if not dry_run:
                                self._log_audit(
                                    "contradiction_detected",
                                    1,
                                    [contradiction]
                                )

        return contradictions

    def _analyze_contradiction(
        self,
        entity_name: str,
        entity_type: str,
        field: str,
        value_a: str,
        value_b: str,
    ) -> Dict[str, Any]:
        """Use LLM to determine if two values represent a contradiction.

        Args:
            entity_name: The entity being analyzed.
            entity_type: Type of the entity.
            field: The property field.
            value_a: First value.
            value_b: Second value.

        Returns:
            Dict with is_contradiction (bool), confidence (0-1),
            and explanation (str).
        """
        prompt = self._build_contradiction_prompt(
            entity_name, entity_type, field, value_a, value_b
        )

        try:
            response = self._call_llm(prompt)
            return self._parse_llm_response(response)
        except Exception as exc:
            logger.error("LLM analysis failed for %s: %s", entity_name, exc)
            return {
                "is_contradiction": False,
                "confidence": 0.0,
                "explanation": f"LLM analysis error: {exc}",
            }

    def _build_contradiction_prompt(
        self,
        entity_name: str,
        entity_type: str,
        field: str,
        value_a: str,
        value_b: str,
    ) -> str:
        """Build LLM prompt for contradiction analysis.

        Args:
            entity_name: Entity name.
            entity_type: Entity type.
            field: Property field.
            value_a: First value.
            value_b: Second value.

        Returns:
            Formatted prompt string.
        """
        return (
            f"Analyze whether these two descriptions of '{entity_name}' "
            f"(a {entity_type} entity) contradict each other.\n\n"
            f"Field: {field}\n"
            f"Source A: {value_a}\n"
            f"Source B: {value_b}\n\n"
            "Do these values contradict each other? Consider semantic "
            "meaning, not just wording differences.\n\n"
            "Answer format:\n"
            "VERDICT: CONTRADICTION or CONSISTENT\n"
            "CONFIDENCE: 0.0 to 1.0\n"
            "EXPLANATION: Brief explanation of your reasoning\n\n"
            "Rules:\n"
            "- Use CONTRADICTION only if the values cannot both be true\n"
            "- Use CONSISTENT if they describe the same thing differently\n"
            "- Confidence should reflect your certainty"
        )

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Call LLM endpoint for contradiction analysis.

        Args:
            prompt: The analysis prompt.

        Returns:
            Raw LLM response dict.
        """
        payload = {
            "model": "qwen3.6:35b",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a semantic analysis assistant. "
                        "Detect when property values contradict. "
                        "Be precise and objective."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.llm_max_tokens,
            "temperature": 0.0,
            "stream": False,
        }

        response = requests.post(
            self.llm_endpoint,
            json=payload,
            timeout=self.llm_timeout,
        )
        response.raise_for_status()
        return response.json()

    def _parse_llm_response(
        self, response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Parse LLM response for contradiction verdict.

        Tries reasoning_content first, then content.

        Args:
            response: Raw LLM response dict.

        Returns:
            Parsed dict with is_contradiction, confidence, explanation.
        """
        choices = response.get("choices", [])
        if not choices:
            logger.warning("Empty choices in LLM response")
            return {"is_contradiction": False, "confidence": 0.0, "explanation": ""}

        message = choices[0].get("message", {})

        # Try reasoning_content first, fallback to content
        text = message.get("reasoning_content", "") or message.get("content", "")
        if not text:
            logger.warning("Empty LLM message content")
            return {"is_contradiction": False, "confidence": 0.0, "explanation": ""}

        text = str(text).strip()

        # Parse verdict
        is_contradiction = False
        if re.search(self.CONTRADICTION_PATTERN, text, re.IGNORECASE):
            is_contradiction = True
        elif re.search(self.CONSISTENT_PATTERN, text, re.IGNORECASE):
            is_contradiction = False
        else:
            # Default to no contradiction if unclear
            logger.debug("Ambiguous verdict, defaulting to CONSISTENT")

        # Parse confidence
        confidence_match = re.search(
            r"CONFIDENCE:\s*([0-9.]+)", text, re.IGNORECASE
        )
        confidence = 0.5
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                confidence = 0.5

        # Extract explanation
        explanation = ""
        expl_match = re.search(
            r"EXPLANATION:\s*(.+?)(?=\n\n|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if expl_match:
            explanation = expl_match.group(1).strip()
        else:
            # Fallback: use everything after VERDICT line
            verdict_end = re.search(
                r"VERDICT:\s*\w+",
                text,
                re.IGNORECASE
            )
            if verdict_end:
                explanation = text[verdict_end.end():].strip()[:200]

        return {
            "is_contradiction": is_contradiction,
            "confidence": confidence,
            "explanation": explanation,
        }

    def _log_audit(
        self,
        action: str,
        count: int,
        details: List[Dict[str, Any]],
    ) -> None:
        """Log contradiction operation to audit chain.

        Args:
            action: Action performed (contradiction_scan or contradiction_detected).
            count: Number of items.
            details: Operation details.
        """
        try:
            self.audit.append(
                action=action,
                target_type="entity",
                target_id="multi_source_analysis",
                source="kg_dreamer.operations.contradiction",
                metadata={
                    "count": count,
                    "min_confidence": self.min_confidence,
                    "fields_checked": self.property_fields,
                    "details": details[:10],  # Limit stored details
                },
            )
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)
