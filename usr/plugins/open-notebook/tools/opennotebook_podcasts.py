"""
Open Notebook Plugin - Podcasts Tool

Provides podcast episode management: list, get, generate, status, retry, delete, profiles.
Methods: list, get, generate, status, retry, delete, profiles
"""

from helpers.tool import Tool, Response

import sys
from pathlib import Path

# Add plugin root to path for imports
_plugin_root = str(Path(__file__).resolve().parent.parent)
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

import config
import client
import errors
sys.modules.pop('shared', None)
from shared import format_date, format_status, get_asset_type, handle_error, prepare_content_for_backend

# Limits
_MAX_EPISODES = 20
_MAX_TRANSCRIPT_CHARS = 2000

class OpenNotebookPodcasts(Tool):
    async def execute(self, **kwargs):
        method = kwargs.get("action") or self.method or "list"

        if method == "list":
            return await self._list()
        elif method == "get":
            episode_id = kwargs.get("episode_id", "")
            return await self._get(episode_id)
        elif method == "generate":
            episode_profile = kwargs.get("episode_profile", "")
            speaker_profile = kwargs.get("speaker_profile", "")
            episode_name = kwargs.get("episode_name", "")
            content = kwargs.get("content", "")
            notebook_id = kwargs.get("notebook_id", "")
            briefing_suffix = kwargs.get("briefing_suffix", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._generate(
                episode_profile, speaker_profile, episode_name,
                content, notebook_id, briefing_suffix, confirmed,
            )
        elif method == "status":
            job_id = kwargs.get("job_id", "")
            return await self._status(job_id)
        elif method == "retry":
            episode_id = kwargs.get("episode_id", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._retry(episode_id, confirmed)
        elif method == "delete":
            episode_id = kwargs.get("episode_id", "")
            confirmed = str(kwargs.get("confirmed", "false")).lower() == "true"
            return await self._delete(episode_id, confirmed)
        elif method == "profiles":
            return await self._profiles()
        else:
            return Response(
                message=f"❌ Unknown method '{method}'. Available: list, get, generate, status, retry, delete, profiles",
                break_loop=False,
            )

    async def _list(self) -> Response:
        """List all podcast episodes."""
        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/podcasts/episodes"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)
            response.raise_for_status()
            episodes = response.json()

            if not episodes:
                return Response(
                    message="🎙️ No podcast episodes yet. Use `opennotebook_podcasts:generate` to create one.",
                    break_loop=False,
                )

            lines = ["🎙️ **Podcast Episodes**\n"]
            lines.append("| Name | Profile | Status | Created |")
            lines.append("|------|---------|--------|---------|")

            total = len(episodes)
            for ep in episodes[:_MAX_EPISODES]:
                name = ep.get("name") or "Untitled"
                profile_obj = ep.get("episode_profile") or {}
                profile_name = profile_obj.get("name", "unknown") if isinstance(profile_obj, dict) else str(profile_obj)
                status = format_status(ep.get("job_status"))
                created = format_date(ep.get("created", ""))
                lines.append(f"| **{name}** | {profile_name} | {status} | {created} |")

            if total > _MAX_EPISODES:
                remaining = total - _MAX_EPISODES
                lines.append(f"\n...and {remaining} more")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _get(self, episode_id: str) -> Response:
        """Get episode details."""
        if not episode_id:
            return Response(
                message=(
                    "❌ **Episode ID required.**\n"
                    "Use `opennotebook_podcasts:list` to see available episodes."
                ),
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/podcasts/episodes/{episode_id}"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)

            if response.status_code == 404:
                return Response(
                    message=(
                        f"❌ **Episode `{episode_id}` not found.**\n"
                        "Use `opennotebook_podcasts:list` to see available episodes."
                    ),
                    break_loop=False,
                )

            response.raise_for_status()
            ep = response.json()

            # Build metadata
            name = ep.get("name") or "Untitled"
            profile_obj = ep.get("episode_profile") or {}
            profile_name = profile_obj.get("name", "unknown") if isinstance(profile_obj, dict) else str(profile_obj)
            speaker_obj = ep.get("speaker_profile") or {}
            speaker_name = speaker_obj.get("name", "unknown") if isinstance(speaker_obj, dict) else str(speaker_obj)
            status = format_status(ep.get("job_status"))
            created = format_date(ep.get("created", ""))
            audio_url = ep.get("audio_url") or ""
            audio_file = ep.get("audio_file") or ""
            error_message = ep.get("error_message") or ""

            lines = [
                f"🎙️ **{name}**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| ID | `{ep.get('id', '')}` |",
                f"| Episode Profile | {profile_name} |",
                f"| Speaker Profile | {speaker_name} |",
                f"| Status | {status} |",
                f"| Created | {created} |",
            ]

            # Briefing
            briefing = ep.get("briefing", "")
            if briefing:
                lines.append(f"\n**Briefing:**\n{briefing}")

            # Audio info
            if audio_url:
                lines.append(f"\n🎵 **Audio:** {audio_url}")
            elif audio_file:
                lines.append(f"\n🎵 **Audio file:** `{audio_file}`")

            # Error message if failed
            if error_message:
                lines.append(f"\n❌ **Error:** {error_message}")

            # Transcript excerpt
            transcript = ep.get("transcript")
            if transcript and isinstance(transcript, dict):
                transcript_text = transcript.get("text", "") or str(transcript)
            elif transcript and isinstance(transcript, str):
                transcript_text = transcript
            else:
                transcript_text = ""

            if transcript_text:
                lines.append(f"\n**Transcript excerpt:**\n")
                if len(transcript_text) > _MAX_TRANSCRIPT_CHARS:
                    lines.append(transcript_text[:_MAX_TRANSCRIPT_CHARS])
                    lines.append("\n...transcript truncated. Use Open Notebook UI for full transcript.")
                else:
                    lines.append(transcript_text)
            else:
                lines.append("\n*Transcript not yet available.*")

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _generate(
        self,
        episode_profile: str,
        speaker_profile: str,
        episode_name: str,
        content: str,
        notebook_id: str,
        briefing_suffix: str,
        confirmed: bool,
    ) -> Response:
        """Start podcast generation."""
        # Validate required fields
        if not episode_profile:
            return Response(
                message=(
                    "❌ **Episode profile required.**\n"
                    "Use `opennotebook_podcasts:profiles` to see available profiles."
                ),
                break_loop=False,
            )
        if not speaker_profile:
            return Response(
                message=(
                    "❌ **Speaker profile required.**\n"
                    "Use `opennotebook_podcasts:profiles` to see available profiles."
                ),
                break_loop=False,
            )
        if not episode_name:
            return Response(
                message="❌ **Episode name required.** Provide a descriptive name for the episode.",
                break_loop=False,
            )

        # Read-only check
        if config.is_read_only(self.agent):
            return Response(
                message="⚠️ Plugin is in read-only mode. Cannot generate podcasts.",
                break_loop=False,
            )

        # Detect and read file content if content looks like a local file path
        if content:
            try:
                content = prepare_content_for_backend(content)
            except ValueError as e:
                return Response(
                    message=f"❌ **Error processing content:** {str(e)}",
                    break_loop=False
                )

        # Confirmation check
        if config.needs_confirmation(self.agent) and not confirmed:
            details = [
                f"⚠️ **Confirm podcast generation**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| Episode Name | **{episode_name}** |",
                f"| Episode Profile | `{episode_profile}` |",
                f"| Speaker Profile | `{speaker_profile}` |",
            ]
            if content:
                preview = content[:100] + ("..." if len(content) > 100 else "")
                details.append(f"| Content Preview | {preview} |")
            if notebook_id:
                details.append(f"| Notebook ID | `{notebook_id}` |")
            if briefing_suffix:
                details.append(f"| Briefing Suffix | {briefing_suffix[:100]} |")
            details.append("\nTo confirm, call again with `confirmed: true`")

            return Response(
                message="\n".join(details),
                break_loop=False,
            )

        # Build request body
        body = {
            "episode_profile": episode_profile,
            "speaker_profile": speaker_profile,
            "episode_name": episode_name,
        }
        if content:
            body["content"] = content
        if notebook_id:
            body["notebook_id"] = notebook_id
        if briefing_suffix:
            body["briefing_suffix"] = briefing_suffix

        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/podcasts/generate"

        try:
            http_client = await client.get_client()
            response = await http_client.post(url, json=body)
            response.raise_for_status()
            data = response.json()

            job_id = data.get("job_id", "unknown")
            job_status = data.get("status", "unknown")
            message = data.get("message", "")

            return Response(
                message=(
                    f"🎙️ **Podcast generation started**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Episode | **{episode_name}** |"
                    f"\n| Job ID | `{job_id}` |"
                    f"\n| Initial Status | {format_status(job_status)} |"
                    f"\n\n💡 Generation is asynchronous. Use `opennotebook_podcasts:status` with `job_id: {job_id}` to check progress."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _status(self, job_id: str) -> Response:
        """Check job status with pipeline-stage detection."""
        if not job_id:
            return Response(
                message=(
                    "❌ **Job ID required.**\n"
                    "Provide the job_id returned from `opennotebook_podcasts:generate`."
                ),
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/podcasts/jobs/{job_id}"

        try:
            http_client = await client.get_client()
            response = await http_client.get(url)

            if response.status_code == 404:
                return Response(
                    message=f"❌ Job `{job_id}` not found. It may have expired.",
                    break_loop=False,
                )

            response.raise_for_status()
            data = response.json()

            raw_status = str(data.get("status", "")).lower()
            status = format_status(raw_status)
            message = data.get("message", "")
            episode_id = data.get("episode_id", "")

            lines = [
                f"📊 **Job Status**\n",
                f"| Detail | Value |",
                f"|--------|-------|",
                f"| Job ID | `{job_id}` |",
                f"| Status | {status} |",
            ]
            if message:
                lines.append(f"| Message | {message} |")

            # Pipeline stage detection — fetch episode to determine progress
            if raw_status == "running" and episode_id:
                stage, stage_hint = await self._detect_pipeline_stage(
                    http_client, api_url, episode_id
                )
                lines.append(f"| Pipeline Stage | {stage} |")
                if stage_hint:
                    lines.append(f"\n💡 {stage_hint}")
                lines.append(
                    "\n⏳ **Generation takes 15-25 min with free models, 8-15 min with paid models.** "
                    "Wait 3-5 minutes before checking again."
                )
            elif raw_status in ("completed", "done", "finished"):
                if episode_id:
                    lines.append(
                        f"\n✅ **Episode ready!** Use `opennotebook_podcasts:get` with `episode_id: {episode_id}` for full details and audio URL."
                    )
                else:
                    lines.append(
                        "\n✅ **Generation complete!** Use `opennotebook_podcasts:list` to find your episode."
                    )
            elif raw_status in ("failed", "error"):
                error_msg = data.get("error_message", "") or message
                if error_msg:
                    lines.append(f"| Error | {error_msg[:200]} |")
                lines.append(
                    "\n❌ **Generation failed.** Use `opennotebook_podcasts:retry` with the episode ID to try again."
                )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _detect_pipeline_stage(
        self, http_client, api_url: str, episode_id: str
    ) -> tuple:
        """Detect which pipeline stage the episode is in. Returns (stage_label, hint)."""
        try:
            r = await http_client.get(f"{api_url}/api/podcasts/episodes/{episode_id}")
            if r.status_code != 200:
                return "Unknown", None

            ep = r.json()
            has_outline = ep.get("outline") is not None
            has_transcript = ep.get("transcript") is not None
            has_audio = ep.get("audio_url") is not None

            if has_audio:
                return "✅ Complete (audio ready)", "Audio is ready — check status again, it may complete shortly."
            elif has_transcript:
                return "⏳ TTS audio generating", "Transcript done, generating speech. This is the longest step (5-15 min). Wait 5 minutes before checking again."
            elif has_outline:
                return "⏳ Transcript generating", "Outline done, generating transcript (3-8 min). Wait 3 minutes before checking again."
            else:
                return "⏳ Outline generating", "Starting outline generation (2-5 min). Wait 3 minutes before checking again."
        except Exception:
            return "Unknown", None

    async def _retry(self, episode_id: str, confirmed: bool) -> Response:
        """Retry a failed episode generation."""
        if not episode_id:
            return Response(
                message=(
                    "❌ **Episode ID required.**\n"
                    "Use `opennotebook_podcasts:list` to see available episodes."
                ),
                break_loop=False,
            )

        # Read-only check
        if config.is_read_only(self.agent):
            return Response(
                message="⚠️ Plugin is in read-only mode. Cannot retry episode generation.",
                break_loop=False,
            )

        # Confirmation check
        if config.needs_confirmation(self.agent) and not confirmed:
            return Response(
                message=(
                    f"⚠️ **Confirm retry**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Episode ID | `{episode_id}` |"
                    f"\n\nThis will retry the failed generation. Call again with `confirmed: true` to proceed."
                ),
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)
        url = f"{api_url}/api/podcasts/episodes/{episode_id}/retry"

        try:
            http_client = await client.get_client()
            response = await http_client.post(url)

            if response.status_code == 404:
                return Response(
                    message=f"❌ Episode `{episode_id}` not found.",
                    break_loop=False,
                )

            response.raise_for_status()
            data = response.json()

            job_id = data.get("job_id", "unknown")
            retry_status = format_status(data.get("status"))

            return Response(
                message=(
                    f"🔄 **Retry started**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Episode ID | `{episode_id}` |"
                    f"\n| Job ID | `{job_id}` |"
                    f"\n| Status | {retry_status} |"
                    f"\n\n💡 Use `opennotebook_podcasts:status` with `job_id: {job_id}` to check progress."
                ),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _delete(self, episode_id: str, confirmed: bool) -> Response:
        """Delete an episode."""
        if not episode_id:
            return Response(
                message=(
                    "❌ **Episode ID required.**\n"
                    "Use `opennotebook_podcasts:list` to see available episodes."
                ),
                break_loop=False,
            )

        # Read-only check
        if config.is_read_only(self.agent):
            return Response(
                message="⚠️ Plugin is in read-only mode. Cannot delete episodes.",
                break_loop=False,
            )

        api_url = config.get_api_url(self.agent)

        # Confirmation check — fetch episode name first
        if config.needs_confirmation(self.agent) and not confirmed:
            try:
                http_client = await client.get_client()
                response = await http_client.get(f"{api_url}/api/podcasts/episodes/{episode_id}")
                if response.status_code == 200:
                    ep = response.json()
                    ep_name = ep.get("name") or "Untitled"
                else:
                    ep_name = episode_id
            except Exception:
                ep_name = episode_id

            return Response(
                message=(
                    f"⚠️ **Confirm deletion**\n"
                    f"\n| Detail | Value |"
                    f"\n|--------|-------|"
                    f"\n| Episode | **{ep_name}** |"
                    f"\n| ID | `{episode_id}` |"
                    f"\n\nThis action cannot be undone. Call again with `confirmed: true` to proceed."
                ),
                break_loop=False,
            )

        url = f"{api_url}/api/podcasts/episodes/{episode_id}"

        try:
            http_client = await client.get_client()
            # Fetch name before deleting for confirmation message
            ep_name = episode_id
            try:
                get_resp = await http_client.get(url)
                if get_resp.status_code == 200:
                    ep_name = get_resp.json().get("name") or episode_id
            except Exception:
                pass

            response = await http_client.delete(url)

            if response.status_code == 404:
                return Response(
                    message=f"❌ Episode `{episode_id}` not found. It may have already been deleted.",
                    break_loop=False,
                )

            response.raise_for_status()

            return Response(
                message=f"✅ **Episode deleted:** {ep_name}",
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, url), break_loop=False)

    async def _profiles(self) -> Response:
        """List available episode and speaker profiles."""
        api_url = config.get_api_url(self.agent)

        try:
            http_client = await client.get_client()

            # Fetch both profile types in parallel
            import asyncio
            ep_task = http_client.get(f"{api_url}/api/episode-profiles")
            sp_task = http_client.get(f"{api_url}/api/speaker-profiles")
            ep_resp, sp_resp = await asyncio.gather(ep_task, sp_task, return_exceptions=True)

            # Handle episode profiles
            if isinstance(ep_resp, Exception):
                return Response(message=handle_error(ep_resp, f"{api_url}/api/episode-profiles"), break_loop=False)
            ep_resp.raise_for_status()
            episode_profiles = ep_resp.json()

            # Handle speaker profiles
            if isinstance(sp_resp, Exception):
                return Response(message=handle_error(sp_resp, f"{api_url}/api/speaker-profiles"), break_loop=False)
            sp_resp.raise_for_status()
            speaker_profiles = sp_resp.json()

            lines = ["📋 **Available Podcast Profiles**\n"]

            # Episode profiles table
            lines.append("**Episode Profiles:**\n")
            if episode_profiles:
                lines.append("| Name | Description | Segments |")
                lines.append("|------|-------------|----------|")
                for p in episode_profiles:
                    name = p.get("name", "unknown")
                    desc = p.get("description", "") or ""
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    segments = p.get("num_segments", "?")
                    lines.append(f"| `{name}` | {desc} | {segments} |")
            else:
                lines.append("*No episode profiles available.*")

            lines.append("")

            # Speaker profiles table
            lines.append("**Speaker Profiles:**\n")
            if speaker_profiles:
                for sp in speaker_profiles:
                    sp_name = sp.get("name", "unknown")
                    sp_desc = sp.get("description", "") or ""
                    lines.append(f"**`{sp_name}`** — {sp_desc}")

                    speakers = sp.get("speakers", [])
                    if speakers:
                        lines.append("\n| Speaker | Voice ID |")
                        lines.append("|---------|----------|")
                        for s in speakers:
                            s_name = s.get("name", "unknown")
                            voice_id = s.get("voice_id", "default")
                            lines.append(f"| {s_name} | `{voice_id}` |")
                    lines.append("")
            else:
                lines.append("*No speaker profiles available.*")

            lines.append(
                "💡 Use profile names (e.g. `tech_discussion`, `tech_experts`) with `opennotebook_podcasts:generate`."
            )

            return Response(
                message="\n".join(lines),
                break_loop=False,
            )

        except Exception as e:
            return Response(message=handle_error(e, f"{api_url}/api/episode-profiles"), break_loop=False)

