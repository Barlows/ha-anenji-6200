"""Small shared primitives for the stub-based Home Assistant unit tests."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


def ensure_module(name: str) -> types.ModuleType:
    """Return a module for ``name``, importing the real one when it exists.

    Previously this only looked in ``sys.modules``, so the first test to ask
    for a not-yet-imported name installed an empty synthetic module that then
    shadowed the real one for the entire process. A test double would patch a
    few attributes onto a blank object, and every later test importing that
    module got ``ImportError: cannot import name ... (unknown location)``.

    Test doubles should overlay the real module, not replace it, so try the
    real import first and only synthesise when there is genuinely nothing to
    import (the ``homeassistant.*`` stubs, which do not exist in this repo).
    """

    module = sys.modules.get(name)
    if module is not None:
        return module

    try:
        return importlib.import_module(name)
    except ImportError:
        module = types.ModuleType(name)
        sys.modules[name] = module
        return module


def ensure_package(name: str, path: Path) -> types.ModuleType:
    """Return a test module that still permits importing real child modules."""

    module = ensure_module(name)
    package_path = str(path)
    paths = list(getattr(module, "__path__", ()))
    if package_path not in paths:
        paths.append(package_path)
    module.__path__ = paths
    return module
