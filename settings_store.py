"""Persistent settings for Comfy Pilot."""

from __future__ import annotations

import json
import os

try:
    from .cli_adapters import ADAPTERS, ADAPTER_ORDER, DEFAULT_ADAPTER_ID, resolve_default_adapter_id
except ImportError:  # pragma: no cover - direct file import in tests
    from cli_adapters import ADAPTERS, ADAPTER_ORDER, DEFAULT_ADAPTER_ID, resolve_default_adapter_id


DEFAULT_SETTINGS = {
    "default_cli": DEFAULT_ADAPTER_ID,
    "enabled_clis": list(ADAPTER_ORDER),
    "show_unavailable": False,
    "window_closed": False,
    "command_overrides": {},
}


def sanitize_settings(data: dict | None) -> dict:
    raw = data or {}
    enabled_clis = raw.get("enabled_clis", DEFAULT_SETTINGS["enabled_clis"])
    if not isinstance(enabled_clis, list):
        enabled_clis = list(DEFAULT_SETTINGS["enabled_clis"])
    enabled_clis = [adapter_id for adapter_id in enabled_clis if adapter_id in ADAPTERS]
    if not enabled_clis:
        enabled_clis = list(DEFAULT_SETTINGS["enabled_clis"])

    default_cli = resolve_default_adapter_id(raw.get("default_cli"))
    if default_cli not in enabled_clis:
        enabled_clis.insert(0, default_cli)

    command_overrides = raw.get("command_overrides", {})
    if not isinstance(command_overrides, dict):
        command_overrides = {}
    command_overrides = {
        adapter_id: str(command).strip()
        for adapter_id, command in command_overrides.items()
        if adapter_id in ADAPTERS and str(command).strip()
    }

    return {
        "default_cli": default_cli,
        "enabled_clis": enabled_clis,
        "show_unavailable": bool(raw.get("show_unavailable", DEFAULT_SETTINGS["show_unavailable"])),
        "window_closed": bool(raw.get("window_closed", DEFAULT_SETTINGS["window_closed"])),
        "command_overrides": command_overrides,
    }


class SettingsStore:
    def __init__(self, path: str):
        self.path = path
        self._cache = None

    def load(self, force: bool = False) -> dict:
        if self._cache is not None and not force:
            return dict(self._cache)

        data = None
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError):
                data = None

        self._cache = sanitize_settings(data)
        return dict(self._cache)

    def save(self, data: dict) -> dict:
        sanitized = sanitize_settings(data)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(sanitized, file, indent=2, sort_keys=True)
        self._cache = sanitized
        return dict(sanitized)

    def update(self, updates: dict) -> dict:
        current = self.load()
        current.update(updates or {})
        return self.save(current)
