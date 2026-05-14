import asyncio

from helpers import runtime


def test_call_development_function_falls_back_to_local_when_rfc_password_missing(monkeypatch):
    monkeypatch.setattr(runtime, "args", {}, raising=False)
    monkeypatch.delenv("RFC_PASSWORD", raising=False)

    def local_func(value):
        return value + 1

    result = asyncio.run(runtime.call_development_function(local_func, 41))
    assert result == 42


def test_call_development_function_falls_back_to_async_local_when_rfc_password_missing(monkeypatch):
    monkeypatch.setattr(runtime, "args", {}, raising=False)
    monkeypatch.delenv("RFC_PASSWORD", raising=False)

    async def local_func(value):
        return value + 1

    result = asyncio.run(runtime.call_development_function(local_func, 41))
    assert result == 42
