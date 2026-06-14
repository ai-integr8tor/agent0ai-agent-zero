from agent import AgentContext, UserMessage
from helpers.api import ApiHandler, Request, Response
from helpers import files, extension, message_queue as mq
import os
from helpers.security import safe_filename
from helpers.defer import DeferredTask


class MessageAsync(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        task, context = await self.communicate(input=input, request=request)
        return await self.respond(task, context)

    async def respond(self, task: DeferredTask, context: AgentContext):
        return {
            "message": "Message received.",
            "context": context.id,
        }

    async def communicate(self, input: dict, request: Request):
        if request.content_type.startswith("multipart/form-data"):
            text = request.form.get("text", "")
            ctxid = request.form.get("context", "")
            message_id = request.form.get("message_id", None)
            attachments = request.files.getlist("attachments")
            attachment_paths = []

            upload_folder_int = "/a0/usr/uploads"
            upload_folder_ext = files.get_abs_path("usr/uploads")

            if attachments:
                os.makedirs(upload_folder_ext, exist_ok=True)
                for attachment in attachments:
                    if attachment.filename is None:
                        continue
                    filename = safe_filename(attachment.filename)
                    if not filename:
                        continue
                    save_path = files.get_abs_path(upload_folder_ext, filename)
                    attachment.save(save_path)
                    attachment_paths.append(os.path.join(upload_folder_int, filename))
        else:
            input_data = request.get_json()
            text = input_data.get("text", "")
            ctxid = input_data.get("context", "")
            message_id = input_data.get("message_id", None)
            attachment_paths = []

        message = text
        context = self.use_context(ctxid)

        data = {"message": message, "attachment_paths": attachment_paths}
        await extension.call_extensions_async("user_message_ui", agent=context.get_agent(), data=data)
        message = data.get("message", "")
        attachment_paths = data.get("attachment_paths", [])

        mq.log_user_message(context, message, attachment_paths, message_id)

        return context.communicate(UserMessage(message=message, attachments=attachment_paths, id=message_id or "")), context
