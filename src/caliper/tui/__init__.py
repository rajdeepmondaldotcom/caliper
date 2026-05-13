"""Caliper's Textual TUI — the immersive workspace.

Public surface intentionally tiny: :func:`run_tui` is the single entry
point invoked by the ``caliper tui`` CLI command. Everything else lives
under submodules to keep the import-on-launch cost low.

``textual`` is a runtime dependency of ``caliper-ai`` itself, so
importing this package never raises ``ImportError`` on a normal install.
"""

from __future__ import annotations

from caliper.tui.app import CaliperApp, run_tui

__all__ = ["CaliperApp", "run_tui"]
