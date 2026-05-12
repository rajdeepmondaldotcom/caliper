"""Codex Meter — offline-first Codex usage analytics."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("codex-meter")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
