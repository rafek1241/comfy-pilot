"""Tests for edit_graph() input parsing, validation, and operation handling."""

import importlib.util
import json
import os
import pytest
from unittest.mock import patch

# Load mcp_server.py directly to avoid importing the root __init__.py (ComfyUI plugin)
import sys
_spec = importlib.util.spec_from_file_location(
    "mcp_server",
    os.path.join(os.path.dirname(__file__), "..", "mcp_server.py"),
)
mcp_server = importlib.util.module_from_spec(_spec)
sys.modules["mcp_server"] = mcp_server
_spec.loader.exec_module(mcp_server)
edit_graph = mcp_server.edit_graph


@pytest.fixture
def mock_comfyui():
    """Patch all network-dependent functions used by edit_graph."""
    with patch("mcp_server.get_object_info_cached") as mock_info, \
         patch("mcp_server.send_graph_command") as mock_cmd, \
         patch("mcp_server.get_workflow") as mock_wf:

        mock_info.return_value = {"KSampler": {}, "CLIPTextEncode": {}}
        mock_cmd.return_value = {"node_id": "1", "size": [300, 100]}
        mock_wf.return_value = {"workflow": {"nodes": []}}

        yield {
            "info": mock_info,
            "cmd": mock_cmd,
            "wf": mock_wf,
        }


# --- Input parsing (PR #4 fix) ---

class TestEditGraphInputParsing:
    """Tests for the JSON string parsing fix from PR #4."""

    def test_json_string_list(self, mock_comfyui):
        ops = json.dumps([{"action": "create", "node_type": "KSampler"}])
        result = edit_graph(ops)
        assert "ok: 1/1" in result
        mock_comfyui["cmd"].assert_called_once()

    def test_json_string_single_object(self, mock_comfyui):
        ops = json.dumps({"action": "create", "node_type": "KSampler"})
        result = edit_graph(ops)
        assert "ok: 1/1" in result

    def test_normal_list(self, mock_comfyui):
        result = edit_graph([{"action": "create", "node_type": "KSampler"}])
        assert "ok: 1/1" in result

    def test_normal_dict(self, mock_comfyui):
        result = edit_graph({"action": "create", "node_type": "KSampler"})
        assert "ok: 1/1" in result

    def test_invalid_json_string(self, mock_comfyui):
        result = edit_graph("not valid json")
        assert "error:" in result
        assert "Invalid operations" in result
        mock_comfyui["cmd"].assert_not_called()

    def test_json_primitive_int(self, mock_comfyui):
        result = edit_graph("42")
        assert "error:" in result
        assert "Invalid operations" in result

    def test_json_primitive_null(self, mock_comfyui):
        result = edit_graph("null")
        assert "error:" in result
        assert "Invalid operations" in result

    def test_json_primitive_bool(self, mock_comfyui):
        result = edit_graph("true")
        assert "error:" in result
        assert "Invalid operations" in result

    def test_double_encoded_string(self, mock_comfyui):
        inner = json.dumps([{"action": "create", "node_type": "KSampler"}])
        double_encoded = json.dumps(inner)  # string wrapping a string
        result = edit_graph(double_encoded)
        assert "error:" in result
        assert "Invalid operations" in result


# --- Operation validation ---

class TestEditGraphOperations:

    def test_empty_list(self, mock_comfyui):
        result = edit_graph([])
        assert "ok: 0/0" in result
        mock_comfyui["cmd"].assert_not_called()

    def test_unknown_node_type(self, mock_comfyui):
        result = edit_graph([{"action": "create", "node_type": "DoesNotExist"}])
        assert "failed:" in result
        assert "Unknown node type" in result

    def test_create_missing_node_type(self, mock_comfyui):
        result = edit_graph([{"action": "create"}])
        assert "failed:" in result
        assert "node_type is required" in result

    def test_unknown_action(self, mock_comfyui):
        result = edit_graph([{"action": "foo"}])
        assert "failed:" in result
        assert "Unknown action: foo" in result

    def test_get_object_info_error(self, mock_comfyui):
        mock_comfyui["info"].return_value = {"error": "Connection refused"}
        result = edit_graph([{"action": "create", "node_type": "KSampler"}])
        assert "error:" in result
        assert "Connection refused" in result

    def test_create_with_ref_resolution(self, mock_comfyui):
        mock_comfyui["cmd"].side_effect = [
            {"node_id": "10", "size": [300, 100]},
            {"node_id": "11", "size": [300, 100]},
            {"status": "ok"},
        ]
        result = edit_graph([
            {"action": "create", "node_type": "KSampler", "ref": "sampler"},
            {"action": "create", "node_type": "CLIPTextEncode", "ref": "clip"},
            {"action": "connect", "from_node": "clip", "from_slot": 0, "to_node": "sampler", "to_slot": 1},
        ])
        assert "ok: 3/3" in result
        # Verify connect was called with resolved node IDs, not refs
        connect_call = mock_comfyui["cmd"].call_args_list[2]
        assert connect_call[0][1]["from_node_id"] == "11"
        assert connect_call[0][1]["to_node_id"] == "10"

    def test_mixed_success_and_failure(self, mock_comfyui):
        result = edit_graph([
            {"action": "create", "node_type": "KSampler"},
            {"action": "create", "node_type": "DoesNotExist"},
        ])
        assert "failed: 1/2" in result

    def test_set_single_property(self, mock_comfyui):
        mock_comfyui["cmd"].return_value = {"status": "ok"}
        result = edit_graph([{"action": "set", "node_id": "1", "property": "steps", "value": 30}])
        assert "ok: 1/1" in result
        mock_comfyui["cmd"].assert_called_once_with("set_node_property", {
            "node_id": "1",
            "property_name": "steps",
            "value": 30,
        })

    def test_set_multiple_properties(self, mock_comfyui):
        mock_comfyui["cmd"].return_value = {"status": "ok"}
        result = edit_graph([{"action": "set", "node_id": "1", "properties": {"steps": 30, "cfg": 7.5}}])
        assert "ok: 1/1" in result
        assert mock_comfyui["cmd"].call_count == 2

    def test_set_missing_node_id(self, mock_comfyui):
        result = edit_graph([{"action": "set", "property": "steps", "value": 30}])
        assert "failed:" in result
        assert "node_id is required" in result

    def test_connect_missing_nodes(self, mock_comfyui):
        result = edit_graph([{"action": "connect", "from_node": "1"}])
        assert "failed:" in result
        assert "from_node and to_node are required" in result
