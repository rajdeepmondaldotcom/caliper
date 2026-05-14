"""Compatibility imports for the pre-0.0.12 TUI screen module path."""

from __future__ import annotations

from caliper.tui.screens.budgets import BudgetsScreen
from caliper.tui.screens.doctor import DoctorScreen
from caliper.tui.screens.forecast import ForecastScreen
from caliper.tui.screens.insights import InsightsScreen
from caliper.tui.screens.intervals import IntervalsScreen
from caliper.tui.screens.limits import LimitsScreen
from caliper.tui.screens.live import LiveScreen
from caliper.tui.screens.models import ModelsScreen
from caliper.tui.screens.projects import ProjectsScreen
from caliper.tui.screens.receipt import ReceiptScreen
from caliper.tui.screens.sessions import SessionsScreen
from caliper.tui.screens.welcome import WelcomeScreen
from caliper.tui.screens.whatif import WhatIfScreen

__all__ = [
    "BudgetsScreen",
    "DoctorScreen",
    "ForecastScreen",
    "InsightsScreen",
    "IntervalsScreen",
    "LimitsScreen",
    "LiveScreen",
    "ModelsScreen",
    "ProjectsScreen",
    "ReceiptScreen",
    "SessionsScreen",
    "WelcomeScreen",
    "WhatIfScreen",
]
