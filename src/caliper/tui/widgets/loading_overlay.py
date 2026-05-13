"""Loading overlay that shows file-by-file parse progress."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import ProgressBar, Static


class LoadingOverlay(Vertical):
    """Centered overlay with a progress bar and 'Reading X / Y' label."""

    DEFAULT_CSS = """
    LoadingOverlay {
        width: 60%;
        height: auto;
        padding: 1 2;
        border: round $primary;
        content-align: center middle;
        layer: overlay;
    }
    LoadingOverlay .label { content-align: center middle; }
    """

    total: reactive[int] = reactive(0)
    done: reactive[int] = reactive(0)
    cached: reactive[int] = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Static("Reading your AI coding sessions…", classes="label", id="overlay-title")
        self._bar = ProgressBar(total=100, show_eta=False, show_percentage=True)
        yield self._bar
        yield Static("Counting files…", classes="label", id="overlay-detail")

    def update_progress(self, *, total: int, done: int, cached: int) -> None:
        self.total = total
        self.done = done
        self.cached = cached
        pct = 0 if total <= 0 else int(100 * (done + cached) / total)
        self._bar.progress = pct
        detail = self.query_one("#overlay-detail", Static)
        detail.update(f"Read {done + cached} / {total}   ({cached} cached)")
