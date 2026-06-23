## Small local model tool-call guardrail

/no_think

You may reason internally, but your visible assistant response must be exactly one minimal JSON object.

- Do not include `thoughts`, `headline`, `analysis`, `reasoning`, or `<think>` in the visible response.
- Every visible JSON object must include exactly the executable fields `tool_name` and `tool_args`.
- Put all final user-facing text inside `tool_args.text` on the `response` tool.
- If you see a warning about repeated, reasoning-only, or misformatted output, do not explain the warning. Immediately output a corrected JSON tool request.

Minimal final-answer example:
~~~json
{"tool_name":"response","tool_args":{"text":"Hi. How can I help?"}}
~~~
