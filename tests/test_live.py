from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from rich.console import Console
from typer.testing import CliRunner

from caliper import live
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
        today_cost_usd=12.34,
        week_cost_usd=10_000.0,
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


def _render_state(frame: LiveFrame, *, show_help: bool = False, paused: bool = False) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(render_frame(frame, show_help=show_help, paused=paused))
    return console.export_text()


def test_render_frame_shows_usage_and_windows() -> None:
    text = _render(_frame())
    assert "Caliper" in text
    assert "q quit" in text
    assert "? help" in text
    assert "Today" in text
    assert "$12.34" in text
    assert "$10,000.00" in text
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
    assert "Caliper" in text
    assert text.index("Usage") < text.index("Primary 5h") < text.index("Secondary weekly")


def test_render_frame_help_and_non_exact_pricing_details() -> None:
    text = _render_state(_frame(), show_help=True, paused=True)
    assert "Live Help" in text
    assert "resume" in text
    assert "refresh immediately" in text

    warning_text = _render(
        _frame(
            today_cache_savings=1.25,
            today_sparkline="▁█",
            pricing_status="partial",
            pricing_warnings=("first warning", "second warning", "third warning"),
            primary=_make_state("primary", used=90.0),
        )
    )
    assert "Cache saved" in warning_text
    assert "Pricing" in warning_text
    assert "partial" in warning_text
    assert "first warning" in warning_text
    assert "second warning" in warning_text
    assert "third warning" not in warning_text
    assert "Today trend" in warning_text


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


def test_live_helpers_cover_keyboard_and_stop_paths(monkeypatch) -> None:
    state = live.LiveLoopState(frame=_frame())
    monkeypatch.setattr(live, "_read_key", lambda: "q")
    assert live._handle_live_key(state, object()) is True

    monkeypatch.setattr(live, "_read_key", lambda: "?")
    assert live._handle_live_key(state, object()) is False
    assert state.show_help is True

    monkeypatch.setattr(live, "_read_key", lambda: "p")
    assert live._handle_live_key(state, object()) is False
    assert state.paused is True

    refreshed = _frame(today_cost_usd=999)
    state.paused = False
    monkeypatch.setattr(live, "_read_key", lambda: "r")
    monkeypatch.setattr(live, "collect_frame", lambda _options: refreshed)
    assert live._handle_live_key(state, object()) is False
    assert state.frame.today_cost_usd == 999

    assert live._should_stop(state, {"flag": False}, max_ticks=None) is False
    assert live._should_stop(state, {"flag": True}, max_ticks=None) is True
    state.ticks = 2
    assert live._should_stop(state, {"flag": False}, max_ticks=2) is True

    state.show_help = False
    state.paused = False
    assert live._auto_refresh_enabled(state) is True
    state.show_help = True
    assert live._auto_refresh_enabled(state) is False
    state.show_help = False
    state.paused = True
    assert live._auto_refresh_enabled(state) is False


def test_live_loop_updates_until_max_ticks(monkeypatch) -> None:
    updates: list[object] = []
    state = live.LiveLoopState(frame=_frame())
    fake_live = SimpleNamespace(update=updates.append)
    monkeypatch.setattr(live, "_read_key", lambda: "")
    monkeypatch.setattr(live.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(live, "collect_frame", lambda _options: _frame(today_cost_usd=321))

    live._run_live_loop(fake_live, state, object(), 0.01, 2, {"flag": False}, 140)

    assert state.ticks == 2
    assert state.frame.today_cost_usd == 321
    assert len(updates) == 1


def test_read_key_and_sparkline_edge_cases(monkeypatch) -> None:
    assert live._sparkline([]) == ""
    assert live._sparkline([3.0, 3.0]) == "▁▁"
    assert live._sparkline([0.0, 10.0]) == "▁█"

    monkeypatch.setattr(live.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert live._read_key() == ""

    tty = SimpleNamespace(isatty=lambda: True, read=lambda _count: "x")
    monkeypatch.setattr(live.sys, "stdin", tty)
    monkeypatch.setattr(live.select, "select", lambda *_args: ([], [], []))
    assert live._read_key() == ""

    monkeypatch.setattr(live.select, "select", lambda *_args: ([tty], [], []))
    assert live._read_key() == "x"
