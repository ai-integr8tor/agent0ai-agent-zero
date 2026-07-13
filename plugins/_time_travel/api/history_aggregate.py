from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from plugins._time_travel.helpers.time_travel import (
    TimeTravelError,
    aggregate_history,
    list_all_workspaces,
)


class HistoryAggregate(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            display_path = str(input.get("display_path") or "").strip()
            mode = str(input.get("mode") or "history").strip().lower()

            if mode == "workspaces":
                workspaces = list_all_workspaces(display_path)
                return {"ok": True, "workspaces": workspaces}

            return aggregate_history(
                display_path,
                limit=int(input.get("limit") or 100),
                offset=int(input.get("offset") or 0),
            )
        except TimeTravelError as exc:
            return {"ok": False, "error": str(exc)}
