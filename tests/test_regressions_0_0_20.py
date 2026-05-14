"""Regressions caught by the live-QA pass on 0.0.19.

Each test pins one user-visible fix that shipped in 0.0.20.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from pathlib import Path

from typer.testing import CliRunner

from caliper.cli import app
from caliper.intervals import parse_interval
from caliper.parser import load_tier_overrides
from caliper.pricing import RateCard

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path: Path):
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-regress.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db


def test_bad_config_emits_friendly_error_not_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not valid toml: ::")
    session_root, state_db = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "--config",
            str(bad),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "overview",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output, result.output
    assert "error:" in result.output


def test_bad_rates_file_emits_friendly_error_not_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "rates.json"
    bad.write_text("{not json")
    session_root, state_db = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "--rates",
            str(bad),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "overview",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output, result.output
    assert "error:" in result.output


def test_bad_tier_map_emits_friendly_error_not_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "tier-map.json"
    bad.write_text("{not json")
    session_root, state_db = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "--tier-map",
            str(bad),
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "overview",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output, result.output
    assert "error:" in result.output


def test_load_tier_overrides_accepts_str_path(tmp_path: Path) -> None:
    target = tmp_path / "tiers.json"
    target.write_text('{"overrides": []}')

    # Path-style input still works.
    assert load_tier_overrides(target) == []
    # Plain-string input is the regression we fixed: previously
    # `str.expanduser` was called and raised AttributeError.
    assert load_tier_overrides(str(target)) == []


def test_rate_card_load_accepts_str_path(tmp_path: Path) -> None:
    rates = tmp_path / "rates.json"
    rates.write_text("{}")

    # Should not raise; previously `str.expanduser()` was called.
    card_from_path = RateCard.load(rates)
    card_from_str = RateCard.load(str(rates))
    assert card_from_path.pricing_mode == card_from_str.pricing_mode


def test_since_accepts_natural_language_window(tmp_path: Path) -> None:
    session_root, state_db = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "daily",
            "--since",
            "last 7 days",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    # Either ok (table) or non-error code 0. Prior bug: rejected with
    # "Invalid isoformat string" and exit code 2.
    assert result.exit_code == 0, result.output
    assert "Invalid isoformat" not in result.output


def test_natural_language_window_parser_still_works() -> None:
    now = dt.datetime(2026, 5, 14, 12, 0, tzinfo=dt.UTC)
    interval = parse_interval("last 7 days", now)
    assert interval.end == now
    assert interval.start == now - dt.timedelta(days=7)


def test_markdown_overview_total_does_not_triple_count(tmp_path: Path) -> None:
    session_root, state_db = _fixture(tmp_path)

    result = runner.invoke(
        app,
        [
            "overview",
            "--format",
            "markdown",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.startswith("| ")]
    # Header + separator + (>= 3 windows) + Total row.
    total_lines = [line for line in lines if "**Total**" in line]
    assert len(total_lines) == 1, lines
    # The Total cost cell must not exceed the longest single rolling
    # window — that was the symptom of the overlap triple-count bug.
    window_cost_cells: list[float] = []
    total_cost_cell: float | None = None
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "**Total**":
            total_cost_cell = float(cells[6])
        else:
            with contextlib.suppress(ValueError, IndexError):
                window_cost_cells.append(float(cells[6]))
    assert total_cost_cell is not None
    if window_cost_cells:
        assert total_cost_cell <= max(window_cost_cells) + 1e-6, (
            f"Total {total_cost_cell} > max window {max(window_cost_cells)}; "
            "the Markdown Total row appears to be summing overlapping windows again."
        )
