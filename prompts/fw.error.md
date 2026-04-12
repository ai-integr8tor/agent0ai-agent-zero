~~~json
{
    "system_error": "{{error}}"
}
~~~

Before retrying, diagnose the error type:
- **Parameter error** (wrong arg name/type/value): Read the tool's parameter spec, fix the argument, retry.
- **Environment error** (file not found, connection refused): Verify the path/URL exists, use an alternative approach if unreachable.
- **Logic error** (wrong tool for the task): Switch to a more appropriate tool or break the task into smaller steps.
- **Timeout/limit error** (too large input, rate limit): Reduce input size, add pagination, or wait and retry.
If the same error repeats, change your approach instead of repeating the same action.
