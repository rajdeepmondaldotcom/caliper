"""Welcome screen. Runs once per machine."""

from __future__ import annotations

import json
import os
from pathlib import Path

from textual.widgets import Static

from caliper.tui.screens._base import CaliperScreen


def _state_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caliper" / "state.json"


def welcome_already_seen() -> bool:
    path = _state_path()
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text()).get("welcome_seen_at"))
    except (OSError, ValueError):
        return False


def mark_welcome_seen() -> None:
    import datetime as dt

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"welcome_seen_at": dt.datetime.now(tz=dt.UTC).isoformat()}))


class WelcomeScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper"
    SCREEN_QUESTION = "Local cost ledger for AI-assisted coding."

    BINDINGS = [
        ("space", "dismiss", "continue"),
        ("escape", "dismiss", "continue"),
    ]

    def top(self):
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")

    def middle(self):
        yield Static(
            "We read the logs already on this machine.\n"
            "Nothing leaves the device. No login. No upload.\n\n"
            "Press space to enter."
        )

    def footer_pills(self) -> str:
        return "[ space continue ]  [ esc skip ]"

    def action_dismiss(self) -> None:
        mark_welcome_seen()
        self.app.pop_screen()
