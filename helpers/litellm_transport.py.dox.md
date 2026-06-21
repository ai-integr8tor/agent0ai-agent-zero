# litellm_transport.py DOX

## Purpose

- Own the LiteLLM transport layer that normalizes Agent Zero chat and Responses API calls.
- Provide fallback between Responses and chat-completions modes while preserving A0 tool-call semantics.

## Ownership

- `LiteLLMTransport` selects the active transport, performs sync/async complete and stream calls, and exposes the last `LLMResult`.
- `TransportPolicy` owns mode selection, Responses fallback, and provider capability cache behavior.
- `ChatCompletionsTransport` owns chat-completions request preparation and response parsing.
- `ResponsesTransport` owns Responses API request preparation, output parsing, and conversion between chat messages and Responses input items.
- `ResponsesEventParser` owns stateful parsing of streamed Responses events.

## Runtime Contracts

- A0-only kwargs such as `a0_api_mode`, `a0_responses_function_tools`, and Responses state fields must not leak to LiteLLM provider calls.
- Explicit `chat_completions` mode may receive A0-generated function tools through `a0_responses_function_tools`; these must be converted into standard chat-completions `tools`.
- Chat-completions tool calls are converted back into canonical A0 JSON tool requests so the existing tool executor can process them.
- Responses fallback must keep provider-state, local-state, and unsupported-capability caches bounded to transport decisions only.

## Work Guidance

- Keep request conversion and response parsing symmetric: if a tool schema is converted into provider format, returned tool calls must convert back into A0 format.
- Avoid broad provider-specific branches unless LiteLLM cannot normalize the behavior.
- Keep streaming changes explicit; chat-completions streaming tool-call deltas require stateful accumulation before they can replace non-stream tool-call turns.

## Verification

- Run focused transport tests in `tests/test_stream_tool_early_stop.py` after changing request preparation, parsing, fallback, or cache behavior.
- For local Ollama tool-call changes, verify both final-response and executable-tool prompts when the model is available.

## Child DOX Index

No child DOX files.
