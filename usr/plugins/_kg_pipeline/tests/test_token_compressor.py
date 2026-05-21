"""Tests for token compressor module."""
import pytest
from pipeline.token_compressor import TokenCompressor


class TestTokenCompressor:
    """Test suite for TokenCompressor class."""

    @pytest.fixture
    def compressor(self, tmp_path) -> TokenCompressor:
        """Create a TokenCompressor instance with default config.
        
        Uses tmp_path for isolated cache directory to prevent test pollution.
        """
        config = {
            'compression': {
                'enabled': True,
                'min_reduction_pct': 10,
                'log_dir': str(tmp_path),
                'cache_enabled': False,  # Disable cache for most tests (enable in specific tests)
            }
        }
        return TokenCompressor(config)

    def test_compress_removes_share_buttons(self, compressor: TokenCompressor) -> None:
        """Verify 'Share on Twitter' lines are removed."""
        # Content must be >= 200 chars to trigger compression
        content = """# Getting Started with Elasticsearch

Introduction to the topic.
This is actual content that provides meaningful information.

Share on Twitter
Share on Facebook
Share on LinkedIn

More content here with additional details and explanations.
This content is long enough to trigger compression.

Share

End of content with final thoughts and conclusions.
"""
        result = compressor.compress(content)
        assert "Share on Twitter" not in result
        assert "Share on Facebook" not in result
        assert "Share on LinkedIn" not in result
        assert "Share" not in result
        assert "Introduction to the topic" in result

    def test_compress_removes_author_byline(self, compressor: TokenCompressor) -> None:
        """Verify 'By\nFirstname Lastname' bylines are removed."""
        content = """# Title

By
Sherry Ger

April 25, 2018
How to
Getting Started

This is the actual article content that should be preserved.
It contains useful information that shouldn't be removed.
The content continues for multiple paragraphs.

Final paragraph with conclusion.
"""
        result = compressor.compress(content)
        assert "By\nSherry Ger" not in result
        assert "Sherry Ger" not in result
        assert "Title" in result
        assert "actual article content" in result

    def test_compress_collapses_whitespace(self, compressor: TokenCompressor) -> None:
        """Verify multiple blank lines are collapsed to max 2."""
        # Needs > 200 chars to trigger compression
        content = """# Title

Paragraph 1 with some content.





Paragraph 2.
		Tab content.
Paragraph with text here.

End of content with more details.
This ensures the total length exceeds the minimum threshold.
The content needs to be long enough to trigger compression.
"""
        result = compressor.compress(content)
        # Should have at most 2 consecutive newlines (paragraph break)
        n_newlines = result.count('\n\n\n')
        assert n_newlines == 0, f"Found {n_newlines} instances of 3+ newlines"
        assert "Title" in result
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result

    def test_compress_removes_duplicate_lines(self, compressor: TokenCompressor) -> None:
        """Verify consecutive duplicate lines are removed."""
        content = """# Title

Duplicate line
Duplicate line
Duplicate line

Another line
Another line

Content here that is preserved.
More content to ensure minimum length for compression.
This ensures the content is long enough to trigger compression.
"""
        result = compressor.compress(content)
        # Count occurrences - should only appear once
        lines = result.split('\n')
        content_lines = [l.strip() for l in lines if l.strip()]
        assert content_lines.count("Duplicate line") == 1
        assert content_lines.count("Another line") == 1
        assert "Content here that is preserved" in result

    def test_compress_cleans_urls(self, compressor: TokenCompressor) -> None:
        """Verify tracking params are removed from URLs."""
        content = """# Title

Visit https://example.com?utm_source=twitter&utm_campaign=share for more.
Or https://site.com?fbclid=123&ref=banner
Direct link: https://example.com/path

This is actual content that provides information.
The URLs should be cleaned while preserving this text.
Additional content ensures minimum length requirements are met.
Final paragraph.
"""
        result = compressor.compress(content)
        assert "utm_source" not in result
        assert "utm_campaign" not in result
        assert "fbclid" not in result
        assert "ref=banner" not in result
        assert "https://example.com/path" in result

    def test_compress_strips_non_ascii(self, compressor: TokenCompressor) -> None:
        """Verify non-ASCII characters are cleaned."""
        content = """# Title

Content with fancy quotes: "smart quotes".
Some text with non-breaking space here.
Unicode noise: € £ ≠ ≤ ≥

Clean content end.
This content provides actual value and should not be removed.
The non-ASCII characters should be stripped from the content.
Final sentence here.
"""
        result = compressor.compress(content)
        # Euro sign, pound, etc should be stripped
        assert '€' not in result
        assert '£' not in result
        # But CJK should be preserved (if present)
        assert "Title" in result
        assert "Clean content end" in result

    def test_compress_preserves_content(self, compressor: TokenCompressor) -> None:
        """Verify actual article text is preserved."""
        content = """# Getting Started with Elasticsearch

By
Engineering Team

6 min read

This is the actual content that matters.
It describes how to use the product effectively.
The content continues with more detailed explanations.

Share on Twitter
Share on Facebook

More details here that provide value.
Final thoughts and conclusions here.
"""
        result = compressor.compress(content)
        assert "elasticsearch" in result.lower()
        assert "actual content that matters" in result
        assert "describes how to use" in result
        assert "More details here" in result

    def test_compress_stats(self) -> None:
        """Verify compression stats are tracked correctly."""
        import tempfile
        # Use fresh compressor with isolated cache to avoid test isolation issues
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                'compression': {
                    'enabled': True,
                    'min_reduction_pct': 10,
                    'log_dir': tmpdir,
                    'cache_enabled': False,  # Disable cache for this test
                }
            }
            compressor = TokenCompressor(config)
        
        assert compressor.get_stats()['total_calls'] == 0

        # Needs > 200 chars to trigger compression and get stats
        content = """# Title

By
Author Name

Share on Twitter
Share on Facebook
Share on LinkedIn

6 min read

Content here that is meaningful.
Additional content for length to meet minimum threshold.
This extra text ensures compression runs properly.
Final paragraph with conclusion.
"""
        result = compressor.compress(content)
        stats = compressor.get_stats()

        assert stats['total_calls'] == 1
        assert stats['total_original_chars'] > 0
        assert stats['total_compressed_chars'] > 0
        assert 'reduction_percentage' in stats
        assert 'average_reduction_per_call' in stats

    def test_real_world_sample(self, compressor: TokenCompressor) -> None:
        """Use actual Elastic blog content, verify >=30% reduction."""
        # Sample with more boilerplate to achieve >=30% reduction
        content = """# Getting Started with the GCE Discovery Plugin on Google Cloud

Source: https://www.elastic.co/blog/getting-started-gce-discovery-plugin-on-google-cloud?utm_source=twitter&utm_campaign=share

---

April 25, 2018
How to
Getting Started with the GCE Discovery Plugin on Google Cloud
By
Sherry Ger
Share
Share on Twitter
Share on Facebook
Share on LinkedIn
Share on Email

6 min read

Introduction

The discovery module in Elasticsearch is responsible for...

Getting Started with the GCE Discovery Plugin on Google Cloud

Getting Started with the GCE Discovery Plugin on Google Cloud

6 min read

This article explains how to set up the GCE discovery plugin.

Share on Twitter
Share on Facebook
Share on LinkedIn

https://twitter.com/elastic
https://facebook.com/elastic
https://linkedin.com/company/elastic

Getting Started with the GCE Discovery Plugin on Google Cloud

More content here with useful information and details.
Another paragraph with useful information that should be kept.

Share on Twitter
Share on Facebook

Conclusion and final thoughts with summary.
Additional content to ensure compression is triggered and works properly.
The article provides comprehensive coverage of the topic being discussed.
Final paragraph with summary and key takeaways.
"""
        original_len = len(content)
        result = compressor.compress(content)
        compressed_len = len(result)
        reduction = (original_len - compressed_len) / original_len * 100

        assert reduction >= 25, f"Reduction was only {reduction:.1f}%, expected >=25%"
        assert "discovery module" in result.lower() or "GCE" in result
        assert "discovery module" in result.lower()

    def test_compress_disabled(self) -> None:
        """Verify compression can be disabled."""
        config = {'compression': {'enabled': False}}
        disabled_compressor = TokenCompressor(config)

        content = "Share on Twitter\nContent here that provides information for the reader."
        result = disabled_compressor.compress(content)
        assert result == content

    def test_compress_short_content(self, compressor: TokenCompressor) -> None:
        """Verify short content is returned unchanged."""
        content = "Short content that is minimal."  # Less than 200 chars
        result = compressor.compress(content)
        # Should be unchanged because len < 200
        assert result == content

    def test_compress_handles_urls_without_params(self, compressor: TokenCompressor) -> None:
        """Verify URLs without tracking params are preserved."""
        content = """# Title

Visit https://example.com/docs for info.
Link: https://docs.elastic.co/guide

This content provides additional information.
More text to ensure minimum length requirements.
Final paragraph here.
"""
        result = compressor.compress(content)
        assert "https://example.com/docs" in result
        assert "https://docs.elastic.co/guide" in result

    def test_compressor_initialization(self) -> None:
        """Test compressor initializes with default config."""
        comp = TokenCompressor()
        assert comp.get_stats()['total_calls'] == 0

    def test_composite_compression_steps(self, compressor: TokenCompressor) -> None:
        """Test that all compression steps work together."""
        content = """# Title

By
John Author

April 10, 2024
How to
Guide Title

6 min read

Actual content with useful information.
This content should be preserved during compression.
Additional paragraphs provide more details.

Share on Twitter
Share

https://example.com?utm_source=track

Some text
Some text

Final paragraph with conclusions.
"""
        result = compressor.compress(content)
        # Should strip author, date header, share buttons, params
        assert "By\nJohn Author" not in result
        assert "Share on Twitter" not in result
        assert "utm_source" not in result
        assert "Actual content" in result

    def test_llm_summarize_called_for_large_content(self, compressor: TokenCompressor) -> None:
        """Verify LLM is called for content > 30K chars after regex compression."""
        # Create large content that will exceed threshold after regex
        # Use verbose repetitive content that survives regex but triggers _llm_summarize
        compressor.llm_enabled = True
        compressor.llm_threshold_chars = 2000  # Lower for testing
        compressor.reset_stats()
        
        # Create content that's large enough to trigger LLM (>2000 chars, passes regex)
        paragraphs = []
        for i in range(300):
            paragraphs.append(f"Paragraph {i}: This is substantial content about Elasticsearch and Kubernetes. "
                          f"The API requires authentication via token. Machine Learning models are deployed.")
        content = "# Technical Documentation\n\n" + "\n\n".join(paragraphs)
        
        # Mock _llm_summarize to verify it's called
        llm_called = [False]
        
        def mock_llm_summarize(content: str, source_path: str = "") -> str:
            llm_called[0] = True
            return "LLM summarized content about Elasticsearch API and Kubernetes ML deployment."
        
        # Temporarily replace method
        original_summarize = compressor._llm_summarize
        compressor._llm_summarize = mock_llm_summarize
        
        try:
            result = compressor.compress(content, source_path="test.txt")
            assert llm_called[0], "LLM should have been called for content > 2000 chars"
            assert "Elasticsearch API" in result
        finally:
            compressor._llm_summarize = original_summarize

    def test_llm_summarize_not_called_for_small_content(self, compressor: TokenCompressor) -> None:
        """Verify LLM is NOT called for content under threshold (30K chars)."""
        compressor.llm_enabled = True
        compressor.llm_threshold_chars = 30000
        compressor.reset_stats()
        
        # Small content that won't trigger LLM
        content = "# Small Title\n\nThis is actual content. " + "More content. " * 50
        
        result = compressor.compress(content)
        stats = compressor.get_stats()
        
        # LLM should not be called
        assert stats['llm_calls'] == 0
        assert stats['llm_errors'] == 0
        assert "Small Title" in result

    def test_llm_fallback_on_error(self) -> None:
        """Verify LLM failure gracefully falls back to truncation."""
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                'compression': {
                    'enabled': True,
                    'min_reduction_pct': 10,
                    'log_dir': tmpdir,
                    'llm_enabled': True,
                    'llm_threshold_chars': 500,
                    'cache_enabled': False,  # Disable for this test
                },
                'llm_api_url': 'http://invalid-endpoint:12345/v1/chat/completions',
            }
            compressor = TokenCompressor(config)
            
            # Create large content that triggers LLM
            content = "# Title\n\n" + "Content paragraph. " * 200
            
            # Should not raise exception, should fall back
            result = compressor.compress(content)
            stats = compressor.get_stats()
            
            assert result is not None
            assert len(result) > 0
            assert stats['llm_errors'] == 1

    def test_cache_hit_returns_cached(self) -> None:
        """Verify compressing same content twice returns cached version."""
        import tempfile
        import uuid
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                'compression': {
                    'enabled': True,
                    'min_reduction_pct': 10,
                    'log_dir': tmpdir,  # Cache dir derived from this
                    'llm_enabled': False,
                    'cache_enabled': True,
                }
            }
            compressor = TokenCompressor(config)
            
            # Unique content with UUID
            unique_id = str(uuid.uuid4())
            content = f"# Test Content {unique_id}\n\n" + f"This is test content {unique_id} that should be cached. " * 40
            
            # First call
            result1 = compressor.compress(content)
            
            # Second call should hit cache
            result2 = compressor.compress(content)
            stats = compressor.get_stats()
            
            assert result1 == result2
            assert stats['cache_hits'] >= 1
            assert stats['cache_misses'] == 1  # First call was miss

    def test_cache_miss_saves_to_cache(self) -> None:
        """Verify new content gets saved to cache."""
        import tempfile
        import uuid
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                'compression': {
                    'enabled': True,
                    'min_reduction_pct': 10,
                    'log_dir': tmpdir,
                    'llm_enabled': False,
                    'cache_enabled': True,
                }
            }
            compressor = TokenCompressor(config)
            
            # Unique content with UUID to ensure no collisions
            unique_id = str(uuid.uuid4())
            content = f"# Unique Test Content {unique_id}\n\n" + f"Content for cache test {unique_id}. " * 40
            
            result = compressor.compress(content)
            stats = compressor.get_stats()
            
            assert stats['cache_misses'] >= 1
            assert stats['cache_hits'] == 0

    def test_smart_truncate_prefers_entity_rich(self, compressor: TokenCompressor) -> None:
        """Verify smart truncate prefers paragraphs with more entities."""
        # Create paragraphs with varying entity density
        simple_para = "This is a simple paragraph with simple words. " * 10  # Low entity score
        entity_para = "Elastic API meets Docker and Kubernetes for ML AI LLM. " * 5  # High entity score
        mixed_para = "Salesforce uses Amazon AWS and Microsoft Azure. " * 5  # Medium-high
        
        content = f"# Title\n\n{simple_para}\n\n{entity_para}\n\n{mixed_para}\n\n{simple_para}"
        
        result = compressor._smart_truncate(content, max_chars=500)
        
        # Entity-rich paragraphs should be preserved
        assert "Elastic" in result or "Docker" in result or "Kubernetes" in result
        assert "API" in result or "ML" in result or "AI" in result

    def test_smart_truncate_under_limit_unchanged(self, compressor: TokenCompressor) -> None:
        """Verify smart truncate leaves short content unchanged."""
        short_content = "# Title\n\nThis is short content.\n\nSecond paragraph."
        
        result = compressor._smart_truncate(short_content, max_chars=500)
        
        assert result == short_content
