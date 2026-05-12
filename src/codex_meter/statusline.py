from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from codex_meter.aggregation import aggregate_projects, aggregate_total
from codex_meter.models import LoadResult, RuntimeOptions, UsageEvent, decimal_string
from codex_meter.pricing import RateCard
from codex_meter.render import pricing_status, pricing_warnings
from codex_meter.subscriptions import subscription_plan_payload, subscription_warnings
from codex_meter.timeutil import iso_z, load_timezone
from codex_meter.windows import WindowState, compute_window_state, format_seconds_remaining


@dataclass(frozen=True)
class StatuslineTotals:
    credits: Decimal
    api_dollars: Decimal
    cache_savings_api_dollars: Decimal
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
    top_project_credits: Decimal
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
    projects = aggregate_projects(result, options, rate_card=rate_card)
    top_project = projects[0] if projects else None
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
        top_project=top_project.label if top_project else "",
        top_project_credits=top_project.costs.adjusted_credits if top_project else Decimal("0"),
        today=today,
        trailing_7d=trailing,
        primary=compute_window_state(result.credit_samples, now, "primary"),
        secondary=compute_window_state(result.credit_samples, now, "secondary"),
        plan_types=tuple(sorted(result.plan_types)),
        pricing_status=pricing_status(full_total),
        warnings=warnings,
    )


def statusline_payload(snapshot: StatuslineSnapshot) -> dict:
    latest = snapshot.latest_event
    return {
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
            "session_id": latest.session_id,
            "project": latest.thread.cwd,
            "model": latest.model,
            "service_tier": latest.service_tier,
            "plan_type": latest.plan_type,
        },
        "top_project": {
            "label": snapshot.top_project,
            "credits": float(snapshot.top_project_credits),
            "credits_exact": decimal_string(snapshot.top_project_credits),
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


def render_statusline_text(snapshot: StatuslineSnapshot) -> str:
    latest = snapshot.latest_event
    identity = "no usage"
    if latest is not None:
        model = latest.model or "unknown model"
        tier = latest.service_tier or "unknown tier"
        identity = f"{model}/{tier}"
    parts = [
        identity,
        f"today {_amount(snapshot.today.credits)} cr (${snapshot.today.api_dollars:,.2f})",
        f"7d {_amount(snapshot.trailing_7d.credits)} cr",
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
        credit_samples=[],
        warnings=[],
    )
    total = aggregate_total(scoped, options, label=label, rate_card=rate_card)
    return StatuslineTotals(
        credits=total.costs.adjusted_credits,
        api_dollars=total.costs.api_dollars,
        cache_savings_api_dollars=total.cache_savings.api_dollars,
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
        "credits": float(totals.credits),
        "credits_exact": decimal_string(totals.credits),
        "api_dollars": float(totals.api_dollars),
        "api_dollars_exact": decimal_string(totals.api_dollars),
        "cache_savings_api_dollars": float(totals.cache_savings_api_dollars),
        "cache_savings_api_dollars_exact": decimal_string(totals.cache_savings_api_dollars),
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
    reset = format_seconds_remaining(state.seconds_remaining)
    return f"{percent} reset {reset}"


def _amount(value: Decimal) -> str:
    return f"{float(value):,.2f}"


def _project_text(value: str) -> str:
    label = value.rstrip("/").split("/")[-1] or value
    if len(label) > 28:
        label = label[:25] + "..."
    return f"project {label}"
