# ComfyUI Comfy Pilot Plugin
# A floating multi-terminal extension with CLI-agnostic adapters

import asyncio
import json
import os
import struct
import sys

from aiohttp import web

try:
    from .cli_adapters import (
        DEFAULT_ADAPTER_ID,
        ensure_adapter_mcp_config,
        get_adapter,
        get_adapter_mcp_status,
        install_claude_code,
        list_adapters,
        pick_active_adapter_id,
    )
    from .settings_store import SettingsStore
except ImportError:  # pragma: no cover - fallback for direct execution
    from cli_adapters import (
        DEFAULT_ADAPTER_ID,
        ensure_adapter_mcp_config,
        get_adapter,
        get_adapter_mcp_status,
        install_claude_code,
        list_adapters,
        pick_active_adapter_id,
    )
    from settings_store import SettingsStore

# Platform detection
IS_WINDOWS = sys.platform == "win32"

# Unix-only imports (for terminal functionality)
if not IS_WINDOWS:
    import fcntl
    import pty
    import resource
    import signal
    import termios
else:
    fcntl = None
    pty = None
    resource = None
    signal = None
    termios = None

WEB_DIRECTORY = "./js"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

PLUGIN_LOG_PREFIX = "[Comfy Pilot]"
ROUTE_BASE = "/comfy-pilot"
LEGACY_ROUTE_BASE = "/claude-code"
WS_ROUTE = "/ws/comfy-pilot-terminal"
LEGACY_WS_ROUTE = "/ws/claude-terminal"


def plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


settings_store = SettingsStore(os.path.join(plugin_dir(), ".comfy_pilot_settings.json"))


class WebSocketTerminal:
    """Manages a PTY session connected via WebSocket."""

    def __init__(self):
        self.fd = None
        self.pid = None
        self.running = False
        self._decoder = None

    def spawn(self, command=None):
        """Spawn a new PTY with an optional command."""
        if IS_WINDOWS:
            print(f"{PLUGIN_LOG_PREFIX} Terminal not supported on Windows")
            return False

        shell = os.environ.get("SHELL", "/bin/bash")
        self.pid, self.fd = pty.fork()

        if self.pid == 0:
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"

            if command:
                os.execlpe(shell, shell, "-l", "-i", "-c", command, env)
            else:
                shell_name = os.path.basename(shell)
                os.execlpe(shell, f"-{shell_name}", env)
        else:
            flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
            fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self.running = True
            return True

    def resize(self, rows, cols):
        """Resize the PTY and notify the child process."""
        if IS_WINDOWS or not self.fd:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGWINCH)
            except OSError:
                pass

    def write(self, data):
        """Write data to the PTY."""
        if IS_WINDOWS or not self.fd:
            return
        os.write(self.fd, data.encode("utf-8"))

    def read_nonblock(self):
        """Non-blocking read from PTY."""
        if IS_WINDOWS or not self.fd:
            return None
        try:
            data = os.read(self.fd, 4096)
            if data:
                if self._decoder is None:
                    import codecs

                    self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                return self._decoder.decode(data)
        except BlockingIOError:
            return None
        except (OSError, IOError):
            self.running = False
        return None

    def close(self):
        """Close the PTY."""
        self.running = False
        if IS_WINDOWS:
            return
        if self.fd:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.pid:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
            except (OSError, ChildProcessError):
                pass
            self.pid = None


class TerminalSessionManager:
    """Tracks live terminal sessions independently of a specific CLI provider."""

    def __init__(self):
        self._sessions = {}

    def add(self, session_id, adapter_id, terminal, window_session_id=None):
        self._sessions[session_id] = {
            "adapter_id": adapter_id,
            "window_session_id": window_session_id,
            "terminal": terminal,
        }

    def remove(self, session_id):
        self._sessions.pop(session_id, None)

    def count(self):
        return len(self._sessions)


terminal_session_manager = TerminalSessionManager()

# Global storage for the current workflow (updated by frontend)
current_workflow = {"workflow": None, "workflow_api": None, "timestamp": None}

# Pending graph commands to be executed by frontend
pending_commands = []
command_results = {}

# Memory logging
_last_memory_log = 0
MEMORY_LOG_INTERVAL = 60


def load_settings(force=False):
    return settings_store.load(force=force)


def save_settings(updates):
    return settings_store.update(updates)


def get_requested_adapter_id(request):
    adapter_id = request.query.get("adapter")
    if adapter_id:
        return adapter_id
    if request.path == LEGACY_WS_ROUTE or request.path.startswith(LEGACY_ROUTE_BASE):
        return DEFAULT_ADAPTER_ID
    return load_settings().get("default_cli", DEFAULT_ADAPTER_ID)


def get_requested_adapter(request):
    return get_adapter(get_requested_adapter_id(request))


def get_memory_mb():
    """Get current memory usage in MB."""
    if IS_WINDOWS:
        try:
            import psutil

            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0

    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024


def get_plugin_memory_breakdown():
    """Get memory breakdown of plugin data structures."""
    workflow_size = len(json.dumps(current_workflow)) if current_workflow.get("workflow") else 0
    commands_size = len(json.dumps(pending_commands)) if pending_commands else 0
    results_size = len(json.dumps(command_results)) if command_results else 0

    return {
        "workflow_bytes": workflow_size,
        "pending_commands_bytes": commands_size,
        "command_results_bytes": results_size,
        "terminal_sessions": terminal_session_manager.count(),
        "total_plugin_kb": round((workflow_size + commands_size + results_size) / 1024, 2),
    }


def log_memory(context=""):
    """Log memory usage if enough time has passed since last log."""
    global _last_memory_log
    import time

    now = time.time()
    if now - _last_memory_log >= MEMORY_LOG_INTERVAL:
        _last_memory_log = now
        breakdown = get_plugin_memory_breakdown()
        suffix = f" | {context}" if context else ""
        print(
            f"{PLUGIN_LOG_PREFIX} Plugin data: {breakdown['total_plugin_kb']:.1f}KB | "
            f"Sessions: {breakdown['terminal_sessions']}{suffix}"
        )


async def memory_stats_handler(request):
    """Return current memory stats as JSON."""
    mem_mb = get_memory_mb()
    breakdown = get_plugin_memory_breakdown()

    return web.json_response(
        {
            "process_memory_mb": round(mem_mb, 2),
            "note": "process_memory_mb is the entire ComfyUI process, not just this plugin",
            "plugin_data": breakdown,
        }
    )


async def workflow_handler(request):
    """Handle workflow GET/POST requests."""
    global current_workflow

    if request.method == "POST":
        try:
            data = await request.json()
            current_workflow = {
                "workflow": data.get("workflow"),
                "workflow_api": data.get("workflow_api"),
                "timestamp": data.get("timestamp"),
            }
            log_memory("workflow update")
            return web.json_response({"status": "ok"})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(current_workflow)


async def graph_command_handler(request):
    """Handle graph manipulation commands from the MCP server."""
    global pending_commands, command_results

    if request.method == "GET":
        if pending_commands:
            cmd = pending_commands.pop(0)
            return web.json_response({"command": cmd})
        return web.json_response({"command": None})

    try:
        data = await request.json()

        if "result" in data:
            cmd_id = data.get("command_id")
            command_results[cmd_id] = data.get("result")
            return web.json_response({"status": "ok"})

        import uuid

        cmd_id = str(uuid.uuid4())
        cmd = {
            "id": cmd_id,
            "action": data.get("action"),
            "params": data.get("params", {}),
        }
        pending_commands.append(cmd)

        import time

        start = time.time()
        while cmd_id not in command_results and time.time() - start < 5:
            await asyncio.sleep(0.1)

        if cmd_id in command_results:
            result = command_results.pop(cmd_id)
            return web.json_response(result)

        return web.json_response({"error": "Timeout waiting for frontend to execute command"}, status=504)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return web.json_response({"error": str(exc)}, status=500)


async def run_node_handler(request):
    """Run the workflow up to a specific node."""
    try:
        data = await request.json()
        node_id = data.get("node_id")

        if not node_id:
            return web.json_response({"error": "node_id is required"}, status=400)

        if not current_workflow.get("workflow_api"):
            return web.json_response(
                {"error": "No workflow available. Make sure ComfyUI is open in browser."},
                status=400,
            )

        workflow_api = current_workflow["workflow_api"]
        prompt = workflow_api.get("output", workflow_api)
        node_id_str = str(node_id)

        if node_id_str not in prompt:
            return web.json_response({"error": f"Node {node_id} not found in workflow"}, status=400)

        from server import PromptServer
        import uuid

        prompt_id = str(uuid.uuid4())
        PromptServer.instance.prompt_queue.put(
            (0, prompt_id, prompt, {"client_id": "comfy-pilot"}, [node_id_str])
        )

        return web.json_response({"status": "queued", "prompt_id": prompt_id, "node_id": node_id_str})
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return web.json_response({"error": str(exc)}, status=500)


def build_cli_inventory():
    settings = load_settings()
    adapters = []
    for adapter in list_adapters():
        adapter_info = adapter.to_public_dict()
        adapter_info["enabled"] = adapter.id in settings.get("enabled_clis", [])
        adapter_info["selected"] = adapter.id == settings.get("default_cli")
        adapters.append(adapter_info)

    return {
        "default_cli": settings.get("default_cli", DEFAULT_ADAPTER_ID),
        "active_default_cli": pick_active_adapter_id(
            settings.get("default_cli"), require_terminal_usable=True
        ),
        "enabled_clis": settings.get("enabled_clis", []),
        "show_unavailable": settings.get("show_unavailable", False),
        "window_closed": settings.get("window_closed", False),
        "adapters": adapters,
    }


async def clis_handler(request):
    """Return CLI adapter inventory and settings."""
    return web.json_response(build_cli_inventory())


async def settings_handler(request):
    """Get or update persisted Comfy Pilot settings."""
    if request.method == "GET":
        return web.json_response(load_settings())

    try:
        data = await request.json()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)

    saved = save_settings(data)
    if not IS_WINDOWS:
        maybe_setup_default_adapter_mcp(saved)
    return web.json_response(saved)


async def mcp_status_handler(request):
    """Check adapter-specific MCP configuration and shared backend availability."""
    adapter = get_requested_adapter(request)
    status = get_adapter_mcp_status(adapter, plugin_dir(), sys.executable)
    status["platform"] = "windows" if IS_WINDOWS else "unix"
    status["default_cli"] = load_settings().get("default_cli", DEFAULT_ADAPTER_ID)
    return web.json_response(status)


async def platform_info_handler(request):
    """Return platform information."""
    return web.json_response(
        {
            "platform": sys.platform,
            "is_windows": IS_WINDOWS,
            "terminal_supported": not IS_WINDOWS,
            "python_version": sys.version,
            "comfyui_url": get_comfyui_url_cached(),
            "default_cli": load_settings().get("default_cli", DEFAULT_ADAPTER_ID),
        }
    )


async def websocket_handler(request):
    """Handle WebSocket connections for terminal sessions."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    adapter = get_requested_adapter(request)
    window_session_id = request.query.get("session")

    if IS_WINDOWS:
        adapter_status = adapter.to_public_dict()
        await ws.send_str(
            json.dumps(
                {
                    "type": "error",
                    "message": adapter_status.get("unavailable_reason")
                    or (
                        f"Embedded terminals are not supported on Windows for {adapter.label}. "
                        "Use the CLI directly and keep Comfy Pilot's REST/MCP integration."
                    ),
                }
            )
        )
        await ws.close()
        return ws

    session_id = id(ws)
    terminal = WebSocketTerminal()
    terminal_session_manager.add(session_id, adapter.id, terminal, window_session_id=window_session_id)
    terminal_started = False

    print(f"{PLUGIN_LOG_PREFIX} WebSocket connected: session={session_id} adapter={adapter.id}")
    log_memory(f"ws connect {adapter.id}")

    settings = load_settings()
    command_override = settings.get("command_overrides", {}).get(adapter.id)
    explicit_command = request.query.get("cmd")
    command = explicit_command or adapter.build_command(os.getcwd(), command_override=command_override)

    if not explicit_command and adapter.id == "claude" and not adapter.is_available():
        print(f"{PLUGIN_LOG_PREFIX} Claude CLI not found, attempting auto-install...")
        success, message = install_claude_code()
        if success:
            command = adapter.build_command(os.getcwd(), command_override=command_override)
            print(f"{PLUGIN_LOG_PREFIX} Claude CLI installed, using command: {command}")
        else:
            print(f"{PLUGIN_LOG_PREFIX} Claude auto-install failed: {message}")

    if not IS_WINDOWS and adapter.supports_mcp_autoconfig:
        result = ensure_adapter_mcp_config(adapter, plugin_dir(), sys.executable)
        if result.get("configured"):
            print(f"{PLUGIN_LOG_PREFIX} {adapter.label} MCP ready")
        elif result.get("error"):
            print(f"{PLUGIN_LOG_PREFIX} {adapter.label} MCP setup skipped: {result['error']}")

    async def read_pty():
        """Read from PTY and send to WebSocket."""
        loop = asyncio.get_event_loop()
        fd = terminal.fd
        read_event = asyncio.Event()
        pending_data = []

        def on_readable():
            try:
                data = terminal.read_nonblock()
                if data:
                    pending_data.append(data)
                    read_event.set()
            except Exception as exc:
                print(f"{PLUGIN_LOG_PREFIX} Read callback error ({adapter.id}): {exc}")

        loop.add_reader(fd, on_readable)

        try:
            while terminal.running and not ws.closed:
                await read_event.wait()
                read_event.clear()
                while pending_data:
                    await ws.send_str("o" + pending_data.pop(0))
        except Exception as exc:
            print(f"{PLUGIN_LOG_PREFIX} Read error ({adapter.id}): {exc}")
        finally:
            try:
                loop.remove_reader(fd)
            except Exception:
                pass

    read_task = None

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "i":
                        terminal.write(data.get("d", ""))
                    elif msg_type == "input":
                        terminal.write(data.get("data", ""))
                    elif msg_type == "resize":
                        rows = data.get("rows", 24)
                        cols = data.get("cols", 80)

                        if not terminal_started:
                            terminal.spawn(command)
                            terminal.resize(rows, cols)
                            terminal_started = True
                            read_task = asyncio.create_task(read_pty())
                            print(
                                f"{PLUGIN_LOG_PREFIX} Terminal started: "
                                f"adapter={adapter.id} size={cols}x{rows}"
                            )
                        else:
                            terminal.resize(rows, cols)
                except json.JSONDecodeError:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                print(f"{PLUGIN_LOG_PREFIX} WebSocket error ({adapter.id}): {ws.exception()}")
                break
    finally:
        terminal.running = False
        if read_task:
            read_task.cancel()
        terminal.close()
        terminal_session_manager.remove(session_id)
        print(f"{PLUGIN_LOG_PREFIX} WebSocket disconnected: session={session_id} adapter={adapter.id}")
        log_memory(f"ws disconnect {adapter.id}")

    return ws


_comfyui_url_cache = None


def get_comfyui_url_cached():
    """Get the cached ComfyUI URL."""
    global _comfyui_url_cache
    if _comfyui_url_cache:
        return _comfyui_url_cache
    try:
        from server import PromptServer

        address = PromptServer.instance.address
        port = PromptServer.instance.port
        _comfyui_url_cache = f"http://{address}:{port}"
        return _comfyui_url_cache
    except Exception:
        return "http://127.0.0.1:8188"


def write_comfyui_url():
    """Write the ComfyUI server URL to a file for the MCP server to read."""
    url_file = os.path.join(plugin_dir(), ".comfyui_url")

    try:
        from server import PromptServer

        address = PromptServer.instance.address
        port = PromptServer.instance.port
        url = f"http://{address}:{port}"
        with open(url_file, "w", encoding="utf-8") as file:
            file.write(url)
        print(f"{PLUGIN_LOG_PREFIX} ComfyUI URL written to {url_file}: {url}")
    except Exception:
        with open(url_file, "w", encoding="utf-8") as file:
            file.write("http://127.0.0.1:8188")
        print(f"{PLUGIN_LOG_PREFIX} Using default ComfyUI URL")


def maybe_setup_default_adapter_mcp(settings=None):
    """Attempt MCP configuration for the selected default adapter when supported."""
    if IS_WINDOWS:
        print(f"{PLUGIN_LOG_PREFIX} Skipping MCP auto-config on Windows")
        return

    settings = settings or load_settings()
    adapter = get_adapter(settings.get("default_cli"))
    if not adapter.supports_mcp_autoconfig:
        print(f"{PLUGIN_LOG_PREFIX} {adapter.label} requires manual MCP setup")
        return

    result = ensure_adapter_mcp_config(adapter, plugin_dir(), sys.executable)
    if result.get("configured"):
        print(f"{PLUGIN_LOG_PREFIX} {adapter.label} MCP configured")
    elif result.get("error"):
        print(f"{PLUGIN_LOG_PREFIX} {adapter.label} MCP not configured: {result['error']}")


def add_route_once(app, method, path, handler):
    """Register a route unless it already exists."""
    method = method.upper()
    for route in app.router.routes():
        resource = getattr(route, "resource", None)
        canonical = getattr(resource, "canonical", None)
        if canonical == path and getattr(route, "method", None) == method:
            return False

    add_method = getattr(app.router, f"add_{method.lower()}")
    add_method(path, handler)
    return True


def setup_routes(app):
    """Set up provider-neutral and compatibility API routes."""
    routes = [
        ("GET", WS_ROUTE, websocket_handler),
        ("GET", LEGACY_WS_ROUTE, websocket_handler),
        ("GET", f"{ROUTE_BASE}/workflow", workflow_handler),
        ("POST", f"{ROUTE_BASE}/workflow", workflow_handler),
        ("GET", f"{LEGACY_ROUTE_BASE}/workflow", workflow_handler),
        ("POST", f"{LEGACY_ROUTE_BASE}/workflow", workflow_handler),
        ("POST", f"{ROUTE_BASE}/run-node", run_node_handler),
        ("POST", f"{LEGACY_ROUTE_BASE}/run-node", run_node_handler),
        ("GET", f"{ROUTE_BASE}/graph-command", graph_command_handler),
        ("POST", f"{ROUTE_BASE}/graph-command", graph_command_handler),
        ("GET", f"{LEGACY_ROUTE_BASE}/graph-command", graph_command_handler),
        ("POST", f"{LEGACY_ROUTE_BASE}/graph-command", graph_command_handler),
        ("GET", f"{ROUTE_BASE}/mcp-status", mcp_status_handler),
        ("GET", f"{LEGACY_ROUTE_BASE}/mcp-status", mcp_status_handler),
        ("GET", f"{ROUTE_BASE}/memory", memory_stats_handler),
        ("GET", f"{LEGACY_ROUTE_BASE}/memory", memory_stats_handler),
        ("GET", f"{ROUTE_BASE}/platform", platform_info_handler),
        ("GET", f"{LEGACY_ROUTE_BASE}/platform", platform_info_handler),
        ("GET", f"{ROUTE_BASE}/clis", clis_handler),
        ("GET", f"{ROUTE_BASE}/settings", settings_handler),
        ("POST", f"{ROUTE_BASE}/settings", settings_handler),
    ]

    for method, path, handler in routes:
        add_route_once(app, method, path, handler)

    print(f"{PLUGIN_LOG_PREFIX} Terminal WebSocket endpoint registered at {WS_ROUTE}")
    print(f"{PLUGIN_LOG_PREFIX} Workflow API endpoint registered at {ROUTE_BASE}/workflow")
    print(f"{PLUGIN_LOG_PREFIX} Graph command endpoint registered at {ROUTE_BASE}/graph-command")
    print(f"{PLUGIN_LOG_PREFIX} CLI inventory endpoint registered at {ROUTE_BASE}/clis")
    print(f"{PLUGIN_LOG_PREFIX} Settings endpoint registered at {ROUTE_BASE}/settings")
    if IS_WINDOWS:
        print(f"{PLUGIN_LOG_PREFIX} Note: Terminal functionality disabled on Windows")


# Hook into ComfyUI's server setup
try:
    from server import PromptServer

    setup_routes(PromptServer.instance.app)
    write_comfyui_url()
    maybe_setup_default_adapter_mcp()

    mem_mb = get_memory_mb()
    platform_note = " (Windows - terminal disabled)" if IS_WINDOWS else ""
    print(f"{PLUGIN_LOG_PREFIX} Plugin loaded successfully{platform_note} (Memory: {mem_mb:.1f}MB)")
except Exception as exc:
    print(f"{PLUGIN_LOG_PREFIX} Failed to register routes: {exc}")
    import traceback

    traceback.print_exc()
