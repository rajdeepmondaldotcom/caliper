"""In-app keyboard map."""

from __future__ import annotations

from textual.widgets import Static

from caliper.tui.screens._base import CaliperScreen


class HelpScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - Help"
    SCREEN_QUESTION = "Keyboard map."

    BINDINGS = [
        ("escape", "app.pop_screen", "back"),
    ]

    def middle(self):
        yield Static(
            "\n".join(
                [
                    "Start here: run caliper doctor if Home shows no usage.",
                    "ctrl+p opens the command palette from any screen.",
                    "",
                    "1 Home       2 Intervals   3 Sessions   4 Projects",
                    "5 Models     6 Limits      7 Live       8 Forecast",
                    "9 Doctor     0 Receipt     w What-If    b Budgets",
                    "i Insights   r Refresh     t Theme      p Redact",
                    "[ / ] shift interval        esc Back     q Quit",
                ]
            )
        )

    def footer_pills(self) -> str:
        return "[ ctrl+p palette ]  [ esc back ]  [ r refresh ]  [ q quit ]"
