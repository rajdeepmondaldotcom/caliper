"""Three-band layout contract for every Caliper screen.

Every real screen subclasses :class:`CaliperScreen`. The base class
wires three named containers via :meth:`compose`:

  +-------------------------------------------------+
  | top band   (#top, height: 3 max)                |
  |   header + scope chip + one Notice              |
  +-------------------------------------------------+
  | middle band (#middle, height: 1fr)              |
  |   primary widget (DataTable, Tree, etc.)        |
  +-------------------------------------------------+
  | footer band (#footer, height: 1)                |
  |   decision pills + last refresh + globals       |
  +-------------------------------------------------+

Subclasses override :meth:`top`, :meth:`middle`, and optionally
:meth:`footer_pills` to fill the slots. The shell stays consistent.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class CaliperScreen(Screen):
    """Base class for every Caliper TUI screen.

    The three-band layout is enforced by composing three named
    containers. Subclasses override the helper methods rather than
    :meth:`compose` so the layout stays inviolate.
    """

    DEFAULT_CSS = """
    CaliperScreen #top {
        height: auto;
        max-height: 5;
        padding: 0 1;
        border-bottom: solid $primary 30%;
    }
    CaliperScreen #middle {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }
    CaliperScreen #footer-band {
        height: 1;
        padding: 0 1;
        color: $foreground 70%;
    }
    """

    SCREEN_TITLE: str = "Caliper"
    SCREEN_QUESTION: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="top"):
            for widget in self.top():
                yield widget
        with Container(id="middle"):
            for widget in self.middle():
                yield widget
        with Container(id="footer-band"):
            yield Static(self.footer_pills(), id="footer-pills")
        yield Footer()

    def top(self):
        """Yield top-band widgets. Override in the subclass."""
        if self.SCREEN_QUESTION:
            yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")
        else:
            yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]")

    def middle(self):
        """Yield middle-band widgets. Override in the subclass."""
        yield Static("")

    def footer_pills(self) -> str:
        """Return the decision-pill line for the footer band."""
        return "[ r refresh ]  [ ? help ]  [ q quit ]"
