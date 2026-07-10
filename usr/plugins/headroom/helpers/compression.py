from __future__ import annotations

from dataclasses import dataclass
import inspect
import os
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from helpers import tokens


@dataclass
class HeadroomStats:
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 0.0
    transforms: list[str] | None = None


class HeadroomUnavailable(RuntimeError):
    pass


def compress_langchain_messages(
    messages: list[BaseMessage],
    *,
    model_name: str,
    min_total_tokens: int,
    compress_user_messages: bool = True,
    protect_recent: int = 4,
    target_ratio: float | None = 0.35,
    min_tokens_to_compress: int = 250,
    kompress_model: str | None = "disabled",
    clear_proxy_for_headroom: bool = True,
    skip_non_text_messages: bool = True,
) -> tuple[list[BaseMessage], HeadroomStats | None]:
    if not messages:
        return messages, None

    total_tokens = tokens.approximate_tokens(_messages_text(messages))
    if total_tokens < max(0, int(min_total_tokens or 0)):
        return messages, None

    payload = _to_headroom_messages(messages, skip_non_text_messages=skip_non_text_messages)
    if payload is None:
        return messages, None

    try:
        from headroom import compress
    except ImportError as exc:
        raise HeadroomUnavailable("Python package 'headroom-ai' is not installed") from exc

    compress_config = None
    try:
        from headroom import CompressConfig

        config_kwargs = {
            "compress_user_messages": compress_user_messages,
            "compress_system_messages": True,
            "protect_recent": max(0, int(protect_recent or 0)),
            "target_ratio": target_ratio,
            "min_tokens_to_compress": max(0, int(min_tokens_to_compress or 0)),
            "kompress_model": kompress_model or None,
        }
        supported = set(inspect.signature(CompressConfig).parameters)
        compress_config = CompressConfig(
            **{key: value for key, value in config_kwargs.items() if key in supported}
        )
    except Exception:
        compress_config = None

    previous_proxy_env = _clear_proxy_env() if clear_proxy_for_headroom else {}
    try:
        result = compress(payload, model=model_name, config=compress_config)
    finally:
        _restore_env(previous_proxy_env)
    compressed_payload = getattr(result, "messages", None)
    if not isinstance(compressed_payload, list):
        return messages, None

    compressed_messages = _from_headroom_messages(compressed_payload, fallback=messages)
    stats = HeadroomStats(
        tokens_before=int(getattr(result, "tokens_before", total_tokens) or total_tokens),
        tokens_after=int(
            getattr(
                result,
                "tokens_after",
                tokens.approximate_tokens(_messages_text(compressed_messages)),
            )
            or 0
        ),
        tokens_saved=int(getattr(result, "tokens_saved", 0) or 0),
        compression_ratio=float(getattr(result, "compression_ratio", 0.0) or 0.0),
        transforms=list(getattr(result, "transforms_applied", []) or []),
    )
    return compressed_messages, stats


def _messages_text(messages: list[BaseMessage]) -> str:
    return "\n\n".join(str(message.content) for message in messages)


def _to_headroom_messages(
    messages: list[BaseMessage],
    *,
    skip_non_text_messages: bool,
) -> list[dict[str, str]] | None:
    payload: list[dict[str, str]] = []
    role_map = {
        "system": "system",
        "human": "user",
        "ai": "assistant",
    }

    for message in messages:
        if not isinstance(message.content, str):
            if skip_non_text_messages:
                return None
            content = str(message.content)
        else:
            content = message.content

        role = role_map.get(message.type)
        if not role:
            return None
        payload.append({"role": role, "content": content})

    return payload


def _from_headroom_messages(
    payload: list[dict[str, Any]],
    *,
    fallback: list[BaseMessage],
) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return fallback
        role = str(item.get("role") or "")
        content = item.get("content", "")
        if not isinstance(content, str):
            content = str(content)

        original = fallback[index] if index < len(fallback) else None
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "user":
            result.append(HumanMessage(content=content))
        elif isinstance(original, BaseMessage):
            result.append(type(original)(content=content))
        else:
            return fallback

    return result or fallback


def _clear_proxy_env() -> dict[str, str | None]:
    names = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
