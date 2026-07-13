from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _legacy_id(display_path: str) -> str:
    normalized = display_path.rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _new_id(display_path: str, context_id: str = "") -> str:
    normalized = display_path.rstrip("/")
    if context_id:
        composite = f"{normalized}:{context_id}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()[:32]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


class TestPerChatWorkspaceIsolation:
    DISPLAY_PATH = "/a0/usr/workdir"
    CTX_A = "chat-abc123"
    CTX_B = "chat-xyz789"

    def test_different_contexts_produce_different_ids(self):
        assert _new_id(self.DISPLAY_PATH, self.CTX_A) != _new_id(self.DISPLAY_PATH, self.CTX_B)

    def test_per_chat_id_differs_from_shared(self):
        shared = _new_id(self.DISPLAY_PATH, "")
        assert _new_id(self.DISPLAY_PATH, self.CTX_A) != shared
        assert _new_id(self.DISPLAY_PATH, self.CTX_B) != shared

    def test_backward_compatibility_empty_context(self):
        assert _new_id(self.DISPLAY_PATH, "") == _legacy_id(self.DISPLAY_PATH)

    def test_deterministic_ids(self):
        id1 = _new_id(self.DISPLAY_PATH, self.CTX_A)
        id2 = _new_id(self.DISPLAY_PATH, self.CTX_A)
        assert id1 == id2

    def test_different_paths_with_same_context(self):
        assert _new_id("/a0/usr/workdir", self.CTX_A) != _new_id("/a0/usr/projects/myproject", self.CTX_A)

    def test_three_concurrent_chats_all_isolated(self):
        ctx_c = "chat-lmn456"
        id_a = _new_id(self.DISPLAY_PATH, self.CTX_A)
        id_b = _new_id(self.DISPLAY_PATH, self.CTX_B)
        id_c = _new_id(self.DISPLAY_PATH, ctx_c)
        assert len({id_a, id_b, id_c}) == 3

    def test_legacy_workspace_id_matches_current_shared(self):
        expected = "975eb797fc68061b3d6b10289d5e8eba"
        assert _new_id("/a0/usr/workdir", "") == expected
        assert _legacy_id("/a0/usr/workdir") == expected
