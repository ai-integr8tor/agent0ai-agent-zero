from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers.extract_tools import json_parse_dirty


def test_json_parse_dirty_sanitizes_common_llm_wrappers() -> None:
    payload = """```json
<invoke>discard this wrapper artifact</invoke>
functions.search:123
{"tool_name":"search","tool_args":{"query":"agent zero"}}
```"""

    assert json_parse_dirty(payload) == {
        "tool_name": "search",
        "tool_args": {"query": "agent zero"},
    }
