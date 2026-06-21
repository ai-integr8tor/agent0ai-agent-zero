import sys
import threading
import types
from pathlib import Path

import pytest
from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules["giturlparse"] = types.SimpleNamespace(parse=lambda *args, **kwargs: None)
sys.modules["whisper"] = types.SimpleNamespace(load_model=lambda *args, **kwargs: None)


class _DummyObserver:
    def __init__(self):
        self._alive = False

    def is_alive(self):
        return self._alive

    def start(self):
        self._alive = True

    def stop(self):
        self._alive = False

    def join(self, *args, **kwargs):
        return None

    def unschedule_all(self):
        return None

    def schedule(self, *args, **kwargs):
        return None


watchdog = types.ModuleType("watchdog")
watchdog.observers = types.SimpleNamespace(Observer=_DummyObserver)
watchdog.events = types.SimpleNamespace(FileSystemEventHandler=object)
sys.modules["watchdog"] = watchdog
sys.modules["watchdog.observers"] = watchdog.observers
sys.modules["watchdog.events"] = watchdog.events

from plugins._model_config.api.api_keys import ApiKeys
from plugins._model_config.extensions.python.banners import _20_missing_api_key as missing_key_banner
import models


def test_model_config_api_keys_can_be_cleared_via_backend(monkeypatch, tmp_path):
    from helpers import dotenv

    env_file = tmp_path / ".env"
    monkeypatch.setattr(dotenv, "get_dotenv_file_path", lambda: str(env_file))

    for key in ("API_KEY_OPENROUTER", "OPENROUTER_API_KEY", "OPENROUTER_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)

    handler = ApiKeys(Flask(__name__), threading.Lock())

    assert handler._set_keys({"keys": {"openrouter": "sk-test-openrouter"}}) == {"ok": True}
    assert models.get_api_key("openrouter") == "sk-test-openrouter"

    assert handler._set_keys({"keys": {"openrouter": ""}}) == {"ok": True}
    assert models.get_api_key("openrouter") == "None"
    assert handler._reveal_key({"provider": "openrouter"}) == {"ok": True, "value": ""}


@pytest.mark.asyncio
async def test_missing_api_key_banner_exposes_missing_providers(monkeypatch):
    from plugins._model_config.helpers import model_config

    fake = [{"model_type": "Chat Model", "provider": "openai"}]
    monkeypatch.setattr(model_config, "get_missing_api_key_providers", lambda: fake)

    banners = []
    await missing_key_banner.MissingApiKeyCheck(agent=None).execute(
        banners=banners, frontend_context={}
    )
    row = next(b for b in banners if b.get("id") == "missing-api-key")
    assert row.get("missing_providers") == fake


def test_model_config_frontend_tracks_inline_api_key_edits():
    store_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "model-config-store.js"
    api_keys_mixin_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "api-keys-mixin.js"
    composer_store_path = PROJECT_ROOT / "webui" / "components" / "chat" / "input" / "composer-banner-store.js"
    config_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "config.html"
    model_field_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "model-field.html"
    modal_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "api-keys.html"

    store_content = (
        store_path.read_text(encoding="utf-8")
        + "\n"
        + api_keys_mixin_path.read_text(encoding="utf-8")
    )
    composer_store_content = composer_store_path.read_text(encoding="utf-8")
    config_content = (
        config_path.read_text(encoding="utf-8")
        + "\n"
        + model_field_path.read_text(encoding="utf-8")
    )
    modal_content = modal_path.read_text(encoding="utf-8")

    assert "apiKeyDirty" in store_content
    assert "resetApiKeyDrafts()" in store_content
    assert "!provider || seen.has(provider) || !this.apiKeyDirty[provider]" in store_content
    assert "normalized[provider] = value.trim() ? value : '';" in store_content
    assert '"missing-api-key"' in composer_store_content
    assert 'callJsonApi("/banners"' in composer_store_content
    assert "/plugins/_model_config/missing_api_key_status" not in composer_store_content
    assert "$store.modelConfig.resetApiKeyDrafts();" in config_content
    assert '@input="$store.modelConfig.setApiKeyValue(_prov, $el.value)"' in config_content
    assert "persistAllDirtyApiKeys()" in modal_content
    assert "$store.modelConfig.resetApiKeyDrafts();" in modal_content


def test_model_config_snapshot_sync_only_adjusts_clean_loaded_configs():
    config_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "config.html"
    store_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "model-config-store.js"
    config_content = config_path.read_text(encoding="utf-8")
    store_content = store_path.read_text(encoding="utf-8")

    assert "x-effect" not in config_content
    assert "syncContextConfigFields(context, true)" in store_content
    assert "context.loadSettings = async" in store_content
    assert "context.settingsSnapshotJson === snapshotBeforeInit" in store_content


def test_model_switcher_frontend_renders_custom_overrides():
    switcher_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "switcher-mixin.js"
    refresh_extension_path = (
        PROJECT_ROOT
        / "plugins"
        / "_model_config"
        / "extensions"
        / "webui"
        / "apply_snapshot_before"
        / "refresh-switcher.js"
    )

    switcher_content = switcher_path.read_text(encoding="utf-8")
    refresh_extension_content = refresh_extension_path.read_text(encoding="utf-8")

    assert "function normalizeModelIdentity(value)" in switcher_content
    assert "formatModelIdentity(models.main)" in switcher_content
    assert "formatModelIdentity(models.utility)" in switcher_content
    assert "normalizeModelIdentity(o.chat || o)" in switcher_content
    assert "normalizeModelIdentity(o.utility)" in switcher_content
    assert "_model_config_override_revision" in refresh_extension_content
    assert "modelConfigStore.refreshSwitcher(contextId)" in refresh_extension_content


def test_model_override_notifies_state_sync(monkeypatch):
    from helpers import state_monitor_integration
    from plugins._model_config.api import model_override

    calls = []

    class FakeContext:
        id = "ctx-1"

        def __init__(self):
            self.output_data = {}

        def set_output_data(self, key, value):
            self.output_data[key] = value

    ctx = FakeContext()
    monkeypatch.setattr(
        state_monitor_integration,
        "mark_dirty_for_context",
        lambda context_id, *, reason=None: calls.append((context_id, reason)),
    )

    model_override._notify_model_override_changed(ctx)

    assert "_model_config_override_revision" in ctx.output_data
    assert calls == [("ctx-1", "model_config.model_override")]


def test_connector_model_switcher_notifies_state_sync(monkeypatch):
    from helpers import state_monitor_integration
    from plugins._a0_connector.api.v1 import model_switcher

    calls = []

    class FakeContext:
        def __init__(self):
            self.output_data = {}

        def set_output_data(self, key, value):
            self.output_data[key] = value

    ctx = FakeContext()
    monkeypatch.setattr(
        state_monitor_integration,
        "mark_dirty_for_context",
        lambda context_id, *, reason=None: calls.append((context_id, reason)),
    )

    model_switcher._notify_model_override_changed(ctx, "ctx-1")

    assert "_model_config_override_revision" in ctx.output_data
    assert calls == [("ctx-1", "a0_connector.model_switcher")]


def test_model_config_provider_switch_resets_custom_api_base():
    model_field_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "model-field.html"
    content = model_field_path.read_text(encoding="utf-8")
    select_start = content.index('<select x-model="model.provider"')
    select_end = content.index("</select>", select_start)
    provider_select = content[select_start:select_end]

    assert 'x-model="model.provider"' in provider_select
    assert '@change="model.api_base = \'\'"' in provider_select


def test_model_config_vision_toggle_is_outside_advanced_settings():
    model_field_path = PROJECT_ROOT / "plugins" / "_model_config" / "webui" / "model-field.html"
    content = model_field_path.read_text(encoding="utf-8")

    vision_start = content.index('<div class="field-title">Supports Vision</div>')
    advanced_start = content.index("<!-- Advanced Settings (collapsed by default) -->")
    max_embeds_start = content.index('<div class="field-title">Max embeds</div>')

    assert content.count('<div class="field-title">Supports Vision</div>') == 1
    assert vision_start < advanced_start
    assert advanced_start < max_embeds_start


def test_ollama_cloud_provider_config_requires_key_and_base_url():
    import yaml

    provider_path = PROJECT_ROOT / "conf/model_providers.yaml"
    provider_config = yaml.safe_load(provider_path.read_text(encoding="utf-8"))
    ollama_cloud = provider_config["chat"]["ollama_cloud"]

    assert ollama_cloud["name"] == "Ollama Cloud"
    assert ollama_cloud["kwargs"]["api_base"] == "https://ollama.com/v1"
    assert ollama_cloud["models_list"]["endpoint_url"] == "/models"
    assert "api_key_mode" not in ollama_cloud


def test_missing_api_key_banner_includes_auto_modal_metadata(monkeypatch):
    from plugins._model_config.helpers import model_config

    fake = [{"model_type": "Chat Model", "provider": "openai"}]
    monkeypatch.setattr(model_config, "get_missing_api_key_providers", lambda: fake)

    async def run():
        banners = []
        await missing_key_banner.MissingApiKeyCheck(agent=None).execute(
            banners=banners, frontend_context={}
        )
        return next(b for b in banners if b.get("id") == "missing-api-key")

    import asyncio
    row = asyncio.run(run())

    assert row["auto_modal_path"] == "/plugins/_onboarding/webui/onboarding.html"
    assert row["auto_modal_reason"] == "missing-api-key"
    assert row["auto_modal_priority"] == 100
    assert row["type"] == "warning"
    assert row["dismissible"] is False
    assert row["missing_providers"] == fake


def test_provider_key_modes_for_local_and_ollama_cloud():
    from plugins._model_config.helpers import model_config

    assert model_config.provider_requires_api_key("ollama") is False
    assert model_config.provider_requires_api_key("lm_studio") is False
    assert model_config.provider_requires_api_key("llama_cpp") is False
    assert model_config.provider_requires_api_key("omlx") is False
    assert model_config.provider_requires_api_key("vllm") is False
    assert model_config.provider_requires_api_key("other") is False
    assert model_config.provider_requires_api_key("ollama_cloud") is True
    assert "llama_cpp" in missing_key_banner.MissingApiKeyCheck.LOCAL_PROVIDERS
    assert "omlx" in missing_key_banner.MissingApiKeyCheck.LOCAL_PROVIDERS
    assert "vllm" in missing_key_banner.MissingApiKeyCheck.LOCAL_PROVIDERS


def test_local_provider_defaults_are_docker_friendly():
    import yaml

    provider_path = PROJECT_ROOT / "conf" / "model_providers.yaml"
    provider_config = yaml.safe_load(provider_path.read_text(encoding="utf-8"))

    assert provider_config["chat"]["lm_studio"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:1234/v1"
    )
    assert provider_config["chat"]["lm_studio"]["kwargs"]["api_key"] == "lm-studio"
    assert provider_config["chat"]["lm_studio"]["models_list"]["default_base"] == (
        "http://host.docker.internal:1234"
    )
    assert provider_config["chat"]["llama_cpp"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["chat"]["llama_cpp"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8080/v1"
    )
    assert provider_config["chat"]["llama_cpp"]["kwargs"]["api_key"] == "llama-cpp"
    assert provider_config["chat"]["llama_cpp"]["models_list"]["default_base"] == (
        "http://host.docker.internal:8080"
    )
    assert provider_config["chat"]["llama_cpp"]["models_list"]["endpoint_url"] == "/v1/models"
    assert provider_config["chat"]["ollama"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:11434"
    )
    assert provider_config["chat"]["ollama"]["models_list"]["default_base"] == (
        "http://host.docker.internal:11434"
    )
    assert provider_config["chat"]["omlx"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["chat"]["omlx"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8000/v1"
    )
    assert provider_config["chat"]["omlx"]["kwargs"]["api_key"] == "omlx"
    assert provider_config["chat"]["omlx"]["models_list"]["default_base"] == (
        "http://host.docker.internal:8000"
    )
    assert provider_config["chat"]["omlx"]["models_list"]["endpoint_url"] == "/v1/models"
    assert provider_config["chat"]["vllm"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["chat"]["vllm"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8000/v1"
    )
    assert provider_config["chat"]["vllm"]["kwargs"]["api_key"] == "vllm"
    assert provider_config["chat"]["vllm"]["models_list"]["default_base"] == (
        "http://host.docker.internal:8000"
    )
    assert provider_config["chat"]["vllm"]["models_list"]["endpoint_url"] == "/v1/models"
    assert provider_config["embedding"]["lm_studio"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:1234/v1"
    )
    assert provider_config["embedding"]["lm_studio"]["kwargs"]["api_key"] == "lm-studio"
    assert provider_config["embedding"]["llama_cpp"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["embedding"]["llama_cpp"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8080/v1"
    )
    assert provider_config["embedding"]["llama_cpp"]["kwargs"]["api_key"] == "llama-cpp"
    assert provider_config["embedding"]["ollama"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:11434"
    )
    assert provider_config["embedding"]["omlx"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["embedding"]["omlx"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8000/v1"
    )
    assert provider_config["embedding"]["omlx"]["kwargs"]["api_key"] == "omlx"
    assert provider_config["embedding"]["vllm"]["litellm_provider"] == "hosted_vllm"
    assert provider_config["embedding"]["vllm"]["kwargs"]["api_base"] == (
        "http://host.docker.internal:8000/v1"
    )
    assert provider_config["embedding"]["vllm"]["kwargs"]["api_key"] == "vllm"


def test_local_provider_runtime_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(models, "get_api_key", lambda provider: "None")

    lm_chat = models.get_chat_model("lm_studio", "local-chat-model")
    assert lm_chat.model_name == "lm_studio/local-chat-model"
    assert lm_chat.kwargs["api_base"] == "http://host.docker.internal:1234/v1"
    assert lm_chat.kwargs["api_key"] == "lm-studio"

    lm_embedding = models.get_embedding_model("lm_studio", "nomic-embed-text")
    assert lm_embedding.model_name == "lm_studio/nomic-embed-text"
    assert lm_embedding.kwargs["api_base"] == "http://host.docker.internal:1234/v1"
    assert lm_embedding.kwargs["api_key"] == "lm-studio"

    custom_lm_embedding = models.get_embedding_model(
        "lm_studio",
        "nomic-embed-text",
        api_base="http://127.0.0.1:1234/v1",
        api_key="real-local-key",
    )
    assert custom_lm_embedding.kwargs["api_base"] == "http://127.0.0.1:1234/v1"
    assert custom_lm_embedding.kwargs["api_key"] == "real-local-key"

    llama_cpp_chat = models.get_chat_model("llama_cpp", "local-chat-model")
    assert llama_cpp_chat.model_name == "hosted_vllm/local-chat-model"
    assert llama_cpp_chat.kwargs["api_base"] == "http://host.docker.internal:8080/v1"
    assert llama_cpp_chat.kwargs["api_key"] == "llama-cpp"

    llama_cpp_embedding = models.get_embedding_model("llama_cpp", "local-embedding-model")
    assert llama_cpp_embedding.model_name == "hosted_vllm/local-embedding-model"
    assert llama_cpp_embedding.kwargs["api_base"] == "http://host.docker.internal:8080/v1"
    assert llama_cpp_embedding.kwargs["api_key"] == "llama-cpp"

    ollama_embedding = models.get_embedding_model("ollama", "nomic-embed-text")
    assert ollama_embedding.model_name == "ollama/nomic-embed-text"
    assert ollama_embedding.kwargs["api_base"] == "http://host.docker.internal:11434"
    assert "api_key" not in ollama_embedding.kwargs

    omlx_chat = models.get_chat_model("omlx", "local-chat-model")
    assert omlx_chat.model_name == "hosted_vllm/local-chat-model"
    assert omlx_chat.kwargs["api_base"] == "http://host.docker.internal:8000/v1"
    assert omlx_chat.kwargs["api_key"] == "omlx"

    omlx_embedding = models.get_embedding_model("omlx", "local-embedding-model")
    assert omlx_embedding.model_name == "hosted_vllm/local-embedding-model"
    assert omlx_embedding.kwargs["api_base"] == "http://host.docker.internal:8000/v1"
    assert omlx_embedding.kwargs["api_key"] == "omlx"

    custom_omlx_chat = models.get_chat_model(
        "omlx",
        "local-chat-model",
        api_base="http://127.0.0.1:8000/v1",
        api_key="real-local-key",
    )
    assert custom_omlx_chat.kwargs["api_base"] == "http://127.0.0.1:8000/v1"
    assert custom_omlx_chat.kwargs["api_key"] == "real-local-key"

    vllm_chat = models.get_chat_model("vllm", "local-chat-model")
    assert vllm_chat.model_name == "hosted_vllm/local-chat-model"
    assert vllm_chat.kwargs["api_base"] == "http://host.docker.internal:8000/v1"
    assert vllm_chat.kwargs["api_key"] == "vllm"

    vllm_embedding = models.get_embedding_model("vllm", "local-embedding-model")
    assert vllm_embedding.model_name == "hosted_vllm/local-embedding-model"
    assert vllm_embedding.kwargs["api_base"] == "http://host.docker.internal:8000/v1"
    assert vllm_embedding.kwargs["api_key"] == "vllm"

    custom_vllm_chat = models.get_chat_model(
        "vllm",
        "local-chat-model",
        api_base="http://127.0.0.1:8001/v1",
        api_key="real-local-key",
    )
    assert custom_vllm_chat.kwargs["api_base"] == "http://127.0.0.1:8001/v1"
    assert custom_vllm_chat.kwargs["api_key"] == "real-local-key"


def test_embedding_config_repairs_sentence_transformer_aliases(monkeypatch):
    from plugins._model_config.helpers import model_config

    cases = [
        (
            {"provider": "", "name": "sentence-transformers/all-MiniLM-L6-v2"},
            ("huggingface", "sentence-transformers/all-MiniLM-L6-v2"),
        ),
        (
            {"provider": "openai", "name": "sentence-transformers/all-MiniLM-L6-v2"},
            ("huggingface", "sentence-transformers/all-MiniLM-L6-v2"),
        ),
        (
            {
                "provider": "other",
                "name": "huggingface/sentence-transformers/all-MiniLM-L6-v2",
            },
            ("huggingface", "sentence-transformers/all-MiniLM-L6-v2"),
        ),
        (
            {"provider": "huggingface", "name": "all-MiniLM-L6-v2"},
            ("huggingface", "sentence-transformers/all-MiniLM-L6-v2"),
        ),
    ]

    for raw_embedding, expected in cases:
        monkeypatch.setattr(
            model_config,
            "get_config",
            lambda *args, raw_embedding=raw_embedding, **kwargs: {
                "embedding_model": raw_embedding
            },
        )
        cfg = model_config.get_embedding_model_config_object()

        assert (cfg.provider, cfg.name) == expected

    monkeypatch.setattr(
        model_config,
        "get_config",
        lambda *args, **kwargs: {
            "embedding_model": {
                "provider": "openai",
                "name": "text-embedding-3-small",
            }
        },
    )
    cfg = model_config.get_embedding_model_config_object()

    assert (cfg.provider, cfg.name) == ("openai", "text-embedding-3-small")

    monkeypatch.setattr(
        model_config,
        "get_config",
        lambda *args, **kwargs: {
            "embedding_model": {
                "provider": "openai",
                "name": "sentence-transformers/all-MiniLM-L6-v2",
            }
        },
    )
    assert model_config.get_missing_api_key_providers() == []


def test_docker_compose_maps_host_docker_internal_for_local_models():
    import yaml

    compose_path = PROJECT_ROOT / "docker" / "run" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    service = compose["services"]["agent-zero"]

    assert "host.docker.internal:host-gateway" in service["extra_hosts"]
