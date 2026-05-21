"""Token compression module for KG ingestion pipeline.

Compresses content before LLM extraction to reduce token usage by stripping
boilerplate, social sharing noise, and other non-content elements.
"""
import hashlib
import json
import os
import re
import time
from typing import Dict, List, Optional, Any, Pattern
from urllib.parse import urlparse, urlunparse
import logging
import urllib.request

logger = logging.getLogger(__name__)


class TokenCompressor:
    """Compress content before LLM extraction to reduce token usage."""

    # Pre-compiled regex patterns - handle leading whitespace (indented strings)
    _SHARE_BUTTONS: Pattern = re.compile(
        r'^\s*Share on (Twitter|X|Facebook|LinkedIn|Email)\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    _SHARE_STANDALONE: Pattern = re.compile(
        r'^\s*Share\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    # Handle "By" followed by author name on same line OR next line
    _AUTHOR_BYLINE: Pattern = re.compile(
        r'^\s*By\s+\w[\w\s-]+\w\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    # Handle multi-line "By\nName" pattern
    _AUTHOR_BYLINE_MULTILINE: Pattern = re.compile(
        r'^\s*By\s*\n\s*\w[\w\s-]+\w\s*$',
        re.MULTILINE | re.IGNORECASE,
    )
    _READING_TIME: Pattern = re.compile(
        r'^\s*\d+\s*min(?:ute)?(?:s)?\s*read\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    _CATEGORY_DATE_HEADERS: Pattern = re.compile(
        r'^\s*\d{1,2}\s+(January|February|March|April|May|June|'
        r'July|August|September|October|November|December)\s+\d{4}\s*'
        r'(?:\n+\s*[A-Z][a-z]+)*',
        re.MULTILINE | re.IGNORECASE,
    )
    _SOCIAL_URLS: Pattern = re.compile(
        r'^\s*https?://(?:twitter\.com|x\.com|facebook\.com|linkedin\.com)/\S+$',
        re.IGNORECASE | re.MULTILINE,
    )
    _REPEATED_TITLES: Pattern = re.compile(
        r'^(\s*#+)\s+(.+?)\s*$\n+\s*\1\s+\2\s*$',
        re.MULTILINE,
    )

    # URL tracking parameters to strip
    _UTM_PARAMS: List[str] = [
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
        'utm_content', 'fbclid', 'gclid', 'twitterclid', 'li_fat_id',
        'mc_cid', 'mc_eid', 'ref', 'referral', 'referrer', 'source',
        'track', 'clickid', 'affiliate', 'aff', 'partner', 'cid',
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize with optional config overrides.

        Args:
            config: Configuration dictionary with compression settings.
        """
        self.config = config or {}
        comp_config = self.config.get('compression', {})
        self.enabled = comp_config.get('enabled', True)
        self.min_reduction_pct = comp_config.get('min_reduction_pct', 10)
        self.llm_enabled = comp_config.get('llm_enabled', True)
        self.llm_threshold_chars = comp_config.get('llm_threshold_chars', 30000)
        self.llm_max_output_tokens = comp_config.get('llm_max_output_tokens', 4096)
        self.cache_enabled = comp_config.get('cache_enabled', True)
        self.cache_ttl_days = comp_config.get('cache_ttl_days', 7)
        
        # LLM endpoint configuration
        self.llm_api_url = self.config.get(
            'llm_api_url', 'http://192.168.1.250:11435/v1/chat/completions'
        )
        self.llm_model = self.config.get(
            'llm_model', 'Qwen3.6-35B-A3B-MTP-UD-Q5_K_XL.gguf'
        )
        
        # Initialize cache directory
        self._cache_dir = os.path.join(
            os.path.dirname(comp_config.get('log_dir', '/a0/usr/workdir/logs')),
            'cache', 'kg_compression'
        )
        if self.cache_enabled:
            os.makedirs(self._cache_dir, exist_ok=True)
        
        self.stats: Dict[str, Any] = {
            'total_calls': 0,
            'total_original_chars': 0,
            'total_compressed_chars': 0,
            'total_reduction_pct': 0.0,
            'llm_calls': 0,
            'llm_errors': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'warnings': [],
        }
        logger.info(
            f"TokenCompressor initialized (enabled={self.enabled}, "
            f"llm_enabled={self.llm_enabled}, cache_enabled={self.cache_enabled})"
        )

    def compress(self, content: str, source_path: str = "") -> str:
        """Apply all compression steps to content.

        Args:
            content: Raw content string to compress.
            source_path: Source file path for context.

        Returns:
            Compressed content string.
        """
        if not self.enabled:
            return content

        if not content or len(content) < 200:
            return content

        original_size = len(content)
        
        # Check cache first
        if self.cache_enabled:
            cached = self._check_cache(content)
            if cached is not None:
                self.stats['cache_hits'] += 1
                logger.debug(f"Cache hit for content (original {original_size:,} chars)")
                return cached
            self.stats['cache_misses'] += 1

        self.stats['total_calls'] += 1
        self.stats['total_original_chars'] += original_size

        # Step 1: Regex compression (fast, always applied)
        result = self._strip_boilerplate(content)
        result = self._collapse_whitespace(result)
        result = self._remove_duplicate_lines(result)
        result = self._clean_urls(result)
        result = self._strip_non_ascii(result)

        # Step 2: LLM summarization (only for large files)
        if self.llm_enabled and len(result) > self.llm_threshold_chars:
            result = self._llm_summarize(result, source_path)

        # Step 3: Smart truncation (preserve entity-rich sections)
        if len(result) > self.llm_threshold_chars:
            result = self._smart_truncate(result)

        compressed_size = len(result)
        self.stats['total_compressed_chars'] += compressed_size

        reduction = original_size - compressed_size
        pct = (reduction / original_size) * 100 if original_size > 0 else 0

        logger.info(
            f"Compressed {original_size:,} → {compressed_size:,} chars "
            f"({pct:.1f}% reduction)"
        )

        if pct < self.min_reduction_pct:
            self.stats['warnings'].append(
                f"Low compression: {pct:.1f}% < {self.min_reduction_pct}% target"
            )
            logger.warning(
                f"Compression below threshold: {pct:.1f}% < "
                f"{self.min_reduction_pct}%"
            )

        self.stats['total_reduction_pct'] = (
            (self.stats['total_original_chars']
             - self.stats['total_compressed_chars'])
            / self.stats['total_original_chars'] * 100
            if self.stats['total_original_chars'] > 0 else 0
        )

        # Save to cache
        if self.cache_enabled:
            self._save_to_cache(content, result)

        return result

    def _llm_summarize(self, content: str, source_path: str = "") -> str:
        """Use LLM to summarize large content while preserving entity information.

        Only called for content >30K chars after regex compression.
        Sends content to Mediaserver Qwen3.6-35B for intelligent summarization.

        Args:
            content: Pre-compressed (regex already applied) content
            source_path: Source file path for context

        Returns:
            Summarized content preserving all entity information
        """
        if not self.llm_enabled:
            return content

        # Send first 20K chars (enough context for summarization)
        content_to_summarize = content[:20000]
        
        prompt = (
            "Summarize the following content for knowledge extraction. "
            "Preserve ALL named entities (people, organizations, products, "
            "technologies, concepts, locations). Remove repetitive descriptions, "
            "examples, and filler. Keep the essential information and relationships. "
            "Output a concise summary:\n\n"
            f"{content_to_summarize}"
        )

        payload = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.llm_max_output_tokens,
            "temperature": 0.1,
        }

        try:
            req = urllib.request.Request(
                self.llm_api_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                },
                method='POST',
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                response_data = json.loads(response.read().decode('utf-8'))
                message = response_data.get('choices', [{}])[0].get('message', {})
                summary = message.get('content', '')
                
                # Fallback: Qwen models may put reasoning in reasoning_content field
                if not summary or len(summary) < 50:
                    summary = message.get('reasoning_content', '')
                
                if summary and len(summary) > 100:
                    self.stats['llm_calls'] += 1
                    logger.info(
                        f"LLM summarization: {len(content):,} → {len(summary):,} chars"
                    )
                    return summary
                else:
                    logger.warning("LLM returned empty or too short summary")
                    return content
                    
        except urllib.error.HTTPError as e:
            self.stats['llm_errors'] += 1
            logger.error(f"LLM HTTP error: {e.code} - {e.read().decode('utf-8', errors='ignore')}")
            return content
        except urllib.error.URLError as e:
            self.stats['llm_errors'] += 1
            logger.error(f"LLM URL error: {e.reason}")
            return content
        except Exception as e:
            self.stats['llm_errors'] += 1
            logger.error(f"LLM summarization failed: {e}")
            return content

    def _get_cache_path(self, content_hash: str) -> str:
        """Get cache file path for a content hash."""
        return os.path.join(self._cache_dir, f"{content_hash}.compressed")

    def _check_cache(self, content: str) -> Optional[str]:
        """Check if compressed version exists in cache.
        
        Args:
            content: Original content to check cache for.
            
        Returns:
            Cached compressed content if found and not expired, else None.
        """
        if not self.cache_enabled:
            return None
            
        content_hash = hashlib.md5(content.encode()).hexdigest()
        cache_path = self._get_cache_path(content_hash)
        
        if os.path.exists(cache_path):
            # Check if cache is less than configured TTL
            ttl_seconds = self.cache_ttl_days * 86400
            if time.time() - os.path.getmtime(cache_path) < ttl_seconds:
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"Failed to read cache: {e}")
        return None

    def _save_to_cache(self, content: str, compressed: str) -> None:
        """Save compressed content to cache.
        
        Args:
            content: Original content (for hash generation)
            compressed: Compressed content to cache
        """
        if not self.cache_enabled:
            return
            
        content_hash = hashlib.md5(content.encode()).hexdigest()
        cache_path = self._get_cache_path(content_hash)
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(compressed)
        except Exception as e:
            logger.warning(f"Failed to write cache: {e}")

    def _smart_truncate(self, content: str, max_chars: int = 30000) -> str:
        """Truncate content preferring sections with more entity signals.
        
        Instead of cutting at max_chars, prefer sections with more entity signals
        (capitalized words, technical terms, product names).
        
        Args:
            content: Content to truncate
            max_chars: Maximum characters to keep
            
        Returns:
            Truncated content with entity-rich sections prioritized
        """
        if len(content) <= max_chars:
            return content

        # Split into paragraphs
        paragraphs = content.split('\n\n')

        # Score each paragraph by entity signals
        def entity_score(p: str) -> float:
            score = 0.0
            # Capitalized words (likely entities)
            caps = len(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', p))
            score += caps * 0.5
            # Technical terms
            tech = len(re.findall(
                r'\b(?:API|SDK|CLI|HTTP|REST|SQL|NoSQL|ML|AI|LLM|SaaS|'
                r'IaaS|Docker|Kubernetes)\b', p, re.IGNORECASE
            ))
            score += tech * 2.0
            # Length (prefer substance)
            score += min(len(p) / 100, 5.0)
            return score

        # Sort by score descending, take top paragraphs that fit
        scored = [(p, entity_score(p)) for p in paragraphs]
        scored.sort(key=lambda x: x[1], reverse=True)

        result: List[str] = []
        total = 0
        for p, score in scored:
            if total + len(p) + 2 <= max_chars:
                result.append(p)
                total += len(p) + 2

        return '\n\n'.join(result)

    def _strip_boilerplate(self, content: str) -> str:
        """Remove known boilerplate patterns.

        Args:
            content: Content to process.

        Returns:
            Content with boilerplate removed.
        """
        # Remove share buttons (line by line)
        content = self._SHARE_BUTTONS.sub('', content)
        content = self._SHARE_STANDALONE.sub('', content)

        # Remove author bylines (handle single line and multi-line)
        content = self._AUTHOR_BYLINE_MULTILINE.sub('', content)
        content = self._AUTHOR_BYLINE.sub('', content)

        # Remove reading time indicators
        content = self._READING_TIME.sub('', content)

        # Remove date+category headers
        content = self._CATEGORY_DATE_HEADERS.sub('', content)

        # Remove standalone social URLs
        content = self._SOCIAL_URLS.sub('', content)

        # Remove repeated titles (title appears in both heading and subheading)
        content = self._REPEATED_TITLES.sub(r'\1 \2', content)

        return content

    def _collapse_whitespace(self, content: str) -> str:
        """Collapse multiple blank lines to max 2 (paragraph break).

        Args:
            content: Content to process.

        Returns:
            Content with collapsed whitespace.
        """
        # Replace 3+ newlines with 2 (paragraph break preserves structure)
        content = re.sub(r'\n{3,}', '\n\n', content)
        # Replace tabs with spaces
        content = re.sub(r'\t+', ' ', content)
        # Collapse multiple spaces (but keep newlines)
        content = re.sub(r' +', ' ', content)
        # Remove trailing whitespace per line
        content = re.sub(r' +$', '', content, flags=re.MULTILINE)
        # Collapse any remaining multiple blank lines
        content = re.sub(r'\n\n+', '\n\n', content)
        return content

    def _remove_duplicate_lines(self, content: str) -> str:
        """Remove consecutive duplicate lines.

        Args:
            content: Content to process.

        Returns:
            Content with duplicate lines removed.
        """
        lines = content.split('\n')
        result: List[str] = []
        prev_line = None

        for line in lines:
            stripped = line.strip()
            if stripped == prev_line and stripped:
                continue
            result.append(line)
            prev_line = stripped

        return '\n'.join(result)

    def _clean_urls(self, content: str) -> str:
        """Remove tracking query parameters from URLs.

        Args:
            content: Content to process.

        Returns:
            Content with cleaned URLs.
        """
        def clean_url_match(match: re.Match) -> str:
            url = match.group(0)
            try:
                parsed = urlparse(url)
                if parsed.query:
                    params: List[str] = []
                    for param in parsed.query.split('&'):
                        if '=' in param:
                            key = param.split('=')[0]
                            if key.lower() not in self._UTM_PARAMS:
                                params.append(param)
                        else:
                            params.append(param)
                    new_query = '&'.join(params) if params else ''
                    parsed = parsed._replace(query=new_query)
                    return urlunparse(parsed) if new_query else parsed.path
                return url
            except Exception as e:
                logger.debug(f"URL cleaning failed for {url}: {e}")
                return url

        # Find URLs and clean them
        url_pattern = r'https?://[^\s<>"\)`\]\n]+'
        return re.sub(url_pattern, clean_url_match, content)

    def _strip_non_ascii(self, content: str) -> str:
        """Remove non-ASCII characters except CJK, emojis, and common symbols.

        Args:
            content: Content to process.

        Returns:
            Content with non-ASCII cleaned.
        """
        result: List[str] = []
        for char in content:
            code = ord(char)
            # ASCII
            if code < 128:
                result.append(char)
            # CJK Unified Ideographs, Extensions
            elif 0x4E00 <= code <= 0x9FFF:
                result.append(char)
            # CJK Extension A
            elif 0x3400 <= code <= 0x4DBF:
                result.append(char)
            # CJK Extension B-F
            elif 0x20000 <= code <= 0x2EBFF:
                result.append(char)
            # Hiragana, Katakana
            elif 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
                result.append(char)
            # Hangul
            elif 0xAC00 <= code <= 0xD7AF:
                result.append(char)
            # Emojis (common range)
            elif 0x1F300 <= code <= 0x1F9FF:
                result.append(char)
            # Replace control characters with space
            elif code < 0x20:
                result.append(' ')
            # Skip other non-ASCII (likely noise)
            else:
                continue

        return ''.join(result)

    def get_stats(self) -> Dict[str, Any]:
        """Get compression statistics.

        Returns:
            Dictionary with compression statistics.
        """
        return {
            'total_calls': self.stats['total_calls'],
            'total_original_chars': self.stats['total_original_chars'],
            'total_compressed_chars': self.stats['total_compressed_chars'],
            'reduction_percentage': round(self.stats['total_reduction_pct'], 2),
            'average_reduction_per_call': round(
                self.stats['total_reduction_pct'] / self.stats['total_calls'],
                2
            ) if self.stats['total_calls'] > 0 else 0,
            'llm_calls': self.stats['llm_calls'],
            'llm_errors': self.stats['llm_errors'],
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'warnings': self.stats['warnings'][:10],  # Limit to 10
        }

    def reset_stats(self) -> None:
        """Reset compression statistics."""
        self.stats = {
            'total_calls': 0,
            'total_original_chars': 0,
            'total_compressed_chars': 0,
            'total_reduction_pct': 0.0,
            'llm_calls': 0,
            'llm_errors': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'warnings': [],
        }
