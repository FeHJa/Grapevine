"""Lets tests import custom_components.ha_mqtt_bridge.<module> directly.

discovery.py is deliberately framework-free (no homeassistant import), but
it lives inside a package whose __init__.py *is* the real HA integration
entrypoint and does import homeassistant/voluptuous. A plain `import
custom_components.ha_mqtt_bridge.discovery` would execute that __init__.py
first and fail in an environment without homeassistant installed.

We register lightweight stub parent packages in sys.modules before any
test imports a submodule, so Python's import machinery resolves
`custom_components.ha_mqtt_bridge.discovery` (and its `from .const import
...` relative import) via the real files on disk without ever executing
`custom_components/ha_mqtt_bridge/__init__.py`. Modules that do need the
real HA integration entrypoint (config flow, scheduler, __init__ itself)
are out of scope for this test env and belong in an HA-core-provisioned
dev environment instead.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DIR = _REPO_ROOT / "custom_components" / "ha_mqtt_bridge"


def _stub_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_stub_package("custom_components", _REPO_ROOT / "custom_components")
_stub_package("custom_components.ha_mqtt_bridge", _PACKAGE_DIR)
