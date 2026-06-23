# litellm_transport.py DOX

## Purpose

- Own Agent Zero's LiteLLM transport adapter for Chat Completions and Responses API calls.
- Normalize Agent Zero model-call kwargs into provider-safe LiteLLM requests.
- Provide fallback between Responses and chat-completions modes while preserving A0 tool-call semantics.
- Preserve canonical response metadata for history, provider-state continuation, and fallback decisions.

## Ownership

- `litellm_transport.py` owns the runtime implementation.
- `litellm_transport.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `TransportMode`
- `TransportRecovery`
- `LiteLLMTransport` selects the active transport, performs sync/async complete and stream calls, and exposes the last `LLMResult`.
- `TransportPolicy` owns mode selection, Responses fallback, and provider capability cache behavior.
- `ChatCompletionsTransport` owns chat-completions request preparation and response parsing.
- `ResponsesTransport` owns Responses API request preparation, output parsing, and conversion between chat messages and Responses input items.
- `ResponsesEventParser` owns stateful parsing of streamed Responses events.
- Top-level functions include transport cache reset, request normalization, parsing, prompt-cache preparation, and response/error classifiers.

## Runtime Contracts

- Keep provider selection and provider-specific defaults outside this helper; callers pass a resolved LiteLLM model name and kwargs.
- A0-only kwargs such as `a0_api_mode`, `a0_responses_function_tools`, and Responses state fields must not leak to LiteLLM provider calls.
- Strip Agent Zero internal kwargs before sending requests to LiteLLM.
- Do not send orphan tool controls when no tools are present; strict OpenAI-compatible servers can reject empty `tools` arrays.
- Explicit `chat_completions` mode may receive A0-generated function tools through `a0_responses_function_tools`; these must be converted into standard chat-completions `tools`.
- Chat-completions tool calls are converted back into canonical A0 JSON tool requests so the existing tool executor can process them.
- Prefer Responses API when configured, but fallback to Chat Completions when the provider does not support Responses.
- Preserve provider-state metadata when Responses API calls succeed, and fall back to local replay when provider state is unsupported.
- Keep prompt-cache markers only for providers that accept them.
- Responses fallback must keep provider-state, local-state, and unsupported-capability caches bounded to transport decisions only.

## Work Guidance

- Add provider-agnostic request cleanup here when multiple OpenAI-compatible providers can benefit.
- Treat fallback behavior as a shared transport contract, not a provider registry.
- Keep request conversion and response parsing symmetric: if a tool schema is converted into provider format, returned tool calls must convert back into A0 format.
- Avoid broad provider-specific branches unless LiteLLM cannot normalize the behavior.
- Keep streaming changes explicit; chat-completions streaming tool-call deltas require stateful accumulation before they can replace non-stream tool-call turns.

## Verification

- Run focused transport tests in `tests/test_stream_tool_early_stop.py` after changing request preparation, parsing, fallback, or cache behavior.
- Run `pytest tests/test_stream_tool_early_stop.py tests/test_responses_architecture.py -q` after changing transport normalization or fallback behavior.
- For local Ollama tool-call changes, verify both final-response and executable-tool prompts when the model is available.
- Run local-provider smoke checks when changing OpenAI-compatible request cleanup.

## Child DOX Index

No child DOX files.
