from __future__ import annotations

from typing import Any

from helpers import plugins
from helpers.extension import Extension
from helpers.print_style import PrintStyle

from usr.plugins.headroom.helpers.compression import (
    HeadroomUnavailable,
    compress_langchain_messages,
)


class HeadroomCompressBeforeChatModel(Extension):
    async def execute(self, call_data: dict[str, Any] | None = None, **kwargs):
        if not self.agent or not call_data:
            return

        config = plugins.get_plugin_config("headroom", agent=self.agent) or {}
        if not config.get("enabled", True):
            return

        messages = call_data.get("messages")
        if not isinstance(messages, list):
            return

        model = call_data.get("model")
        model_name = str(config.get("model_name_override") or getattr(model, "model_name", "") or "")
        if not model_name:
            return

        try:
            compressed, stats = compress_langchain_messages(
                messages,
                model_name=model_name,
                min_total_tokens=int(config.get("min_total_tokens", 4000) or 0),
                compress_user_messages=bool(config.get("compress_user_messages", True)),
                protect_recent=int(config.get("protect_recent", 4) or 0),
                target_ratio=_optional_float(config.get("target_ratio", 0.35)),
                min_tokens_to_compress=int(config.get("min_tokens_to_compress", 250) or 0),
                kompress_model=str(config.get("kompress_model", "disabled") or ""),
                clear_proxy_for_headroom=bool(config.get("clear_proxy_for_headroom", True)),
                skip_non_text_messages=bool(config.get("skip_non_text_messages", True)),
            )
        except HeadroomUnavailable as exc:
            self._warn_once(str(exc), config)
            return
        except Exception as exc:
            PrintStyle.warning(f"Headroom compression skipped: {exc}")
            return

        if compressed is messages:
            return

        call_data["messages"] = compressed
        if stats and stats.tokens_saved > 0:
            self._record_stats(stats)
            if config.get("log_savings", True):
                transforms = ", ".join(stats.transforms or []) or "none"
                self.agent.context.log.log(
                    type="info",
                    heading="icon://compress Headroom compressed context",
                    content=(
                        f"Saved {stats.tokens_saved} tokens "
                        f"({stats.tokens_before} -> {stats.tokens_after}). "
                        f"Transforms: {transforms}"
                    ),
                )

    def _warn_once(self, message: str, config: dict[str, Any]) -> None:
        if not config.get("warn_missing_dependency", True):
            return
        key = "_headroom_missing_dependency_warned"
        if self.agent and not self.agent.context.get_data(key):
            self.agent.context.set_data(key, True)
            self.agent.context.log.log(
                type="warning",
                heading="icon://warning Headroom is not installed",
                content=message + ". Install 'headroom-ai' in the Agent Zero framework runtime.",
            )

    def _record_stats(self, stats) -> None:
        if not self.agent:
            return
        key = "_headroom_stats"
        current = self.agent.context.get_data(key) or {
            "calls": 0,
            "tokens_saved": 0,
            "tokens_before": 0,
            "tokens_after": 0,
        }
        current["calls"] += 1
        current["tokens_saved"] += stats.tokens_saved
        current["tokens_before"] += stats.tokens_before
        current["tokens_after"] += stats.tokens_after
        self.agent.context.set_data(key, current)


def _optional_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
