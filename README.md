# Comfy Pilot

[![Stars](https://img.shields.io/github/stars/ConstantineB6/Comfy-Pilot)](https://github.com/ConstantineB6/Comfy-Pilot/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ComfyUI Registry](https://img.shields.io/badge/ComfyUI-Registry-blue)](https://registry.comfy.org/publishers/constantine/nodes/comfy-pilot)

Talk to your ComfyUI workflows. Comfy Pilot gives supported coding CLIs direct access to see, edit, and run your workflows - with embedded terminal tabs right inside ComfyUI.

![Comfy Pilot](thumbnail.jpg)

## Why?

Building ComfyUI workflows means manually searching for nodes, dragging connections, and tweaking values one at a time. With Comfy Pilot, you just describe what you want:

- *"Build me an SDXL workflow with ControlNet"* — Claude creates all the nodes, connects them, and sets the parameters
- *"Look at the output and increase the detail"* — Claude sees your generated image and adjusts the workflow
- *"Download the FLUX schnell model and set up a workflow for it"* — Claude downloads the model and builds a workflow from scratch

No copy-pasting node names. No hunting through menus. Just say what you want.

## Installation

**CLI (Recommended):**
```bash
comfy node install comfy-pilot
```

**ComfyUI Manager:**
1. Open ComfyUI
2. Click **Manager** → **Install Custom Nodes**
3. Search for "Comfy Pilot"
4. Click **Install**
5. Restart ComfyUI

**Git Clone:**
```bash
cd ~/Documents/ComfyUI/custom_nodes && git clone https://github.com/ConstantineB6/comfy-pilot.git
```

Claude Code can still be auto-installed when selected as the default CLI. Other supported CLIs can be enabled when they are installed on your system.

## Requirements

- ComfyUI
- Python 3.8+

## Features

- **MCP Server** - Gives supported coding CLIs direct access to view, edit, and run your ComfyUI workflows
- **Tabbed Embedded Terminals** - One live xterm.js terminal per available CLI, running in parallel inside ComfyUI
- **Configurable Default CLI** - Choose the default terminal tab from ComfyUI settings
- **Image Viewing** - Claude can see outputs from Preview Image and Save Image nodes
- **Graph Editing** - Create, delete, move, and connect nodes programmatically

## Demo

https://github.com/user-attachments/assets/325b1194-2334-48a1-94c3-86effd1fef02

## Usage

1. Restart ComfyUI after installation
2. The floating Comfy Pilot terminal window appears in the top-right corner
3. Available CLIs each get their own terminal tab and stay live in parallel
4. Configure the default CLI tab in ComfyUI settings if needed
5. Ask your selected CLI agent to help with your workflow:
   - "What nodes are in my current workflow?"
   - "Add a KSampler node connected to my checkpoint loader"
   - "Look at the preview image and tell me what you see"
   - "Run the workflow up to node 5"

## MCP Tools

The MCP server provides these tools to supported CLI agents:

| Tool | Description |
|------|-------------|
| `get_workflow` | Get the current workflow from the browser |
| `summarize_workflow` | Human-readable workflow summary |
| `get_node_types` | Search available node types with filtering |
| `get_node_info` | Get detailed info about a specific node type |
| `get_status` | Queue status, system stats, and execution history |
| `run` | Run workflow (optionally up to a specific node) or interrupt |
| `edit_graph` | Batch create, delete, move, connect, and configure nodes |
| `view_image` | View images from Preview Image / Save Image nodes |
| `search_custom_nodes` | Search ComfyUI Manager registry for custom nodes |
| `install_custom_node` | Install a custom node from the registry |
| `uninstall_custom_node` | Uninstall a custom node |
| `update_custom_node` | Update a custom node to latest version |
| `download_model` | Download models from Hugging Face, CivitAI, or direct URLs |

### Example: Creating Nodes

```
Create a KSampler and connect it to my checkpoint loader
```

Claude will use `edit_graph` to:
1. Create the KSampler node
2. Connect the MODEL output from CheckpointLoader to KSampler's model input
3. Position it appropriately in the graph

### Example: Viewing Images

```
Look at the preview image and describe what you see
```

Claude will use `view_image` to fetch and analyze the image output.

### Example: Downloading Models

```
Download the FLUX.1 schnell model for me
```

Claude will use `download_model` to download from Hugging Face to your ComfyUI models folder. Supports:
- Hugging Face (including gated models with token auth)
- CivitAI
- Direct download URLs

## Terminal Controls

- **Drag** title bar to move
- **Drag** bottom-right corner to resize
- **−** Minimize
- **×** Close
- **↻** Reconnect session

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (ComfyUI)                                  │
│  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │  xterm.js       │  │  Workflow State          │  │
│  │  Terminal       │  │  (synced to backend)     │  │
│  └────────┬────────┘  └────────────┬─────────────┘  │
│           │ WebSocket              │ REST API       │
└───────────┼────────────────────────┼────────────────┘
            │                        │
            ▼                        ▼
┌─────────────────────────────────────────────────────┐
│  ComfyUI Server                                     │
│  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │  PTY Process    │  │  Plugin Endpoints        │  │
│  │  (CLI tabs)     │  │  /comfy-pilot/*          │  │
│  └─────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────┘
            │                        │
            │                        ▼
            │           ┌──────────────────────────┐
            └──────────▶│  MCP Server              │
                        │  (stdio transport)       │
                        └──────────────────────────┘
```

## Files

- `__init__.py` - Plugin backend: CLI adapters, terminal sessions, REST endpoints
- `cli_adapters.py` - Built-in CLI adapter registry and MCP integration metadata
- `settings_store.py` - Persistent settings for default CLI and visibility
- `js/claude-code.js` - Frontend: multi-tab xterm.js workspace, workflow sync
- `mcp_server.py` - Shared MCP server for CLI integrations
- `CLAUDE.md` - Instructions for Claude when working with ComfyUI

## Troubleshooting

### Supported CLIs

Comfy Pilot currently includes built-in adapters for:

- Claude Code
- GitHub Copilot CLI
- OpenCode CLI
- Gemini CLI
- Kilo Code CLI

Only CLIs with a usable embedded terminal are shown as live tabs by default. You can choose whether unavailable adapters should still appear in ComfyUI settings.

### Windows

Comfy Pilot now supports embedded terminals on native Windows by using the ConPTY/winpty backend provided by `pywinpty`. The Windows package dependency is declared in this project; if you manage the environment manually and terminals are still unavailable, install `pywinpty` into the same Python environment that runs ComfyUI and restart ComfyUI.

If a CLI should be detected but is reported missing, make sure its launch script directory is on PATH for the ComfyUI process, then restart ComfyUI. Common Windows locations include `%APPDATA%\npm`, `C:\nvm4w\nodejs`, and your virtualenv's `Scripts` folder.

### "Command 'claude' not found"

Install Claude Code CLI:

**macOS / Linux / WSL:**
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://claude.ai/install.ps1 | iex
```

**Windows (CMD):**
```cmd
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

### MCP server not connecting

The plugin uses provider-neutral `/comfy-pilot/*` endpoints and can auto-configure MCP for Claude Code on startup. Other CLIs may require manual MCP/tool configuration depending on their capabilities. For Claude Code, you can still manually add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "python3",
      "args": ["/path/to/comfy-pilot/mcp_server.py"]
    }
  }
}
```

### Terminal disconnected

Click the ↻ button to reconnect, or check ComfyUI console for errors.

## License

MIT
