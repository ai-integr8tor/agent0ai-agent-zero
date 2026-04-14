from helpers.api import ApiHandler, Request, Response

from helpers import settings, whisper

class Transcribe(ApiHandler):
    async def process(self, payload: dict, _request: Request) -> dict | Response:
        audio = payload.get("audio")
        ctxid = payload.get("ctxid", "")

        if not audio:
            return Response("Missing 'audio'.", 400)

        if ctxid:
            self.use_context(ctxid)

        try:
            settings_data = settings.get_settings()
            result = await whisper.transcribe(settings_data["stt_model_size"], audio) # type: ignore
            return result
        except Exception as e:
            return Response(str(e), 500)
