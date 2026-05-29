### opennotebook_podcasts:
podcast episode generation and management

**Methods:** `profiles`, `list`, `get`, `generate`, `status`, `retry`, `delete`

**Key params:**
- `episode_profile` (string, required for generate) — profile **name** not ID
- `speaker_profile` (string, required for generate) — profile **name** not ID
- `episode_name` (string, required for generate)
- `notebook_id` / `content` / `briefing_suffix` (optional for generate)
- `episode_id` (for get/retry/delete)
- `job_id` (for status)
- `confirmed` ("true"/"false")

⚠️ **This is an async workflow.** Use the `open-notebook-podcast` skill for the full guided workflow including polling strategy and timing estimates.

usage:
~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": {
        "method": "generate",
        "episode_profile": "tech_discussion",
        "speaker_profile": "tech_experts",
        "episode_name": "Episode Name",
        "notebook_id": "notebook-id"
    }
}
~~~
