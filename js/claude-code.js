import { app } from "../../scripts/app.js";

const API_BASE = "/comfy-pilot";
const WS_PATH = "/ws/comfy-pilot-terminal";
const DEFAULT_CLI_SETTING_ID = "ComfyPilot.defaultCli";
const SHOW_UNAVAILABLE_SETTING_ID = "ComfyPilot.showUnavailableCliTabs";
const CLI_OPTIONS = [
    { value: "claude", label: "Claude Code" },
    { value: "copilot", label: "GitHub Copilot CLI" },
    { value: "opencode", label: "OpenCode CLI" },
    { value: "gemini", label: "Gemini CLI" },
    { value: "kilo", label: "Kilo Code CLI" },
];

let floatingWindow = null;
let actionbarReopenButton = null;
const workspace = {
    adapters: [],
    settings: {
        default_cli: "claude",
        enabled_clis: CLI_OPTIONS.map((option) => option.value),
        show_unavailable: false,
        window_closed: false,
    },
    activeAdapterId: null,
    terminalStates: new Map(),
    windowSessionId: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
};

app.registerExtension({
    name: "comfy.comfy-pilot",
    settings: [
        {
            id: DEFAULT_CLI_SETTING_ID,
            name: "Default CLI",
            type: "combo",
            defaultValue: "claude",
            options: CLI_OPTIONS.map((option) => ({ value: option.value, text: option.label })),
            attrs: {
                options: CLI_OPTIONS.map((option) => ({ value: option.value, text: option.label })),
            },
            onChange: (value) => {
                void handleDefaultCliSettingChange(value);
            },
        },
        {
            id: SHOW_UNAVAILABLE_SETTING_ID,
            name: "Show unavailable CLI tabs",
            type: "boolean",
            defaultValue: false,
            onChange: (value) => {
                void handleShowUnavailableSettingChange(value);
            },
        },
    ],

    async setup() {
        console.log("Comfy Pilot extension loading...");

        await loadXtermDependencies();
        await initializeWorkspaceConfig();

        floatingWindow = createFloatingWindow();
        document.body.appendChild(floatingWindow);

        makeDraggable(floatingWindow, floatingWindow.querySelector(".pilot-header"));
        makeResizable(floatingWindow);
        addMenuButton(floatingWindow);
        addActionbarReopenButton();
        addContextMenuOption();
        renderWorkspace();
        applySavedWindowVisibility();
        startWorkflowSync();

        console.log("Comfy Pilot extension loaded");
    },
});

async function handleDefaultCliSettingChange(value) {
    if (!value || workspace.settings.default_cli === value) {
        return;
    }
    await syncBackendSettings({ default_cli: value });
    await refreshCliInventory();
    if (floatingWindow) {
        renderWorkspace();
    }
}

async function handleShowUnavailableSettingChange(value) {
    const boolValue = Boolean(value);
    if (workspace.settings.show_unavailable === boolValue) {
        return;
    }
    await syncBackendSettings({ show_unavailable: boolValue });
    await refreshCliInventory();
    if (floatingWindow) {
        renderWorkspace();
    }
}

function getSettingsApi() {
    return app.extensionManager?.setting;
}

function getExtensionSetting(id, fallbackValue) {
    const settingsApi = getSettingsApi();
    if (!settingsApi?.get) {
        return fallbackValue;
    }
    const value = settingsApi.get(id);
    return value === undefined || value === null ? fallbackValue : value;
}

async function loadXtermDependencies() {
    const xtermCss = document.createElement("link");
    xtermCss.rel = "stylesheet";
    xtermCss.href = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css";
    document.head.appendChild(xtermCss);

    await loadScript("https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js");
    await loadScript("https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js");
    await loadScript("https://cdn.jsdelivr.net/npm/xterm-addon-canvas@0.5.0/lib/xterm-addon-canvas.min.js");
    await loadScript("https://cdn.jsdelivr.net/npm/xterm-addon-unicode11@0.6.0/lib/xterm-addon-unicode11.min.js");
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
}

function shouldShowFloatingWindow() {
    return !workspace.settings.window_closed;
}

function updateWindowVisibility(visible, { persist = true, focusTerminal = true } = {}) {
    workspace.settings.window_closed = !visible;

    if (floatingWindow) {
        floatingWindow.style.display = visible ? "flex" : "none";
    }

    updateActionbarButtonVisibility();

    if (visible && focusTerminal) {
        setTimeout(() => {
            fitAllTerminals();
            const activeState = workspace.terminalStates.get(workspace.activeAdapterId);
            activeState?.terminal?.focus();
        }, 100);
    }

    if (persist) {
        void persistWindowClosedState();
    }
}

function openFloatingWindow({ persist = true, focusTerminal = true } = {}) {
    updateWindowVisibility(true, { persist, focusTerminal });
}

function closeFloatingWindow({ persist = true } = {}) {
    updateWindowVisibility(false, { persist, focusTerminal: false });
}

function applySavedWindowVisibility() {
    updateWindowVisibility(shouldShowFloatingWindow(), { persist: false, focusTerminal: false });
}

async function persistWindowClosedState() {
    try {
        await syncBackendSettings({ window_closed: workspace.settings.window_closed });
    } catch (error) {
        console.warn("Failed to persist Comfy Pilot window state:", error);
    }
}

async function syncBackendSettings(patch) {
    const data = await fetchJson(`${API_BASE}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
    });
    workspace.settings = {
        ...workspace.settings,
        ...data,
    };
    return data;
}

async function refreshCliInventory() {
    try {
        const inventory = await fetchJson(`${API_BASE}/clis`);
        workspace.settings = {
            ...workspace.settings,
            default_cli: inventory.default_cli ?? workspace.settings.default_cli,
            enabled_clis: inventory.enabled_clis ?? workspace.settings.enabled_clis,
            show_unavailable: inventory.show_unavailable ?? workspace.settings.show_unavailable,
            window_closed: inventory.window_closed ?? workspace.settings.window_closed,
        };
        workspace.adapters = inventory.adapters || [];
        return inventory;
    } catch (error) {
        console.warn("Failed to fetch CLI inventory:", error);
        return null;
    }
}

async function initializeWorkspaceConfig() {
    workspace.settings.default_cli = getExtensionSetting(DEFAULT_CLI_SETTING_ID, workspace.settings.default_cli);
    workspace.settings.show_unavailable = Boolean(
        getExtensionSetting(SHOW_UNAVAILABLE_SETTING_ID, workspace.settings.show_unavailable),
    );

    try {
        await syncBackendSettings({
            default_cli: workspace.settings.default_cli,
            show_unavailable: workspace.settings.show_unavailable,
        });
    } catch (error) {
        console.warn("Failed to persist Comfy Pilot settings:", error);
    }

    await refreshCliInventory();
}

function createFloatingWindow() {
    ensureStyles();

    const container = document.createElement("div");
    container.id = "comfy-pilot-window";

    container.innerHTML = `
        <div class="pilot-resize-edge pilot-resize-n"></div>
        <div class="pilot-resize-edge pilot-resize-s"></div>
        <div class="pilot-resize-edge pilot-resize-e"></div>
        <div class="pilot-resize-edge pilot-resize-w"></div>
        <div class="pilot-resize-corner pilot-resize-nw"></div>
        <div class="pilot-resize-corner pilot-resize-ne"></div>
        <div class="pilot-resize-corner pilot-resize-sw"></div>
        <div class="pilot-resize-corner pilot-resize-se"></div>
        <div class="pilot-header">
            <div class="pilot-title-area">
                <span class="pilot-title">Comfy Pilot</span>
                <span class="pilot-active-cli">Loading...</span>
                <div class="pilot-mcp-status" title="MCP status">
                    <span class="mcp-indicator"></span>
                    <span class="mcp-label">MCP</span>
                </div>
            </div>
            <div class="pilot-controls">
                <button class="pilot-btn pilot-reload" title="Reload active terminal">↻</button>
                <button class="pilot-btn pilot-minimize" title="Minimize">−</button>
                <button class="pilot-btn pilot-close" title="Close">×</button>
            </div>
        </div>
        <div class="pilot-content">
            <div class="pilot-tabs"></div>
            <div class="pilot-panes"></div>
        </div>
    `;

    setTimeout(() => {
        container.querySelector(".pilot-close").addEventListener("click", () => {
            closeFloatingWindow();
        });

        container.querySelector(".pilot-reload").addEventListener("click", () => {
            reloadActiveTerminal();
        });

        const minimizeBtn = container.querySelector(".pilot-minimize");
        let savedWidth = null;
        let savedRight = null;
        minimizeBtn.addEventListener("click", () => {
            const isMinimized = container.classList.toggle("minimized");
            minimizeBtn.textContent = isMinimized ? "+" : "−";
            minimizeBtn.title = isMinimized ? "Expand" : "Minimize";

            if (isMinimized) {
                savedWidth = container.offsetWidth;
                const rect = container.getBoundingClientRect();
                savedRight = window.innerWidth - rect.right;
                container.style.left = "auto";
                container.style.right = `${savedRight}px`;
                container.classList.add("collapsed-width");
            } else {
                container.classList.remove("collapsed-width");
                if (savedWidth) {
                    container.style.width = `${savedWidth}px`;
                }
                setTimeout(() => {
                    fitAllTerminals();
                }, 50);
            }
        });

        container.querySelector(".pilot-mcp-status").addEventListener("click", () => {
            void checkMcpStatus();
        });
    }, 0);

    return container;
}

function ensureStyles() {
    if (document.getElementById("comfy-pilot-styles")) {
        return;
    }

    const style = document.createElement("style");
    style.id = "comfy-pilot-styles";
    style.textContent = `
        #comfy-pilot-window {
            position: fixed;
            top: 100px;
            right: 20px;
            width: 980px;
            height: 620px;
            background-color: #0d0d0d;
            border: 1px solid #333;
            border-radius: 8px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
            z-index: 10000;
            color: #e0e0e0;
            will-change: transform, left, top;
            contain: layout style;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 13px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .pilot-header {
            cursor: move;
            background: #1a1a1a;
            padding: 8px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #333;
            user-select: none;
            flex-shrink: 0;
        }

        .pilot-title-area {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .pilot-title {
            font-weight: 600;
            font-size: 13px;
            color: #d1d5db;
        }

        .pilot-active-cli {
            font-size: 12px;
            color: #93c5fd;
        }

        .pilot-mcp-status {
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 3px 8px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.05);
            cursor: pointer;
            transition: background 0.15s;
        }

        .pilot-mcp-status:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .mcp-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #666;
            transition: background 0.3s;
        }

        .mcp-indicator.connected {
            background: #4ade80;
            box-shadow: 0 0 6px rgba(74, 222, 128, 0.5);
        }

        .mcp-indicator.disconnected {
            background: #f87171;
        }

        .mcp-indicator.checking {
            background: #fbbf24;
            animation: pilot-pulse 1s infinite;
        }

        @keyframes pilot-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .mcp-label {
            font-size: 11px;
            color: #888;
            font-weight: 500;
        }

        .pilot-controls {
            display: flex;
            gap: 4px;
        }

        .pilot-btn {
            background: transparent;
            border: none;
            color: #666;
            width: 24px;
            height: 24px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            line-height: 1;
            transition: all 0.15s;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .pilot-btn:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .pilot-close:hover {
            background: #e74c3c;
            color: #fff;
        }

        .pilot-reload:hover {
            background: #27ae60;
            color: #fff;
        }

        .pilot-minimize:hover {
            background: #f39c12;
            color: #fff;
        }

        #comfy-pilot-window.minimized {
            height: auto !important;
            min-height: 0 !important;
        }

        #comfy-pilot-window.minimized.collapsed-width {
            width: auto !important;
            min-width: 0 !important;
        }

        #comfy-pilot-window.minimized .pilot-content {
            display: none;
        }

        #comfy-pilot-window.minimized .pilot-resize-edge,
        #comfy-pilot-window.minimized .pilot-resize-corner {
            display: none;
        }

        #comfy-pilot-window.minimized .pilot-header {
            padding: 8px 10px;
        }

        #comfy-pilot-window.minimized .mcp-label,
        #comfy-pilot-window.minimized .pilot-active-cli {
            display: none;
        }

        .pilot-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
        }

        .pilot-tabs {
            display: flex;
            gap: 6px;
            padding: 10px 10px 0;
            border-bottom: 1px solid #222;
            background: #101010;
            flex-shrink: 0;
        }

        .pilot-tab {
            border: 1px solid #2c2c2c;
            background: #161616;
            color: #a3a3a3;
            border-radius: 8px 8px 0 0;
            padding: 8px 12px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
            max-width: 240px;
        }

        .pilot-tab.active {
            background: #1f2937;
            color: #fff;
            border-color: #3b82f6;
        }

        .pilot-tab.unavailable {
            opacity: 0.6;
        }

        .pilot-tab-status {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #666;
            flex-shrink: 0;
        }

        .pilot-tab-status.connected {
            background: #4ade80;
        }

        .pilot-tab-status.connecting {
            background: #fbbf24;
        }

        .pilot-tab-status.disconnected {
            background: #f87171;
        }

        .pilot-tab-status.unavailable {
            background: #666;
        }

        .pilot-tab-label {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .pilot-panes {
            position: relative;
            flex: 1;
            overflow: hidden;
        }

        .pilot-pane {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            visibility: hidden;
            pointer-events: none;
        }

        .pilot-pane.active {
            visibility: visible;
            pointer-events: auto;
        }

        .pilot-terminal-host {
            flex: 1;
            padding: 4px;
            overflow: hidden;
        }

        .pilot-terminal-host .xterm {
            height: 100%;
        }

        .pilot-terminal-host .xterm-viewport {
            overflow-y: auto !important;
        }

        .pilot-empty-state {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #9ca3af;
            padding: 24px;
            text-align: center;
            background: #0f0f0f;
        }

        .pilot-unavailable-card {
            margin: 16px;
            padding: 16px;
            border: 1px solid #2c2c2c;
            border-radius: 8px;
            background: #111827;
            color: #d1d5db;
            max-width: 560px;
        }

        .pilot-unavailable-card h3 {
            margin: 0 0 8px;
            font-size: 15px;
        }

        .pilot-unavailable-card p {
            margin: 0;
            color: #9ca3af;
        }

        .pilot-resize-edge {
            position: absolute;
            z-index: 10;
        }

        .pilot-resize-n {
            top: 0;
            left: 8px;
            right: 8px;
            height: 6px;
            cursor: ns-resize;
        }

        .pilot-resize-s {
            bottom: 0;
            left: 8px;
            right: 8px;
            height: 6px;
            cursor: ns-resize;
        }

        .pilot-resize-e {
            right: 0;
            top: 8px;
            bottom: 8px;
            width: 6px;
            cursor: ew-resize;
        }

        .pilot-resize-w {
            left: 0;
            top: 8px;
            bottom: 8px;
            width: 6px;
            cursor: ew-resize;
        }

        .pilot-resize-corner {
            position: absolute;
            width: 12px;
            height: 12px;
            z-index: 11;
        }

        .pilot-resize-nw {
            top: 0;
            left: 0;
            cursor: nwse-resize;
        }

        .pilot-resize-ne {
            top: 0;
            right: 0;
            cursor: nesw-resize;
        }

        .pilot-resize-sw {
            bottom: 0;
            left: 0;
            cursor: nesw-resize;
        }

        .pilot-resize-se {
            bottom: 0;
            right: 0;
            cursor: nwse-resize;
        }

        #comfy-pilot-menu-btn {
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            border: none;
            color: white;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            margin-left: 8px;
        }

        #comfy-pilot-menu-btn:hover {
            background: linear-gradient(135deg, #7c7ff2 0%, #6366f1 100%);
        }

        .comfy-pilot-actionbar-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.92);
            color: #e5e7eb;
            cursor: pointer;
            transition: background 0.15s, border-color 0.15s, transform 0.15s;
        }

        .comfy-pilot-actionbar-btn:hover {
            background: rgba(30, 41, 59, 0.98);
            border-color: rgba(96, 165, 250, 0.7);
            transform: translateY(-1px);
        }

        .comfy-pilot-actionbar-btn svg {
            width: 18px;
            height: 18px;
            stroke: currentColor;
            fill: none;
            stroke-width: 1.7;
            stroke-linecap: round;
            stroke-linejoin: round;
        }
    `;
    document.head.appendChild(style);
}

function createActionbarReopenButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "comfy-pilot-actionbar-btn";
    button.title = "Reopen Comfy Pilot terminal";
    button.setAttribute("aria-label", "Reopen Comfy Pilot terminal");
    button.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <rect x="3" y="5" width="18" height="14" rx="2"></rect>
            <path d="M7.5 10 10.5 12 7.5 14"></path>
            <path d="M13 14h4"></path>
        </svg>
    `;
    button.addEventListener("click", () => {
        openFloatingWindow();
    });
    return button;
}

function ensureActionbarReopenButton() {
    const container = document.querySelector(".actionbar-container");
    if (!container) {
        return null;
    }

    if (!actionbarReopenButton) {
        actionbarReopenButton = createActionbarReopenButton();
    }

    if (actionbarReopenButton.parentElement !== container) {
        container.appendChild(actionbarReopenButton);
    }

    return actionbarReopenButton;
}

function updateActionbarButtonVisibility() {
    const button = ensureActionbarReopenButton();
    if (!button) {
        return;
    }
    button.style.display = workspace.settings.window_closed ? "inline-flex" : "none";
}

function addActionbarReopenButton() {
    if (ensureActionbarReopenButton()) {
        updateActionbarButtonVisibility();
        return;
    }

    const checkActionbar = setInterval(() => {
        if (ensureActionbarReopenButton()) {
            updateActionbarButtonVisibility();
            clearInterval(checkActionbar);
        }
    }, 500);

    setTimeout(() => clearInterval(checkActionbar), 10000);
}

function getVisibleAdapters() {
    return workspace.adapters.filter((adapter) => {
        if (!workspace.settings.enabled_clis.includes(adapter.id)) {
            return false;
        }
        return isTerminalUsable(adapter) || workspace.settings.show_unavailable;
    });
}

function isTerminalUsable(adapter) {
    if (typeof adapter.terminal_usable === "boolean") {
        return adapter.terminal_usable;
    }
    return Boolean(adapter.available && adapter.terminal_supported !== false);
}

function getAdapterUnavailableHeading(adapter) {
    if (!adapter.available) {
        return `${adapter.label} is not installed`;
    }
    if (adapter.terminal_supported === false) {
        return `${adapter.label} terminal is unavailable on this platform`;
    }
    return `${adapter.label} is unavailable`;
}

function getAdapterUnavailableReason(adapter) {
    if (adapter.unavailable_reason) {
        return adapter.unavailable_reason;
    }
    if (!adapter.available) {
        return adapter.install_hint || `Install ${adapter.label} to use it in Comfy Pilot.`;
    }
    if (adapter.terminal_supported === false) {
        return (
            `${adapter.label} is installed, but embedded terminals are not supported on this platform. ` +
            "Use the CLI directly and keep Comfy Pilot's REST/MCP integration."
        );
    }
    return `${adapter.label} is unavailable.`;
}

function resolveActiveAdapterId(visibleAdapters) {
    if (!visibleAdapters.length) {
        return null;
    }

    const preferred = workspace.settings.default_cli;
    if (visibleAdapters.some((adapter) => adapter.id === preferred)) {
        return preferred;
    }

    const available = visibleAdapters.find((adapter) => isTerminalUsable(adapter));
    return available ? available.id : visibleAdapters[0].id;
}

function renderWorkspace() {
    if (!floatingWindow) {
        return;
    }

    const tabsContainer = floatingWindow.querySelector(".pilot-tabs");
    const panesContainer = floatingWindow.querySelector(".pilot-panes");
    tabsContainer.innerHTML = "";
    panesContainer.innerHTML = "";

    const visibleAdapters = getVisibleAdapters();
    if (!visibleAdapters.length) {
        panesContainer.innerHTML = `
            <div class="pilot-empty-state">
                No usable CLI terminal tabs are available. Install a supported CLI, use a terminal-supported
                platform for embedded terminals, or enable unavailable tabs in settings.
            </div>
        `;
        workspace.activeAdapterId = null;
        updateActiveCliLabel();
        void checkMcpStatus();
        return;
    }

    visibleAdapters.forEach((adapter) => {
        const state = ensureTerminalState(adapter);
        state.adapter = adapter;
        const terminalUsable = isTerminalUsable(adapter);
        const unavailableReason = getAdapterUnavailableReason(adapter);
        const unavailableHeading = getAdapterUnavailableHeading(adapter);

        const tab = document.createElement("button");
        tab.className = `pilot-tab${terminalUsable ? "" : " unavailable"}`;
        tab.dataset.adapterId = adapter.id;
        tab.innerHTML = `
            <span class="pilot-tab-status ${terminalUsable ? state.status || "connecting" : "unavailable"}"></span>
            <span class="pilot-tab-label">${adapter.label}</span>
        `;
        tab.title = terminalUsable ? adapter.label : unavailableReason;
        tab.addEventListener("click", () => {
            selectAdapterTab(adapter.id);
        });
        tabsContainer.appendChild(tab);
        state.tabButton = tab;

        const pane = document.createElement("div");
        pane.className = "pilot-pane";
        pane.dataset.adapterId = adapter.id;
        panesContainer.appendChild(pane);
        state.pane = pane;

        if (terminalUsable) {
            pane.appendChild(state.host);
            if (!state.initialized) {
                initTerminalState(state);
            } else {
                requestAnimationFrame(() => fitTerminalState(state));
            }
        } else {
            pane.innerHTML = `
                <div class="pilot-empty-state">
                    <div class="pilot-unavailable-card">
                        <h3>${unavailableHeading}</h3>
                        <p>${unavailableReason}</p>
                    </div>
                </div>
            `;
            state.status = "unavailable";
            state.statusMessage = unavailableReason;
        }

        updateTabStatus(state);
    });

    workspace.activeAdapterId = resolveActiveAdapterId(visibleAdapters);
    selectAdapterTab(workspace.activeAdapterId);
}

function ensureTerminalState(adapter) {
    let state = workspace.terminalStates.get(adapter.id);
    if (!state) {
        const host = document.createElement("div");
        host.className = "pilot-terminal-host";
        state = {
            adapter,
            host,
            pane: null,
            tabButton: null,
            terminal: null,
            fitAddon: null,
            websocket: null,
            initialized: false,
            status: isTerminalUsable(adapter) ? "connecting" : "unavailable",
            statusMessage: "",
            capabilityError: false,
        };
        workspace.terminalStates.set(adapter.id, state);
    }
    return state;
}

function updateActiveCliLabel() {
    if (!floatingWindow) {
        return;
    }
    const label = floatingWindow.querySelector(".pilot-active-cli");
    if (!label) {
        return;
    }
    const activeState = workspace.terminalStates.get(workspace.activeAdapterId);
    label.textContent = activeState?.adapter?.label || "No active CLI";
}

function updateTabStatus(state) {
    if (!state.tabButton) {
        return;
    }
    const dot = state.tabButton.querySelector(".pilot-tab-status");
    if (dot) {
        dot.className = `pilot-tab-status ${state.status || "disconnected"}`;
    }
    if (state.statusMessage) {
        state.tabButton.title = `${state.adapter.label}: ${state.statusMessage}`;
    }
}

function setStateStatus(state, status, message = "") {
    state.status = status;
    state.statusMessage = message;
    updateTabStatus(state);
}

function selectAdapterTab(adapterId) {
    workspace.activeAdapterId = adapterId;
    updateActiveCliLabel();

    for (const state of workspace.terminalStates.values()) {
        if (state.tabButton) {
            state.tabButton.classList.toggle("active", state.adapter.id === adapterId);
        }
        if (state.pane) {
            state.pane.classList.toggle("active", state.adapter.id === adapterId);
        }
    }

    const activeState = workspace.terminalStates.get(adapterId);
    if (activeState?.terminal) {
        setTimeout(() => {
            fitTerminalState(activeState);
            activeState.terminal.focus();
        }, 50);
    }
    void checkMcpStatus();
}

function createTerminalOptions() {
    return {
        cursorBlink: true,
        cursorStyle: "block",
        fontSize: 13,
        fontFamily: '"SF Mono", "Monaco", "Inconsolata", "Fira Code", "Consolas", "Courier New", monospace',
        theme: {
            background: "#0d0d0d",
            foreground: "#e0e0e0",
            cursor: "#4ade80",
            cursorAccent: "#0d0d0d",
            selectionBackground: "rgba(255, 255, 255, 0.2)",
            black: "#000000",
            red: "#f87171",
            green: "#4ade80",
            yellow: "#fbbf24",
            blue: "#60a5fa",
            magenta: "#c084fc",
            cyan: "#22d3ee",
            white: "#e0e0e0",
            brightBlack: "#666666",
            brightRed: "#fca5a5",
            brightGreen: "#86efac",
            brightYellow: "#fcd34d",
            brightBlue: "#93c5fd",
            brightMagenta: "#d8b4fe",
            brightCyan: "#67e8f9",
            brightWhite: "#ffffff",
        },
        allowProposedApi: true,
        scrollback: 1000,
        smoothScrollDuration: 0,
        fastScrollModifier: "none",
        scrollOnUserInput: true,
    };
}

function initTerminalState(state) {
    const terminal = new Terminal(createTerminalOptions());
    const fitAddon = new FitAddon.FitAddon();
    terminal.loadAddon(fitAddon);

    try {
        const unicode11Addon = new Unicode11Addon.Unicode11Addon();
        terminal.loadAddon(unicode11Addon);
        terminal.unicode.activeVersion = "11";
    } catch (error) {
        console.log("Unicode11 addon not available:", error.message);
    }

    try {
        terminal.loadAddon(new CanvasAddon.CanvasAddon());
    } catch (error) {
        console.log("Canvas addon not available, using DOM renderer:", error.message);
    }

    terminal.open(state.host);
    state.terminal = terminal;
    state.fitAddon = fitAddon;
    state.initialized = true;

    terminal.onData((data) => {
        if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
            state.websocket.send(JSON.stringify({ type: "i", d: data }));
        }
    });

    terminal.attachCustomKeyEventHandler((event) => {
        if (event.type !== "keydown") return true;

        const isMac = navigator.platform.toUpperCase().includes("MAC");
        const modKey = isMac ? event.metaKey : event.ctrlKey;
        const altKey = event.altKey;

        const send = (data) => {
            if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
                state.websocket.send(JSON.stringify({ type: "i", d: data }));
            }
        };

        if (event.key === "Enter" && event.shiftKey) {
            send("\x1b\r");
            return false;
        }
        if (altKey && event.key === "ArrowLeft") {
            send("\x1bb");
            return false;
        }
        if (altKey && event.key === "ArrowRight") {
            send("\x1bf");
            return false;
        }
        if (modKey && event.key === "ArrowLeft") {
            send("\x01");
            return false;
        }
        if (modKey && event.key === "ArrowRight") {
            send("\x05");
            return false;
        }
        if (altKey && event.key === "Backspace") {
            send("\x17");
            return false;
        }
        if (modKey && event.key === "Backspace") {
            send("\x15");
            return false;
        }
        if (altKey && event.key === "Delete") {
            send("\x1bd");
            return false;
        }
        if (modKey && event.key === "Delete") {
            send("\x0b");
            return false;
        }

        return true;
    });

    terminal.onResize(({ rows, cols }) => {
        if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
            state.websocket.send(JSON.stringify({ type: "resize", rows, cols }));
        }
    });

    setTimeout(() => {
        const viewport = state.host.querySelector(".xterm-viewport");
        const textarea = terminal.textarea;
        if (viewport && textarea) {
            let savedScrollTop = null;
            textarea.addEventListener("blur", () => {
                savedScrollTop = viewport.scrollTop;
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        if (savedScrollTop !== null && viewport.scrollTop !== savedScrollTop) {
                            viewport.scrollTop = savedScrollTop;
                        }
                    });
                });
            });
        }
    }, 200);

    setTimeout(() => fitTerminalState(state), 100);
    connectWebSocket(state);
}

function fitTerminalState(state) {
    if (!state?.terminal || !state?.fitAddon) {
        return;
    }

    const buffer = state.terminal.buffer.active;
    const viewport = state.host.querySelector(".xterm-viewport");
    const isAtBottom = buffer.viewportY >= buffer.baseY;
    const scrollTop = viewport ? viewport.scrollTop : 0;

    state.fitAddon.fit();

    if (!isAtBottom && viewport) {
        viewport.scrollTop = scrollTop;
    }
}

function fitAllTerminals() {
    for (const state of workspace.terminalStates.values()) {
        if (state.initialized) {
            fitTerminalState(state);
        }
    }
}

function buildWebSocketUrl(adapterId) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const query = new URLSearchParams({
        adapter: adapterId,
        session: workspace.windowSessionId,
    });
    return `${protocol}//${window.location.host}${WS_PATH}?${query.toString()}`;
}

function sendTerminalSize(state) {
    const dims = state.fitAddon?.proposeDimensions();
    if (!dims || !state.websocket || state.websocket.readyState !== WebSocket.OPEN) {
        return;
    }
    state.websocket.send(JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols }));
}

function connectWebSocket(state) {
    if (state.websocket) {
        state.websocket.close();
    }

    state.capabilityError = false;
    setStateStatus(state, "connecting", "Connecting...");
    const wsUrl = buildWebSocketUrl(state.adapter.id);
    const websocket = new WebSocket(wsUrl);
    state.websocket = websocket;

    websocket.onopen = () => {
        state.capabilityError = false;
        setStateStatus(state, "connected", "Connected");
        state.terminal.clear();
        fitTerminalState(state);
        sendTerminalSize(state);
        setTimeout(() => sendTerminalSize(state), 300);
        setTimeout(() => sendTerminalSize(state), 800);
        setTimeout(() => sendTerminalSize(state), 1500);
        if (workspace.activeAdapterId === state.adapter.id) {
            state.terminal.focus();
        }
    };

    websocket.onmessage = (event) => {
        const data = event.data;
        if (data[0] === "o") {
            const filteredData = data.slice(1).replace(/\x1b\[\[?[IO]/g, "");
            if (filteredData) {
                state.terminal.write(filteredData);
            }
            return;
        }

        try {
            const message = JSON.parse(data);
            if (message.type === "output" && message.data) {
                const filteredData = message.data.replace(/\x1b\[\[?[IO]/g, "");
                if (filteredData) {
                    state.terminal.write(filteredData);
                }
            } else if (message.type === "error" && message.message) {
                state.capabilityError = true;
                setStateStatus(state, "unavailable", message.message);
                state.terminal.writeln(`\x1b[1;31m${message.message}\x1b[0m`);
            }
        } catch (error) {
            console.debug("Ignoring non-JSON websocket message", error);
        }
    };

    websocket.onclose = () => {
        state.websocket = null;
        if (state.capabilityError) {
            return;
        }
        setStateStatus(state, "disconnected", "Disconnected");
        state.terminal.writeln("\n\x1b[1;31mTerminal disconnected.\x1b[0m");
        state.terminal.writeln("Click ↻ to reconnect.\n");
    };

    websocket.onerror = () => {
        setStateStatus(state, "disconnected", "Connection error");
    };
}

function reloadActiveTerminal() {
    const state = workspace.terminalStates.get(workspace.activeAdapterId);
    if (!state) {
        return;
    }
    if (!isTerminalUsable(state.adapter)) {
        setStateStatus(state, "unavailable", getAdapterUnavailableReason(state.adapter));
        return;
    }
    if (!state.terminal) {
        return;
    }
    state.terminal.clear();
    state.terminal.writeln("\x1b[1;34mReloading terminal...\x1b[0m\n");
    connectWebSocket(state);
}

function makeDraggable(element, handle) {
    let pos1 = 0;
    let pos2 = 0;
    let pos3 = 0;
    let pos4 = 0;

    handle.onmousedown = dragMouseDown;

    function dragMouseDown(event) {
        if (event.target.closest(".pilot-btn") || event.target.closest(".pilot-tab")) return;

        event.preventDefault();
        pos3 = event.clientX;
        pos4 = event.clientY;
        document.onmouseup = closeDragElement;
        document.onmousemove = elementDrag;
    }

    function elementDrag(event) {
        event.preventDefault();
        pos1 = pos3 - event.clientX;
        pos2 = pos4 - event.clientY;
        pos3 = event.clientX;
        pos4 = event.clientY;

        const newTop = element.offsetTop - pos2;
        const newLeft = element.offsetLeft - pos1;
        const maxTop = window.innerHeight - element.offsetHeight;
        const maxLeft = window.innerWidth - element.offsetWidth;

        element.style.top = `${Math.max(0, Math.min(newTop, maxTop))}px`;
        element.style.left = `${Math.max(0, Math.min(newLeft, maxLeft))}px`;
        element.style.right = "auto";
    }

    function closeDragElement() {
        document.onmouseup = null;
        document.onmousemove = null;
    }
}

function makeResizable(element) {
    const minWidth = 520;
    const minHeight = 320;
    let resizeTimeout = null;
    const resizeElements = element.querySelectorAll(".pilot-resize-edge, .pilot-resize-corner");

    resizeElements.forEach((resizer) => {
        resizer.addEventListener("mousedown", (event) => {
            event.preventDefault();
            event.stopPropagation();

            const startX = event.clientX;
            const startY = event.clientY;
            const startWidth = element.offsetWidth;
            const startHeight = element.offsetHeight;
            const startLeft = element.offsetLeft;
            const startTop = element.offsetTop;

            const isLeft = resizer.classList.contains("pilot-resize-w")
                || resizer.classList.contains("pilot-resize-nw")
                || resizer.classList.contains("pilot-resize-sw");
            const isTop = resizer.classList.contains("pilot-resize-n")
                || resizer.classList.contains("pilot-resize-nw")
                || resizer.classList.contains("pilot-resize-ne");
            const isRight = resizer.classList.contains("pilot-resize-e")
                || resizer.classList.contains("pilot-resize-ne")
                || resizer.classList.contains("pilot-resize-se");
            const isBottom = resizer.classList.contains("pilot-resize-s")
                || resizer.classList.contains("pilot-resize-sw")
                || resizer.classList.contains("pilot-resize-se");

            function resize(moveEvent) {
                const dx = moveEvent.clientX - startX;
                const dy = moveEvent.clientY - startY;

                if (isRight) {
                    element.style.width = `${Math.max(minWidth, startWidth + dx)}px`;
                }

                if (isBottom) {
                    element.style.height = `${Math.max(minHeight, startHeight + dy)}px`;
                }

                if (isLeft) {
                    const newWidth = Math.max(minWidth, startWidth - dx);
                    if (newWidth >= minWidth) {
                        element.style.width = `${newWidth}px`;
                        element.style.left = `${startLeft + dx}px`;
                        element.style.right = "auto";
                    }
                }

                if (isTop) {
                    const newHeight = Math.max(minHeight, startHeight - dy);
                    if (newHeight >= minHeight) {
                        element.style.height = `${newHeight}px`;
                        element.style.top = `${startTop + dy}px`;
                    }
                }

                if (resizeTimeout) {
                    clearTimeout(resizeTimeout);
                }
                resizeTimeout = setTimeout(() => {
                    fitAllTerminals();
                }, 16);
            }

            function stopResize() {
                document.removeEventListener("mousemove", resize);
                document.removeEventListener("mouseup", stopResize);
                setTimeout(() => {
                    fitAllTerminals();
                }, 50);
            }

            document.addEventListener("mousemove", resize);
            document.addEventListener("mouseup", stopResize);
        });
    });
}

function addMenuButton(windowElement) {
    const checkMenu = setInterval(() => {
        const menu = document.querySelector(".comfy-menu") || document.querySelector(".comfyui-menu");
        if (!menu) {
            return;
        }

        clearInterval(checkMenu);
        const button = document.createElement("button");
        button.id = "comfy-pilot-menu-btn";
        button.textContent = "Comfy Pilot";
        button.addEventListener("click", () => {
            if (windowElement.style.display === "none") {
                openFloatingWindow();
                return;
            }
            closeFloatingWindow();
        });

        menu.appendChild(button);
    }, 500);

    setTimeout(() => clearInterval(checkMenu), 10000);
}

function addContextMenuOption() {
    const originalGetCanvasMenuOptions = LGraphCanvas.prototype.getCanvasMenuOptions;

    LGraphCanvas.prototype.getCanvasMenuOptions = function (...args) {
        const options = originalGetCanvasMenuOptions.apply(this, args);
        options.push(null);
        options.push({
            content: "Open Comfy Pilot",
            callback: () => {
                if (!floatingWindow) {
                    return;
                }
                openFloatingWindow();
            },
        });
        return options;
    };
}

window.addEventListener("resize", () => {
    if (floatingWindow && floatingWindow.style.display !== "none") {
        fitAllTerminals();
    }
});

async function checkMcpStatus() {
    if (!floatingWindow || !workspace.activeAdapterId) {
        return;
    }

    const indicator = floatingWindow.querySelector(".mcp-indicator");
    const label = floatingWindow.querySelector(".mcp-label");
    if (!indicator || !label) {
        return;
    }

    indicator.className = "mcp-indicator checking";
    label.textContent = "MCP...";

    try {
        const response = await fetchJson(`${API_BASE}/mcp-status?adapter=${encodeURIComponent(workspace.activeAdapterId)}`);
        if (response.ready) {
            indicator.className = "mcp-indicator connected";
            label.textContent = "MCP";
            indicator.parentElement.title = `${response.label} MCP ready`;
        } else {
            indicator.className = "mcp-indicator disconnected";
            label.textContent = "MCP";
            indicator.parentElement.title = `${response.label}: ${response.error || "MCP not ready"}`;
        }
    } catch (error) {
        indicator.className = "mcp-indicator disconnected";
        label.textContent = "MCP";
        indicator.parentElement.title = "MCP status unknown";
    }
}

function startWorkflowSync() {
    syncWorkflow();
    setInterval(syncWorkflow, 2000);

    pollGraphCommands();
    setInterval(pollGraphCommands, 200);
}

let lastWorkflowHash = null;

async function syncWorkflow() {
    try {
        if (!app.graph) return;

        const workflow = app.graph.serialize();
        const workflowStr = JSON.stringify(workflow);
        const hash = `${workflowStr.length}_${workflowStr.charCodeAt(100) || 0}`;
        if (hash === lastWorkflowHash) return;
        lastWorkflowHash = hash;

        await fetch(`${API_BASE}/workflow`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                workflow,
                workflow_api: null,
                timestamp: Date.now(),
            }),
        });
    } catch (error) {
        // Ignore sync errors to avoid console spam.
    }
}

async function getWorkflowApi() {
    try {
        if (!app.graph) return null;
        return await app.graphToPrompt();
    } catch (error) {
        return null;
    }
}

async function pollGraphCommands() {
    try {
        const response = await fetch(`${API_BASE}/graph-command`);
        const data = await response.json();

        if (data.command) {
            const result = await executeGraphCommand(data.command);
            await fetch(`${API_BASE}/graph-command`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    command_id: data.command.id,
                    result,
                }),
            });
        }
    } catch (error) {
        // Ignore polling errors.
    }
}

async function executeGraphCommand(command) {
    const { action, params } = command;

    try {
        if (!app.graph) {
            return { error: "Graph not available" };
        }

        switch (action) {
            case "get_workflow_api": {
                try {
                    const workflowApi = await app.graphToPrompt();
                    return { workflow_api: workflowApi };
                } catch (error) {
                    return { error: `Failed to get workflow API: ${error.message}` };
                }
            }

            case "queue_prompt": {
                try {
                    await app.queuePrompt(0, 1);
                    return { status: "queued" };
                } catch (error) {
                    return { error: `Failed to queue prompt: ${error.message}` };
                }
            }

            case "center_on_node": {
                const nodeId = parseInt(params.node_id);
                const node = app.graph.getNodeById(nodeId);
                if (!node) {
                    return { error: `Node ${params.node_id} not found` };
                }
                if (app.canvas && app.canvas.centerOnNode) {
                    app.canvas.centerOnNode(node);
                    return { status: "centered", node_id: params.node_id };
                }
                return { error: "Canvas centerOnNode not available" };
            }

            case "create_node": {
                const node = LiteGraph.createNode(params.type);
                if (!node) {
                    return { error: `Failed to create node of type: ${params.type}` };
                }

                const nodeWidth = node.size ? node.size[0] : 200;
                const nodeHeight = node.size ? node.size[1] : 100;
                const gap = 30;

                const checkCollision = (x, y, w, h) => {
                    for (const other of app.graph._nodes) {
                        if (other === node) continue;
                        const ox = other.pos[0];
                        const oy = other.pos[1];
                        const ow = other.size ? other.size[0] : 200;
                        const oh = other.size ? other.size[1] : 100;
                        if (x < ox + ow && x + w > ox && y < oy + oh && y + h > oy) {
                            return other;
                        }
                    }
                    return null;
                };

                const findFreePosition = (startX, startY) => {
                    const collider = checkCollision(startX, startY, nodeWidth, nodeHeight);
                    if (!collider) return [startX, startY];

                    const directions = [
                        [1, 0],
                        [0, 1],
                        [-1, 0],
                        [0, -1],
                    ];

                    for (let distance = 1; distance <= 10; distance++) {
                        for (const [dx, dy] of directions) {
                            const tryX = startX + dx * (nodeWidth + gap) * distance;
                            const tryY = startY + dy * (nodeHeight + gap) * distance;
                            if (!checkCollision(tryX, tryY, nodeWidth, nodeHeight)) {
                                return [tryX, tryY];
                            }
                        }
                    }

                    return [startX + nodeWidth + gap, startY];
                };

                if (params.place_in_view && app.canvas) {
                    const canvas = app.canvas;
                    const offset = canvas.ds.offset;
                    const scale = canvas.ds.scale;
                    const sidebarOffset = 130;
                    const screenCenterX = (canvas.canvas.width - sidebarOffset) / 2;
                    const screenCenterY = canvas.canvas.height / 2;
                    const centerX = (screenCenterX - offset[0]) / scale;
                    const centerY = (screenCenterY - offset[1]) / scale;
                    const targetX = centerX - nodeWidth / 2 + (params.viewport_offset || 0);
                    const targetY = centerY - nodeHeight / 2;
                    node.pos = findFreePosition(targetX, targetY);
                } else {
                    const targetX = params.pos_x || 100;
                    const targetY = params.pos_y || 100;
                    node.pos = findFreePosition(targetX, targetY);
                }

                if (params.title) {
                    node.title = params.title;
                }
                app.graph.add(node);
                app.graph.setDirtyCanvas(true, true);
                return {
                    status: "created",
                    node_id: node.id,
                    type: params.type,
                    title: node.title,
                    pos: node.pos,
                    size: node.size,
                };
            }

            case "delete_node": {
                const nodeId = parseInt(params.node_id);
                const node = app.graph.getNodeById(nodeId);
                if (!node) {
                    return { error: `Node ${params.node_id} not found` };
                }
                app.graph.remove(node);
                app.graph.setDirtyCanvas(true, true);
                return {
                    status: "deleted",
                    node_id: params.node_id,
                };
            }

            case "set_node_property": {
                const nodeId = parseInt(params.node_id);
                const node = app.graph.getNodeById(nodeId);
                if (!node) {
                    return { error: `Node ${params.node_id} not found` };
                }

                let found = false;
                if (node.widgets) {
                    for (const widget of node.widgets) {
                        if (widget.name === params.property_name) {
                            widget.value = params.value;
                            if (widget.callback) {
                                widget.callback(params.value, app.canvas, node, [0, 0], null);
                            }
                            found = true;
                            break;
                        }
                    }
                }

                if (!found) {
                    if (params.property_name in node) {
                        node[params.property_name] = params.value;
                        found = true;
                    } else if (node.properties && params.property_name in node.properties) {
                        node.properties[params.property_name] = params.value;
                        found = true;
                    }
                }

                if (!found) {
                    return { error: `Property '${params.property_name}' not found on node ${params.node_id}` };
                }

                app.graph.setDirtyCanvas(true, true);
                return {
                    status: "updated",
                    node_id: params.node_id,
                    property: params.property_name,
                    value: params.value,
                };
            }

            case "connect_nodes": {
                const fromNodeId = parseInt(params.from_node_id);
                const toNodeId = parseInt(params.to_node_id);
                const fromNode = app.graph.getNodeById(fromNodeId);
                const toNode = app.graph.getNodeById(toNodeId);

                if (!fromNode) {
                    return { error: `Source node ${params.from_node_id} not found` };
                }
                if (!toNode) {
                    return { error: `Target node ${params.to_node_id} not found` };
                }

                const link = fromNode.connect(params.from_slot, toNode, params.to_slot);
                app.graph.setDirtyCanvas(true, true);

                return {
                    status: "connected",
                    from_node: params.from_node_id,
                    from_slot: params.from_slot,
                    to_node: params.to_node_id,
                    to_slot: params.to_slot,
                    link_id: link ? link.id : null,
                };
            }

            case "disconnect_nodes": {
                const fromNodeId = parseInt(params.from_node_id);
                const toNodeId = parseInt(params.to_node_id);
                const fromNode = app.graph.getNodeById(fromNodeId);
                const toNode = app.graph.getNodeById(toNodeId);

                if (!fromNode) {
                    return { error: `Source node ${params.from_node_id} not found` };
                }
                if (!toNode) {
                    return { error: `Target node ${params.to_node_id} not found` };
                }

                if (toNode.inputs && toNode.inputs[params.to_slot]) {
                    const linkId = toNode.inputs[params.to_slot].link;
                    if (linkId !== null) {
                        app.graph.removeLink(linkId);
                    }
                }

                app.graph.setDirtyCanvas(true, true);
                return {
                    status: "disconnected",
                    from_node: params.from_node_id,
                    from_slot: params.from_slot,
                    to_node: params.to_node_id,
                    to_slot: params.to_slot,
                };
            }

            case "move_node": {
                const nodeId = parseInt(params.node_id);
                const node = app.graph.getNodeById(nodeId);

                if (!node) {
                    return { error: `Node ${params.node_id} not found` };
                }

                let newX;
                let newY;

                if (params.relative_to && params.direction) {
                    const refNodeId = parseInt(params.relative_to);
                    const refNode = app.graph.getNodeById(refNodeId);

                    if (!refNode) {
                        return { error: `Reference node ${params.relative_to} not found` };
                    }

                    const gap = params.gap || 30;
                    const refPos = refNode.pos;
                    const refSize = refNode.size || [200, 100];
                    const nodeSize = node.size || [200, 100];

                    switch (params.direction) {
                        case "right":
                            newX = refPos[0] + refSize[0] + gap;
                            newY = refPos[1];
                            break;
                        case "left":
                            newX = refPos[0] - nodeSize[0] - gap;
                            newY = refPos[1];
                            break;
                        case "below":
                            newX = refPos[0];
                            newY = refPos[1] + refSize[1] + gap;
                            break;
                        case "above":
                            newX = refPos[0];
                            newY = refPos[1] - nodeSize[1] - gap;
                            break;
                        default:
                            return { error: `Unknown direction: ${params.direction}` };
                    }
                } else if (params.x !== null && params.x !== undefined
                        && params.y !== null && params.y !== undefined) {
                    newX = params.x;
                    newY = params.y;
                } else if (params.width || params.height) {
                    newX = node.pos[0];
                    newY = node.pos[1];
                } else {
                    return { error: "Must provide (x, y), (relative_to, direction), or (width, height)" };
                }

                node.pos = [newX, newY];

                if (params.width || params.height) {
                    const currentSize = node.size || [200, 100];
                    node.size = [
                        params.width || currentSize[0],
                        params.height || currentSize[1],
                    ];
                }

                app.graph.setDirtyCanvas(true, true);

                return {
                    status: "moved",
                    node_id: params.node_id,
                    pos: node.pos,
                    size: node.size,
                };
            }

            default:
                return { error: `Unknown action: ${action}` };
        }
    } catch (error) {
        return { error: error.message || String(error) };
    }
}
