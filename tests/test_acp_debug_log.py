from __future__ import annotations

from helpers.acp.debug_log import DebugLog


def test_debug_log_bounded_oldest_to_newest_snapshot():
    log = DebugLog(max_records=2)

    log.system("one")
    log.system("two")
    log.system("three")

    snapshot = log.snapshot()
    assert [record["preview"] for record in snapshot] == ["two", "three"]
    assert all(set(record) == {"timestamp", "direction", "kind", "method", "id", "preview"} for record in snapshot)


def test_debug_log_masks_and_bounds_payload_preview():
    log = DebugLog(max_preview_chars=80, masker=lambda text: text.replace("secret-token", "***"))

    log.outbound({"jsonrpc": "2.0", "id": 7, "method": "example", "params": {"aaa_token": "secret-token", "padding": "x" * 100}})

    [record] = log.snapshot()
    assert record["direction"] == "outbound"
    assert record["kind"] == "request"
    assert record["method"] == "example"
    assert record["id"] == 7
    assert "secret-token" not in record["preview"]
    assert "***" in record["preview"]
    assert len(record["preview"]) <= 80


def test_debug_log_clear_removes_records():
    log = DebugLog()
    log.stderr("diagnostic")

    log.clear()

    assert log.snapshot() == []
