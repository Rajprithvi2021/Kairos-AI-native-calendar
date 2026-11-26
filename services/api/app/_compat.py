"""Platform compatibility shims, installed before any third-party import (see app/__init__.py).

Windows Smart App Control / WDAC can block unsigned, low-reputation native modules. On the
development machine it blocked SQLAlchemy 2.1's Cython accelerators (``*_cy.pyd``) with
"An Application Control policy has blocked this file". SQLAlchemy ships an identical pure-Python
``*_cy.py`` twin for each, so when the native module is blocked we load the twin instead:
same behaviour, slightly slower, and no change to the user's security settings.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys


class _PreferPureCython(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):  # type: ignore[no-untyped-def]
        if not path or not fullname.startswith("sqlalchemy.") or not fullname.endswith("_cy"):
            return None
        name = fullname.rpartition(".")[2]
        for entry in path:
            candidate = os.path.join(entry, name + ".py")
            if os.path.isfile(candidate):
                return importlib.util.spec_from_file_location(fullname, candidate)
        return None


def _sqlalchemy_native_blocked() -> bool:
    if os.environ.get("KAIROS_PURE_SQLALCHEMY") == "1":
        return True
    if sys.platform != "win32":
        return False
    spec = importlib.util.find_spec("sqlalchemy")  # locates without importing
    if spec is None or not spec.origin:
        return False
    import ctypes

    root = os.path.dirname(spec.origin)
    # Reputation is judged per file, so probe every accelerator; if any is blocked, use the
    # pure-Python twins for all of them (never mix compiled and pure variants).
    for sub in ("engine", "sql", "util"):
        folder = os.path.join(root, sub)
        for fname in os.listdir(folder):
            if "_cy" in fname and fname.endswith(".pyd"):
                try:
                    ctypes.WinDLL(os.path.join(folder, fname))
                except OSError:
                    return True
    return False


def install() -> None:
    if any(isinstance(f, _PreferPureCython) for f in sys.meta_path):
        return
    if _sqlalchemy_native_blocked():
        sys.meta_path.insert(0, _PreferPureCython())
