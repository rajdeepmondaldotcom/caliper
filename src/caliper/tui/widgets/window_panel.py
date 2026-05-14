"""Render a :class:`caliper.windows.WindowState` as a Textual panel.

Mirrors the look-and-feel of ``caliper live`` but uses Textual's CSS
for hierarchy. Severity hue flips at 80% used.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static

from caliper.windows import WindowState, format_burn_rate, format_seconds_remaining


class WindowPanel(Vertical):
    """Compact one-window view: percent used, reset countdown, burn rate."""

    DEFAULT_CSS = """
    WindowPanel { padding: 1 2; height: 8; border: round $primary 40%; margin: 0 1 1 0; }
    WindowPanel .label { color: $foreground 70%; }
    WindowPanel .percent { text-style: bold; }
    WindowPanel .reset { color: $foreground 60%; }
    WindowPanel.alarm { border: round $error; }
    """

    def __init__(self, label: str, state: WindowState | None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._state = state
        if state is not None and (state.used_percent or 0) >= 80:
            self.add_class("alarm")

    def compose(self) -> ComposeResult:
        if self._state is None:
            yield Static(self._label, classes="label")
            yield Static("No samples yet.", classes="reset")
            return
        state = self._state
        title = self._label + (f"  ({state.window_minutes}m)" if state.window_minutes else "")
        yield Static(title, classes="label")
        pct = state.used_percent or 0
        yield Static(_usage_percent_text(state.used_percent), classes="percent")
        bar = ProgressBar(total=100, show_eta=False, show_percentage=True)
        bar.advance(pct)
        yield bar
        yield Static(
            f"reset in {format_seconds_remaining(state.seconds_remaining)}   "
            f"burn {format_burn_rate(state.burn_rate_per_hour)}",
            classes="reset",
        )


def _usage_percent_text(value: float | None) -> str:
    return "usage -" if value is None else f"usage {value:.0f}%"
