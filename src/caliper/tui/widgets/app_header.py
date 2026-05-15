"""Stable TUI header widget."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static


class CaliperHeader(Static):
    """Small Caliper-owned header that avoids Textual Header mount races."""

    DEFAULT_CSS = """
    CaliperHeader {
        dock: top;
        width: 100%;
        background: $primary 40%;
        color: $foreground;
        height: 1;
        padding: 0 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def __init__(self, show_clock: bool = False, **kwargs: Any) -> None:
        del show_clock
        super().__init__("[bold]Caliper[/bold]  local AI usage ledger", **kwargs)
