"""Regression tests for helpers.git._validate_git_url URL allowlist.

Codex review on PR #1601 (commit ce38afa) flagged that an early version of
_SAFE_URL_RE only accepted the literal `git@` SSH username, which would
reject valid Git remotes that use a different SSH user (e.g. self-hosted
or enterprise repositories using `alice@host:org/repo.git`).

Commit 49a0ff9 loosened the regex to allow any safe username class.
These tests guard against a regression of that fix.
"""

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
      sys.path.insert(0, str(PROJECT_ROOT))

# Stub giturlparse so importing helpers.git does not require the optional dep.
sys.modules.setdefault(
      "giturlparse",
      types.SimpleNamespace(
                parse=lambda *args, **kwargs: types.SimpleNamespace(
                              owner="",
                              repo="",
                              name="",
                              valid=False,
                )
      ),
)

from helpers import git as git_helpers  # noqa: E402


@pytest.mark.parametrize(
      "url",
      [
                # Non-git SSH usernames - the case Codex flagged.
          "alice@host:org/repo.git",
                "ssh://alice@host/org/repo.git",
                "ssh://alice@host:2222/org/repo.git",
                # Original git@ form must still work.
                "git@github.com:agent0ai/agent-zero.git",
                "ssh://git@github.com/agent0ai/agent-zero.git",
                # https form for completeness.
                "https://github.com/agent0ai/agent-zero.git",
      ],
)
def test_validate_git_url_accepts_safe_urls(url):
      """_validate_git_url must accept SSH URLs with arbitrary safe usernames."""
      git_helpers._validate_git_url(url)


@pytest.mark.parametrize(
      "url",
      [
                "",
                "file:///etc/passwd",
                "https://example.com/repo.git; rm -rf /",
                "ssh://user@host/path`whoami`",
      ],
)
def test_validate_git_url_rejects_unsafe_urls(url):
      """_validate_git_url must reject empty, non-http(s)/ssh, or shell-meta URLs."""
      with pytest.raises(ValueError):
                git_helpers._validate_git_url(url)
        
