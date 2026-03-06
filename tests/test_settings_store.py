import importlib.util
import os
import sys


cli_spec = importlib.util.spec_from_file_location(
    "cli_adapters",
    os.path.join(os.path.dirname(__file__), "..", "cli_adapters.py"),
)
cli_adapters = importlib.util.module_from_spec(cli_spec)
sys.modules["cli_adapters"] = cli_adapters
cli_spec.loader.exec_module(cli_adapters)

settings_spec = importlib.util.spec_from_file_location(
    "settings_store",
    os.path.join(os.path.dirname(__file__), "..", "settings_store.py"),
)
settings_store = importlib.util.module_from_spec(settings_spec)
sys.modules["settings_store"] = settings_store
settings_spec.loader.exec_module(settings_store)


def test_sanitize_settings_filters_unknown_cli_ids():
    sanitized = settings_store.sanitize_settings(
        {
            "default_cli": "copilot",
            "enabled_clis": ["copilot", "unknown"],
            "command_overrides": {"copilot": "copilot --fast", "bad": "nope"},
        }
    )

    assert sanitized["default_cli"] == "copilot"
    assert sanitized["enabled_clis"] == ["copilot"]
    assert sanitized["command_overrides"] == {"copilot": "copilot --fast"}


def test_sanitize_settings_reinserts_default_cli_when_missing():
    sanitized = settings_store.sanitize_settings({"default_cli": "gemini", "enabled_clis": ["claude"]})
    assert sanitized["enabled_clis"][0] == "gemini"
    assert "claude" in sanitized["enabled_clis"]


def test_settings_store_persists_sanitized_payload(tmp_path):
    store = settings_store.SettingsStore(str(tmp_path / "comfy_pilot_settings.json"))
    saved = store.save(
        {
            "default_cli": "kilo",
            "enabled_clis": ["kilo"],
            "show_unavailable": True,
            "window_closed": True,
        }
    )

    assert saved["default_cli"] == "kilo"
    assert store.load()["show_unavailable"] is True
    assert store.load()["window_closed"] is True


def test_sanitize_settings_coerces_window_closed_to_bool():
    sanitized = settings_store.sanitize_settings({"window_closed": 1})

    assert sanitized["window_closed"] is True
