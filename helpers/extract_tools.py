
from .dirty_json import DirtyJson
import regex, re
from helpers.modules import load_classes_from_file, load_classes_from_folder # keep here for backwards compatibility
from typing import Any


def _sanitize_for_json_parsing(content: str) -> str:
    """
    Remove common LLM output artifacts that break JSON parsing:
    markdown fences, XML-like wrappers, text outside JSON, and leading/trailing whitespace.
    """
    if not isinstance(content, str):
        return ""

    # 1. Strip markdown code blocks (```json ... ``` and ``` ... ```)
    cleaned = re.sub(r'^```[a-zA-Z]*\s*\n?', '', content, flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned, flags=re.MULTILINE)

    # 2. Strip XML-style wrappers (<invoke>...</invoke>)
    cleaned = re.sub(r'<\s*invoke\b[^>]*>.*?</\s*invoke\s*>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<\s*/\s*invoke\s*>', '', cleaned, flags=re.DOTALL)

    # 3. Remove function-style wrappers (functions.tool_name:123)
    cleaned = re.sub(r'functions\.\w+\s*:\s*\w+\s*', '', cleaned)

    # 4. Remove leading text before the first '{' if any
    first_brace = cleaned.find('{')
    if first_brace > 0:
        cleaned = cleaned[first_brace:]

    return cleaned


def json_parse_dirty(json: str) -> dict[str, Any] | None:
    if not json or not isinstance(json, str):
        return None

    sanitized = _sanitize_for_json_parsing(json)
    ext_json = extract_json_object_string(sanitized.strip())
    if ext_json:
        try:
            data = DirtyJson.parse_string(ext_json)
            if isinstance(data, dict):
                return data
        except Exception:
            # If parsing fails, return None instead of crashing
            return None
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
    tool_args = dict(tool_args)
    if ":" in tool_name:
        tool_name, action = tool_name.split(":", 1)
        if not tool_name or not action:
            raise ValueError("tool_name method suffix must include tool and action")
        tool_args.setdefault("action", action)
    method = tool_args.get("method")
    if "action" not in tool_args and isinstance(method, str) and method:
        tool_args["action"] = method
    return tool_name, tool_args


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
