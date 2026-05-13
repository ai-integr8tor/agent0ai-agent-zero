"""Regression tests for GPT-style null tool_calls normalization and the
chat-completion temperature=1 default.

Motivation: gpt-5.5 (and certain proxies) return ``tool_calls: null`` on turns
where the model did not invoke a tool. Downstream Agent Zero / LangChain code
paths iterate ``tool_calls`` directly and crash with
``TypeError: 'NoneType' object is not iterable`` when this happens. We normalize
``tool_calls: None`` to ``[]`` at the LiteLLM response boundary inside
``models._parse_chunk``, and we also default chat completions to
``temperature=1`` to keep tool-calling output deterministic.
"""

import os
import sys
import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402  (sys.path mutated above)


class _Obj:
    """Tiny attribute-style object to mimic pydantic-shaped LiteLLM responses."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_normalize_dict_message_null_tool_calls():
    chunk = {
        "choices": [
            {
                "message": {
                    "content": "hello world",
                    "tool_calls": None,
                }
            }
        ]
    }
    models._normalize_tool_calls(chunk)
    assert chunk["choices"][0]["message"]["tool_calls"] == []

    parsed = models._parse_chunk(chunk)
    assert parsed["response_delta"] == "hello world"
    assert parsed["reasoning_delta"] == ""


def test_normalize_dict_delta_null_tool_calls_streaming():
    chunk = {
        "choices": [
            {
                "delta": {
                    "content": "streamed",
                    "tool_calls": None,
                }
            }
        ]
    }
    models._normalize_tool_calls(chunk)
    assert chunk["choices"][0]["delta"]["tool_calls"] == []

    parsed = models._parse_chunk(chunk)
    assert parsed["response_delta"] == "streamed"


def test_normalize_object_style_message_null_tool_calls():
    msg = _Obj(content="obj-style", tool_calls=None)
    chunk = _Obj(choices=[_Obj(message=msg, delta=None)])
    models._normalize_tool_calls(chunk)
    assert msg.tool_calls == []


def test_populated_tool_calls_are_preserved():
    populated = [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]
    chunk = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": populated,
                }
            }
        ]
    }
    models._normalize_tool_calls(chunk)
    assert chunk["choices"][0]["message"]["tool_calls"] is populated


def test_no_choices_is_safe():
    # Must not raise even on malformed input.
    models._normalize_tool_calls({})
    models._normalize_tool_calls({"choices": []})
    models._normalize_tool_calls(None)  # type: ignore[arg-type]


def test_chat_temperature_default_zero(monkeypatch):
    """_merge_provider_defaults must default chat temperature to 1 and respect overrides."""

    # Stub get_provider_config to a minimal dict so the function does not need real config.
    monkeypatch.setattr(
        models,
        "get_provider_config",
        lambda provider_type, provider: {"litellm_provider": provider},
    )
    # Stub get_api_key so no real keys are needed.
    monkeypatch.setattr(models, "get_api_key", lambda service: "None")
    # Stub global kwargs.
    fake_settings = types.SimpleNamespace(get=lambda key, default=None: {} if key == "litellm_global_kwargs" else default)
    monkeypatch.setattr(models.settings, "get_settings", lambda: fake_settings)

    # Default is enforced for chat
    _, kwargs = models._merge_provider_defaults("chat", "openai", {})
    assert kwargs["temperature"] == 1

    # Caller override is preserved
    _, kwargs = models._merge_provider_defaults("chat", "openai", {"temperature": 0.7})
    assert kwargs["temperature"] == 0.7

    # Embedding path is NOT forced to temperature=1
    _, kwargs = models._merge_provider_defaults("embedding", "openai", {})
    assert "temperature" not in kwargs
