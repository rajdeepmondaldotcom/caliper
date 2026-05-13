"""Caliper.

Measure every line of AI-written code with offline-first usage intelligence.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("caliper-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
