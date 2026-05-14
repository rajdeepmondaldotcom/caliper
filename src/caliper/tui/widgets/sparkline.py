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
        # Do not name this helper _render — that collides with the Textual
        # Widget.render pipeline (Widget._render is a virtual method on the
        # base). Use _render_text instead.
        super().__init__(self._render_text(values), **kwargs)
        self.values = tuple(values)

    def watch_values(self, new: tuple[float, ...]) -> None:
        self.update(self._render_text(new))

    @staticmethod
    def _render_text(values: tuple[float, ...] | list[float]) -> str:
        return sparkline(list(values)) or "—"
