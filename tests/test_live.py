from __future__ import annotations

import datetime as dt

from rich.console import Console

from codex_meter.live import LiveFrame, render_frame
from codex_meter.windows import WindowState


def _make_state(
    window: str = "primary",
    used: float | None = 42.5,
    seconds: int | None = 1234,
    burn: float | None = 3.2,
) -> WindowState:
    return WindowState(
        window=window,
        used_percent=used,
        window_minutes=300 if window == "primary" else 10080,
        reset_at=None if seconds is None else dt.datetime(2026, 5, 12, 17, 0, tzinfo=dt.UTC),
        seconds_remaining=seconds,
        burn_rate_per_hour=burn,
        eta_to_100=None,
        samples=5,
    )


def _frame(**overrides) -> LiveFrame:
    base = dict(
        now=dt.datetime(2026, 5, 12, 15, 30, tzinfo=dt.UTC),
        today_credits=1234.5,
        today_api_dollars=12.34,
        week_credits=10_000.0,
        primary=_make_state("primary"),
        secondary=_make_state("secondary", used=12.0, seconds=86400),
        plan_types=("pro",),
        events_loaded=42,
    )
    base.update(overrides)
    return LiveFrame(**base)


def _render(frame: LiveFrame) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(render_frame(frame))
    return console.export_text()


def test_render_frame_shows_usage_and_windows() -> None:
    text = _render(_frame())
    assert "Codex Meter" in text
    assert "Today" in text
    assert "1,234.50 credits" in text
    assert "$12.34" in text
    assert "Last 7d" in text
    assert "Primary 5h" in text
    assert "Secondary weekly" in text
    assert "42.5%" in text


def test_render_frame_handles_missing_window_data() -> None:
    blank_primary = WindowState(
        window="primary",
        used_percent=None,
        window_minutes=None,
        reset_at=None,
        seconds_remaining=None,
        burn_rate_per_hour=None,
        eta_to_100=None,
        samples=0,
    )
    text = _render(_frame(primary=blank_primary))
    # Missing fields should render as the em dash placeholder.
    assert "—" in text


def test_render_frame_eta_line_appears_when_present() -> None:
    primary = WindowState(
        window="primary",
        used_percent=50.0,
        window_minutes=300,
        reset_at=dt.datetime(2026, 5, 12, 17, 0, tzinfo=dt.UTC),
        seconds_remaining=5400,
        burn_rate_per_hour=25.0,
        eta_to_100=dt.datetime(2026, 5, 12, 17, 30, tzinfo=dt.UTC),
        samples=4,
    )
    text = _render(_frame(primary=primary))
    assert "Hits 100% by" in text
