"""Placeholder screens for areas not yet implemented in full.

Each stub keeps the keymap navigable end-to-end so the user can move
between sections without getting stuck. Replaced with real screens in
later commits (T09-T20).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class _StubScreen(Screen):
    DEFAULT_CSS = """
    _StubScreen Static { content-align: center middle; width: 1fr; height: 1fr; }
    """

    TITLE: str = "Caliper"
    HEADLINE: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            f"[b]{self.HEADLINE}[/b]\n\n"
            "This screen lands in a later commit (T09-T20).\n"
            "Press `esc` to return Home.",
        )
        yield Footer()

    def on_key(self, event) -> None:  # noqa: D401
        if event.key == "escape":
            self.app.pop_screen()


class SessionsScreen(_StubScreen):
    HEADLINE = "Sessions"


class IntervalsScreen(_StubScreen):
    HEADLINE = "Daily / Weekly / Monthly"


class ProjectsScreen(_StubScreen):
    HEADLINE = "Projects"


class ModelsScreen(_StubScreen):
    HEADLINE = "Models + Tiers"


class LimitsScreen(_StubScreen):
    HEADLINE = "Limits"


class LiveScreen(_StubScreen):
    HEADLINE = "Live"


class ForecastScreen(_StubScreen):
    HEADLINE = "Forecast"


class WhatIfScreen(_StubScreen):
    HEADLINE = "What-If"


class BudgetsScreen(_StubScreen):
    HEADLINE = "Budgets"


class InsightsScreen(_StubScreen):
    HEADLINE = "Insights"


class DoctorScreen(_StubScreen):
    HEADLINE = "Doctor"


class ReceiptScreen(_StubScreen):
    HEADLINE = "Receipt"


class WelcomeScreen(_StubScreen):
    HEADLINE = "Welcome to Caliper"
