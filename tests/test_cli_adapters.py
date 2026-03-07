import importlib.util
import os
import sys
from unittest.mock import patch


_spec = importlib.util.spec_from_file_location(
    "cli_adapters",
    os.path.join(os.path.dirname(__file__), "..", "cli_adapters.py"),
)
cli_adapters = importlib.util.module_from_spec(_spec)
sys.modules["cli_adapters"] = cli_adapters
_spec.loader.exec_module(cli_adapters)


def test_get_adapter_falls_back_to_default():
    adapter = cli_adapters.get_adapter("does-not-exist")
    assert adapter.id == cli_adapters.DEFAULT_ADAPTER_ID


def test_resolve_default_adapter_id_rejects_unknown_values():
    assert cli_adapters.resolve_default_adapter_id("copilot") == "copilot"
    assert cli_adapters.resolve_default_adapter_id("unknown") == cli_adapters.DEFAULT_ADAPTER_ID


def test_claude_build_command_adds_resume_flag_when_conversation_exists():
    adapter = cli_adapters.get_adapter("claude")
    with patch.object(cli_adapters, "has_claude_conversation", return_value=True):
        command = adapter.build_command(command_override="claude")
    assert command == "claude -c"


def test_build_command_prefers_override_for_non_claude_adapter():
    adapter = cli_adapters.get_adapter("copilot")
    command = adapter.build_command(command_override="custom-copilot --safe")
    assert command == '"custom-copilot --safe"'


def test_pick_active_adapter_returns_first_available_when_preferred_missing():
    availability = {
        "claude": False,
        "copilot": True,
        "opencode": False,
        "gemini": False,
        "kilo": False,
    }

    with patch.object(cli_adapters.CliAdapter, "is_available", autospec=True) as mock_is_available:
        mock_is_available.side_effect = lambda adapter: availability[adapter.id]
        assert cli_adapters.pick_active_adapter_id("claude") == "copilot"


def test_find_executable_accepts_powershell_shims_on_windows():
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch("cli_adapters.shutil.which") as mock_which,
    ):
        mock_which.side_effect = lambda candidate: (
            r"C:\nvm4w\nodejs\copilot.ps1" if candidate == "copilot.ps1" else None
        )
        assert cli_adapters.find_executable("copilot") == r"C:\nvm4w\nodejs\copilot.ps1"


def test_to_public_dict_marks_windows_terminal_usable_when_backend_is_available():
    adapter = cli_adapters.get_adapter("copilot")
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch.object(
            cli_adapters,
            "get_terminal_backend_status",
            return_value={"supported": True, "backend": "pywinpty", "reason": ""},
        ),
        patch.object(cli_adapters.CliAdapter, "find_executable", return_value=r"C:\nvm4w\nodejs\copilot.ps1"),
    ):
        public = adapter.to_public_dict()

    assert public["available"] is True
    assert public["terminal_supported"] is True
    assert public["terminal_usable"] is True
    assert public["executable_path"] == r"C:\nvm4w\nodejs\copilot.ps1"
    assert public["unavailable_reason"] == ""


def test_to_public_dict_reports_missing_windows_terminal_backend():
    adapter = cli_adapters.get_adapter("copilot")
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch.object(
            cli_adapters,
            "get_terminal_backend_status",
            return_value={
                "supported": False,
                "backend": None,
                "reason": "Install pywinpty to enable embedded terminals on Windows.",
            },
        ),
        patch.object(cli_adapters.CliAdapter, "find_executable", return_value=r"C:\nvm4w\nodejs\copilot.ps1"),
    ):
        public = adapter.to_public_dict()

    assert public["available"] is True
    assert public["terminal_supported"] is False
    assert public["terminal_usable"] is False
    assert public["unavailable_reason"] == "Install pywinpty to enable embedded terminals on Windows."


def test_to_public_dict_adds_windows_path_guidance_when_cli_missing():
    adapter = cli_adapters.get_adapter("copilot")
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch.object(
            cli_adapters,
            "get_terminal_backend_status",
            return_value={"supported": True, "backend": "pywinpty", "reason": ""},
        ),
        patch.object(cli_adapters.CliAdapter, "find_executable", return_value=None),
    ):
        public = adapter.to_public_dict()

    assert public["available"] is False
    assert public["terminal_usable"] is False
    assert "%APPDATA%\\npm" in public["install_hint"]
    assert "C:\\nvm4w\\nodejs" in public["unavailable_reason"]


def test_build_spawn_command_wraps_powershell_shims_on_windows():
    adapter = cli_adapters.get_adapter("copilot")
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch.object(cli_adapters.CliAdapter, "find_executable", return_value=r"C:\nvm4w\nodejs\copilot.ps1"),
        patch("cli_adapters.shutil.which") as mock_which,
    ):
        mock_which.side_effect = lambda candidate: "powershell.exe" if candidate == "powershell.exe" else None
        command = adapter.build_spawn_command()

    assert command == [
        "powershell.exe",
        "-NoLogo",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        r"C:\nvm4w\nodejs\copilot.ps1",
    ]


def test_build_spawn_command_wraps_command_overrides_for_windows_shell():
    adapter = cli_adapters.get_adapter("copilot")
    with (
        patch.object(cli_adapters, "IS_WINDOWS", True),
        patch.object(cli_adapters, "_find_cmd_executable", return_value="cmd.exe"),
    ):
        command = adapter.build_spawn_command(command_override="custom-copilot --safe")

    assert command == ["cmd.exe", "/d", "/s", "/c", "custom-copilot --safe"]


def test_pick_active_adapter_can_require_terminal_support():
    availability = {
        "claude": True,
        "copilot": False,
        "opencode": False,
        "gemini": False,
        "kilo": False,
    }
    terminal_support = {
        "claude": False,
        "copilot": False,
        "opencode": True,
        "gemini": False,
        "kilo": False,
    }

    with (
        patch.object(cli_adapters.CliAdapter, "is_available", autospec=True) as mock_is_available,
        patch.object(cli_adapters.CliAdapter, "is_terminal_usable", autospec=True) as mock_is_terminal_usable,
    ):
        mock_is_available.side_effect = lambda adapter: availability[adapter.id]
        mock_is_terminal_usable.side_effect = lambda adapter: terminal_support[adapter.id]
        assert cli_adapters.pick_active_adapter_id("claude", require_terminal_usable=True) == "opencode"
