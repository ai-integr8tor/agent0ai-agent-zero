---
name: open-notebook-podcast
description: >
  Generate and manage podcast episodes from Open Notebook content.
  Full async workflow: profile discovery, generation, polling, and retrieval.
version: 1.0.0
tags: ["podcast", "generation", "audio", "TTS", "async", "workflow"]
triggers:
  - create podcast
  - generate podcast
  - podcast generation
  - check podcast status
  - podcast profiles
  - list podcasts
  - open notebook podcast
---

# Podcast Generation — Async Workflow Skill

Generate and manage podcast episodes from Open Notebook content.
Use when the user wants to create, check, or manage podcasts.

## Podcast Generation Workflow

This is a **multi-step async workflow**. The skill orchestrates the full lifecycle.

**Content Sources:** Podcasts are generated from content within a specific notebook. If you have **local files** (PDF, DOCX, TXT, etc.) you want to use, add them to the notebook first using `opennotebook_sources:add` (which supports local file auto-detection). The podcast generator will then process those embedded sources.

### Step 1: Discover Profiles

Before generating, discover available profiles:

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": { "method": "profiles" }
}
~~~

Present the profiles clearly. Guide the user to pick:
- An **episode profile** (format/style: tech_discussion, business_analysis, etc.)
- A **speaker profile** (voices: tech_experts, solo_expert, etc.)

**Note:** Profile names are used (not IDs). Filter out `solo_expert` speaker profile — it has invalid TTS config.

### Step 2: Generate Episode

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": {
        "method": "generate",
        "episode_profile": "profile_name",
        "speaker_profile": "speaker_name",
        "episode_name": "Descriptive Episode Name",
        "notebook_id": "optional-notebook-id",
        "content": "optional-custom-content",
        "briefing_suffix": "optional-extra-instructions"
    }
}
~~~

This returns a `job_id`. **Generation is asynchronous.**

### Step 3: Wait, Then Check Status

**Do NOT poll immediately.** Wait at least 3-5 minutes before first check.

**Polling API:**
- **Endpoint:** `GET /api/podcasts/jobs/{jobId}`
- **Response:** `{ status: string, message: string, episode_id: string }`
- **Status values:** `pending` | `running` | `completed` | `failed`
- **WebUI polls at 5-second intervals** (store's `pollJobStatus` method)

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": {
        "method": "status",
        "job_id": "returned-job-id"
    }
}
~~~

### Timing Estimates

| Stage | Duration |
|-------|----------|
| Outline generation | 2-5 min |
| Transcript generation | 3-8 min |
| TTS audio generation | 5-15 min |
| **Total (free models)** | **15-25 min** |
| **Total (paid models)** | **8-15 min** |

### Pipeline Stages

The status response includes pipeline stage detection:

1. ⏳ **Outline generating** — no outline yet
2. ⏳ **Transcript generating** — outline done, no transcript
3. ⏳ **TTS audio generating** — transcript done, no audio
4. ✅ **Complete** — audio_url available

### Polling Strategy

- Wait **3-5 minutes** between checks
- Maximum **5 checks** before advising user to check later
- If still running after 25 min, suggest `retry`

### Step 4: Retrieve Completed Episode

When status shows completed:

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": {
        "method": "get",
        "episode_id": "episode-id"
    }
}
~~~

This returns transcript excerpt, audio URL, and full metadata.

### Step 5: Send Transcript to Agent Zero Chat

The WebUI has a 📤 button on each episode that calls `sendPodcastToChat(episodeId)` to inject the transcript into Agent Zero's chat input.

### Error Recovery

- **Failed generation** → use `retry` method with `episode_id`
- **Stuck job** (>25 min) → suggest retry
- **Audio not available** → check status again, TTS may still be processing

### Listing Episodes

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": { "method": "list" }
}
~~~

### Deleting Episodes

~~~json
{
    "tool_name": "opennotebook_podcasts",
    "tool_args": {
        "method": "delete",
        "episode_id": "episode-id",
        "confirmed": "true"
    }
}
~~~

## Quick Reference

| Action | Method | Key Args |
|--------|--------|----------|
| See profiles | `profiles` | — |
| List episodes | `list` | — |
| Get episode | `get` | `episode_id` |
| Generate | `generate` | `episode_profile`, `speaker_profile`, `episode_name` |
| Check status | `status` | `job_id` |
| Retry failed | `retry` | `episode_id` |
| Delete | `delete` | `episode_id`, `confirmed` |
| Send to chat | WebUI 📤 | `episode_id` |
