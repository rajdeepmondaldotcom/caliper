"""Caliper.

Offline cost ledger for AI-assisted coding. Reads local Codex,
Claude Code, Cursor, and Aider logs. Prints what each PR cost.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from caliper.persona import VoiceLintError, VoiceViolation, voice_lint, voice_lint_strict

try:
    __version__ = version("caliper-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

SCHEMA_VERSION = 2

__all__ = [
    "SCHEMA_VERSION",
    "VoiceLintError",
    "VoiceViolation",
    "__version__",
    "voice_lint",
    "voice_lint_strict",
]
