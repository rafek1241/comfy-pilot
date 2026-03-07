"""CLI adapter registry and provider-specific integration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import glob
import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
MCP_SERVER_NAME = "comfyui"
WINDOWS_COMMAND_EXTENSIONS = (".exe", ".cmd", ".bat", ".ps1")
WINDOWS_TERMINAL_BACKEND_HINT = "Install pywinpty to enable embedded terminals on Windows."
WINDOWS_PATH_GUIDANCE = (
    "If it is already installed, add its launch-script directory to PATH for the ComfyUI process "
    "and restart ComfyUI. Common Windows locations include %APPDATA%\\npm, C:\\nvm4w\\nodejs, "
    "and your virtualenv's Scripts folder."
)


def has_claude_conversation(working_dir: str | None = None) -> bool:
    """Check whether Claude has a saved conversation for the working directory."""
    if working_dir is None:
        working_dir = os.getcwd()

    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return False

    folder_name = os.path.abspath(working_dir).replace("/", "-").replace("\\", "-")
    project_dir = claude_dir / folder_name
    if not project_dir.exists():
        return False

    return any(project_dir.glob("*.jsonl"))


def _candidate_command_names(name: str) -> list[str]:
    candidates = [name]
    if IS_WINDOWS:
        _, extension = os.path.splitext(name)
        if not extension:
            candidates.extend(f"{name}{suffix}" for suffix in WINDOWS_COMMAND_EXTENSIONS)
    return candidates


def _is_runnable_path(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    if not IS_WINDOWS:
        return os.access(path, os.X_OK)
    return os.path.splitext(path)[1].lower() in WINDOWS_COMMAND_EXTENSIONS


def find_executable(name: str, verbose: bool = False) -> str | None:
    """Find an executable by checking PATH and common install locations."""
    for candidate in _candidate_command_names(name):
        path = shutil.which(candidate)
        if path:
            if verbose:
                print(f"[Comfy Pilot] Found {candidate} via PATH: {path}")
            return path

    if verbose:
        print(f"[Comfy Pilot] {name} not in PATH, checking common locations...")

    common_paths = [
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        os.path.expanduser(f"~/.nvm/versions/node/*/bin/{name}"),
        os.path.expanduser(f"~/.npm-global/bin/{name}"),
        os.path.expanduser(f"~/node_modules/.bin/{name}"),
        f"/usr/local/n/versions/node/*/bin/{name}",
        os.path.expanduser(f"~/anaconda3/bin/{name}"),
        os.path.expanduser(f"~/miniconda3/bin/{name}"),
        f"/opt/conda/bin/{name}",
        f"/workspace/.local/bin/{name}",
        f"/root/.local/bin/{name}",
        f"/home/*/.local/bin/{name}",
    ]

    if IS_WINDOWS:
        for candidate in _candidate_command_names(name):
            common_paths.extend(
                [
                    os.path.expanduser(f"~\\AppData\\Local\\Programs\\{name}\\{candidate}"),
                    os.path.expanduser(f"~\\AppData\\Roaming\\npm\\{candidate}"),
                    os.path.expanduser(f"~\\AppData\\Local\\Microsoft\\WinGet\\Packages\\*\\{candidate}"),
                    os.path.expanduser(f"~\\AppData\\Local\\Microsoft\\WinGet\\Links\\{candidate}"),
                    os.path.expanduser(f"~\\AppData\\Local\\Microsoft\\WindowsApps\\{candidate}"),
                    os.path.expanduser(f"~\\scoop\\shims\\{candidate}"),
                    f"C:\\Program Files\\nodejs\\{candidate}",
                    f"C:\\nvm4w\\nodejs\\{candidate}",
                    os.path.expanduser(f"~\\.{name}\\local\\{candidate}"),
                ]
            )

    for pattern in common_paths:
        matches = sorted(glob.glob(pattern), reverse=True)
        if verbose and matches:
            print(f"[Comfy Pilot] Checking {pattern}: found {matches}")
        for match in matches:
            if _is_runnable_path(match):
                return match

    if verbose:
        print(f"[Comfy Pilot] {name} not found in common locations")
    return None


def install_claude_code() -> tuple[bool, str]:
    """Attempt to install Claude Code CLI. Returns (success, message)."""
    try:
        if IS_WINDOWS:
            print("[Comfy Pilot] Installing Claude Code CLI via PowerShell...")
            result = subprocess.run(
                ["powershell", "-Command", "irm https://claude.ai/install.ps1 | iex"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print("[Comfy Pilot] PowerShell install failed, trying CMD...")
                result = subprocess.run(
                    ["cmd", "/c", "curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
        else:
            print("[Comfy Pilot] Installing Claude Code CLI...")
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"],
                capture_output=True,
                text=True,
                timeout=120,
            )

        if result.returncode == 0:
            return True, "Claude Code CLI installed successfully"

        error_msg = (result.stderr or result.stdout or "Unknown error").strip()
        return False, f"Installation failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return False, "Installation timed out after 120 seconds"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Installation error: {exc}"


def _quote_part(part: str) -> str:
    if not part:
        return '""'
    if any(char in part for char in (" ", "\t", '"')):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def _join_command(parts: list[str]) -> str:
    return " ".join(_quote_part(part) for part in parts if part)


def _find_cmd_executable() -> str:
    return os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"


def _find_powershell_executable() -> str:
    return shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"


def get_terminal_backend_status() -> dict:
    if not IS_WINDOWS:
        return {"supported": True, "backend": "pty", "reason": ""}

    try:
        import winpty  # noqa: F401
    except ImportError:
        return {
            "supported": False,
            "backend": None,
            "reason": WINDOWS_TERMINAL_BACKEND_HINT,
        }

    return {"supported": True, "backend": "pywinpty", "reason": ""}


def _build_windows_spawn_command(executable: str, arguments: list[str]) -> list[str]:
    extension = os.path.splitext(executable)[1].lower()
    if extension == ".ps1":
        return [
            _find_powershell_executable(),
            "-NoLogo",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            executable,
            *arguments,
        ]
    if extension in (".cmd", ".bat"):
        command_line = subprocess.list2cmdline([executable, *arguments])
        return [_find_cmd_executable(), "/d", "/s", "/c", command_line]
    return [executable, *arguments]


@dataclass(frozen=True)
class CliAdapter:
    id: str
    label: str
    command_candidates: tuple[str, ...]
    fallback_command: str
    install_hint: str
    supports_mcp: bool = True
    supports_mcp_autoconfig: bool = False
    resume_argument: str | None = None
    mcp_notes: str = ""

    def find_executable(self) -> str | None:
        for candidate in self.command_candidates:
            path = find_executable(candidate)
            if path:
                return path
        return None

    def is_available(self) -> bool:
        return self.find_executable() is not None

    def is_terminal_supported(self) -> bool:
        return get_terminal_backend_status()["supported"]

    def is_terminal_usable(self) -> bool:
        return self.find_executable() is not None and self.is_terminal_supported()

    def install_advice(self) -> str:
        if IS_WINDOWS:
            return f"{self.install_hint} {WINDOWS_PATH_GUIDANCE}"
        return self.install_hint

    def describe_terminal_availability(self) -> dict:
        executable = self.find_executable()
        available = executable is not None
        backend_status = get_terminal_backend_status()
        terminal_supported = backend_status["supported"]
        terminal_usable = available and terminal_supported

        if terminal_usable:
            unavailable_reason = ""
        elif available:
            unavailable_reason = backend_status["reason"]
        else:
            unavailable_reason = self.install_advice()

        return {
            "available": available,
            "terminal_supported": terminal_supported,
            "terminal_usable": terminal_usable,
            "executable_path": executable,
            "unavailable_reason": unavailable_reason,
        }

    def build_command(self, working_dir: str | None = None, command_override: str | None = None) -> str:
        executable = command_override or self.find_executable() or self.fallback_command
        parts = [executable]
        if self.resume_argument and has_claude_conversation(working_dir):
            parts.append(self.resume_argument)
        return _join_command(parts)

    def build_spawn_command(
        self,
        working_dir: str | None = None,
        command_override: str | None = None,
    ) -> str | list[str]:
        if command_override:
            if IS_WINDOWS:
                return [_find_cmd_executable(), "/d", "/s", "/c", command_override]
            return command_override

        executable = self.find_executable() or self.fallback_command
        arguments = []
        if self.resume_argument and has_claude_conversation(working_dir):
            arguments.append(self.resume_argument)

        if IS_WINDOWS:
            return _build_windows_spawn_command(executable, arguments)
        return _join_command([executable, *arguments])

    def to_public_dict(self) -> dict:
        public_status = self.describe_terminal_availability()
        return {
            "id": self.id,
            "label": self.label,
            **public_status,
            "supports_mcp": self.supports_mcp,
            "supports_mcp_autoconfig": self.supports_mcp_autoconfig,
            "install_hint": self.install_advice(),
            "mcp_notes": self.mcp_notes,
        }


ADAPTERS: dict[str, CliAdapter] = {
    "claude": CliAdapter(
        id="claude",
        label="Claude Code",
        command_candidates=("claude",),
        fallback_command="claude",
        install_hint="Install Claude Code CLI and ensure the 'claude' command is available.",
        supports_mcp=True,
        supports_mcp_autoconfig=True,
        resume_argument="-c",
        mcp_notes="Comfy Pilot can auto-configure Claude's MCP entry when the CLI is installed.",
    ),
    "copilot": CliAdapter(
        id="copilot",
        label="GitHub Copilot CLI",
        command_candidates=("copilot", "github-copilot", "github-copilot-cli"),
        fallback_command="copilot",
        install_hint="Install GitHub Copilot CLI and ensure one of 'copilot', 'github-copilot', or 'github-copilot-cli' is available.",
        supports_mcp=True,
        supports_mcp_autoconfig=False,
        mcp_notes="Manual MCP/tool configuration for GitHub Copilot CLI may be required until provider-specific setup automation is added.",
    ),
    "opencode": CliAdapter(
        id="opencode",
        label="OpenCode CLI",
        command_candidates=("opencode",),
        fallback_command="opencode",
        install_hint="Install OpenCode CLI and ensure the 'opencode' command is available.",
        supports_mcp=True,
        supports_mcp_autoconfig=False,
        mcp_notes="Manual MCP/tool configuration for OpenCode CLI may be required until provider-specific setup automation is added.",
    ),
    "gemini": CliAdapter(
        id="gemini",
        label="Gemini CLI",
        command_candidates=("gemini",),
        fallback_command="gemini",
        install_hint="Install Gemini CLI and ensure the 'gemini' command is available.",
        supports_mcp=True,
        supports_mcp_autoconfig=False,
        mcp_notes="Manual MCP/tool configuration for Gemini CLI may be required until provider-specific setup automation is added.",
    ),
    "kilo": CliAdapter(
        id="kilo",
        label="Kilo Code CLI",
        command_candidates=("kilo", "kilocode", "kilo-code"),
        fallback_command="kilo",
        install_hint="Install Kilo Code CLI and ensure one of 'kilo', 'kilocode', or 'kilo-code' is available.",
        supports_mcp=True,
        supports_mcp_autoconfig=False,
        mcp_notes="Manual MCP/tool configuration for Kilo Code CLI may be required until provider-specific setup automation is added.",
    ),
}

ADAPTER_ORDER = tuple(ADAPTERS.keys())
DEFAULT_ADAPTER_ID = "claude"


def list_adapters() -> list[CliAdapter]:
    return [ADAPTERS[adapter_id] for adapter_id in ADAPTER_ORDER]


def get_adapter(adapter_id: str | None) -> CliAdapter:
    if adapter_id and adapter_id in ADAPTERS:
        return ADAPTERS[adapter_id]
    return ADAPTERS[DEFAULT_ADAPTER_ID]


def resolve_default_adapter_id(preferred_id: str | None = None) -> str:
    if preferred_id in ADAPTERS:
        return preferred_id
    return DEFAULT_ADAPTER_ID


def pick_active_adapter_id(preferred_id: str | None = None, require_terminal_usable: bool = False) -> str:
    preferred = resolve_default_adapter_id(preferred_id)
    predicate = (
        (lambda adapter: adapter.is_terminal_usable())
        if require_terminal_usable
        else (lambda adapter: adapter.is_available())
    )
    if predicate(ADAPTERS[preferred]):
        return preferred
    for adapter in list_adapters():
        if predicate(adapter):
            return adapter.id
    return preferred


def ensure_adapter_mcp_config(adapter: CliAdapter, plugin_dir: str, python_path: str) -> dict:
    """Try to configure the shared MCP server for adapters that support autoconfig."""
    mcp_server_path = os.path.join(plugin_dir, "mcp_server.py")
    if not os.path.isfile(mcp_server_path):
        return {"configured": False, "error": "MCP server file not found"}

    executable = adapter.find_executable()
    if not executable:
        return {"configured": False, "error": f"{adapter.label} executable not found"}

    if not adapter.supports_mcp_autoconfig:
        return {"configured": False, "error": adapter.mcp_notes or "Manual MCP setup required"}

    try:
        result = subprocess.run(
            [executable, "mcp", "get", MCP_SERVER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {"configured": True, "message": "MCP server already configured"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            [executable, "mcp", "add", MCP_SERVER_NAME, python_path, mcp_server_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"configured": False, "error": "Timeout adding MCP server"}
    except FileNotFoundError:
        return {"configured": False, "error": f"{adapter.label} executable not found"}

    if result.returncode == 0:
        return {"configured": True, "message": "MCP server added successfully"}

    error_text = (result.stderr or result.stdout or "Failed to configure MCP").strip()
    return {"configured": False, "error": error_text}


def get_adapter_mcp_status(adapter: CliAdapter, plugin_dir: str, python_path: str) -> dict:
    """Return adapter-specific MCP readiness details."""
    mcp_server_path = os.path.join(plugin_dir, "mcp_server.py")
    shared_available = os.path.isfile(mcp_server_path)
    status = {
        "adapter": adapter.id,
        "label": adapter.label,
        "connected": shared_available,
        "configured": False,
        "ready": False,
        "supports_mcp": adapter.supports_mcp,
        "supports_mcp_autoconfig": adapter.supports_mcp_autoconfig,
        "tools": 15 if shared_available else 0,
        "terminal_supported": adapter.is_terminal_supported(),
        "executable_path": None,
    }

    if not shared_available:
        status["error"] = "MCP server file not found"
        return status

    executable = adapter.find_executable()
    if not executable:
        status["error"] = adapter.install_advice()
        return status
    status["executable_path"] = executable

    if adapter.supports_mcp_autoconfig:
        try:
            result = subprocess.run(
                [executable, "mcp", "get", MCP_SERVER_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                status["configured"] = True
                status["ready"] = True
                status["message"] = "MCP server configured"
            else:
                status["error"] = (result.stderr or result.stdout or "MCP server not configured").strip()
        except subprocess.TimeoutExpired:
            status["error"] = "Timeout checking MCP configuration"
        except FileNotFoundError:
            status["error"] = adapter.install_hint
        return status

    status["error"] = adapter.mcp_notes or "Manual MCP setup required"
    return status
