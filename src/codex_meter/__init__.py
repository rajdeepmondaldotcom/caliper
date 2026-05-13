"""Compatibility package for the original ``codex_meter`` import path.

Caliper's canonical Python package is ``caliper``. This module keeps older
library imports working by aliasing ``codex_meter.<module>`` to
``caliper.<module>`` on demand.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys

from caliper import __version__

__all__ = ["__version__"]

_COMPAT_PREFIX = f"{__name__}."
_TARGET_PREFIX = "caliper."
_FINDER_MARKER = "_codex_meter_compat_finder"


class _CompatLoader(importlib.abc.Loader):
    def create_module(self, spec: importlib.machinery.ModuleSpec):
        target_name = str(spec.loader_state)
        target = importlib.import_module(target_name)
        sys.modules[spec.name] = target
        return target

    def exec_module(self, module) -> None:
        return None


class _CompatFinder(importlib.abc.MetaPathFinder):
    _codex_meter_compat_finder = True

    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith(_COMPAT_PREFIX):
            return None
        target_name = f"{_TARGET_PREFIX}{fullname.removeprefix(_COMPAT_PREFIX)}"
        target_spec = importlib.util.find_spec(target_name)
        if target_spec is None:
            return None
        spec = importlib.machinery.ModuleSpec(
            fullname,
            _CompatLoader(),
            is_package=target_spec.submodule_search_locations is not None,
        )
        spec.loader_state = target_name
        if target_spec.submodule_search_locations is not None:
            spec.submodule_search_locations = []
        return spec


def _install_compat_finder() -> None:
    if any(getattr(finder, _FINDER_MARKER, False) for finder in sys.meta_path):
        return
    sys.meta_path.insert(0, _CompatFinder())


_install_compat_finder()
