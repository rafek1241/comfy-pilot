import importlib.util
import os
import sys
from unittest.mock import patch


_spec = importlib.util.spec_from_file_location(
    "mcp_server_plugin_test",
    os.path.join(os.path.dirname(__file__), "..", "mcp_server.py"),
)
mcp_server = importlib.util.module_from_spec(_spec)
sys.modules["mcp_server_plugin_test"] = mcp_server
_spec.loader.exec_module(mcp_server)


def test_make_plugin_request_prefers_neutral_endpoint():
    with patch.object(mcp_server, "make_request", return_value={"workflow": "ok"}) as mock_make_request:
        result = mcp_server.make_plugin_request("workflow")

    assert result == {"workflow": "ok"}
    mock_make_request.assert_called_once_with("/comfy-pilot/workflow", method="GET", data=None, timeout=None)


def test_make_plugin_request_falls_back_to_legacy_endpoint_on_404():
    with patch.object(
        mcp_server,
        "make_request",
        side_effect=[
            {"error": "HTTP error from ComfyUI: 404 Not Found"},
            {"workflow": "legacy"},
        ],
    ) as mock_make_request:
        result = mcp_server.make_plugin_request("workflow")

    assert result == {"workflow": "legacy"}
    assert mock_make_request.call_count == 2
    assert mock_make_request.call_args_list[1].args[0] == "/claude-code/workflow"
