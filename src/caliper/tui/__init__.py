"""Caliper's Textual TUI — opt-in immersive workspace.

Public surface intentionally tiny: :func:`run_tui` is the single entry
point invoked by the ``caliper tui`` CLI command. Everything else lives
under submodules to keep the import-on-launch cost low.

Importing this package requires the optional ``[tui]`` extra; callers
are expected to handle a missing ``textual`` import with a friendly
install hint (see ``caliper.cli.tui``).
"""

from __future__ import annotations

from caliper.tui.app import CaliperApp, run_tui

__all__ = ["CaliperApp", "run_tui"]
