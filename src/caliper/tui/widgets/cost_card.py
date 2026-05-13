"""Headline + delta + sparkline card. The Home screen's main vocabulary."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from caliper.humanize import compact_number, sparkline


class CostCard(Vertical):
    """A single 'how much did we spend?' tile.

    Composed of three lines: label, headline number, sparkline + delta.
    Styling lives in TCSS; this class only assembles the renderables.
    """

    DEFAULT_CSS = """
    CostCard {
        height: 6;
        padding: 0 2;
        border: round $primary 40%;
        margin: 0 1 1 0;
    }
    CostCard .label { color: $foreground 70%; }
    CostCard .headline { color: $primary; text-style: bold; }
    CostCard .meta { color: $foreground 60%; }
    """

    def __init__(
        self,
        label: str,
        *,
        api_dollars: float,
        credits: float,
        series: list[float] | tuple[float, ...] = (),
        delta_pct: float | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._api_dollars = api_dollars
        self._credits = credits
        self._series = list(series)
        self._delta_pct = delta_pct

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="label")
        yield Static(self._headline_text(), classes="headline")
        yield Static(self._meta_text(), classes="meta")

    def _headline_text(self) -> str:
        return f"${compact_number(self._api_dollars)}  ·  {compact_number(self._credits)} credits"

    def _meta_text(self) -> str:
        spark = sparkline(self._series) if self._series else "—"
        if self._delta_pct is None:
            return spark
        sign = "+" if self._delta_pct >= 0 else ""
        return f"{spark}   {sign}{self._delta_pct:.1f}% vs prev"
