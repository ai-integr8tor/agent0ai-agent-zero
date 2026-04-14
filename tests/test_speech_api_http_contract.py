from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIBE_PATH = PROJECT_ROOT / "api" / "transcribe.py"
SYNTHESIZE_PATH = PROJECT_ROOT / "api" / "synthesize.py"


class StubResponse:
    def __init__(self, response=None, status=200, mimetype=None):
        self.response = response
        self.status_code = status
        self.mimetype = mimetype

    def get_data(self, as_text: bool = False):
        if as_text:
            if self.response is None:
                return ""
            return self.response if isinstance(self.response, str) else str(self.response)

        if self.response is None:
            return b""
        if isinstance(self.response, bytes):
            return self.response
        return str(self.response).encode()


class StubApiHandler:
    def __init__(self, app=None, thread_lock=None):
        self.app = app
        self.thread_lock = thread_lock

    def use_context(self, ctxid: str, create_if_not_exists: bool = True):
        return {"ctxid": ctxid, "create_if_not_exists": create_if_not_exists}


def _install_speech_stubs(
    monkeypatch,
    *,
    transcribe_impl=None,
    synthesize_impl=None,
    settings_data=None,
):
    helpers_pkg = types.ModuleType("helpers")
    helpers_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "helpers", helpers_pkg)

    api_mod = types.ModuleType("helpers.api")
    api_mod.ApiHandler = StubApiHandler
    api_mod.Request = object
    api_mod.Response = StubResponse
    monkeypatch.setitem(sys.modules, "helpers.api", api_mod)

    runtime_mod = types.ModuleType("helpers.runtime")
    monkeypatch.setitem(sys.modules, "helpers.runtime", runtime_mod)

    settings_mod = types.ModuleType("helpers.settings")
    settings_mod.get_settings = lambda: settings_data or {"stt_model_size": "base"}
    monkeypatch.setitem(sys.modules, "helpers.settings", settings_mod)

    whisper_mod = types.ModuleType("helpers.whisper")

    async def default_transcribe(model_name, audio):
        return {"text": f"{model_name}:{audio}"}

    whisper_mod.transcribe = transcribe_impl or default_transcribe
    monkeypatch.setitem(sys.modules, "helpers.whisper", whisper_mod)

    kokoro_mod = types.ModuleType("helpers.kokoro_tts")

    async def default_synthesize(chunks):
        return "|".join(chunks)

    kokoro_mod.synthesize_sentences = synthesize_impl or default_synthesize
    monkeypatch.setitem(sys.modules, "helpers.kokoro_tts", kokoro_mod)

    helpers_pkg.runtime = runtime_mod
    helpers_pkg.settings = settings_mod
    helpers_pkg.whisper = whisper_mod
    helpers_pkg.kokoro_tts = kokoro_mod


def _load_module(monkeypatch, module_path: Path, **stub_kwargs):
    _install_speech_stubs(monkeypatch, **stub_kwargs)

    spec = importlib.util.spec_from_file_location(
        f"test_{module_path.stem}_{module_path.stat().st_size}",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transcribe_missing_audio_returns_400(monkeypatch):
    module = _load_module(monkeypatch, TRANSCRIBE_PATH)

    response = asyncio.run(module.Transcribe(None, None).process({}, None))

    assert response.status_code == 400
    assert response.get_data(as_text=True) == "Missing 'audio'."


def test_transcribe_backend_failure_returns_500(monkeypatch):
    async def failing_transcribe(model_name, audio):
        raise RuntimeError("stt exploded")

    module = _load_module(monkeypatch, TRANSCRIBE_PATH, transcribe_impl=failing_transcribe)

    response = asyncio.run(module.Transcribe(None, None).process({"audio": "abc"}, None))

    assert response.status_code == 500
    assert response.get_data(as_text=True) == "stt exploded"


def test_transcribe_success_keeps_json_payload(monkeypatch):
    async def transcribe_ok(model_name, audio):
        return {"text": f"decoded:{model_name}:{audio}"}

    module = _load_module(
        monkeypatch,
        TRANSCRIBE_PATH,
        transcribe_impl=transcribe_ok,
        settings_data={"stt_model_size": "tiny"},
    )

    response = asyncio.run(module.Transcribe(None, None).process({"audio": "abc"}, None))

    assert response == {"text": "decoded:tiny:abc"}


def test_synthesize_missing_text_returns_400(monkeypatch):
    module = _load_module(monkeypatch, SYNTHESIZE_PATH)

    response = asyncio.run(module.Synthesize(None, None).process({}, None))

    assert response.status_code == 400
    assert response.get_data(as_text=True) == "Missing 'text'."


def test_synthesize_backend_failure_returns_500(monkeypatch):
    async def failing_synthesize(chunks):
        raise RuntimeError("tts exploded")

    module = _load_module(monkeypatch, SYNTHESIZE_PATH, synthesize_impl=failing_synthesize)

    response = asyncio.run(module.Synthesize(None, None).process({"text": "hello"}, None))

    assert response.status_code == 500
    assert response.get_data(as_text=True) == "tts exploded"


def test_synthesize_success_keeps_json_payload(monkeypatch):
    async def synthesize_ok(_chunks):
        return "audio-bytes"

    module = _load_module(monkeypatch, SYNTHESIZE_PATH, synthesize_impl=synthesize_ok)

    response = asyncio.run(module.Synthesize(None, None).process({"text": "hello"}, None))

    assert response == {"audio": "audio-bytes", "success": True}
