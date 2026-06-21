
from .dirty_json import DirtyJson
import regex, re
from helpers.modules import load_classes_from_file, load_classes_from_folder # keep here for backwards compatibility
from helpers.strings import sanitize_string
from typing import Any

TOOL_NAME_KEYS = ("tool_name", "tool", "toolName", "function_name", "functionName")
TOOL_ARGS_KEYS = ("tool_args", "args", "arguments", "parameters", "input")
META_KEYS = {
    "thought",
    "thoughts",
    "headline",
    "reasoning",
    "analysis",
    "plan",
    "intent",
    "title",
}
RESPONSE_TEXT_KEYS = (
    "text",
    "message",
    "response",
    "answer",
    "final",
    "final_answer",
    "content",
)
RESPONSE_INTENT_MARKERS = (
    "response tool",
    "final answer",
    "respond",
    "reply",
    "answer the user",
    "acknowledg",
    "greeting",
    "offer of assistance",
)
ACTION_INTENT_MARKERS = (
    "text_editor",
    "text editor",
    "code_execution",
    "terminal",
    "shell command",
    "run command",
    "search_engine",
    "browser",
    "computer_use",
    "vision_load",
    "call_subordinate",
    "write file",
    "read file",
    "edit file",
    "create file",
    "open in canvas",
)


def json_parse_dirty(json: str) -> dict[str, Any] | None:
    if not json or not isinstance(json, str):
        return None

    ext_json = extract_json_object_string(json.strip())
    if ext_json:
        try:
            data = DirtyJson.parse_string(ext_json)
            if isinstance(data, dict):
                return data
        except Exception:
            # If parsing fails, return None instead of crashing
            return None
    return None


def extract_tool_request(content: str) -> dict[str, Any] | None:
    """Extract and repair the first executable tool request from model text."""

    for tool_request in iter_json_dicts(content):
        try:
            tool_name, tool_args = normalize_tool_request(tool_request)
            return {"tool_name": tool_name, "tool_args": tool_args}
        except ValueError:
            repaired = repair_tool_request(tool_request)
            if not repaired:
                continue
            try:
                tool_name, tool_args = normalize_tool_request(repaired)
            except ValueError:
                continue
            return {"tool_name": tool_name, "tool_args": tool_args}
    return None


def iter_json_dicts(content: str) -> list[dict[str, Any]]:
    if not content or not isinstance(content, str):
        return []

    result: list[dict[str, Any]] = []
    for candidate in iter_json_object_strings(content):
        try:
            data = DirtyJson.parse_string(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            result.append(data)
    return result


def iter_json_object_strings(content: str) -> list[str]:
    if not content or not isinstance(content, str):
        return []

    strings: list[str] = []
    index = 0
    while index < len(content):
        start = content.find("{", index)
        if start == -1:
            break
        candidate = extract_json_root_string(content[start:])
        if candidate:
            strings.append(candidate)
            index = start + len(candidate)
        else:
            index = start + 1
    return strings


def repair_tool_request(tool_request: Any) -> dict[str, Any] | None:
    if not isinstance(tool_request, dict):
        return None

    tool_name = _first_string_value(tool_request, TOOL_NAME_KEYS)
    raw_args = _first_value(tool_request, TOOL_ARGS_KEYS)
    tool_args = _normalize_repaired_args(raw_args, tool_name=tool_name)

    if tool_name:
        if tool_args is None:
            tool_args = _root_args(tool_request)
        if tool_name == "response":
            response_text = _response_text(tool_request, tool_args)
            if response_text:
                tool_args = {**tool_args, "text": response_text}
        if not tool_args and tool_name == "response":
            response_text = _synthesized_response_text(tool_request)
            if response_text:
                tool_args = {"text": response_text}
        if isinstance(tool_args, dict):
            return {"tool_name": tool_name, "tool_args": sanitize_tool_args(tool_args)}
        return None

    if _looks_like_final_response_intent(tool_request):
        response_text = _response_text(tool_request, {}) or _synthesized_response_text(
            tool_request
        )
        if response_text:
            return {
                "tool_name": "response",
                "tool_args": sanitize_tool_args({"text": response_text}),
            }

    return None


def normalize_tool_request(tool_request: Any) -> tuple[str, dict]:
    if not isinstance(tool_request, dict):
        raise ValueError("Tool request must be a dictionary")
    tool_name = tool_request.get("tool_name")
    if not tool_name or not isinstance(tool_name, str):
        tool_name = tool_request.get("tool")
    if not tool_name or not isinstance(tool_name, str):
        raise ValueError("Tool request must have a tool_name (type string) field")
    tool_args = tool_request.get("tool_args")
    if not isinstance(tool_args, dict):
        tool_args = tool_request.get("args")
    if not isinstance(tool_args, dict):
        raise ValueError("Tool request must have a tool_args (type dictionary) field")
    tool_args = sanitize_tool_args(dict(tool_args))
    if ":" in tool_name:
        tool_name, action = tool_name.split(":", 1)
        if not tool_name or not action:
            raise ValueError("tool_name method suffix must include tool and action")
        tool_args.setdefault("action", action)
    method = tool_args.get("method")
    if "action" not in tool_args and isinstance(method, str) and method:
        tool_args["action"] = method
    return tool_name, tool_args


def sanitize_tool_args(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_string(value)
    if isinstance(value, dict):
        return {
            sanitize_string(key) if isinstance(key, str) else key: sanitize_tool_args(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_tool_args(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_tool_args(item) for item in value)
    return value


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _first_string_value(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    value = _first_value(data, keys)
    return value.strip() if isinstance(value, str) else ""


def _normalize_repaired_args(raw_args: Any, *, tool_name: str) -> dict[str, Any] | None:
    if isinstance(raw_args, dict):
        return dict(raw_args)
    if isinstance(raw_args, str) and tool_name == "response":
        text = raw_args.strip()
        return {"text": text} if text else {}
    if raw_args is None:
        return None
    return None


def _root_args(data: dict[str, Any]) -> dict[str, Any]:
    excluded = set(TOOL_NAME_KEYS) | set(TOOL_ARGS_KEYS) | META_KEYS
    return {key: value for key, value in data.items() if key not in excluded}


def _response_text(data: dict[str, Any], tool_args: dict[str, Any]) -> str:
    for source in (tool_args, data):
        value = _first_value(source, RESPONSE_TEXT_KEYS)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _synthesized_response_text(data: dict[str, Any]) -> str:
    text = _intent_text(data)
    lowered = text.lower()
    if any(marker in lowered for marker in ("hi", "hello", "greeting")):
        return "Hi. How can I help?"
    if "thank" in lowered:
        return "You're welcome."
    return ""


def _looks_like_final_response_intent(data: dict[str, Any]) -> bool:
    text = _intent_text(data)
    lowered = text.lower()
    if any(marker in lowered for marker in ACTION_INTENT_MARKERS):
        return False
    return any(marker in lowered for marker in RESPONSE_INTENT_MARKERS)


def _intent_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_intent_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_intent_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def extract_json_root_string(content: str) -> str | None:
    if not content or not isinstance(content, str):
        return None

    start = content.find("{")
    if start == -1:
        return None
    first_array = content.find("[")
    if first_array != -1 and first_array < start:
        return None

    parser = DirtyJson()
    try:
        parser.parse(content[start:])
    except Exception:
        return None

    if not parser.completed:
        return None

    return content[start : start + parser.index]


def extract_json_object_string(content):
    start = content.find("{")
    if start == -1:
        return ""

    # Find the first '{'
    end = content.rfind("}")
    if end == -1:
        # If there's no closing '}', return from start to the end
        return content[start:]
    else:
        # If there's a closing '}', return the substring from start to end
        return content[start : end + 1]


def extract_json_string(content):
    # Regular expression pattern to match a JSON object
    pattern = r'\{(?:[^{}]|(?R))*\}|\[(?:[^\[\]]|(?R))*\]|"(?:\\.|[^"\\])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'

    # Search for the pattern in the content
    match = regex.search(pattern, content)

    if match:
        # Return the matched JSON string
        return match.group(0)
    else:
        return ""


def fix_json_string(json_string):
    # Function to replace unescaped line breaks within JSON string values
    def replace_unescaped_newlines(match):
        return match.group(0).replace("\n", "\\n")

    # Use regex to find string values and apply the replacement function
    fixed_string = re.sub(
        r'(?<=: ")(.*?)(?=")', replace_unescaped_newlines, json_string, flags=re.DOTALL
    )
    return fixed_string
