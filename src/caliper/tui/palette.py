"""Command palette provider exposing every Caliper action by name.

Bound to ``ctrl+p`` via Textual's default palette key. Each command
yields a :class:`DiscoveryHit` whose help string reads in voice.
"""

from __future__ import annotations

import inspect

from textual.command import DiscoveryHit, Hit, Hits, Provider


class CaliperCommands(Provider):
    """Surface every named action to the user without leaving the keyboard."""

    @property
    def app_actions(self) -> list[tuple[str, str, str]]:
        return [
            ("Go to Home", "1", "Three windows: last 7, 30, 90 days."),
            ("Go to Intervals", "2", "Daily, weekly, monthly tabs."),
            ("Go to Sessions", "3", "Recent sessions ranked by spend."),
            ("Go to Projects", "4", "Per-project rollup tree."),
            ("Go to Models", "5", "Model and tier breakdown."),
            ("Go to Limits", "6", "Primary and secondary credit windows."),
            ("Go to Live", "7", "Real-time event stream."),
            ("Go to Forecast", "8", "Linear + EWMA projection."),
            ("Go to Doctor", "9", "Environment health checks."),
            ("Go to Receipt", "0", "Monthly export preview."),
            ("Go to What-If", "w", "Compare service-tier scenarios."),
            ("Go to Budgets", "b", "Budget thresholds and status."),
            ("Go to Insights", "i", "Ranked spend and behavior signals."),
            ("Go to Help", "question_mark", "Keyboard map and screen guide."),
            ("Refresh", "r", "Re-run the load worker."),
            ("Cycle theme", "t", "slate → parchment → colorblind → mono."),
            ("Toggle redact", "p", "Show or hide prompt-derived labels."),
            ("Step interval back", "left_square_bracket", "Move the window earlier by one period."),
            (
                "Step interval forward",
                "right_square_bracket",
                "Move the window later by one period.",
            ),
        ]

    async def discover(self) -> Hits:
        for name, key, help_text in self.app_actions:
            yield DiscoveryHit(
                display=name,
                command=self._make_runner(key),
                help=help_text,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, key, help_text in self.app_actions:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score=score,
                    match_display=matcher.highlight(name),
                    command=self._make_runner(key),
                    help=help_text,
                )

    def _make_runner(self, key: str):
        async def _run() -> None:
            app = self.app
            result = None
            nav = {
                "1": "home",
                "2": "intervals",
                "3": "sessions",
                "4": "projects",
                "5": "models",
                "6": "limits",
                "7": "live",
                "8": "forecast",
                "9": "doctor",
                "0": "receipt",
                "w": "whatif",
                "b": "budgets",
                "i": "insights",
            }
            if key in nav and callable(getattr(app, "action_go", None)):
                result = app.action_go(nav[key])
            elif key == "question_mark" and callable(getattr(app, "action_show_help", None)):
                result = app.action_show_help()
            elif key == "r" and callable(getattr(app, "action_refresh", None)):
                result = app.action_refresh()
            elif key == "t" and callable(getattr(app, "action_cycle_theme", None)):
                result = app.action_cycle_theme()
            elif key == "p" and callable(getattr(app, "action_toggle_redact", None)):
                result = app.action_toggle_redact()
            elif key == "left_square_bracket" and callable(getattr(app, "action_step_back", None)):
                result = app.action_step_back()
            elif key == "right_square_bracket" and callable(
                getattr(app, "action_step_forward", None)
            ):
                result = app.action_step_forward()
            if inspect.isawaitable(result):
                await result

        return _run
