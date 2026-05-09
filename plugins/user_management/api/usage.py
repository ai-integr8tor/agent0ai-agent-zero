from helpers.api import ApiHandler, Input, Output, Request, Response
from flask import session, send_file
import io
from usr.plugins.user_management.helpers.token_logger import (
    get_usage,
    get_usage_summary,
    export_to_excel,
)


class Usage(ApiHandler):
    """Token usage queries and Excel export."""

    async def process(self, input: Input, request: Request) -> Output:
        action = str(input.get("action", "query")).strip().lower()
        role = session.get("um_role")
        current_user_id = session.get("um_user_id")

        # Non-admins can only see their own usage
        user_id = input.get("user_id")
        if role != "admin":
            user_id = current_user_id

        from_date = input.get("from_date")
        to_date = input.get("to_date")

        if action == "query":
            data = get_usage(
                user_id=user_id,
                from_date=from_date,
                to_date=to_date,
                model=input.get("model"),
                context_id=input.get("context_id"),
                limit=int(input.get("limit", 500)),
            )
            # Serialize datetimes
            for row in data:
                if row.get("timestamp"):
                    row["timestamp"] = str(row["timestamp"])
            return {"ok": True, "data": data}

        elif action == "summary":
            data = get_usage_summary(
                user_id=user_id,
                group_by=str(input.get("group_by", "day")),
                from_date=from_date,
                to_date=to_date,
            )
            for row in data:
                if row.get("group_key"):
                    row["group_key"] = str(row["group_key"])
            return {"ok": True, "data": data}

        elif action == "export":
            excel_bytes = export_to_excel(
                user_id=user_id,
                from_date=from_date,
                to_date=to_date,
            )
            return Response(
                response=excel_bytes,
                status=200,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": "attachment; filename=token_usage.xlsx",
                },
            )

        return Response("Unknown action", 400)
