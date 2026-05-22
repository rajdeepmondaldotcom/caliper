from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from caliper.aggregation import aggregate_total, event_cost
from caliper.humanize import session_display_label
from caliper.models import LoadResult, RuntimeOptions, UsageEvent, decimal_string
from caliper.pricing import RateCard
from caliper.render import _redact_paths, pricing_status, pricing_warnings
from caliper.subscriptions import subscription_plan_payload, subscription_warnings
from caliper.timeutil import iso_z, load_timezone
from caliper.windows import WindowState, compute_window_state, format_seconds_remaining


@dataclass(frozen=True)
class StatuslineTotals:
    cost_usd: Decimal
    cache_savings_cost_usd: Decimal
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    events: int

    @property
    def cache_ratio(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return self.cached_input_tokens / self.input_tokens


@dataclass(frozen=True)
class StatuslineSnapshot:
    generated_at: dt.datetime
    window_start: dt.datetime
    window_end: dt.datetime
    events: int
    sessions: int
    latest_event: UsageEvent | None
    top_project: str
    top_project_cost_usd: Decimal
    today: StatuslineTotals
    trailing_7d: StatuslineTotals
    primary: WindowState
    secondary: WindowState
    plan_types: tuple[str, ...]
    pricing_status: str
    warnings: tuple[str, ...]


def build_statusline_snapshot(
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    now: dt.datetime | None = None,
) -> StatuslineSnapshot:
    now = now or options.end
    tz = load_timezone(options.timezone)
    local_now = now.astimezone(tz)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    trailing_start = now - dt.timedelta(days=7)
    today_events = _events_in_window(result.events, today_start, now)
    trailing_events = _events_in_window(result.events, trailing_start, now)
    today = _totals(today_events, result, options, rate_card, "Today")
    trailing = _totals(trailing_events, result, options, rate_card, "Last 7 days")
    full_total = aggregate_total(result, options, rate_card=rate_card)
    top_project, top_project_cost = _top_project(result.events, rate_card)
    warnings = tuple(
        result.warnings
        + pricing_warnings(full_total)
        + subscription_warnings(full_total.plan_types)
    )
    sessions = {event.session_id for event in result.events if event.session_id}
    return StatuslineSnapshot(
        generated_at=now,
        window_start=options.start,
        window_end=options.end,
        events=len(result.events),
        sessions=len(sessions),
        latest_event=max(result.events, key=lambda event: event.timestamp, default=None),
        top_project=top_project,
        top_project_cost_usd=top_project_cost,
        today=today,
        trailing_7d=trailing,
        primary=compute_window_state(result.rate_limit_samples, now, "primary"),
        secondary=compute_window_state(result.rate_limit_samples, now, "secondary"),
        plan_types=tuple(sorted(result.plan_types)),
        pricing_status=pricing_status(full_total),
        warnings=warnings,
    )


def _top_project(events: list[UsageEvent], rate_card: RateCard) -> tuple[str, Decimal]:
    costs_by_project: dict[str, Decimal] = {}
    for event in events:
        project = event.thread.cwd
        if not project:
            continue
        costs, _long_context, _unknown_model = event_cost(rate_card, event)
        costs_by_project[project] = costs_by_project.get(project, Decimal("0")) + costs.cost_usd
    if not costs_by_project:
        return "", Decimal("0")
    return max(costs_by_project.items(), key=lambda item: (item[1], item[0]))


def statusline_payload(
    snapshot: StatuslineSnapshot,
    options: RuntimeOptions | None = None,
) -> dict:
    latest = snapshot.latest_event
    payload = {
        "generated_at": iso_z(snapshot.generated_at),
        "window": {
            "start": iso_z(snapshot.window_start),
            "end": iso_z(snapshot.window_end),
        },
        "events": snapshot.events,
        "sessions": snapshot.sessions,
        "latest": None
        if latest is None
        else {
            "timestamp": iso_z(latest.timestamp),
            "session": session_display_label(
                latest,
                options.timezone if options is not None else "UTC",
            ),
            "session_id": latest.session_id,
            "project": latest.thread.cwd,
            "model": latest.model,
            "service_tier": latest.service_tier,
            "plan_type": latest.plan_type,
        },
        "top_project": {
            "label": snapshot.top_project,
            "cost_usd": float(snapshot.top_project_cost_usd),
            "cost_usd_exact": decimal_string(snapshot.top_project_cost_usd),
        },
        "today": _totals_payload(snapshot.today),
        "trailing_7d": _totals_payload(snapshot.trailing_7d),
        "rate_limits": {
            "primary": _window_payload(snapshot.primary),
            "secondary": _window_payload(snapshot.secondary),
        },
        "pricing": {
            "status": snapshot.pricing_status,
            "warnings": list(snapshot.warnings),
        },
        "subscription": {
            "plan_types": list(snapshot.plan_types),
            "plans": subscription_plan_payload(set(snapshot.plan_types)),
        },
    }
    return _redact_paths(payload, options) if options is not None else payload


def render_statusline_text(snapshot: StatuslineSnapshot) -> str:
    latest = snapshot.latest_event
    identity = "no usage"
    if latest is not None:
        model = latest.model or "unknown model"
        tier = latest.service_tier or "unknown tier"
        identity = f"{model}/{tier}"
    parts = [
        identity,
        f"today ${snapshot.today.cost_usd:,.2f}",
        f"7d ${snapshot.trailing_7d.cost_usd:,.2f}",
        f"5h {_window_text(snapshot.primary)}",
        f"weekly {_window_text(snapshot.secondary)}",
        f"cache {snapshot.today.cache_ratio:.0%}",
        snapshot.pricing_status,
    ]
    if snapshot.top_project:
        parts.insert(1, _project_text(snapshot.top_project))
    if snapshot.warnings:
        suffix = "s" if len(snapshot.warnings) != 1 else ""
        parts.append(f"{len(snapshot.warnings)} warning{suffix}")
    return " | ".join(parts)


def render_statusline_compact(snapshot: StatuslineSnapshot) -> str:
    parts = [
        f"T ${snapshot.today.cost_usd:,.2f}",
        f"7d ${snapshot.trailing_7d.cost_usd:,.2f}",
        f"5h {_window_compact_text(snapshot.primary)}",
        f"W {_window_compact_text(snapshot.secondary)}",
        f"C {snapshot.today.cache_ratio:.0%}",
    ]
    if snapshot.warnings:
        parts.append(f"!{len(snapshot.warnings)}")
    return " | ".join(parts)


def _events_in_window(
    events: list[UsageEvent], start: dt.datetime, end: dt.datetime
) -> list[UsageEvent]:
    return [event for event in events if start <= event.timestamp < end]


def _totals(
    events: list[UsageEvent],
    result: LoadResult,
    options: RuntimeOptions,
    rate_card: RateCard,
    label: str,
) -> StatuslineTotals:
    scoped = LoadResult(
        events=events,
        duplicates=0,
        tier_sources=result.tier_sources,
        plan_types=result.plan_types,
        rate_limit_samples=[],
        warnings=[],
    )
    total = aggregate_total(scoped, options, label=label, rate_card=rate_card)
    return StatuslineTotals(
        cost_usd=total.costs.cost_usd,
        cache_savings_cost_usd=total.cache_savings.cost_usd,
        input_tokens=total.totals.input_tokens,
        cached_input_tokens=total.totals.cached_input_tokens,
        output_tokens=total.totals.output_tokens,
        total_tokens=total.totals.total_tokens,
        events=total.totals.events,
    )


def _totals_payload(totals: StatuslineTotals) -> dict:
    return {
        "events": totals.events,
        "input_tokens": totals.input_tokens,
        "cached_input_tokens": totals.cached_input_tokens,
        "output_tokens": totals.output_tokens,
        "total_tokens": totals.total_tokens,
        "cache_ratio": totals.cache_ratio,
        "cost_usd": float(totals.cost_usd),
        "cost_usd_exact": decimal_string(totals.cost_usd),
        "cache_savings_cost_usd": float(totals.cache_savings_cost_usd),
        "cache_savings_cost_usd_exact": decimal_string(totals.cache_savings_cost_usd),
    }


def _window_payload(state: WindowState) -> dict:
    return {
        "used_percent": state.used_percent,
        "window_minutes": state.window_minutes,
        "reset_at": iso_z(state.reset_at) if state.reset_at else None,
        "seconds_remaining": state.seconds_remaining,
        "burn_rate_per_hour": state.burn_rate_per_hour,
        "eta_to_100": iso_z(state.eta_to_100) if state.eta_to_100 else None,
        "samples": state.samples,
        "limit_id": state.limit_id,
        "limit_name": state.limit_name,
    }


def _window_text(state: WindowState) -> str:
    percent = "-" if state.used_percent is None else f"{state.used_percent:.0f}%"
    reset = (
        "due"
        if state.reset_at is not None and state.seconds_remaining == 0
        else format_seconds_remaining(state.seconds_remaining)
    )
    return f"{percent} reset {reset}"


def _window_compact_text(state: WindowState) -> str:
    percent = "-" if state.used_percent is None else f"{state.used_percent:.0f}%"
    reset = format_seconds_remaining(state.seconds_remaining)
    return f"{percent}/{reset}"


def _amount(value: Decimal) -> str:
    return f"{float(value):,.2f}"


def _project_text(value: str) -> str:
    label = value.rstrip("/").split("/")[-1] or value
    if len(label) > 28:
        label = label[:25] + "..."
    return f"project {label}"
