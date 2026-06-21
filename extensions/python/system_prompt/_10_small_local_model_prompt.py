import re
from typing import Any
from urllib.parse import urlparse

from helpers.extension import Extension, extensible
from agent import Agent, LoopData


LOCAL_PROVIDER_IDS = {"ollama", "lm_studio"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
THINKING_MODEL_MARKERS = (
    "qwen3",
    "qwen-3",
    "qwq",
    "deepseek-r1",
    "deepseek_r1",
    "gpt-oss",
    "gemma4",
    "gemma-4",
)
SMALL_LOCAL_MAX_B = 14.0
MODEL_SIZE_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)[-_ ]?b(?![a-z])", re.IGNORECASE)


class SmallLocalModelPrompt(Extension):
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        if prompt:
            system_prompt.append(prompt)


@extensible
async def build_prompt(agent: Agent) -> str:
    try:
        from plugins._model_config.helpers.model_config import get_chat_model_config

        chat_cfg = get_chat_model_config(agent)
    except Exception:
        return ""

    if should_include_small_local_prompt(chat_cfg):
        return agent.read_prompt("agent.system.main.small_local_model.md")
    return ""


def should_include_small_local_prompt(chat_cfg: dict[str, Any] | None) -> bool:
    if not isinstance(chat_cfg, dict):
        return False

    provider = str(chat_cfg.get("provider") or "").lower().strip()
    name = str(chat_cfg.get("name") or "").lower().strip()
    api_base = str(chat_cfg.get("api_base") or "").lower().strip()

    is_local = provider in LOCAL_PROVIDER_IDS or _is_local_api_base(api_base)
    if not is_local:
        return False

    if any(marker in name for marker in THINKING_MODEL_MARKERS):
        return True

    size_b = _model_size_billions(name)
    return size_b is not None and size_b <= SMALL_LOCAL_MAX_B


def _is_local_api_base(api_base: str) -> bool:
    if not api_base:
        return False
    parsed = urlparse(api_base if "://" in api_base else f"http://{api_base}")
    host = (parsed.hostname or "").lower()
    return host in LOCAL_HOSTS


def _model_size_billions(model_name: str) -> float | None:
    match = MODEL_SIZE_RE.search(model_name)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None
