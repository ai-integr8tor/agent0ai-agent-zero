from helpers.api import ApiHandler, Input, Output, Request, Response


from helpers import settings, projects, guids
from agent import AgentContext


class CreateChat(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        current_ctxid = input.get("current_context", "") # current context id
        new_ctxid = input.get("new_context", guids.generate_id()) # given or new guid

        # context instance - get or create with authorization check
        current_context = self.use_context(current_ctxid, create_if_not_exists=False) if current_ctxid else None

        # get/create new context
        new_context = self.use_context(new_ctxid)

        # copy selected data from current to new context
        current_project_name = ""
        if current_context:
            current_project_name = current_context.get_data(projects.CONTEXT_DATA_KEY_PROJECT) or ""
            current_project_output = current_context.get_output_data(projects.CONTEXT_DATA_KEY_PROJECT) or ""
            if settings.get_settings().get("chat_inherit_project", True) and current_project_name:
                new_context.set_data(projects.CONTEXT_DATA_KEY_PROJECT, current_project_name)
            if settings.get_settings().get("chat_inherit_project", True) and current_project_output:
                new_context.set_output_data(projects.CONTEXT_DATA_KEY_PROJECT, current_project_output)

            # Preserve structured project metadata when present so project-shared
            # chats continue to group correctly after a new chat is spawned.
            if isinstance(current_project_output, dict) and current_project_output:
                new_context.set_output_data(projects.CONTEXT_DATA_KEY_PROJECT, current_project_output)

        # copy model override from current context (only if override is allowed)
        if current_context:
            model_override = current_context.get_data("chat_model_override")
            if model_override:
                from plugins._model_config.helpers.model_config import is_chat_override_allowed
                if is_chat_override_allowed(new_context.agent0):
                    new_context.set_data("chat_model_override", model_override)

        # New context should appear in other tabs' chat lists via state_push.
        from helpers.state_monitor_integration import mark_dirty_all
        mark_dirty_all(reason="api.chat_create.CreateChat")

        return {
            "ok": True,
            "ctxid": new_context.id,
            "message": "Context created.",
        }
