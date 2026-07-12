"""Log token usage after each agent processing chain.
"""
from __future__ import annotations
import datetime

from helpers.extension import Extension
from helpers.print_style import PrintStyle

DEBUG_LOG = "/a0/tmp/um_debug.log"

def _dbg(msg):
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [log_tokens] {msg}\n"
        PrintStyle.standard(line.strip())
        with open(DEBUG_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


class LogTokens(Extension):

    async def execute(self, **kwargs):
        try:
            _dbg(">>> process_chain_end hook FIRED")

            if not self.agent:
                _dbg("no self.agent")
                return

            _dbg(f"agent.number={self.agent.number}")
            if self.agent.number != 0:
                _dbg("not agent0, skipping")
                return

            context = self.agent.context
            user_id = context.data.get("um_user_id")
            username = context.data.get("um_username", "?")
            _dbg(f"context.id={context.id[:12]}... um_user_id={user_id} um_username={username}")
            _dbg(f"context.data keys={list(context.data.keys())[:15]}")

            if not user_id:
                _dbg("NO um_user_id - CANNOT LOG TOKENS")
                return

            # Get model info
            model_name = "unknown"
            try:
                from helpers import settings as settings_module
                s = settings_module.get_settings()
                model_name = s.get("chat_model_name", "unknown")
            except Exception as e:
                _dbg(f"settings error: {e}")

            # Count tokens
            input_tokens, output_tokens = self._count_exchange_tokens()
            _dbg(f"token count: input={input_tokens} output={output_tokens} model={model_name}")

            if input_tokens <= 0 and output_tokens <= 0:
                _dbg("no tokens to log")
                return

            # Log to DB
            from usr.plugins.user_management.helpers.token_logger import log_tokens
            log_tokens(
                user_id=user_id,
                context_id=context.id,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            _dbg(f"SUCCESS: logged {input_tokens}+{output_tokens} tokens for user {username} model={model_name}")

        except Exception as e:
            _dbg(f"EXCEPTION: {e}")
            import traceback
            _dbg(traceback.format_exc())

    def _count_exchange_tokens(self):
        input_tokens = 0
        output_tokens = 0

        try:
            from helpers.tokens import approximate_tokens

            history = self.agent.history
            if not history:
                _dbg("no history")
                return 0, 0

            messages = []
            if hasattr(history, "messages"):
                messages = history.messages
            elif hasattr(history, "output"):
                messages = history.output()

            _dbg(f"history has {len(messages)} messages")

            if not messages:
                return 0, 0

            # Count the most recent exchange
            last_user_idx = -1
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                is_ai = getattr(msg, "ai", None)
                if is_ai is None:
                    msg_type = getattr(msg, "type", "")
                    is_ai = msg_type in ("ai", "assistant")
                if not is_ai:
                    last_user_idx = i
                    break

            _dbg(f"last_user_idx={last_user_idx}")

            if last_user_idx < 0:
                for msg in messages:
                    content = self._get_content(msg)
                    output_tokens += approximate_tokens(content)
                return 0, output_tokens

            # Input = the user message
            user_msg = messages[last_user_idx]
            input_tokens = approximate_tokens(self._get_content(user_msg))

            # Output = all AI messages after the user message
            for msg in messages[last_user_idx + 1:]:
                content = self._get_content(msg)
                output_tokens += approximate_tokens(content)

        except Exception as e:
            _dbg(f"token count error: {e}")

        return input_tokens, output_tokens

    @staticmethod
    def _get_content(msg):
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            parts = []
            if "response" in content:
                parts.append(str(content["response"]))
            if "reasoning" in content:
                parts.append(str(content["reasoning"]))
            return " ".join(parts) if parts else str(content)
        return str(content)
