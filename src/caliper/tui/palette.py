"""Command palette provider exposing every Caliper action by name.

Bound to ``ctrl+p`` via Textual's default palette key. Each command
yields a :class:`DiscoveryHit` whose help string reads in voice.
"""

from __future__ import annotations

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
            await self.app.simulate_key(key) if hasattr(self.app, "simulate_key") else None
            handler = getattr(self.app, f"action_{key}", None)
            if callable(handler):
                handler()

        return _run
