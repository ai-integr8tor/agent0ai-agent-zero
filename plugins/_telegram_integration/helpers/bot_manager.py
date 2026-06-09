import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType, ContentType
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from helpers.errors import format_error
from helpers.print_style import PrintStyle

# Data models

@dataclass
class BotInstance:
    name: str
    bot: Bot
    dispatcher: Dispatcher
    router: Router
    task: asyncio.Task | None = None  # polling task
    webhook_active: bool = False  # True when webhook mode is registered
    webhook_secret: str = ""  # secret for webhook verification
    group_mode: str = "mention"  # current group_mode setting
    bot_info: object | None = None  # cached result of bot.get_me()

PLUGIN_NAME = "_telegram_integration"

# Bot registry (singleton, persists across module reloads)

_bots: dict[str, BotInstance] = {}


def get_bot(name: str) -> BotInstance | None:
    return _bots.get(name)


def get_all_bots() -> dict[str, BotInstance]:
    return _bots

# Bot creation

def create_bot(
    name: str,
    token: str,
    on_message: Callable[..., Awaitable],
    on_command_start: Callable[..., Awaitable],
    on_command_clear: Callable[..., Awaitable],
    on_command_new: Callable[..., Awaitable] | None = None,
    on_command_control: Callable[..., Awaitable] | None = None,
    on_command_affect_project: Callable[..., Awaitable] | None = None,
    on_callback_query: Callable[..., Awaitable] | None = None,
    on_new_members: Callable[..., Awaitable] | None = None,
    on_forum_topic_closed: Callable[..., Awaitable] | None = None,
    group_mode: str = "mention",
) -> BotInstance:
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    router = Router()

    # Register command handlers
    router.message.register(on_command_start, CommandStart())
    router.message.register(on_command_clear, Command("clear"))
    if on_command_new:
        router.message.register(on_command_new, Command(commands=["new", "branch"]))
    if on_command_control:
        router.message.register(
            on_command_control,
            Command(commands=["config", "preset", "queue", "send", "now", "later", "nudge", "pause", "restart", "topicname"]),
        )
    if on_command_affect_project:
        router.message.register(
            on_command_affect_project,
            Command(commands=["project", "projets"]),
        )

    if on_callback_query:
        router.callback_query.register(on_callback_query)

    if on_new_members:
        router.message.register(on_new_members, F.content_type == ContentType.NEW_CHAT_MEMBERS)

    if on_forum_topic_closed:
        router.message.register(on_forum_topic_closed, F.content_type == ContentType.FORUM_TOPIC_CLOSED)

    # Register message handler with group filtering
    if group_mode == "off":
        # Private chats only
        router.message.register(
            on_message, F.chat.type == ChatType.PRIVATE,
        )
    elif group_mode == "mention":
        # Private chats: all messages; Groups: only when mentioned/replied
        router.message.register(
            on_message, F.chat.type == ChatType.PRIVATE,
        )
        router.message.register(
            _make_group_mention_filter(on_message, bot),
        )
    else:
        # All messages in all chats
        router.message.register(on_message)

    dp.include_router(router)
    instance = BotInstance(name=name, bot=bot, dispatcher=dp, router=router, group_mode=group_mode)
    _bots[name] = instance
    return instance


async def cache_bot_info(instance: BotInstance):
    """Fetch and cache bot info. Call after create_bot."""
    if not instance.bot_info:
        instance.bot_info = await instance.bot.get_me()
    return instance.bot_info


async def set_bot_commands(instance: BotInstance):
    """Publish visible slash commands in Telegram's command menu."""
    commands = [
        BotCommand(command="start", description="Start the Agent Zero bot"),
        BotCommand(command="clear", description="Reset the current conversation"),
        BotCommand(command="new", description="Start a new Agent Zero chat here"),
        BotCommand(command="branch", description="Branch into a new Agent Zero chat here"),
        BotCommand(command="project", description="Show or change the active project"),
        BotCommand(command="config", description="Show or change chat configuration"),
        BotCommand(command="preset", description="Apply a model/config preset"),
        BotCommand(command="queue", description="Voir/envoyer la queue"),
        BotCommand(command="later", description="Ajouter un message à la queue"),
        BotCommand(command="now", description="Interrompre et envoyer maintenant"),
        BotCommand(command="nudge", description="Relancer l’agent actif"),
        BotCommand(command="pause", description="Mettre l’agent actif en pause"),
        BotCommand(command="restart", description="Redémarrer Agent Zero"),
        BotCommand(command="topicname", description="Tester le renommage du sujet"),
        BotCommand(command="send", description="Envoyer la queue"),
    ]
    await instance.bot.set_my_commands(commands)


def _make_group_mention_filter(handler: Callable, bot: Bot):
    """Create a group message handler that only responds to mentions and replies."""
    async def _group_handler(message: Message):
        if message.chat.type == ChatType.PRIVATE:
            return
        # Use cached bot_info from the instance
        bot_info = None
        for b in _bots.values():
            if b.bot is bot:
                bot_info = b.bot_info
                break
        if not bot_info:
            bot_info = await bot.get_me()
        bot_username = bot_info.username or ""

        # Check for reply to bot
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.id == bot_info.id:
                await handler(message)
                return

        # Check for @mention in text or caption (media messages use caption)
        text = message.text or message.caption or ""
        entities = message.entities or message.caption_entities or []

        if text and f"@{bot_username}" in text:
            await handler(message)
            return

        # Check entities for mention
        for entity in entities:
            if entity.type == "mention":
                mention_text = text[entity.offset:entity.offset + entity.length]
                if mention_text.lower() == f"@{bot_username.lower()}":
                    await handler(message)
                    return

    _group_handler.__name__ = f"_group_handler_{id(handler)}"
    return _group_handler

# Polling

async def start_polling(instance: BotInstance) -> asyncio.Task:
    # Ensure any leftover webhook is removed before polling
    try:
        await instance.bot.delete_webhook()
    except Exception:
        pass

    async def _poll():
        try:
            PrintStyle.info(f"Telegram ({instance.name}): starting polling")
            await instance.dispatcher.start_polling(
                instance.bot,
                handle_signals=False,
            )
        except asyncio.CancelledError:
            PrintStyle.info(f"Telegram ({instance.name}): polling cancelled")
        except Exception as e:
            PrintStyle.error(f"Telegram ({instance.name}): polling error: {format_error(e)}")

    task = asyncio.create_task(_poll())
    instance.task = task
    return task


async def stop_polling(instance: BotInstance):
    if instance.task and not instance.task.done():
        await instance.dispatcher.stop_polling()
        instance.task.cancel()
        try:
            await instance.task
        except asyncio.CancelledError:
            pass
    instance.task = None

# Webhook

async def setup_webhook(instance: BotInstance, webhook_url: str, secret: str = ""):
    """Register webhook with Telegram. Updates are received via the API handler."""
    full_url = f"{webhook_url.rstrip('/')}/api/plugins/_telegram_integration/webhook?bot={instance.name}"

    await instance.bot.set_webhook(
        url=full_url,
        secret_token=secret or None,
        drop_pending_updates=False,
        max_connections=40,
        allowed_updates=[
            "message",
            "edited_message",
            "callback_query",
            "my_chat_member",
            "chat_member",
        ],
    )

    instance.webhook_active = True
    instance.webhook_secret = secret
    PrintStyle.info(f"Telegram ({instance.name}): webhook active via {webhook_url.rstrip('/')}")


async def remove_webhook(instance: BotInstance):
    try:
        await instance.bot.delete_webhook()
    except Exception as e:
        PrintStyle.error(f"Telegram ({instance.name}): remove webhook error: {format_error(e)}")
    instance.webhook_active = False
    instance.webhook_secret = ""

# Cleanup

async def stop_bot(name: str):
    instance = _bots.pop(name, None)
    if not instance:
        return
    if instance.task and not instance.task.done():
        await stop_polling(instance)
    else:
        await remove_webhook(instance)
    try:
        await instance.bot.session.close()
    except Exception:
        pass
    PrintStyle.info(f"Telegram ({name}): stopped")


# Test connection

async def test_token(token: str) -> tuple[bool, str]:
    try:
        bot = Bot(token=token)
        info = await bot.get_me()
        await bot.session.close()
        return True, f"Connected as @{info.username} ({info.first_name})"
    except Exception as e:
        return False, format_error(e)


# Webhook-safe bootstrap helpers

def _get_current_bot_cfg(bot_name: str) -> dict:
    """Fetch the latest bot config by name, so handlers always use fresh settings."""
    from helpers import plugins

    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    for b in config.get("bots", []):
        if b.get("name") == bot_name:
            return b
    return {}


def _make_handler(handler_fn):
    """Create a wrapper that resolves fresh bot config on every call."""
    async def _wrapped(event, bot_name: str, bot_cfg: dict):
        await handler_fn(event, bot_name, _get_current_bot_cfg(bot_name) or bot_cfg)
    return _wrapped


async def ensure_bot_running_from_config(name: str) -> BotInstance | None:
    """Recreate a Telegram bot instance from plugin config when registry is empty.

    This makes webhook delivery independent from the periodic job loop: after a process
    restart, the first webhook request can bootstrap the bot/dispatcher/handlers itself.
    """
    inst = get_bot(name)
    if inst:
        return inst

    from functools import partial
    from helpers import plugins
    from plugins._telegram_integration.helpers.handler import (
        handle_start,
        handle_clear,
        handle_new_chat,
        handle_message,
        handle_callback_query,
        handle_affect_project,
        handle_new_members,
        handle_forum_topic_closed,
    )

    config = plugins.get_plugin_config(PLUGIN_NAME) or {}
    bot_cfg = next(
        (
            b for b in config.get("bots", [])
            if b.get("name") == name and b.get("enabled") and b.get("token")
        ),
        None,
    )
    if not bot_cfg:
        return None

    _on_start = partial(_make_handler(handle_start), bot_name=name, bot_cfg=bot_cfg)
    _on_clear = partial(_make_handler(handle_clear), bot_name=name, bot_cfg=bot_cfg)
    _on_new_chat = partial(_make_handler(handle_new_chat), bot_name=name, bot_cfg=bot_cfg)
    _on_message = partial(_make_handler(handle_message), bot_name=name, bot_cfg=bot_cfg)
    _on_callback = partial(_make_handler(handle_callback_query), bot_name=name, bot_cfg=bot_cfg)
    _on_affect_project = partial(_make_handler(handle_affect_project), bot_name=name, bot_cfg=bot_cfg)
    _on_new_members = partial(_make_handler(handle_new_members), bot_name=name, bot_cfg=bot_cfg)
    _on_forum_topic_closed = partial(_make_handler(handle_forum_topic_closed), bot_name=name, bot_cfg=bot_cfg)

    inst = create_bot(
        name=name,
        token=bot_cfg["token"],
        on_message=_on_message,
        on_command_start=_on_start,
        on_command_clear=_on_clear,
        on_command_new=_on_new_chat,
        on_command_control=_on_message,
        on_command_affect_project=_on_affect_project,
        on_callback_query=_on_callback,
        on_new_members=_on_new_members,
        on_forum_topic_closed=_on_forum_topic_closed,
        group_mode=bot_cfg.get("group_mode", "mention"),
    )

    await cache_bot_info(inst)
    await set_bot_commands(inst)

    mode = bot_cfg.get("mode", "polling")
    if mode == "webhook":
        webhook_url = bot_cfg.get("webhook_url", "")
        if webhook_url:
            await setup_webhook(inst, webhook_url, bot_cfg.get("webhook_secret", ""))
    else:
        await start_polling(inst)

    return inst
