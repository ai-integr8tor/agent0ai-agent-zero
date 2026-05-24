import base64
import subprocess
import tempfile
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from contextlib import asynccontextmanager, suppress

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message as TgMessage, CallbackQuery

from agent import AgentContext, UserMessage
from helpers import plugins, files, projects
from helpers import process as a0_process
from helpers import message_queue as mq
from helpers import integration_commands
from helpers.notification import NotificationManager, NotificationType, NotificationPriority
from helpers import persist_chat
from helpers.persist_chat import save_tmp_chat, _serialize_context, _deserialize_context
from helpers.print_style import PrintStyle
from helpers.errors import format_error
from initialize import initialize_agent

from plugins._telegram_integration.helpers import telegram_client as tc
from plugins._telegram_integration.helpers.bot_manager import get_bot
from plugins._telegram_integration.helpers.constants import (
    PLUGIN_NAME,
    DOWNLOAD_FOLDER,
    STATE_FILE,
    CTX_TG_BOT,
    CTX_TG_BOT_CFG,
    CTX_TG_CHAT_ID,
    CTX_TG_USER_ID,
    CTX_TG_USERNAME,
    CTX_TG_TYPING_STOP,
    CTX_TG_REPLY_TO,
    CTX_TG_MESSAGE_THREAD_ID,
    CTX_TG_ATTACHMENTS,
    CTX_TG_KEYBOARD,
    CTX_TG_BRANCH_SEED,
)

# Chat mapping: (bot_name, tg_user_id) → AgentContext ID

_chat_map_lock = threading.Lock()


def _load_state() -> dict:
    path = files.get_abs_path(STATE_FILE)
    if os.path.isfile(path):
        try:
            return json.loads(files.read_file(path))
        except Exception:
            return {}
    return {}


def _save_state(state: dict):
    path = files.get_abs_path(STATE_FILE)
    files.make_dirs(path)
    files.write_file(path, json.dumps(state))


def _map_key(bot_name: str, user_id: int, chat_id: int, message_thread_id: int | None = None) -> str:
    """Map a Telegram user/chat/topic to one AgentContext.

    Forum topics in Telegram groups share the same chat_id, so include
    message_thread_id to avoid cross-topic replies and context leakage.
    """
    thread_part = message_thread_id if message_thread_id is not None else "main"
    return f"{bot_name}:{user_id}:{chat_id}:{thread_part}"


def cleanup_old_attachments():
    """Remove downloaded attachment files older than per-bot max age. 0 = keep forever."""
    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    bots_cfg = config.get("bots") or []
    total_removed = 0
    upload_dir = files.get_abs_path(DOWNLOAD_FOLDER)
    if not os.path.isdir(upload_dir):
        return
    for bot_cfg in bots_cfg:
        bot_name = bot_cfg.get("name", "")
        if not bot_name:
            continue
        max_age_hours = bot_cfg.get("attachment_max_age_hours", 0)
        if not max_age_hours or max_age_hours <= 0:
            continue
        prefix = f"tg_{bot_name}_"
        cutoff = time.time() - max_age_hours * 3600
        for name in os.listdir(upload_dir):
            if not name.startswith(prefix):
                continue
            path = os.path.join(upload_dir, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    total_removed += 1
            except OSError:
                pass
    if total_removed:
        PrintStyle.info(f"Telegram: cleaned up {total_removed} old attachment(s)")

# Access control

def _is_allowed(bot_cfg: dict, user_id: int, username: str | None) -> bool:
    allowed = bot_cfg.get("allowed_users") or []
    if not allowed:
        return True  # empty = allow all
    for entry in allowed:
        entry_str = str(entry).strip()
        if entry_str.startswith("@"):
            if username and f"@{username}" == entry_str:
                return True
        else:
            try:
                if int(entry_str) == user_id:
                    return True
            except ValueError:
                if username and entry_str.lower() == username.lower():
                    return True
    return False


def _get_project(bot_cfg: dict, user_id: int) -> str:
    user_projects = bot_cfg.get("user_projects") or {}
    project = user_projects.get(str(user_id), "")
    if not project:
        project = bot_cfg.get("default_project", "")
    return project

# Message handlers (registered with aiogram by bot_manager)

async def handle_start(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Handle /start command."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_start bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)} text={getattr(message, 'text', '')!r}")
    if not user:
        return

    if not _is_allowed(bot_cfg, user.id, user.username):
        await message.reply("You are not authorized to use this bot.")
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    await _send_with_temp_bot(
        instance.bot.token, message.chat.id,
        f"\U0001f44b Hello {user.first_name}! I'm connected to Agent Zero.\n\n"
        "Send me a message and I'll process it.\n"
        "Use /clear to reset the conversation.\n"
        "Use /project, /config, or /send to control the current chat.",
        parse_mode=None,
    )

    # Ensure a chat context exists
    await _get_or_create_context(bot_name, bot_cfg, message)


async def handle_clear(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Handle /clear command — reset user's chat context."""
    user = message.from_user
    if not user:
        return

    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    message_thread_id = getattr(message, "message_thread_id", None)
    key = _map_key(bot_name, user.id, message.chat.id, message_thread_id)

    with _chat_map_lock:
        state = _load_state()
        ctx_id = state.get("chats", {}).get(key)
        if ctx_id:
            ctx = AgentContext.get(ctx_id)
            if ctx:
                ctx.reset()
                PrintStyle.info(f"Telegram ({bot_name}): cleared chat for user {user.id}")

    instance = get_bot(bot_name)
    if instance:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Chat cleared. Send a new message to start fresh.",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )

    # Send notification
    if bot_cfg.get("notify_messages", False):
        username_str = f"@{user.username}" if user.username else str(user.id)
        NotificationManager.send_notification(
            type=NotificationType.INFO,
            priority=NotificationPriority.NORMAL,
            title="Telegram: chat cleared",
            message=f"{username_str} cleared their chat via /clear",
            display_time=5,
            group="telegram",
        )


def _extract_branch_seed_from_reply(message: TgMessage) -> str:
    replied = getattr(message, "reply_to_message", None)
    if not replied:
        return ""
    text = (getattr(replied, "text", None) or getattr(replied, "caption", None) or "").strip()
    if not text:
        return "[Message Telegram cité sans texte exploitable]"
    return text[:4000]


def _clone_context_for_telegram_branch(
    parent_context: AgentContext,
    bot_name: str,
    bot_cfg: dict,
    chat_id: int,
    message_thread_id: int | None,
    user_id: int,
    username: str | None,
    context_name: str | None = None,
) -> AgentContext:
    """Clone a parent Agent Zero context for Telegram /branch like the UI branch action.

    Unlike /new, /branch must preserve the full parent chat log and agent history.
    """
    data = _serialize_context(parent_context)
    data.pop("id", None)

    src_name = data.get("name") or "Chat"
    data["name"] = context_name or f"{src_name} (branch)"
    data["created_at"] = datetime.now().isoformat()

    ctx_data = data.setdefault("data", {})
    ctx_data[CTX_TG_BOT] = bot_name
    ctx_data[CTX_TG_BOT_CFG] = bot_cfg
    ctx_data[CTX_TG_CHAT_ID] = chat_id
    ctx_data[CTX_TG_MESSAGE_THREAD_ID] = message_thread_id
    ctx_data[CTX_TG_USER_ID] = user_id
    ctx_data[CTX_TG_USERNAME] = username or ""
    if context_name:
        ctx_data["tg_topic_base_name"] = context_name[:128]

    context = _deserialize_context(data)
    save_tmp_chat(context)
    return context


async def handle_new_chat(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Handle /new and /branch — start a fresh Agent Zero context.

    `/branch <name>` creates a Telegram forum topic when possible and maps the
    new Agent Zero chat to that topic. The topic name is also used as the
    Agent Zero UI chat name.
    """
    user = message.from_user
    if not user:
        return

    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    text = (message.text or message.caption or "").strip()
    command_part, _, arg_part = text.partition(" ")
    command = command_part.split("@", 1)[0].lower()
    requested_name = arg_part.strip()

    message_thread_id = getattr(message, "message_thread_id", None)
    context_name = requested_name or None
    branch_seed = _extract_branch_seed_from_reply(message) if command == "/branch" else ""

    parent_context = None
    parent_thread_id = message_thread_id
    if command == "/branch":
        parent_context = await _get_or_create_context(
            bot_name,
            bot_cfg,
            message,
            force_new=False,
            message_thread_id=parent_thread_id,
        )

    if command == "/branch" and requested_name:
        chat_type = getattr(message.chat, "type", None)
        chat_is_forum = getattr(message.chat, "is_forum", False)

        # Aiogram message.chat may be partial and omit is_forum even when the
        # Telegram API getChat endpoint reports the supergroup as a forum.
        if chat_type != "supergroup" or not chat_is_forum:
            with suppress(Exception):
                async with _temp_bot(instance.bot.token) as topic_bot:
                    fresh_chat = await topic_bot.get_chat(message.chat.id)
                chat_type = getattr(fresh_chat, "type", chat_type)
                chat_is_forum = getattr(fresh_chat, "is_forum", chat_is_forum)

        if chat_type != "supergroup" or not chat_is_forum:
            await _send_with_temp_bot(
                instance.bot.token, message.chat.id,
                "La création de sujet Telegram nécessite un supergroupe avec les sujets/forum activés.",
                parse_mode=None,
                message_thread_id=message_thread_id,
            )
            return
        try:
            async with _temp_bot(instance.bot.token) as topic_bot:
                topic = await topic_bot.create_forum_topic(
                    chat_id=message.chat.id,
                    name=requested_name[:128],
                )
            message_thread_id = topic.message_thread_id
        except Exception as e:
            await _send_with_temp_bot(
                instance.bot.token, message.chat.id,
                f"Impossible de créer le sujet Telegram: {format_error(e)}. Vérifie que le bot est admin et a le droit de gérer les sujets.",
                parse_mode=None,
                message_thread_id=getattr(message, "message_thread_id", None),
            )
            return

    if command == "/branch" and parent_context:
        try:
            context = _clone_context_for_telegram_branch(
                parent_context,
                bot_name,
                bot_cfg,
                message.chat.id,
                message_thread_id,
                user.id,
                user.username,
                context_name=context_name,
            )
            with _chat_map_lock:
                state = _load_state()
                chats = state.setdefault("chats", {})
                key = _map_key(bot_name, user.id, message.chat.id, message_thread_id)
                chats[key] = context.id
                _save_state(state)
            PrintStyle.success(
                f"Telegram ({bot_name}): branched chat {parent_context.id} -> {context.id} thread={message_thread_id or 'main'}"
            )
            with suppress(Exception):
                from helpers.state_monitor_integration import mark_dirty_all
                mark_dirty_all(reason="telegram.branch_chat")
        except Exception as e:
            PrintStyle.error(f"Telegram: failed to branch context: {format_error(e)}")
            context = None
    else:
        context = await _get_or_create_context(
            bot_name,
            bot_cfg,
            message,
            force_new=True,
            message_thread_id=message_thread_id,
            context_name=context_name,
        )

    if context:
        if requested_name and command == "/branch":
            context.data["tg_topic_base_name"] = requested_name[:128]
            save_tmp_chat(context)
        if branch_seed:
            context.data[CTX_TG_BRANCH_SEED] = branch_seed
            seed_msg = (
                "Contexte de branche créé depuis ce message Telegram cité :\n\n"
                f"> {branch_seed}"
            )
            msg_id = str(uuid.uuid4())
            mq.log_user_message(context, seed_msg, [], message_id=msg_id, source=" (telegram branch seed)")
            context.communicate(UserMessage(message=seed_msg, id=msg_id))
            save_tmp_chat(context)
        target = f" dans le sujet « {requested_name} »" if requested_name and command == "/branch" else ""
        suffix = " avec le message cité comme point de départ" if branch_seed else ""
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Nouveau chat Agent Zero créé{target}{suffix}. ID: {context.id}",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )
    else:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Impossible de créer un nouveau chat Agent Zero.",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )


def _pop_topic_contexts(bot_name: str, chat_id: int, message_thread_id: int) -> list[tuple[str, str]]:
    """Remove Telegram topic mappings from state and return mapped Agent Zero context ids."""
    removed: list[tuple[str, str]] = []
    with _chat_map_lock:
        state = _load_state()
        chats = state.setdefault("chats", {})
        prefix = f"{bot_name}:"
        suffix = f":{chat_id}:{message_thread_id}"
        for key, ctx_id in list(chats.items()):
            if key.startswith(prefix) and key.endswith(suffix):
                chats.pop(key, None)
                removed.append((key, ctx_id))
        if removed:
            _save_state(state)
    return removed


def _get_context_project_name(context: AgentContext | None, ctx_id: str) -> str | None:
    """Return the Agent Zero project assigned to a chat context.

    Telegram topic archival must use the same project key as chat_project_filter.
    Agent Zero stores project assignment in context.data["project"] via
    helpers.projects.activate_project(...), not in /projects/<name>/chats/<ctx_id>.
    """
    if context:
        with suppress(Exception):
            project_name = context.get_data("project")
            if project_name:
                return str(project_name)
        if hasattr(context, "project") and context.project:
            return context.project.name

    projects_base = "/a0/usr/projects"
    if os.path.exists(projects_base):
        for proj in os.listdir(projects_base):
            if proj.startswith("_"):
                continue
            if os.path.exists(os.path.join(projects_base, proj, "chats", ctx_id)):
                return proj
    return None


def _archive_chat_like_chat_project_filter(ctx_id: str) -> str:
    """Archive then remove an Agent Zero chat using chat_project_filter's archive format."""
    import shutil
    from datetime import datetime

    context = AgentContext.use(ctx_id)
    if not context:
        raise RuntimeError(f"Context {ctx_id} not found")

    project_name = _get_context_project_name(context, ctx_id)
    if project_name:
        archive_dir = os.path.join("/a0/usr/projects", project_name, "chatProject")
    else:
        archive_dir = "/a0/usr/projects/_unassigned/chatProject"
    os.makedirs(archive_dir, exist_ok=True)

    chat_json = persist_chat.export_json_chat(context)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chat_name = getattr(context, "name", None) or f"Chat#{getattr(context, 'no', 'Unknown')}"
    safe_name = "".join(c for c in chat_name if c.isalnum() or c in (" ", "-", "_")).strip()
    safe_name = safe_name.replace(" ", "_")[:50]
    filename = f"{timestamp}_{safe_name}_{ctx_id[:8]}.json"
    file_path = os.path.join(archive_dir, filename)

    archive_data = {
        "original_ctxid": ctx_id,
        "original_name": chat_name,
        "project_name": project_name,
        "archived_at": datetime.now().isoformat(),
        "context_data": json.loads(chat_json) if isinstance(chat_json, str) else chat_json,
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=2, ensure_ascii=False)

    if context:
        context.reset()
    AgentContext.remove(ctx_id)
    chat_dir = f"/a0/usr/chats/{ctx_id}"
    if os.path.exists(chat_dir):
        shutil.rmtree(chat_dir)
    return file_path


def _close_chat(ctx_id: str):
    context = AgentContext.get(ctx_id)
    if context:
        context.reset()
    AgentContext.remove(ctx_id)
    persist_chat.remove_chat(ctx_id)


async def handle_forum_topic_closed(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Archive the Agent Zero chat mapped to a closed Telegram forum topic."""
    message_thread_id = getattr(message, "message_thread_id", None)
    if message_thread_id is None:
        return

    removed = _pop_topic_contexts(bot_name, message.chat.id, message_thread_id)

    archived_paths: list[str] = []
    for _, ctx_id in removed:
        try:
            archived_paths.append(_archive_chat_like_chat_project_filter(ctx_id))
        except Exception as e:
            PrintStyle.error(f"Telegram ({bot_name}): failed to archive closed topic context {ctx_id}: {format_error(e)}")

    if removed:
        PrintStyle.info(
            f"Telegram ({bot_name}): archived {len(archived_paths)}/{len(removed)} Agent Zero chat(s) for closed topic thread={message_thread_id}"
        )
        with suppress(Exception):
            from helpers.state_monitor_integration import mark_dirty_all
            mark_dirty_all(reason="telegram.forum_topic_closed")


async def handle_forum_topic_deleted(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Close the Agent Zero chat mapped to a deleted Telegram forum topic, if Telegram exposes this event."""
    message_thread_id = getattr(message, "message_thread_id", None)
    if message_thread_id is None:
        return

    removed = _pop_topic_contexts(bot_name, message.chat.id, message_thread_id)
    for _, ctx_id in removed:
        try:
            _close_chat(ctx_id)
        except Exception as e:
            PrintStyle.error(f"Telegram ({bot_name}): failed to close deleted topic context {ctx_id}: {format_error(e)}")

    if removed:
        PrintStyle.info(
            f"Telegram ({bot_name}): closed {len(removed)} Agent Zero chat(s) for deleted topic thread={message_thread_id}"
        )
        with suppress(Exception):
            from helpers.state_monitor_integration import mark_dirty_all
            mark_dirty_all(reason="telegram.forum_topic_deleted")


async def handle_restart(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Restart Agent Zero using the same reload mechanism as the UI Restart button."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_restart bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)}")
    if not user:
        return
    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    await _send_with_temp_bot(
        instance.bot.token, message.chat.id,
        "Redémarrage d’Agent Zero demandé. Je reviens dans quelques secondes.",
        parse_mode=None,
        message_thread_id=getattr(message, "message_thread_id", None),
    )

    def _reload_later():
        with suppress(Exception):
            PrintStyle.info(f"Telegram ({bot_name}): restarting Agent Zero via /restart")
        a0_process.reload()

    threading.Timer(1.0, _reload_later).start()


async def handle_topicname(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Diagnostic command: rename the current Telegram forum topic directly."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_topicname bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)}")
    if not user:
        return
    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    text = message.text or message.caption or ""
    _, requested_name = _parse_slash_command(text)
    requested_name = (requested_name or "").strip()
    message_thread_id = getattr(message, "message_thread_id", None)

    if not requested_name:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Usage : /topicname <nouveau nom du sujet>",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )
        return
    if message_thread_id is None:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Impossible : Telegram ne fournit pas l’ID du sujet courant pour cette commande.",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )
        return

    name = requested_name[:128].strip()
    try:
        async with _temp_bot(instance.bot.token) as topic_bot:
            await topic_bot.edit_forum_topic(
                chat_id=message.chat.id,
                message_thread_id=message_thread_id,
                name=name,
            )
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Sujet renommé : {name}",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )
        PrintStyle.info(f"Telegram ({bot_name}): /topicname renamed thread={message_thread_id} to {name!r}")
    except Exception as e:
        error = format_error(e)
        PrintStyle.error(f"Telegram ({bot_name}): /topicname failed thread={message_thread_id} name={name!r}: {error}")
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Erreur renommage sujet : {error}",
            parse_mode=None,
            message_thread_id=message_thread_id,
        )


async def handle_pause(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Pause the active Agent Zero run for this Telegram chat/topic."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_pause bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)}")
    if not user:
        return
    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    context = await _get_or_create_context(bot_name, bot_cfg, message)
    if not context:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Impossible de trouver/créer la session à mettre en pause.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    try:
        context.paused = True
        save_tmp_chat(context)
        with suppress(Exception):
            from helpers.state_monitor_integration import mark_dirty_for_context
            mark_dirty_for_context(context.id, reason="telegram.pause")
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Agent mis en pause.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
    except Exception as e:
        PrintStyle.error(f"Telegram pause failed: {e}")
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Erreur pause : {format_error(e)}",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )


async def handle_nudge(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Nudge the active Agent Zero run for this Telegram chat/topic."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_nudge bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)}")
    if not user:
        return
    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    context = await _get_or_create_context(bot_name, bot_cfg, message)
    if not context:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Impossible de trouver/créer la session à relancer.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    try:
        context.nudge()
        save_tmp_chat(context)
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "✅ Nudge envoyé à l’agent.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
    except Exception as e:
        PrintStyle.error(f"Telegram nudge failed: {e}")
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Erreur nudge : {format_error(e)}",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )


async def handle_message(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Handle incoming user message."""
    user = message.from_user
    PrintStyle.info(f"Telegram handle_message bot={bot_name} chat={message.chat.id} user={getattr(user, 'id', None)} text={(getattr(message, 'text', None) or getattr(message, 'caption', None) or '')[:80]!r}")
    if not user:
        return

    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    text = _extract_message_content(message)
    context = await _get_or_create_context(bot_name, bot_cfg, message)
    if not context:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Failed to create chat session.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    # Telegram-specific /now and /later handling.
    # /now <prompt> forces an immediate intervention (native Agent Zero behavior),
    # /later <prompt> stores work without interrupting the current run.
    command, command_args = _parse_slash_command(text)
    if command == "/restart":
        await handle_restart(message, bot_name, bot_cfg)
        return
    if command == "/topicname":
        await handle_topicname(message, bot_name, bot_cfg)
        return
    if command == "/pause":
        await handle_pause(message, bot_name, bot_cfg)
        return
    if command == "/now":
        if not command_args:
            await _send_with_temp_bot(
                instance.bot.token, message.chat.id,
                "Usage : /now <message> — interrompt le raisonnement courant et envoie immédiatement.",
                parse_mode=None,
                message_thread_id=getattr(message, "message_thread_id", None),
            )
            return
        text = command_args
    elif command == "/later" and command_args:
        async with _temp_bot(instance.bot.token) as dl_bot:
            attachments = await _download_attachments(dl_bot, message, bot_name=bot_name)
            attachments += await _download_quoted_attachments(dl_bot, message, bot_name=bot_name)
        agent = context.agent0
        queued_body = _with_quoted_message_context(message, command_args)
        queued_msg = agent.read_prompt(
            "fw.telegram.user_message.md",
            sender=_format_user(user),
            body=queued_body,
        )
        item = mq.add(context, queued_msg, attachments)
        save_tmp_chat(context)
        with suppress(Exception):
            from helpers.state_monitor_integration import mark_dirty_for_context
            mark_dirty_for_context(context.id, reason="telegram.queue_add")
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            f"Ajouté à la queue #{item.get('seq')}. Utilise /send ou /queue send pour lancer.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    command_reply = integration_commands.try_handle_command(context, text)
    if command_reply is not None:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id, command_reply,
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    # Start persistent typing indicator (thread-based, works across event loops)
    typing_stop = _start_typing(instance.bot.token, message.chat.id, getattr(message, "message_thread_id", None))

    # Store stop event so send_telegram_reply can cancel typing
    context.data[CTX_TG_TYPING_STOP] = typing_stop

    # Preserve Telegram forum topic/thread so replies stay in the originating subject.
    thread_id = getattr(message, "message_thread_id", None)
    context.data[CTX_TG_MESSAGE_THREAD_ID] = thread_id

    # In group chats, if user replied to the bot's message, reply to the user's message
    reply_to_id = None
    if message.chat.type != "private" and instance.bot_info:
        if (message.reply_to_message
                and message.reply_to_message.from_user
                and message.reply_to_message.from_user.id == instance.bot_info.id):
            reply_to_id = message.message_id
    context.data[CTX_TG_REPLY_TO] = reply_to_id

    # Use temp bot for downloads (cross-event-loop safe)
    async with _temp_bot(instance.bot.token) as dl_bot:
        attachments = await _download_attachments(dl_bot, message, bot_name=bot_name)
        attachments += await _download_quoted_attachments(dl_bot, message, bot_name=bot_name)

    # Build user message with prompt, including Telegram quoted/replied message context.
    agent = context.agent0
    body_text = _with_quoted_message_context(message, text)
    user_msg = agent.read_prompt(
        "fw.telegram.user_message.md",
        sender=_format_user(user),
        body=body_text,
    )

    msg_id = str(uuid.uuid4())
    mq.log_user_message(context, user_msg, attachments, message_id=msg_id, source=" (telegram)")
    context.communicate(UserMessage(
        message=user_msg,
        attachments=attachments,
        id=msg_id,
    ))

    save_tmp_chat(context)

    # Send notification
    if bot_cfg.get("notify_messages", False):
        username_str = f"@{user.username}" if user.username else str(user.id)
        preview = (text[:80] + "...") if len(text) > 80 else text
        NotificationManager.send_notification(
            type=NotificationType.INFO,
            priority=NotificationPriority.HIGH,
            title="Telegram: new message",
            message=f"From {username_str}: {preview}",
            display_time=10,
            group="telegram",
        )


def _parse_slash_command(text: str) -> tuple[str, str]:
    line = ""
    for candidate in (text or "").splitlines():
        candidate = candidate.strip()
        if candidate:
            line = candidate
            break
    if not line.startswith("/"):
        return "", ""
    command, _, args = line.partition(" ")
    command = command.split("@", 1)[0].strip().lower()
    return command, args.strip()


def _chunk_rows(items: list[dict], per_row: int = 1) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for i in range(0, len(items), per_row):
        rows.append(items[i:i + per_row])
    return rows


def _active_project_items() -> list[dict]:
    try:
        return projects.get_active_projects_list() or []
    except Exception:
        items: list[dict] = []
        base = "/a0/usr/projects"
        if not os.path.isdir(base):
            return items
        for name in sorted(os.listdir(base)):
            if name.startswith("_"):
                continue
            header = os.path.join(base, name, ".a0proj", "project.json")
            if not os.path.isfile(header):
                continue
            title = name
            with suppress(Exception):
                data = json.loads(files.read_file(header))
                title = data.get("title") or name
            items.append({"name": name, "title": title})
        return items


def _project_label(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    name = str(item.get("name") or "").strip()
    if title and title.lower() != name.lower():
        return f"{title} ({name})"
    return title or name


def _project_picker_keyboard(items: list[dict], current: str | None, message_thread_id: int | None, context_id: str | None = None) -> list[list[dict]]:
    """Build the project picker.

    Prefer encoding the AgentContext id in callback data. Telegram sometimes
    omits message_thread_id on inline callbacks, while the context always stores
    the originating topic id. The legacy thread-based callback remains supported
    by _handle_project_callback for already displayed keyboards.
    """
    current = str(current or "").strip()
    if context_id:
        callback_prefix = f"tg_project_ctx:{context_id}"
    else:
        thread_part = str(message_thread_id) if message_thread_id is not None else "main"
        callback_prefix = f"tg_project:{thread_part}"
    buttons = []
    for index, item in enumerate(items[:48]):
        name = item.get("name") or ""
        label = _project_label(item)
        prefix = "✅ " if name == current else ""
        if context_id:
            callback_data = f"{callback_prefix}:i:{index}"
        else:
            callback_data = f"{callback_prefix}:{name}"
        buttons.append({"text": (prefix + label)[:64], "callback_data": callback_data[:64]})
    buttons.append({"text": "❌ Aucun projet", "callback_data": f"{callback_prefix}:none"[:64]})
    return _chunk_rows(buttons, 1)


async def handle_affect_project(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Show an inline project picker to assign the current Telegram chat/topic."""
    user = message.from_user
    if not user:
        return
    if not _is_allowed(bot_cfg, user.id, user.username):
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    context = await _get_or_create_context(bot_name, bot_cfg, message)
    current = context.get_data("project") if context else ""
    items = _active_project_items()
    if not items:
        await _send_with_temp_bot(
            instance.bot.token, message.chat.id,
            "Aucun projet actif disponible.",
            parse_mode=None,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        return

    message_thread_id = getattr(message, "message_thread_id", None)
    keyboard = _project_picker_keyboard(items, current, message_thread_id, context.id if context else None)

    current_label = current or "aucun"
    await _send_with_temp_bot(
        instance.bot.token, message.chat.id,
        f"Projet actuel : {current_label}\nChoisis le projet à associer à ce chat :",
        parse_mode=None,
        message_thread_id=getattr(message, "message_thread_id", None),
        keyboard=keyboard,
    )


def _strip_project_prefix_from_topic(name: str) -> str:
    name = str(name or "").strip()
    # Remove prefixes previously generated by this plugin to avoid stacking.
    return re.sub(r"^.+?\s+[—-]\s+", "", name, count=1).strip() or name


def _telegram_topic_project_name(label: str | None, base_name: str | None = None) -> str:
    label = str(label or "").strip()
    base_name = _strip_project_prefix_from_topic(base_name or "")
    if not label:
        name = base_name or "Agent Zero"
    elif base_name and base_name.lower() != label.lower():
        name = f"{label} — {base_name}"
    else:
        name = label or base_name or "Agent Zero"
    # Telegram forum topic names are limited to 128 chars; keep the project visible first.
    return name[:128].strip()


def _remember_topic_base_name(context: AgentContext | None, base_name: str | None) -> None:
    if not context:
        return
    base_name = _strip_project_prefix_from_topic(base_name or "")
    if base_name:
        context.data["tg_topic_base_name"] = base_name[:128]


async def _rename_forum_topic_for_project(instance, chat_id: int, message_thread_id: int | None, label: str | None, base_name: str | None = None) -> str | None:
    if not instance or message_thread_id is None:
        return None
    name = _telegram_topic_project_name(label, base_name)
    token = getattr(getattr(instance, "bot", None), "token", None)
    if not token:
        return None
    try:
        async with _temp_bot(token) as topic_bot:
            await topic_bot.edit_forum_topic(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                name=name,
            )
        PrintStyle.info(f"Telegram: renamed forum topic thread={message_thread_id} to {name!r}")
        return name
    except Exception as e:
        PrintStyle.error(f"Telegram: failed to rename forum topic thread={message_thread_id} to {name!r}: {format_error(e)}")
        return None


async def _refresh_project_picker_message(query: CallbackQuery, instance, items: list[dict], current: str | None, message_thread_id: int | None, context_id: str | None = None) -> None:
    """Edit the inline project picker so the green tick moves immediately."""
    if not instance or not query.message:
        return
    token = getattr(getattr(instance, "bot", None), "token", None)
    if not token:
        return
    try:
        keyboard = tc.build_inline_keyboard(_project_picker_keyboard(items, current, message_thread_id, context_id))
        current_label = current or "aucun"
        async with _temp_bot(token) as picker_bot:
            await picker_bot.edit_message_text(
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
                text=f"Projet actuel : {current_label}\nChoisis le projet à associer à ce chat :",
                reply_markup=keyboard,
                parse_mode=None,
            )
    except Exception as e:
        PrintStyle.error(f"Telegram: failed to refresh project picker: {format_error(e)}")


async def _handle_project_callback(query: CallbackQuery, bot_name: str, bot_cfg: dict) -> bool:
    data = query.data or ""
    if not (data.startswith("tg_project:") or data.startswith("tg_project_ctx:")):
        return False

    user = query.from_user
    if not user or not query.message:
        return True
    if not _is_allowed(bot_cfg, user.id, user.username):
        await query.answer("Non autorisé.")
        return True

    context = None
    message_thread_id = getattr(query.message, "message_thread_id", None)
    context_id = None

    if data.startswith("tg_project_ctx:"):
        raw_payload = data.split(":", 1)[1]
        payload_parts = raw_payload.split(":", 1)
        if len(payload_parts) != 2:
            await query.answer("Callback projet invalide.")
            return True
        context_id, selected = payload_parts
        context = AgentContext.get(context_id)
        if context:
            stored_thread_id = context.data.get(CTX_TG_MESSAGE_THREAD_ID)
            if stored_thread_id is not None:
                with suppress(Exception):
                    message_thread_id = int(stored_thread_id)
        if selected.startswith("i:"):
            with suppress(Exception):
                project_index = int(selected.split(":", 1)[1])
                indexed_items = _active_project_items()
                if 0 <= project_index < len(indexed_items[:48]):
                    selected = indexed_items[project_index].get("name") or ""
    else:
        raw_payload = data.split(":", 1)[1]
        payload_parts = raw_payload.split(":", 1)
        if len(payload_parts) == 2 and (payload_parts[0] == "main" or payload_parts[0].isdigit()):
            thread_part, selected = payload_parts
            callback_thread_id = getattr(query.message, "message_thread_id", None)
            # Older project pickers used "main" when Telegram did not expose the
            # thread at send time. On callback, Telegram can still include the real
            # message_thread_id; prefer it so old buttons can rename the topic too.
            if thread_part == "main":
                message_thread_id = callback_thread_id
            else:
                message_thread_id = int(thread_part)
        else:
            selected = raw_payload
            message_thread_id = getattr(query.message, "message_thread_id", None)

    if context is None:
        context = await _get_or_create_context_from_user(
            bot_name, bot_cfg, user.id, user.username, query.message.chat.id,
            message_thread_id,
        )
    if not context:
        await query.answer("Contexte introuvable.")
        return True

    # Telegram callback messages can omit message_thread_id. Fall back to the
    # context value so topic renaming is not skipped after selecting a project.
    if message_thread_id is None:
        stored_thread_id = context.data.get(CTX_TG_MESSAGE_THREAD_ID)
        if stored_thread_id is not None:
            with suppress(Exception):
                message_thread_id = int(stored_thread_id)

    instance = get_bot(bot_name)
    if selected == "none":
        projects.deactivate_project(context.id)
        save_tmp_chat(context)
        with suppress(Exception):
            from helpers.state_monitor_integration import mark_dirty_for_context
            mark_dirty_for_context(context.id, reason="telegram.project_assign_clear")
        await query.answer("Projet retiré.")
        if instance:
            items = _active_project_items()
            await _refresh_project_picker_message(query, instance, items, "", message_thread_id, context.id)
            base_name = context.data.get("tg_topic_base_name") or getattr(context, "name", "")
            _remember_topic_base_name(context, base_name)
            renamed_to = await _rename_forum_topic_for_project(instance, query.message.chat.id, message_thread_id, None, base_name)
            if renamed_to:
                context.data["tg_topic_name"] = renamed_to
                save_tmp_chat(context)
            await _send_with_temp_bot(instance.bot.token, query.message.chat.id, "Projet retiré de ce chat. Le préfixe du sujet a été retiré.", parse_mode=None, message_thread_id=message_thread_id)
        return True

    items = _active_project_items()
    match = next((item for item in items if item.get("name") == selected), None)
    if not match:
        await query.answer("Projet introuvable.")
        return True

    projects.activate_project(context.id, selected)
    save_tmp_chat(context)
    with suppress(Exception):
        from helpers.state_monitor_integration import mark_dirty_for_context
        mark_dirty_for_context(context.id, reason="telegram.project_assign_set")
    label = _project_label(match)
    await query.answer(f"Associé à {label}")
    if instance:
        await _refresh_project_picker_message(query, instance, items, selected, message_thread_id, context.id)
        base_name = context.data.get("tg_topic_base_name") or getattr(context, "name", "")
        _remember_topic_base_name(context, base_name)
        renamed_to = await _rename_forum_topic_for_project(instance, query.message.chat.id, message_thread_id, label, base_name)
        if renamed_to:
            context.data["tg_topic_name"] = renamed_to
        save_tmp_chat(context)
        suffix = f"\nSujet renommé : {renamed_to}" if renamed_to else ""
        await _send_with_temp_bot(instance.bot.token, query.message.chat.id, f"Chat associé au projet : {label}{suffix}", parse_mode=None, message_thread_id=message_thread_id)
    return True


async def handle_callback_query(query: CallbackQuery, bot_name: str, bot_cfg: dict):
    """Handle inline keyboard button press."""
    if await _handle_project_callback(query, bot_name, bot_cfg):
        return

    user = query.from_user
    if not user or not query.message:
        return

    if not _is_allowed(bot_cfg, user.id, user.username):
        await query.answer("Not authorized.")
        return

    await query.answer()

    # Treat callback data as a user message
    text = query.data or ""
    if not text:
        return

    message_thread_id = getattr(query.message, "message_thread_id", None)
    context = await _get_or_create_context_from_user(
        bot_name, bot_cfg, user.id, user.username, query.message.chat.id,
        message_thread_id,
    )
    if not context:
        return

    command_reply = integration_commands.try_handle_command(context, text)
    if command_reply is not None:
        instance = get_bot(bot_name)
        if instance:
            await _send_with_temp_bot(
                instance.bot.token, query.message.chat.id, command_reply,
                parse_mode=None,
                message_thread_id=message_thread_id,
            )
        return

    agent = context.agent0
    user_msg = agent.read_prompt(
        "fw.telegram.user_message.md",
        sender=_format_user(user),
        body=f"[Button pressed: {text}]",
    )

    msg_id = str(uuid.uuid4())
    mq.log_user_message(context, user_msg, [], message_id=msg_id, source=" (telegram)")
    context.communicate(UserMessage(message=user_msg, id=msg_id))
    save_tmp_chat(context)


async def handle_new_members(message: TgMessage, bot_name: str, bot_cfg: dict):
    """Send welcome message when new members join a group."""
    if not bot_cfg.get("welcome_enabled", False):
        return

    new_members = message.new_chat_members or []
    if not new_members:
        return

    instance = get_bot(bot_name)
    if not instance:
        return

    template = bot_cfg.get("welcome_message", "").strip()
    if not template:
        template = "Welcome, {name}!"

    for member in new_members:
        if member.is_bot:
            continue
        name = member.full_name or member.first_name or str(member.id)
        text = template.replace("{name}", name)
        await _send_with_temp_bot(instance.bot.token, message.chat.id, text, parse_mode=None)

# Context management

async def _get_or_create_context(
    bot_name: str,
    bot_cfg: dict,
    message: TgMessage,
    force_new: bool = False,
    message_thread_id: int | None = None,
    context_name: str | None = None,
) -> AgentContext | None:
    user = message.from_user
    if not user:
        return None
    if message_thread_id is None:
        message_thread_id = getattr(message, "message_thread_id", None)
    return await _get_or_create_context_from_user(
        bot_name, bot_cfg, user.id, user.username, message.chat.id,
        message_thread_id,
        force_new=force_new,
        context_name=context_name,
    )


async def _get_or_create_context_from_user(
    bot_name: str,
    bot_cfg: dict,
    user_id: int,
    username: str | None,
    chat_id: int,
    message_thread_id: int | None = None,
    force_new: bool = False,
    context_name: str | None = None,
) -> AgentContext | None:
    key = _map_key(bot_name, user_id, chat_id, message_thread_id)

    with _chat_map_lock:
        state = _load_state()
        chats = state.setdefault("chats", {})
        ctx_id = None if force_new else chats.get(key)

        # Check if existing context is still alive
        if ctx_id:
            ctx = AgentContext.get(ctx_id)
            if ctx:
                ctx.data[CTX_TG_MESSAGE_THREAD_ID] = message_thread_id
                return ctx
            # Context was garbage collected, remove stale mapping
            chats.pop(key, None)

        # Create new context
        try:
            config = initialize_agent()
            display_name = f"@{username}" if username else str(user_id)
            chat_name = context_name or f"Telegram: {display_name}"
            ctx = AgentContext(config, name=chat_name)

            ctx.data[CTX_TG_BOT] = bot_name
            ctx.data[CTX_TG_BOT_CFG] = bot_cfg
            ctx.data[CTX_TG_CHAT_ID] = chat_id
            ctx.data[CTX_TG_MESSAGE_THREAD_ID] = message_thread_id
            ctx.data[CTX_TG_USER_ID] = user_id
            ctx.data[CTX_TG_USERNAME] = username or ""

            project = _get_project(bot_cfg, user_id)
            if project:
                projects.activate_project(ctx.id, project)

            # Inherit model override from an existing context in the same project
            _inherit_model_override(ctx)

            chats[key] = ctx.id
            _save_state(state)

            PrintStyle.success(
                f"Telegram ({bot_name}): new chat {ctx.id} for user {display_name} thread={message_thread_id or 'main'}"
            )
            return ctx

        except Exception as e:
            PrintStyle.error(f"Telegram: failed to create context: {format_error(e)}")
            return None

# Message content extraction

def _format_telegram_sender_from_message(message: TgMessage) -> str:
    user = getattr(message, "from_user", None)
    if not user:
        return "expéditeur inconnu"
    return _format_user(user)


def _extract_quoted_message_context(message: TgMessage) -> str:
    """Return readable context for the Telegram message quoted/replied to, if any."""
    replied = getattr(message, "reply_to_message", None)
    if not replied:
        return ""

    parts: list[str] = []
    sender = _format_telegram_sender_from_message(replied)
    quoted_text = (getattr(replied, "text", None) or getattr(replied, "caption", None) or "").strip()
    if quoted_text:
        parts.append(quoted_text[:4000])

    indicators: list[str] = []
    checks = [
        ("photo", "photo"),
        ("document", "document"),
        ("audio", "audio"),
        ("voice", "message vocal"),
        ("video", "vidéo"),
        ("video_note", "note vidéo"),
        ("animation", "animation"),
        ("sticker", "sticker"),
        ("location", "localisation"),
        ("contact", "contact"),
    ]
    for attr, label in checks:
        if getattr(replied, attr, None):
            indicators.append(label)
    if indicators:
        parts.append("[Pièce(s)/contenu cité(s) : " + ", ".join(indicators) + "]")

    body = "\n".join(parts).strip() or "[Message Telegram cité sans texte exploitable]"
    return f"Message Telegram cité par l’utilisateur (contexte pour comprendre 'ceci') — {sender}:\n{body}"


def _with_quoted_message_context(message: TgMessage, body: str) -> str:
    quoted = _extract_quoted_message_context(message)
    body = (body or "").strip()
    if not quoted:
        return body
    return f"{quoted}\n\nMessage actuel de l’utilisateur:\n{body}"


def _extract_message_content(message: TgMessage) -> str:
    parts = []

    if message.text:
        parts.append(message.text)
    elif message.caption:
        parts.append(message.caption)

    if message.location:
        loc = message.location
        parts.append(f"[Location: {loc.latitude}, {loc.longitude}]")

    if message.contact:
        c = message.contact
        parts.append(f"[Contact: {c.first_name} {c.last_name or ''} phone={c.phone_number}]")

    if message.sticker:
        parts.append(f"[Sticker: {message.sticker.emoji or ''}]")

    # Simple attachment indicators
    for attr, label in [("voice", "Voice message"), ("video_note", "Video note")]:
        if getattr(message, attr, None):
            parts.append(f"[{label} — see attachment]")

    return "\n".join(parts) if parts else "[No text content]"


async def _download_quoted_attachments(bot, message: TgMessage, bot_name: str = "") -> list[str]:
    """Download attachments from the Telegram message quoted/replied to, if any."""
    replied = getattr(message, "reply_to_message", None)
    if not replied:
        return []
    try:
        return await _download_attachments(bot, replied, bot_name=bot_name)
    except Exception as e:
        PrintStyle.error(f"Telegram: failed to download quoted attachments: {format_error(e)}")
        return []


async def _download_attachments(bot, message: TgMessage, bot_name: str = "") -> list[str]:
    """Download photos, documents, audio, voice, video from message."""
    paths: list[str] = []
    tg_prefix = f"tg_{bot_name}_" if bot_name else "tg_"
    # Host-local path for actual file I/O
    download_dir = files.get_abs_path(DOWNLOAD_FOLDER)
    os.makedirs(download_dir, exist_ok=True)
    # Docker-style path for agent references
    download_dir_ref = files.get_abs_path_dockerized(DOWNLOAD_FOLDER)

    async def _dl(file_id: str, filename: str) -> str | None:
        safe_name = f"{tg_prefix}{uuid.uuid4().hex[:8]}_{filename}"
        dest = os.path.join(download_dir, safe_name)
        result = await tc.download_file(bot, file_id, dest)
        if result:
            return os.path.join(download_dir_ref, safe_name)
        return None

    # Photo: get largest resolution
    if message.photo:
        photo = message.photo[-1]
        path = await _dl(photo.file_id, f"photo_{photo.file_unique_id}.jpg")
        if path:
            paths.append(path)

    # Other attachment types: (attr, default_prefix, default_ext)
    _types = [
        ("document",   "file",      None),
        ("audio",      "audio",     ".mp3"),
        ("voice",      "voice",     ".ogg"),
        ("video",      "video",     ".mp4"),
        ("video_note", "videonote", ".mp4"),
    ]
    for attr, prefix, ext in _types:
        obj = getattr(message, attr, None)
        if not obj:
            continue
        fname = getattr(obj, "file_name", None) or f"{prefix}_{obj.file_unique_id}{ext or ''}"
        path = await _dl(obj.file_id, fname)
        if path:
            paths.append(path)

    return paths


def _sanitize_telegram_outbound_text(text: str) -> str:
    """Remove unwanted Agent Zero mobile/status prefixes before Telegram delivery."""
    if not text:
        return text

    cleaned = text.replace("\ufeff", "")
    # Strip leading whitespace and repeated status prefixes such as:
    # "GEN", "GEN 🔵", "🔵", "🟦", bullets/dots/check/status emojis.
    prefix_re = re.compile(
        r"^(?:\s|(?:GEN\b[\s:：\-–—]*)|[🔵🟦🔷🔹🔘●•◦○✅☑️✔️🟢🟡🟠🔴⚪⚫]\s*)+",
        re.IGNORECASE,
    )
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = prefix_re.sub("", cleaned)
    return cleaned.lstrip()

# Reply sending (called from process_chain_end extension)

async def send_telegram_reply(
    context: AgentContext,
    response_text: str,
    attachments: list[str] | None = None,
    keyboard: list[list[dict]] | None = None,
    voice: bool = False,
) -> str | None:
    """Send reply to Telegram user. Returns error string or None on success."""
    bot_name = context.data.get(CTX_TG_BOT)
    if not bot_name:
        return "No Telegram bot configured on context"

    instance = get_bot(bot_name)
    if not instance:
        return f"Bot '{bot_name}' not running"

    chat_id = context.data.get(CTX_TG_CHAT_ID)
    if not chat_id:
        return "No chat_id on context"

    reply_to = context.data.get(CTX_TG_REPLY_TO)
    message_thread_id = context.data.get(CTX_TG_MESSAGE_THREAD_ID)

    try:
        async with _temp_bot(instance.bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as reply_bot:
            if attachments:
                for path in attachments:
                    local_path = files.fix_dev_path(path)
                    if tc.is_image_file(local_path):
                        await tc.send_photo(reply_bot, chat_id, local_path, reply_to_message_id=reply_to, message_thread_id=message_thread_id)
                    else:
                        await tc.send_file(reply_bot, chat_id, local_path, reply_to_message_id=reply_to, message_thread_id=message_thread_id)

            if response_text:
                response_text = _sanitize_telegram_outbound_text(response_text)
                if voice:
                    voice_path = await _generate_telegram_voice(response_text)
                    if voice_path:
                        await tc.send_voice(reply_bot, chat_id, voice_path, reply_to_message_id=reply_to, message_thread_id=message_thread_id)
                    else:
                        PrintStyle.error("Telegram voice requested but TTS generation returned no file; falling back to text")
                html_text = tc.md_to_telegram_html(response_text)
                if keyboard:
                    await tc.send_text_with_keyboard(reply_bot, chat_id, html_text, keyboard, reply_to_message_id=reply_to, message_thread_id=message_thread_id)
                else:
                    await tc.send_text(reply_bot, chat_id, html_text, reply_to_message_id=reply_to, message_thread_id=message_thread_id)

        return None

    except Exception as e:
        error = format_error(e)
        PrintStyle.error(f"Telegram reply failed: {error}")
        return error


async def _generate_telegram_voice(text: str) -> str | None:
    """Generate an OGG/Opus voice note for Telegram using Agent Zero Kokoro TTS."""
    clean = _sanitize_telegram_outbound_text(text or "").strip()
    if not clean:
        return None
    # Keep voice notes concise and avoid speaking huge technical outputs.
    clean = re.sub(r"```.*?```", "", clean, flags=re.S).strip()
    clean = re.sub(r"[`*_~#]", "", clean)
    clean = clean[:1800]
    try:
        from helpers.kokoro_tts import synthesize_sentences
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", clean) if part.strip()] or [clean]
        audio_b64 = await synthesize_sentences(sentences[:12])
        if not audio_b64:
            return None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_file.write(base64.b64decode(audio_b64))
            wav_path = wav_file.name
        ogg_path = wav_path.rsplit(".", 1)[0] + ".ogg"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path, "-c:a", "libopus", "-b:a", "32k", "-application", "voip", ogg_path],
            check=True,
        )
        with suppress(Exception):
            os.unlink(wav_path)
        return ogg_path
    except Exception as e:
        PrintStyle.error(f"Telegram TTS generation failed: {format_error(e)}")
        return None

# Helpers

@asynccontextmanager
async def _temp_bot(token: str, **kwargs):
    """Create a temporary Bot, yield it, and ensure the session is closed."""
    bot = Bot(token=token, **kwargs)
    try:
        yield bot
    finally:
        with suppress(Exception):
            await bot.session.close()


async def _send_with_temp_bot(
    token: str,
    chat_id: int,
    text: str,
    parse_mode: str | None = None,
    message_thread_id: int | None = None,
    keyboard: list[list[dict]] | None = None,
):
    """Send text using a temporary Bot to avoid cross-event-loop session issues."""
    text = _sanitize_telegram_outbound_text(text)
    async with _temp_bot(token) as bot:
        if keyboard:
            await tc.send_text_with_keyboard(
                bot,
                chat_id,
                text,
                keyboard,
                parse_mode=parse_mode,
                message_thread_id=message_thread_id,
            )
        else:
            await tc.send_text(bot, chat_id, text, parse_mode=parse_mode, message_thread_id=message_thread_id)


def _start_typing(token: str, chat_id: int, message_thread_id: int | None = None) -> threading.Event:
    """Spawn a daemon thread that sends typing every 4s. Returns a stop Event."""
    stop = threading.Event()

    def _run():
        import asyncio

        async def _loop():
            async with _temp_bot(token) as bot:
                while not stop.is_set():
                    await tc.send_typing(bot, chat_id, message_thread_id=message_thread_id)
                    for _ in range(8):
                        if stop.is_set():
                            return
                        await asyncio.sleep(0.5)

        try:
            asyncio.run(_loop())
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
    return stop


def _format_user(user) -> str:
    name = user.first_name or ""
    if user.last_name:
        name += f" {user.last_name}"
    if user.username:
        name += f" (@{user.username})"
    return name.strip() or str(user.id)


def _inherit_model_override(ctx: AgentContext):
    """Copy chat_model_override from the most recent sibling context in the same project."""
    project = ctx.get_data("project")
    if not project:
        return
    try:
        from plugins._model_config.helpers.model_config import is_chat_override_allowed
        if not is_chat_override_allowed(ctx.agent0):
            return
    except Exception:
        return
    source = max(
        (c for c in AgentContext.all()
         if c.id != ctx.id and c.get_data("project") == project and c.get_data("chat_model_override")),
        key=lambda c: c.last_message,
        default=None,
    )
    if source:
        ctx.set_data("chat_model_override", source.get_data("chat_model_override"))
