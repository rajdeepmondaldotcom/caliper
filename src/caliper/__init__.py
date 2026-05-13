"""Caliper.

Measure every line of AI-written code with offline-first usage intelligence.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("caliper-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION", "__version__"]
