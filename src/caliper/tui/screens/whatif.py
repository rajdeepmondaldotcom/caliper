"""What-if screen. Re-prices the window under hypothetical tier or model."""

from __future__ import annotations

from textual.widgets import Input, Static

from caliper.intervals import Interval
from caliper.models import LoadResult
from caliper.pricing import available_model_names, normalize_service_tier
from caliper.scenarios import build_whatif_report, events_in_interval
from caliper.tui.formatting import format_cost_usd
from caliper.tui.screens._base import CaliperScreen

_EMPTY_INPUT_NAV_KEYS = {
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


class WhatIfInput(Input):
    """Let global single-key navigation win when an empty field has focus."""

    def on_key(self, event) -> None:
        if self.value or event.key not in _EMPTY_INPUT_NAV_KEYS:
            return
        event.prevent_default()
        event.stop()
        self.app.action_go(_EMPTY_INPUT_NAV_KEYS[event.key])


class WhatIfScreen(CaliperScreen):
    SCREEN_TITLE = "Caliper - What if"
    SCREEN_QUESTION = "What changes if you swap tier or model."

    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("escape", "app.pop_screen", "back"),
    ]

    def top(self):
        yield Static(f"[bold]{self.SCREEN_TITLE}[/bold]   {self.SCREEN_QUESTION}")

    def middle(self):
        yield Static("[dim]Hypothetical tier (standard or fast):[/dim]")
        yield WhatIfInput(placeholder="standard", id="tier-input")
        yield Static("[dim]Hypothetical model (must be in rate card):[/dim]")
        yield WhatIfInput(placeholder="claude-sonnet-4.6", id="model-input")
        yield Static("", id="whatif-result")

    def footer_pills(self) -> str:
        return "[ enter apply ]  [ esc back ]"

    def on_mount(self) -> None:
        self._render_result()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._render_result()

    def _render_result(self) -> None:
        from textual.css.query import NoMatches

        try:
            result_widget = self.query_one("#whatif-result", Static)
        except NoMatches:
            return
        snap = getattr(self.app, "snapshot", None)
        if snap is None or snap.load_result is None or snap.rate_card is None:
            result_widget.update("\n[dim]Waiting for the first load.[/dim]")
            return
        try:
            tier = self._tier_value()
            model = self._model_value()
        except ValueError as exc:
            result_widget.update(f"\n[red]{exc}[/red]")
            return
        if tier is None and model is None:
            result_widget.update("\n[dim]Enter a tier or model, then press Enter.[/dim]")
            return
        scoped = self._scoped_result(snap)
        report = build_whatif_report(
            scoped,
            snap.options,
            snap.rate_card,
            days=max((snap.scope.interval.end - snap.scope.interval.start).days, 1),
            tier=tier,
            model=model,
        )
        if report.noop:
            result_widget.update(f"\n[dim]{report.noop_message}[/dim]")
            return
        totals = report.totals
        if totals is None:
            result_widget.update("\n[dim]No what-if totals available.[/dim]")
            return
        result_widget.update(
            "\n"
            f"[bold]Actual:[/bold] {format_cost_usd(totals.actual_cost_usd)}\n"
            f"[bold]Projected:[/bold] {format_cost_usd(totals.hypothetical_cost_usd)}\n"
            f"[bold]Delta:[/bold] {format_cost_usd(totals.cost_usd_delta)} "
            f"({totals.cost_usd_pct:+.1f}%)\n"
            f"[dim]Events evaluated:[/dim] {report.events_evaluated:,}"
        )

    def _tier_value(self) -> str | None:
        raw = self.query_one("#tier-input", Input).value.strip()
        if not raw:
            return None
        tier = normalize_service_tier(raw)
        if tier not in {"standard", "fast"}:
            raise ValueError("Tier must be standard or fast.")
        return tier

    def _model_value(self) -> str | None:
        model = self.query_one("#model-input", Input).value.strip()
        if not model:
            return None
        if model not in available_model_names():
            raise ValueError(f"{model!r} is not in the active rate card.")
        return model

    @staticmethod
    def _scoped_result(snap) -> LoadResult:
        interval: Interval = snap.scope.interval
        return LoadResult(
            events=events_in_interval(snap.load_result.events, interval),
            duplicates=0,
            tier_sources=snap.load_result.tier_sources,
            plan_types=snap.load_result.plan_types,
            rate_limit_samples=[],
            warnings=snap.load_result.warnings,
            parser_issues=snap.load_result.parser_issues,
            vendor_stats=snap.load_result.vendor_stats,
        )
