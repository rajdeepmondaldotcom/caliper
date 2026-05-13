"""Thin Textual wrapper around :func:`caliper.humanize.sparkline`."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from caliper.humanize import sparkline


class Sparkline(Static):
    """Render a list of floats as a Unicode-block bar string."""

    DEFAULT_CSS = """
    Sparkline {
        color: $accent;
        width: auto;
        height: 1;
    }
    """

    values: reactive[tuple[float, ...]] = reactive(tuple)

    def __init__(self, values: list[float] | tuple[float, ...] = (), **kwargs) -> None:
        super().__init__(self._render(values), **kwargs)
        self.values = tuple(values)

    def watch_values(self, new: tuple[float, ...]) -> None:
        self.update(self._render(new))

    @staticmethod
    def _render(values: tuple[float, ...] | list[float]) -> str:
        return sparkline(list(values)) or "—"
