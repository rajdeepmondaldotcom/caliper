"""Shared HTML report builder for every grouped command.

Caliper's flagship HTML output lives in :mod:`caliper.dashboards`. The
renderer (:func:`caliper.dashboards.html.render_dashboard`) produces a
single self-contained HTML page with inline CSS + JS, lens controls,
deltas, evidence, advisor, forecast, heatmap, and a print stylesheet.

Phase B of the HTML-export overhaul keeps that polished chrome as the
*only* HTML template and routes every grouped command's ``--format
html`` through it. The only per-command knob is which audience lens
(``executive`` / ``engineer`` / ``finance`` / ``audit``) is selected by
default; the renderer surfaces all data either way.

Public entrypoint:

    render_command_html(result, options, *, command, share_safe=True,
                        theme="dark", density="comfortable") -> str
"""

from __future__ import annotations

from typing import Final

from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.data_models import Dashboard, DashboardLens
from caliper.models import LoadResult, RuntimeOptions

# Map each command name to the audience lens that suits its question.
# Commands not listed default to "executive". This is the only Phase B
# decision; the rest of the renderer is shared.
_COMMAND_LENS: Final[dict[str, DashboardLens]] = {
    "overview": "executive",
    "daily": "engineer",
    "weekly": "engineer",
    "monthly": "finance",
    "session": "audit",
    "project": "audit",
    "models": "finance",
    "insights": "executive",
    "limits": "engineer",
    "forecast": "finance",
    "compare": "finance",
    "whatif": "finance",
    "tail": "engineer",
    "agents": "engineer",
    "skills": "engineer",
    "inefficiencies": "executive",
}

# Commands that look at narrow point-in-time data and should suppress
# the period-over-period delta computation. Skipping deltas avoids a
# second parse pass for windows where the comparison is meaningless.
_NO_DELTA_COMMANDS: Final[frozenset[str]] = frozenset(
    {"tail", "limits", "session", "forecast", "whatif", "compare"}
)

ALL_LENSES: Final[tuple[DashboardLens, ...]] = ("executive", "engineer", "finance", "audit")


def lens_for_command(command: str) -> DashboardLens:
    """Return the default audience lens for a command's HTML output."""
    return _COMMAND_LENS.get(command, "executive")


def build_command_dashboard(
    result: LoadResult,
    options: RuntimeOptions,
    *,
    command: str,
    with_deltas: bool | None = None,
) -> Dashboard:
    """Build the ``Dashboard`` payload for a command's ``--format html``.

    ``with_deltas`` defaults to ``False`` for the commands in
    :data:`_NO_DELTA_COMMANDS` and ``True`` otherwise. Pass an explicit
    boolean to override.
    """
    effective_deltas = with_deltas if with_deltas is not None else command not in _NO_DELTA_COMMANDS
    return build_handoff_dashboard(result, options, with_deltas=effective_deltas)


def render_command_html(
    result: LoadResult,
    options: RuntimeOptions,
    *,
    command: str,
    share_safe: bool = True,
    theme: str = "dark",
    density: str = "comfortable",
    with_deltas: bool | None = None,
) -> str:
    """Render a self-contained HTML report for any grouped command.

    The output is the same chrome the ``caliper dashboard`` command
    emits, with the audience lens defaulted to the value selected for
    ``command``. Pass ``share_safe=True`` (the default) to redact
    project paths, project names, session labels, and prompt content
    so the file is safe to forward to a finance recipient or attach to
    a Jira ticket.
    """
    payload = build_command_dashboard(result, options, command=command, with_deltas=with_deltas)
    return render_dashboard(
        payload,
        theme=theme,
        density=density,
        share_safe=share_safe,
    )


__all__ = [
    "ALL_LENSES",
    "build_command_dashboard",
    "lens_for_command",
    "render_command_html",
]
