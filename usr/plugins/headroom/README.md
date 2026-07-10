# Headroom Plugin

Optional Agent Zero integration for `chopratejas/headroom`.

This plugin hooks `chat_model_call_before` and compresses the LangChain message
list before Agent Zero calls LiteLLM. It is intentionally optional: if
`headroom-ai` is not installed in the Agent Zero framework runtime, the plugin
logs a warning once and leaves messages unchanged.

Install dependency in the framework runtime when you want to enable compression.
On Windows, current `headroom-ai` releases may try to build a Rust extension
from source and fail without Visual Studio Build Tools. The tested workaround
for this Agent Zero environment is:

```bash
pip install --force-reinstall --no-deps "headroom-ai==0.5.25"
pip install --no-deps "ast-grep-cli==0.42.3"
```

This keeps Agent Zero's pinned LiteLLM version in place. The plugin temporarily
clears broken proxy environment variables while Headroom loads tokenizer/model
files because this environment sets proxy variables to `127.0.0.1:9`.

Use the latest `headroom-ai[proxy]`, `headroom-ai[mcp]`, or `headroom-ai[all]`
only after installing Visual Studio Build Tools with the Visual C++ workload, or
when a compatible wheel is available for your Python/Windows target.
