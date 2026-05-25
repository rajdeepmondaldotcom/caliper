"""Immutable snapshot of everything the TUI screens need to render.

The single ``AppSnapshot`` flows from the worker layer to the screens
via a reactive store on :class:`caliper.tui.app.CaliperApp`. Changes go
through :func:`apply_scope` so we never accidentally mutate two copies.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

from caliper.intervals import Interval
from caliper.models import Aggregate, LoadResult, RuntimeOptions
from caliper.pricing import RateCard
from caliper.windows import WindowState


@dataclass(frozen=True)
class Scope:
    """Display-only filters; data filters live on :class:`RuntimeOptions`."""

    interval: Interval
    show_dollars: bool = True


def default_scope(now: dt.datetime) -> Scope:
    seven = now - dt.timedelta(days=7)
    return Scope(
        interval=Interval(start=seven, end=now, label="Last 7 days"),
    )


@dataclass(frozen=True)
class AppSnapshot:
    options: RuntimeOptions
    scope: Scope
    load_result: LoadResult | None = None
    rate_card: RateCard | None = None
    overview_windows: tuple[Aggregate, ...] = ()
    overview_total: Aggregate | None = None
    daily: tuple[Aggregate, ...] = ()
    weekly: tuple[Aggregate, ...] = ()
    monthly: tuple[Aggregate, ...] = ()
    sessions: tuple[Aggregate, ...] = ()
    projects: tuple[Aggregate, ...] = ()
    models: tuple[Aggregate, ...] = ()
    insights: tuple = ()  # tuple[Insight, ...]
    primary_window: WindowState | None = None
    secondary_window: WindowState | None = None
    refresh_started_at: dt.datetime | None = None
    refresh_completed_at: dt.datetime | None = None
    refresh_error: str | None = None
    load_total_files: int = 0
    load_files_done: int = 0
    load_files_cached: int = 0
    cancelled: bool = False

    def is_loading(self) -> bool:
        return (
            self.refresh_started_at is not None
            and self.refresh_completed_at is None
            and self.refresh_error is None
            and not self.cancelled
        )


def apply_scope(
    snapshot: AppSnapshot,
    *,
    interval: Interval | None = None,
    project: str | None = ...,  # type: ignore[assignment]
    service_tier: str | None = ...,  # type: ignore[assignment]
    vendors: tuple[str, ...] | None = ...,  # type: ignore[assignment]
    show_prompts: bool | None = None,
    show_paths: bool | None = None,
) -> AppSnapshot:
    """Return a new snapshot whose ``RuntimeOptions`` reflect the changes.

    Use the sentinel ``...`` to mean "leave alone"; pass ``None`` to
    actively clear an existing filter (e.g. unset the project).
    """
    options = snapshot.options
    if interval is not None:
        options = replace(options, start=interval.start, end=interval.end)
    if project is not ...:
        options = replace(options, project=project)
    if service_tier is not ...:
        options = replace(options, service_tier=service_tier or "auto")
    if vendors is not ...:
        options = replace(options, vendors=vendors or ("all",))
    if show_prompts is not None:
        options = replace(options, show_prompts=show_prompts)
    if show_paths is not None:
        options = replace(options, show_paths=show_paths)
    scope = snapshot.scope if interval is None else replace(snapshot.scope, interval=interval)
    return replace(
        snapshot,
        options=options,
        scope=scope,
        load_result=None,
        rate_card=None,
        overview_windows=(),
        overview_total=None,
        daily=(),
        weekly=(),
        monthly=(),
        sessions=(),
        projects=(),
        models=(),
        insights=(),
        primary_window=None,
        secondary_window=None,
        refresh_started_at=None,
        refresh_completed_at=None,
        refresh_error=None,
        load_total_files=0,
        load_files_done=0,
        load_files_cached=0,
        cancelled=False,
    )
