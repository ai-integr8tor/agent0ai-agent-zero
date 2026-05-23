import asyncio
import os
import time
import traceback

from helpers.api import ApiHandler, Request, Response
from helpers.print_style import PrintStyle
from plugins._telegram_integration.helpers.dependencies import ensure_dependencies

_SEEN_UPDATES: dict[str, float] = {}
_SEEN_TTL_SECONDS = 600
_BACKGROUND_TASKS: set[asyncio.Task] = set()
_BOOTSTRAP_LOCKS: dict[str, asyncio.Lock] = {}
_TRACE_FILE = "/a0/logs/telegram_webhook_trace.log"


def _trace(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(_TRACE_FILE), exist_ok=True)
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def _track_background_task(task: asyncio.Task) -> None:
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _ensure_instance_locked(bot_name: str):
    from plugins._telegram_integration.helpers.bot_manager import ensure_bot_running_from_config

    lock = _BOOTSTRAP_LOCKS.setdefault(bot_name, asyncio.Lock())
    async with lock:
        return await ensure_bot_running_from_config(bot_name)


def _cleanup_seen_updates() -> None:
    now = time.time()
    for key, ts in list(_SEEN_UPDATES.items()):
        if now - ts > _SEEN_TTL_SECONDS:
            _SEEN_UPDATES.pop(key, None)


def _is_duplicate(bot_name: str, update_id: int | None) -> bool:
    if update_id is None:
        return False
    _cleanup_seen_updates()
    return f"{bot_name}:{update_id}" in _SEEN_UPDATES


def _mark_processed(bot_name: str, update_id: int | None) -> None:
    if update_id is None:
        return
    _cleanup_seen_updates()
    _SEEN_UPDATES[f"{bot_name}:{update_id}"] = time.time()


def get_bot_instance(bot_name: str):
    from plugins._telegram_integration.helpers.bot_manager import get_bot
    return get_bot(bot_name)


async def _direct_process_update(bot_name: str, bot_cfg: dict, update_data: dict) -> bool:
    """Hermes-style direct processing path.

    Aiogram dispatcher is still available as fallback, but direct routing avoids losing
    updates if router/filter state is broken after hot restarts.
    """
    from aiogram.types import Update
    from plugins._telegram_integration.helpers.handler import (
        handle_start,
        handle_clear,
        handle_new_chat,
        handle_message,
        handle_nudge,
        handle_pause,
        handle_restart,
        handle_affect_project,
        handle_callback_query,
        handle_new_members,
        handle_forum_topic_closed,
    )

    update = Update.model_validate(update_data, context={"bot": get_bot_instance(bot_name).bot if get_bot_instance(bot_name) else None})
    msg = update.message or update.edited_message
    if update.callback_query:
        _trace(f"direct callback bot={bot_name} user={getattr(update.callback_query.from_user, 'id', None)}")
        await handle_callback_query(update.callback_query, bot_name, bot_cfg)
        return True

    if not msg:
        return False

    user_id = getattr(getattr(msg, "from_user", None), "id", None)
    chat_id = getattr(getattr(msg, "chat", None), "id", None)
    text = msg.text or msg.caption or ""
    content_type = getattr(msg, "content_type", "")
    _trace(f"direct message bot={bot_name} user={user_id} chat={chat_id} type={content_type} text={text[:120]!r}")

    if getattr(msg, "new_chat_members", None):
        await handle_new_members(msg, bot_name, bot_cfg)
        return True
    if getattr(msg, "forum_topic_closed", None):
        await handle_forum_topic_closed(msg, bot_name, bot_cfg)
        return True

    command = ""
    if text.startswith("/"):
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()

    if command == "/start":
        await handle_start(msg, bot_name, bot_cfg)
    elif command == "/clear":
        await handle_clear(msg, bot_name, bot_cfg)
    elif command in ("/new", "/branch"):
        await handle_new_chat(msg, bot_name, bot_cfg)
    elif command in ("/project", "/projets"):
        await handle_affect_project(msg, bot_name, bot_cfg)
    elif command == "/nudge":
        await handle_nudge(msg, bot_name, bot_cfg)
    elif command == "/pause":
        await handle_pause(msg, bot_name, bot_cfg)
    elif command == "/restart":
        await handle_restart(msg, bot_name, bot_cfg)
    else:
        await handle_message(msg, bot_name, bot_cfg)
    return True


class TelegramWebhook(ApiHandler):
    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ensure_dependencies()
        bot_name = request.args.get("bot", "")
        _trace(f"process entry bot={bot_name!r} update={input.get('update_id')} keys={list(input.keys())}")
        if not bot_name:
            _trace("reject missing bot")
            return Response("Missing ?bot= parameter", 400)

        instance = await _ensure_instance_locked(bot_name)
        if not instance:
            _trace(f"reject bot not found {bot_name}")
            return Response(f"Bot not found or disabled: {bot_name}", 404)

        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if instance.webhook_secret and secret_header != instance.webhook_secret:
            _trace(f"reject invalid secret bot={bot_name}")
            return Response("Invalid secret token", 403)

        update_id = input.get("update_id")
        if _is_duplicate(bot_name, update_id):
            _trace(f"duplicate bot={bot_name} update={update_id}")
            return {"ok": True, "duplicate": True}

        async def _handle() -> None:
            from plugins._telegram_integration.helpers.bot_manager import _get_current_bot_cfg
            bot_cfg = _get_current_bot_cfg(bot_name)
            handled = await _direct_process_update(bot_name, bot_cfg, input)
            if not handled:
                from aiogram.types import Update
                update = Update.model_validate(input, context={"bot": instance.bot})
                await instance.dispatcher.feed_update(instance.bot, update)
                _trace(f"dispatcher fallback ok bot={bot_name} update={update_id}")
            else:
                _trace(f"direct ok bot={bot_name} update={update_id}")

        # Process inline and ACK Telegram only after successful handling.
        # If handling fails during/around a restart, return 500 so Telegram retries
        # the same update instead of losing it after a premature 200 ACK.
        try:
            await _handle()
        except Exception as e:
            err = traceback.format_exc()
            _trace(f"error bot={bot_name} update={update_id}: {e}\n{err}")
            PrintStyle.error(f"Telegram webhook ({bot_name}): {e}\n{err}")
            return Response("Telegram update processing failed; retry requested", 500)

        _mark_processed(bot_name, update_id)
        return {"ok": True}
