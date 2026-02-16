import types
import sys

# Prevent pytest from importing the root __init__.py (ComfyUI plugin entry point)
# which requires aiohttp and other ComfyUI-specific dependencies.
sys.modules["__init__"] = types.ModuleType("__init__")

collect_ignore = ["__init__.py"]
