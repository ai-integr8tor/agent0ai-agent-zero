import asyncio
import types

import pytest

from plugins._memory.helpers import memory_consolidation


@pytest.mark.asyncio
async def test_memory_consolidation_timeout_inserts_directly(monkeypatch):
    inserted = []
    updates = []

    class FakeMemory:
        async def insert_text(self, text, metadata):
            inserted.append((text, metadata))
            return "memory-1"

    async def fake_memory_get(agent):
        return FakeMemory()

    async def never_finishes(self, new_memory, area, metadata, log_item=None):
        await asyncio.sleep(10)

    monkeypatch.setattr(memory_consolidation.Memory, "get", fake_memory_get)
    monkeypatch.setattr(
        memory_consolidation.MemoryConsolidator,
        "_process_memory_with_consolidation",
        never_finishes,
    )

    consolidator = memory_consolidation.MemoryConsolidator(
        agent=object(),
        config=memory_consolidation.ConsolidationConfig(
            processing_timeout_seconds=0.01
        ),
    )
    result = await consolidator.process_new_memory(
        "important finding",
        "solutions",
        {"source": "test"},
        types.SimpleNamespace(update=lambda **kwargs: updates.append(kwargs)),
    )

    assert result == {"success": True, "memory_ids": ["memory-1"]}
    assert inserted[0][0] == "important finding"
    assert inserted[0][1]["source"] == "test"
    assert inserted[0][1]["timestamp"]
    assert updates[-1]["consolidation_action"] == "timeout_direct_insert"
