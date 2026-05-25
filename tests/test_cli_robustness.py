"""Regression tests for CLI robustness fixes.

These pin the v-next hardening: clean errors instead of tracebacks/hangs for
unwritable --output, non-interactive `live`/`tui`, a lone future --since, and a
too-small --width.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from caliper.cli import app
from caliper.render import write_output
from typer.testing import CliRunner

runner = CliRunner()


def test_write_output_to_directory_errors_cleanly() -> None:
    # Writing to a directory used to raise a raw IsADirectoryError traceback.
    with pytest.raises(typer.Exit) as exc:
        write_output("hello", Path("/tmp"))
    assert exc.value.exit_code == 2


def test_live_requires_tty_in_non_interactive() -> None:
    # CliRunner is non-interactive; `live` without --max-ticks must not hang.
    result = runner.invoke(app, ["live"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.output


def test_tui_requires_tty_even_with_demo() -> None:
    result = runner.invoke(app, ["tui", "--demo"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.output


def test_future_since_gives_clear_message() -> None:
    result = runner.invoke(app, ["overview", "--since", "2999-01-01"])
    assert result.exit_code == 2
    assert "in the future" in result.output


def test_overview_to_directory_errors_cleanly(tmp_path) -> None:
    # End-to-end: a directory target surfaces a one-line error, not a traceback.
    result = runner.invoke(
        app,
        [
            "overview",
            "--since",
            "2999-01-02",
            "--until",
            "2999-01-09",
            "--session-root",
            str(tmp_path / "empty"),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "could not write" in result.output


@pytest.mark.parametrize("value", ["inf", "nan", "-1", "0"])
def test_non_finite_days_errors_cleanly(value: str) -> None:
    # `--days inf` used to raise an uncaught OverflowError traceback.
    result = runner.invoke(app, ["overview", "--days", value])
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "finite number greater than 0" in result.output


def test_tiny_width_is_clamped(tmp_path) -> None:
    # --width 1 used to emit one character per line; it must be floored.
    result = runner.invoke(
        app,
        [
            "overview",
            "--since",
            "2999-01-02",
            "--until",
            "2999-01-09",
            "--session-root",
            str(tmp_path / "empty"),
            "--width",
            "1",
        ],
    )
    assert result.exit_code == 0
    # No single-character-per-line spillage: the title stays on one line.
    assert "Caliper" in result.output
