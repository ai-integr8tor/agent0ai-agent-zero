
from .dirty_json import DirtyJson
import regex, re
from helpers.modules import load_classes_from_file, load_classes_from_folder # keep here for backwards compatibility
from typing import Any
from dataclasses import dataclass, field


@dataclass
class ToolRequestNormalizationResult:
    """Result of tool request normalization with diagnostic info"""
    tool_name: str
    tool_args: dict
    repairs: list[str] = field(default_factory=list)  # Auto-repairs applied
    errors: list[str] = field(default_factory=list)   # Hard errors that prevented normalization


def normalize_tool_request_with_diagnostics(tool_request: Any) -> ToolRequestNormalizationResult:
    """
    Normalize tool request with detailed diagnostics.
    
    Handles aliases like:
    - tool → tool_name
    - name → tool_name  
    - args/arguments → tool_args
    - tool_name:action syntax
    - method → action
    - JSON string → dict parsing
    
    Returns ToolRequestNormalizationResult with repairs list for LLM feedback.
    Raises ValueError only for truly invalid requests (non-dict, missing tool_name).
    """
    errors = []
    repairs = []
    
    # Validate it's a dict
    if not isinstance(tool_request, dict):
        errors.append(f"Tool request must be a dictionary, got {type(tool_request).__name__}")
        raise ValueError(errors[0])
    
    # Extract tool_name with aliases
    tool_name = None
    
    # Try direct tool_name
    if "tool_name" in tool_request:
        tool_name = tool_request["tool_name"]
    # Try tool alias
    elif "tool" in tool_request:
        tool_name = tool_request["tool"]
        repairs.append('Mapped "tool" to "tool_name"')
    # Try name alias
    elif "name" in tool_request:
        tool_name = tool_request["name"]
        repairs.append('Mapped "name" to "tool_name"')
    
    # Validate tool_name
    if not tool_name or not isinstance(tool_name, str):
        errors.append("Tool request must have tool_name (non-empty string)")
        raise ValueError(errors[0])
    
    # Extract tool_args with aliases
    tool_args = None
    
    if "tool_args" in tool_request:
        tool_args = tool_request["tool_args"]
    elif "args" in tool_request:
        tool_args = tool_request["args"]
        repairs.append('Mapped "args" to "tool_args"')
    elif "arguments" in tool_request:
        tool_args = tool_request["arguments"]
        repairs.append('Mapped "arguments" to "tool_args"')
    
    # Normalize tool_args
    if tool_args is None:
        tool_args = {}
    elif isinstance(tool_args, str):
        # Try to parse JSON string
        try:
            parsed = DirtyJson.parse_string(tool_args)
            if isinstance(parsed, dict):
                tool_args = parsed
                repairs.append("Parsed tool_args JSON string into object")
            else:
                errors.append("tool_args must be a JSON object, but got string.")
        except Exception as e:
            errors.append("tool_args must be a JSON object, but got string.")
    elif isinstance(tool_args, list):
        errors.append(
            f"tool_args must be a JSON object, got array/list"
        )
    elif not isinstance(tool_args, dict):
        errors.append(
            f"tool_args must be a JSON object, got {type(tool_args).__name__}"
        )
    
    # If we have errors at this point, raise
    if errors:
        raise ValueError(" | ".join(errors))
    
    # Ensure tool_args is dict
    tool_args = dict(tool_args) if isinstance(tool_args, dict) else {}
    
    # Handle tool_name:action syntax
    if ":" in tool_name:
        parts = tool_name.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            tool_name = parts[0]
            action = parts[1]
            if "action" not in tool_args:
                tool_args["action"] = action
                repairs.append(f'Extracted action "{action}"')
        else:
            errors.append("tool_name:action syntax requires both parts non-empty")
    
    # Map method → action if action missing
    if "action" not in tool_args and "method" in tool_args:
        method = tool_args.get("method")
        if isinstance(method, str) and method:
            tool_args["action"] = method
            repairs.append('Mapped "method" to "action"')
    
    return ToolRequestNormalizationResult(
        tool_name=tool_name,
        tool_args=tool_args,
        repairs=repairs,
        errors=errors
    )


def normalize_tool_request(tool_request: Any) -> tuple[str, dict]:
    """
    Backward compatible wrapper for normalize_tool_request_with_diagnostics.
    Returns (tool_name, tool_args) tuple for existing code.
    """
    result = normalize_tool_request_with_diagnostics(tool_request)
    return result.tool_name, result.tool_args


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
