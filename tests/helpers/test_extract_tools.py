"""Unit tests for extract_tools.py normalization"""
import pytest
from helpers.extract_tools import (
    normalize_tool_request,
    normalize_tool_request_with_diagnostics,
    ToolRequestNormalizationResult,
)


class TestNormalizeToolRequestWithDiagnostics:
    """Test normalize_tool_request_with_diagnostics function"""
    
    def test_valid_dict_request(self):
        """Test normal valid request"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": {"text": "hello"}
        })
        assert result.tool_name == "response"
        assert result.tool_args == {"text": "hello"}
        assert result.repairs == []
        assert result.errors == []
    
    def test_tool_to_tool_name_alias(self):
        """Test tool → tool_name alias"""
        result = normalize_tool_request_with_diagnostics({
            "tool": "response",
            "tool_args": {"text": "hello"}
        })
        assert result.tool_name == "response"
        assert 'Mapped "tool" to "tool_name"' in result.repairs
    
    def test_name_to_tool_name_alias(self):
        """Test name → tool_name alias"""
        result = normalize_tool_request_with_diagnostics({
            "name": "response",
            "tool_args": {"text": "hello"}
        })
        assert result.tool_name == "response"
        assert 'Mapped "name" to "tool_name"' in result.repairs
    
    def test_args_to_tool_args_alias(self):
        """Test args → tool_args alias"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "args": {"text": "hello"}
        })
        assert result.tool_args == {"text": "hello"}
        assert 'Mapped "args" to "tool_args"' in result.repairs
    
    def test_arguments_to_tool_args_alias(self):
        """Test arguments → tool_args alias"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "arguments": {"text": "hello"}
        })
        assert result.tool_args == {"text": "hello"}
        assert 'Mapped "arguments" to "tool_args"' in result.repairs
    
    def test_missing_tool_args(self):
        """Test missing tool_args defaults to empty dict"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response"
        })
        assert result.tool_args == {}
        assert result.repairs == []
    
    def test_null_tool_args(self):
        """Test null tool_args becomes empty dict"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": None
        })
        assert result.tool_args == {}
    
    def test_tool_args_json_string(self):
        """Test tool_args as JSON string gets parsed"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": '{"text": "hello"}'
        })
        assert result.tool_args == {"text": "hello"}
        assert "Parsed tool_args JSON string into object" in result.repairs
    
    def test_tool_args_json_string_with_dirty_json(self):
        """Test tool_args with single quotes (dirty JSON)"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": "{'text': 'hello'}"
        })
        assert result.tool_args == {"text": "hello"}
        assert "Parsed tool_args JSON string into object" in result.repairs
    
    def test_tool_args_list_error(self):
        """Test tool_args as list raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_name": "response",
                "tool_args": ["hello"]
            })
        assert "array/list" in str(exc_info.value)
    
    def test_tool_args_string_non_json_error(self):
        """Test tool_args as non-JSON string raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_name": "response",
                "tool_args": "read file.txt"
            })
        assert "JSON object" in str(exc_info.value)
    
    def test_tool_args_number_error(self):
        """Test tool_args as number raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_name": "response",
                "tool_args": 42
            })
        assert "int" in str(exc_info.value)
    
    def test_tool_name_colon_action(self):
        """Test tool_name:action syntax"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "text_editor:read",
            "tool_args": {"path": "/file.txt"}
        })
        assert result.tool_name == "text_editor"
        assert result.tool_args["action"] == "read"
        assert any('Extracted action "read"' in repair for repair in result.repairs)
    
    def test_tool_name_colon_action_with_existing_action(self):
        """Test tool_name:action doesn't override existing action"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "text_editor:read",
            "tool_args": {"action": "write"}
        })
        assert result.tool_name == "text_editor"
        assert result.tool_args["action"] == "write"
    
    def test_method_to_action(self):
        """Test method → action mapping"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": {"method": "GET"}
        })
        assert result.tool_args["action"] == "GET"
        assert 'Mapped "method" to "action"' in result.repairs
    
    def test_method_to_action_no_override(self):
        """Test method → action doesn't override existing action"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": {"action": "POST", "method": "GET"}
        })
        assert result.tool_args["action"] == "POST"
    
    def test_not_dict_error(self):
        """Test non-dict input raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics([{"tool_name": "response"}])
        assert "must be a dictionary" in str(exc_info.value)
    
    def test_missing_tool_name_error(self):
        """Test missing tool_name raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_args": {}
            })
        assert "tool_name" in str(exc_info.value)
    
    def test_empty_tool_name_error(self):
        """Test empty tool_name raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_name": "",
                "tool_args": {}
            })
        assert "tool_name" in str(exc_info.value)
    
    def test_tool_name_not_string_error(self):
        """Test tool_name as non-string raises error"""
        with pytest.raises(ValueError) as exc_info:
            normalize_tool_request_with_diagnostics({
                "tool_name": 123,
                "tool_args": {}
            })
        assert "tool_name" in str(exc_info.value)
    
    def test_multiple_repairs(self):
        """Test multiple repairs are tracked"""
        result = normalize_tool_request_with_diagnostics({
            "tool": "text_editor:read",
            "args": '{"path": "/file.txt"}'
        })
        assert result.tool_name == "text_editor"
        assert any('Mapped "tool"' in repair for repair in result.repairs)
        assert any('Mapped "args"' in repair for repair in result.repairs)
        assert any('Extracted action "read"' in repair for repair in result.repairs)
    
    def test_empty_args_dict(self):
        """Test empty tool_args dict is valid"""
        result = normalize_tool_request_with_diagnostics({
            "tool_name": "response",
            "tool_args": {}
        })
        assert result.tool_args == {}
        assert result.repairs == []


class TestNormalizeToolRequestBackwardCompatibility:
    """Test backward compatible normalize_tool_request wrapper"""
    
    def test_returns_tuple(self):
        """Test returns (tool_name, tool_args) tuple"""
        tool_name, tool_args = normalize_tool_request({
            "tool_name": "response",
            "tool_args": {"text": "hello"}
        })
        assert tool_name == "response"
        assert tool_args == {"text": "hello"}
    
    def test_handles_alias(self):
        """Test wrapper handles alias"""
        tool_name, tool_args = normalize_tool_request({
            "tool": "response",
            "args": {"text": "hello"}
        })
        assert tool_name == "response"
        assert tool_args == {"text": "hello"}
    
    def test_raises_on_error(self):
        """Test wrapper raises ValueError on invalid input"""
        with pytest.raises(ValueError):
            normalize_tool_request({
                "tool_args": {}
            })


class TestToolRequestNormalizationResult:
    """Test ToolRequestNormalizationResult dataclass"""
    
    def test_fields_present(self):
        """Test result has all required fields"""
        result = ToolRequestNormalizationResult(
            tool_name="test",
            tool_args={},
            repairs=["repair1"],
            errors=[]
        )
        assert result.tool_name == "test"
        assert result.tool_args == {}
        assert result.repairs == ["repair1"]
        assert result.errors == []
    
    def test_default_empty_lists(self):
        """Test repairs and errors default to empty lists"""
        result = ToolRequestNormalizationResult(
            tool_name="test",
            tool_args={}
        )
        assert result.repairs == []
        assert result.errors == []
