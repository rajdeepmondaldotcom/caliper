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
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Static

from caliper.tui.widgets.app_header import CaliperHeader


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
    GLOBAL_BINDINGS = [
        Binding("question_mark", "app.show_help", "help", priority=True),
        Binding("t", "app.cycle_theme", "theme", priority=True),
        Binding("p", "app.toggle_redact", "redact", show=False, priority=True),
        Binding("1", "app.go('home')", "Home", priority=True),
        Binding("2", "app.go('intervals')", "Daily/Weekly", priority=True),
        Binding("3", "app.go('sessions')", "Sessions", priority=True),
        Binding("4", "app.go('projects')", "Projects", priority=True),
        Binding("5", "app.go('models')", "Models", priority=True),
        Binding("6", "app.go('limits')", "Limits", priority=True),
        Binding("7", "app.go('live')", "Live", priority=True),
        Binding("8", "app.go('forecast')", "Forecast", priority=True),
        Binding("9", "app.go('doctor')", "Doctor", priority=True),
        Binding("0", "app.go('receipt')", "Receipt", priority=True),
        Binding("w", "app.go('whatif')", "What-If", priority=True),
        Binding("b", "app.go('budgets')", "Budgets", priority=True),
        Binding("i", "app.go('insights')", "Insights", priority=True),
        Binding("left_square_bracket", "app.step_back", "< interval", show=False, priority=True),
        Binding(
            "right_square_bracket", "app.step_forward", "interval >", show=False, priority=True
        ),
    ]

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        local_bindings = list(getattr(cls, "BINDINGS", []))
        cls.BINDINGS = [*CaliperScreen.GLOBAL_BINDINGS, *local_bindings]

    def compose(self) -> ComposeResult:
        yield CaliperHeader(show_clock=True)
        with Container(id="top"):
            for widget in self.top():
                yield widget
        with Container(id="middle"):
            for widget in self.middle():
                yield widget
        with Container(id="footer-band"):
            yield Static(self.footer_pills(), id="footer-pills", markup=False)

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
        return "[ 0 receipt ] [ i insights ] [ ? help ] [ r refresh ] [ q quit ]"

    def action_refresh(self) -> None:
        """Delegate screen-level refresh bindings to the app shell."""
        refresh = getattr(self.app, "action_refresh", None)
        if callable(refresh):
            refresh()

    def update_from_snapshot(self, _snapshot) -> None:
        """Hook for screens with explicit reactive redraw needs."""
        return None
