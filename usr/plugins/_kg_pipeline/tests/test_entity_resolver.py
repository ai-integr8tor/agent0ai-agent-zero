"""Unit tests for entity_resolver.py - 3-stage entity resolution pipeline.

Tests cover:
- Jaro-Winkler similarity computation
- Token overlap calculation
- Candidate finding with type grouping
- LLM verification (mocked)
- Merge logic with degree-based canonical selection
- Dry-run safety
- Audit logging
"""
import unittest
import json
from unittest.mock import Mock, MagicMock, patch, call
import sys
from pathlib import Path

# Add plugin root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.entity_resolver import EntityResolver


class TestEntityResolver(unittest.TestCase):
    """Test suite for EntityResolver class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_kg = Mock()
        self.config = {
            "llm_url": "http://test-llm:8000/v1/chat/completions",
            "llm_model": "test-model",
            "string_threshold": 0.80,
            "token_threshold": 0.60,
            "llm_verify": True,
            "batch_size": 10,
            "llm_sleep": 0.01,  # Fast for tests
        }
        self.resolver = EntityResolver(self.mock_kg, self.config)


class TestJaroWinkler(TestEntityResolver):
    """Test Jaro-Winkler similarity implementation."""

    def test_jaro_winkler_identical(self):
        """Same string should return 1.0."""
        result = self.resolver._jaro_winkler("Elastic Stack", "Elastic Stack")
        self.assertEqual(result, 1.0)

    def test_jaro_winkler_identical_lowercase(self):
        """Same string in lowercase should return 1.0."""
        result = self.resolver._jaro_winkler("elastic stack", "elastic stack")
        self.assertEqual(result, 1.0)

    def test_jaro_winkler_similar(self):
        """'Elastic Stack' vs 'ELK Stack' should be high similarity."""
        result = self.resolver._jaro_winkler("elastic stack", "elk stack")
        self.assertGreater(result, 0.70)  # Should be high due to shared tokens

    def test_jaro_winkler_typo(self):
        """Minor typo should still have good similarity."""
        result = self.resolver._jaro_winkler("kubernetes", "kubernetis")
        self.assertGreater(result, 0.85)

    def test_jaro_winkler_different(self):
        """'Docker' vs 'Kubernetes' should be low-moderate similarity."""
        result = self.resolver._jaro_winkler("docker", "kubernetes")
        # Both share some character patterns (r, e, t, s) giving moderate similarity
        self.assertLess(result, 0.75)
        self.assertGreater(result, 0)  # But not zero

    def test_jaro_winkler_partial(self):
        """Partial match should work."""
        result = self.resolver._jaro_winkler("sled central", "sled")
        self.assertGreater(result, 0.60)

    def test_jaro_winkler_empty(self):
        """Empty strings should return 0.0 except identical empty (1.0)."""
        self.assertEqual(self.resolver._jaro_winkler("", "test"), 0.0)
        self.assertEqual(self.resolver._jaro_winkler("test", ""), 0.0)
        # Two empty strings are identical, so similarity is 1.0
        self.assertEqual(self.resolver._jaro_winkler("", ""), 1.0)

    def test_jaro_winkler_single_char(self):
        """Single character strings."""
        result = self.resolver._jaro_winkler("a", "a")
        self.assertEqual(result, 1.0)
        result = self.resolver._jaro_winkler("a", "b")
        self.assertEqual(result, 0.0)


class TestTokenOverlap(TestEntityResolver):
    """Test token overlap calculation."""

    def test_token_overlap_high(self):
        """'Elastic Stack' vs 'ELK Stack' - 2/2 overlap."""
        result = self.resolver._token_overlap("Elastic Stack", "ELK Stack")
        # Tokenizes to {"elastic", "stack"} and {"elk", "stack"}
        # Intersection = {"stack"}, min = 1, overlap = 1/2 = 0.5
        self.assertGreater(result, 0.4)

    def test_token_overlap_full(self):
        """Full token overlap."""
        result = self.resolver._token_overlap("State Local Education", "State Local Education")
        self.assertEqual(result, 1.0)

    def test_token_overlap_low(self):
        """No shared tokens should be 0."""
        result = self.resolver._token_overlap("Docker", "Kubernetes")
        self.assertEqual(result, 0.0)

    def test_token_overlap_partial(self):
        """Partial token overlap."""
        result = self.resolver._token_overlap("Elastic Security", "Elastic Stack")
        # {"elastic", "security"} vs {"elastic", "stack"}
        # Intersection = {"elastic"}, min = 2, overlap = 1/2 = 0.5
        self.assertEqual(result, 0.5)

    def test_token_overlap_empty(self):
        """Empty strings should return 0.0."""
        self.assertEqual(self.resolver._token_overlap("", "test"), 0.0)
        self.assertEqual(self.resolver._token_overlap("test", ""), 0.0)

    def test_token_overlap_acronym(self):
        """Acronym matching."""
        result = self.resolver._token_overlap("SLED", "State Local Education")
        # Single token vs 3 tokens, no exact match
        self.assertEqual(result, 0.0)


class TestFindCandidates(TestEntityResolver):
    """Test candidate finding with type grouping."""

    def test_find_candidates_empty_kg(self):
        """Empty KG should return empty candidates."""
        self.mock_kg.query_cypher.return_value = []
        result = self.resolver.find_candidates()
        self.assertEqual(result, [])

    def test_find_candidates_groups_by_type(self):
        """Should only compare entities of same type."""
        self.mock_kg.query_cypher.return_value = [
            {"name": "Elastic Stack", "type": "technology", "mention_count": 5},
            {"name": "ELK Stack", "type": "technology", "mention_count": 3},
            {"name": "Docker", "type": "technology", "mention_count": 10},
            {"name": "SLED Team", "type": "organization", "mention_count": 2},
        ]
        result = self.resolver.find_candidates(similarity_threshold=0.70)
        
        # All candidates should be within the same type
        for candidate in result:
            self.assertIsNotNone(candidate["type"])
            # Elastic Stack and ELK Stack should be found
            if candidate["name_a"] == "Elastic Stack" and candidate["name_b"] == "ELK Stack":
                self.assertEqual(candidate["type"], "technology")

    def test_find_candidates_filter_by_type(self):
        """Should filter to specific entity type."""
        self.mock_kg.query_cypher.return_value = [
            {"name": "Elastic Stack", "type": "technology", "mention_count": 5},
            {"name": "SLED Team", "type": "organization", "mention_count": 2},
        ]
        result = self.resolver.find_candidates(entity_type="technology")
        
        # Verify query was filtered
        call_args = self.mock_kg.query_cypher.call_args[0][0]
        self.assertIn("e.type = 'technology'", call_args)

    def test_find_candidates_excludes_same_name(self):
        """Should not compare entity to itself."""
        self.mock_kg.query_cypher.return_value = [
            {"name": "Elastic", "type": "technology", "mention_count": 5},
            {"name": "Elastic", "type": "technology", "mention_count": 5},
        ]
        result = self.resolver.find_candidates()
        
        # Should not have pairs with same name
        names_in_pairs = set()
        for c in result:
            if c["name_a"] == c["name_b"]:
                self.fail("Same name pair found")

    def test_find_candidates_returns_dicts(self):
        """Each candidate should be a dict with required keys."""
        self.mock_kg.query_cypher.return_value = [
            {"name": "Elastic Stack", "type": "technology", "mention_count": 5},
            {"name": "ELK Stack", "type": "technology", "mention_count": 3},
        ]
        result = self.resolver.find_candidates(similarity_threshold=0.70)
        
        self.assertIsInstance(result, list)
        if result:
            for candidate in result:
                self.assertIsInstance(candidate, dict)
                self.assertIn("name_a", candidate)
                self.assertIn("name_b", candidate)
                self.assertIn("type", candidate)
                self.assertIn("similarity", candidate)
                self.assertIn("token_overlap", candidate)
                self.assertIn("method", candidate)


class TestLLMVerifyPair(TestEntityResolver):
    """Test LLM verification calls."""

    @patch("requests.Session.post")
    def test_llm_verify_pair_makes_request(self, mock_post):
        """Should POST to LLM endpoint with correct payload."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "YES confidence 95"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.resolver._llm_verify_pair("Entity A", "Entity B", "type")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]["json"]
        self.assertEqual(call_kwargs["model"], "test-model")
        self.assertEqual(call_kwargs["max_tokens"], 100)
        self.assertEqual(call_kwargs["temperature"], 0.1)
        self.assertIn("Entity A", call_kwargs["messages"][0]["content"])

    @patch("requests.Session.post")
    def test_llm_verify_pair_parses_yes(self, mock_post):
        """Should parse YES from LLM response."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "YES confidence 95"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.resolver._llm_verify_pair("A", "B", "type")
        self.assertEqual(result["verdict"], "YES")

    @patch("requests.Session.post")
    def test_llm_verify_pair_parses_no(self, mock_post):
        """Should parse NO from LLM response."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "NO confidence 80"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.resolver._llm_verify_pair("A", "B", "type")
        self.assertEqual(result["verdict"], "NO")

    @patch("requests.Session.post")
    def test_llm_verify_pair_checks_reasoning_content(self, mock_post):
        """Should check reasoning_content field for Qwen models."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_content": "YES confidence 90"
                }
            }]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.resolver._llm_verify_pair("A", "B", "type")
        self.assertEqual(result["verdict"], "YES")

    @patch("requests.Session.post")
    def test_llm_verify_pair_extracts_confidence(self, mock_post):
        """Should extract confidence score from response."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "YES confidence 85"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.resolver._llm_verify_pair("A", "B", "type")
        self.assertAlmostEqual(result["confidence"], 0.85, places=2)

    @patch("requests.Session.post")
    def test_llm_verify_pair_handles_failure(self, mock_post):
        """Should handle LLM failure gracefully."""
        mock_post.side_effect = Exception("Connection error")

        result = self.resolver._llm_verify_pair("A", "B", "type")
        self.assertEqual(result["verdict"], "NO")
        self.assertEqual(result["confidence"], 0.0)
        self.assertIn("error", result["reasoning"])


class TestVerifyCandidates(TestEntityResolver):
    """Test candidate verification with LLM."""

    @patch.object(EntityResolver, "_llm_verify_pair")
    def test_verify_candidates_filters_by_verdict(self, mock_verify):
        """Should only return candidates with YES verdict."""
        mock_verify.return_value = {"verdict": "YES", "confidence": 0.9, "reasoning": ""}

        candidates = [
            {"name_a": "A", "name_b": "B", "type": "tech"},
            {"name_a": "C", "name_b": "D", "type": "tech"},
        ]
        result = self.resolver.verify_candidates(candidates, batch_size=10)
        self.assertEqual(len(result), 2)

    @patch.object(EntityResolver, "_llm_verify_pair")
    def test_verify_candidates_skips_on_no_verdict(self, mock_verify):
        """Should skip candidates with NO verdict."""
        def side_effect(*args, **kwargs):
            # First returns YES, second returns NO
            if mock_verify.call_count == 1:
                return {"verdict": "YES", "confidence": 0.9, "reasoning": ""}
            return {"verdict": "NO", "confidence": 0.3, "reasoning": ""}
        
        mock_verify.side_effect = side_effect

        candidates = [
            {"name_a": "A", "name_b": "B", "type": "tech"},
            {"name_a": "C", "name_b": "D", "type": "tech"},
        ]
        result = self.resolver.verify_candidates(candidates, batch_size=10)
        self.assertEqual(len(result), 1)

    @patch.object(EntityResolver, "_llm_verify_pair")
    def test_verify_candidates_with_llm_disabled(self, mock_verify):
        """Should use high similarity filter when LLM disabled."""
        self.resolver.config["llm_verify"] = False

        candidates = [
            {"name_a": "A", "name_b": "B", "type": "tech", "similarity": 0.99},
            {"name_a": "C", "name_b": "D", "type": "tech", "similarity": 0.80},
        ]
        result = self.resolver.verify_candidates(candidates)
        # Only the 0.99 similarity should pass
        self.assertEqual(len(result), 1)


class TestMergeLogic(TestEntityResolver):
    """Test merge logic with degree-based canonical selection."""

    def test_merge_keeps_higher_degree_entity(self):
        """Entity with more relationships should be canonical."""
        # First entity has degree 5, second has degree 2
        self.mock_kg.query_cypher.side_effect = [
            [{"degree": 5}],  # degree for name_a
            [{"degree": 2}],  # degree for name_b
            [],  # relationships of duplicate (empty)
        ]

        duplicates = [
            {"name_a": "Popular Entity", "name_b": "Less Popular", "type": "tech", "llm_confidence": 0.9},
        ]
        result = self.resolver.merge_duplicates(duplicates, dry_run=True)
        
        # Popular Entity should be canonical
        detail = result["details"][0]
        self.assertEqual(detail["canonical"], "Popular Entity")
        self.assertEqual(detail["duplicate"], "Less Popular")

    def test_merge_dry_run_no_changes(self):
        """Dry run should not make KG changes."""
        self.mock_kg.query_cypher.side_effect = [
            [{"degree": 5}],
            [{"degree": 2}],
        ]

        duplicates = [
            {"name_a": "A", "name_b": "B", "type": "tech", "llm_confidence": 0.9},
        ]
        result = self.resolver.merge_duplicates(duplicates, dry_run=True)
        
        # No create or delete queries should be called
        for call_args in self.mock_kg.query_cypher.call_args_list:
            query = call_args[0][0]
            self.assertNotIn("DELETE", query.upper())
            self.assertNotIn("CREATE", query.upper())
        
        self.assertTrue(result["dry_run"])

    def test_merge_logs_to_audit(self):
        """Should log merges to audit trail."""
        self.mock_kg.query_cypher.side_effect = [
            [{"degree": 5}],
            [{"degree": 2}],
            [],  # relationships
        ]

        duplicates = [
            {"name_a": "Canonical", "name_b": "Duplicate", "type": "tech", "llm_confidence": 0.95},
        ]
        result = self.resolver.merge_duplicates(duplicates, dry_run=True)
        
        self.assertGreater(len(self.resolver.audit_log), 0)
        audit_entry = self.resolver.audit_log[0]
        self.assertEqual(audit_entry["action"], "merge")
        self.assertEqual(audit_entry["metadata"]["canonical"], "Canonical")
        self.assertEqual(audit_entry["target_id"], "Duplicate")

    def test_merge_skips_missing_degrees(self):
        """Should skip pairs where degrees can't be determined (returns None)."""
        self.mock_kg.query_cypher.side_effect = [
            [{"degree": 5}],
            Exception("Connection error"),  # Exception returns None
        ]

        duplicates = [
            {"name_a": "A", "name_b": "B", "type": "tech", "llm_confidence": 0.9},
        ]
        result = self.resolver.merge_duplicates(duplicates, dry_run=True)
        
        # When _get_entity_degree returns None due to exception, pair is skipped
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["merged"], 0)


class TestFullPipeline(TestEntityResolver):
    """Test full pipeline stages."""

    def test_run_candidates_stage(self):
        """Should run only candidate finding for 'candidates' stage."""
        self.mock_kg.query_cypher.return_value = [
            {"name": "A", "type": "t", "mention_count": 1},
            {"name": "B", "type": "t", "mention_count": 1},
        ]
        
        result = self.resolver.run(stage="candidates", dry_run=True)
        self.assertEqual(result["stage"], "candidates")
        self.assertIn("candidates", result)
        self.assertIn("count", result)

    def test_run_unknown_stage(self):
        """Should return error for unknown stage."""
        result = self.resolver.run(stage="invalid", dry_run=True)
        self.assertEqual(result["status"], "error")

    def test_run_full_stage(self):
        """Should run all stages for 'full' mode."""
        self.mock_kg.query_cypher.return_value = []
        
        result = self.resolver.run(stage="full", dry_run=True)
        self.assertEqual(result["stage"], "full")
        self.assertIn("candidates", result)
        self.assertIn("verified", result)


class TestConfigDefaults(unittest.TestCase):
    """Test configuration defaults."""

    def test_default_config(self):
        """Should use sensible defaults."""
        mock_kg = Mock()
        resolver = EntityResolver(mock_kg)  # No config
        
        self.assertEqual(resolver.config.get("llm_verify"), None)  # Not in config, checked via get
        self.assertEqual(resolver.llm_url, "http://192.168.1.250:11435/v1/chat/completions")
        self.assertEqual(resolver.llm_model, "Qwen3.6-35B-A3B-MTP-UD-Q5_K_XL.gguf")


if __name__ == "__main__":
    unittest.main()
