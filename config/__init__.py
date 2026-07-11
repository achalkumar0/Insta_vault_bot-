# config/__init__.py
# Re-export everything from the root config module (config.py)
# This allows both `import config` and `from config.packages import PACKAGES` to work.

import importlib.util
import os

# Import the root config.py as a private module
_spec = importlib.util.spec_from_file_location(
    "_config_root",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.py"),
)
_root_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root_mod)

# Copy all public attributes into this package namespace
for _attr in dir(_root_mod):
    if not _attr.startswith("_"):
        globals()[_attr] = getattr(_root_mod, _attr)
