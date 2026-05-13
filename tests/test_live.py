from __future__ import annotations

import datetime as dt

from rich.console import Console
from typer.testing import CliRunner

from caliper.cli import app
from caliper.config import build_options
from caliper.live import LiveFrame, collect_frame, render_frame
from caliper.windows import WindowState

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


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


def _render_width(frame: LiveFrame, width: int) -> str:
    console = Console(record=True, width=width, color_system=None)
    console.print(render_frame(frame, width=width))
    return console.export_text()


def test_render_frame_shows_usage_and_windows() -> None:
    text = _render(_frame())
    assert "Codex Meter" in text
    assert "q quit" in text
    assert "? help" in text
    assert "Today" in text
    assert "1,234.50" in text
    assert "credits" in text
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


def test_render_frame_stacks_panels_in_narrow_terminals() -> None:
    text = _render_width(_frame(), 80)
    assert "Codex Meter" in text
    assert text.index("Usage") < text.index("Primary 5h") < text.index("Secondary weekly")


def test_live_cli_accepts_max_ticks(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-live.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    result = runner.invoke(
        app,
        [
            "live",
            "--max-ticks",
            "1",
            "--interval",
            "0.5",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_live_frame_uses_main_subscription_limit_bucket(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    preview_event = token_event(
        now + dt.timedelta(seconds=1),
        {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        limit_id="codex_bengalfox",
        limit_name="GPT-5.3-Codex-Spark",
    )
    preview_event["payload"]["rate_limits"]["primary"]["used_percent"] = 0.0
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-live-buckets.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                limit_id="codex",
            ),
            preview_event,
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=2)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
        no_parse_cache=True,
    )

    frame = collect_frame(options, now=now + dt.timedelta(seconds=2))

    assert frame.primary.limit_id == "codex"
    assert frame.primary.used_percent == 25.0
