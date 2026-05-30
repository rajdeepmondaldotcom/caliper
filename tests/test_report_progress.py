"""Multi-stage report progress: protocol shape, lifecycle, CLI auto-detect.

Phase A of the HTML + progress overhaul. The new ``ReportProgress`` extends
``ParseProgress`` with stage events (``stage_start``, ``stage_advance``,
``stage_done``). The ``cli_report_progress`` context manager honours
``--progress`` (force on, even on non-TTY / JSON paths) and ``--quiet``
(force off). The auto-detect (TTY + ``--format=table`` + no ``--out``) is
preserved for backward compatibility.

These tests are written before implementation; they encode the contract.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from caliper.progress import NULL_PROGRESS, NullProgress

# ---------------------------------------------------------------------------
# Protocol + NullProgress
# ---------------------------------------------------------------------------


def test_null_progress_stage_methods_return_none() -> None:
    null = NullProgress()
    assert null.stage_start("parse") is None
    assert null.stage_start("parse", total=10) is None
    assert null.stage_advance() is None
    assert null.stage_advance(n=3, detail="reading abc") is None
    assert null.stage_done("parse") is None
    assert null.stage_done("parse", summary="42 files") is None
    assert null.file_progress(Path("/tmp/session.jsonl"), 10, 100) is None
    assert (
        null.usage_footprint(
            total_files=1,
            total_bytes=100,
            vendor_summary="OpenAI Codex 1",
            window_label="Last 7 days",
        )
        is None
    )


def test_null_progress_singleton_has_stage_methods() -> None:
    for name in ("stage_start", "stage_advance", "stage_done"):
        assert hasattr(NULL_PROGRESS, name), f"NULL_PROGRESS missing {name}"


@dataclass
class RecordingReportProgress:
    """Test-side stand-in implementing the new wider Protocol."""

    stages_started: list[tuple[str, int | None]] = field(default_factory=list)
    advances: list[tuple[int, str | None]] = field(default_factory=list)
    stages_done: list[tuple[str, str | None]] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    cached: list[Path] = field(default_factory=list)
    started_total: int | None = None
    finished_count: int = 0

    # ParseProgress (existing)
    def starting(self, total_files: int) -> None:
        self.started_total = total_files

    def file_done(self, path: Path) -> None:
        self.files.append(path)

    def cache_hit(self, path: Path) -> None:
        self.cached.append(path)

    def finished(self) -> None:
        self.finished_count += 1

    # ReportProgress additions
    def stage_start(self, name: str, total: int | None = None) -> None:
        self.stages_started.append((name, total))

    def stage_advance(self, n: int = 1, detail: str | None = None) -> None:
        self.advances.append((n, detail))

    def stage_done(self, name: str, summary: str | None = None) -> None:
        self.stages_done.append((name, summary))


def test_recording_progress_structural_typing_matches_load_usage(tmp_path, monkeypatch):
    """A user-supplied recorder with both old and new methods plugs into
    load_usage() exactly like the existing ParseProgress consumers do."""
    from caliper.config import build_options
    from caliper.parser import load_usage

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-04-01",
        until="2026-05-01",
    )
    progress = RecordingReportProgress()
    load_usage(options, progress=progress)
    assert progress.started_total == 0
    assert progress.finished_count == 1


# ---------------------------------------------------------------------------
# CliReportProgress lifecycle
# ---------------------------------------------------------------------------


def test_cli_report_progress_stage_lifecycle_drives_rich_progress() -> None:
    """``CliReportProgress.stage_start/advance/done`` mutate the underlying
    Rich Progress so users see what stage is running."""
    from rich.console import Console
    from rich.progress import Progress

    from caliper.cli_progress import CliReportProgress

    console = Console(file=io.StringIO(), record=True, width=120, color_system=None)
    with Progress(console=console, transient=False) as rich_progress:
        progress = CliReportProgress(rich_progress)

        progress.stage_start("parse", total=3)
        progress.starting(3)
        progress.file_done(Path("a.jsonl"))
        progress.file_done(Path("b.jsonl"))
        progress.cache_hit(Path("c.jsonl"))
        progress.finished()
        progress.stage_done("parse", summary="3 files (cached 1)")

        progress.stage_start("aggregate")
        progress.stage_advance(detail="totals")
        progress.stage_advance(detail="by-model")
        progress.stage_done("aggregate", summary="2 aggregates")

        progress.stage_start("render")
        progress.stage_done("render", summary="ok")

    transcript = console.export_text()
    # The friendly stage labels surfaced to the user
    assert "Reading sessions" in transcript or "Reading" in transcript
    assert "Aggregating" in transcript
    assert "Rendering" in transcript
    # Stage completion summaries
    assert "3 files (cached 1)" in transcript
    assert "ok" in transcript


def test_cli_report_progress_shows_footprint_and_file_byte_progress() -> None:
    from rich.console import Console
    from rich.progress import Progress

    from caliper.cli_progress import CliReportProgress

    console = Console(file=io.StringIO(), record=True, width=140, color_system=None)
    with Progress(console=console, transient=False) as rich_progress:
        progress = CliReportProgress(rich_progress)
        progress.stage_start("discover", total=1)
        progress.usage_footprint(
            total_files=3_523,
            total_bytes=12_300_000_000,
            vendor_summary="Claude Code 1,890, OpenAI Codex 153",
            window_label="Last 90 days",
            parse_workers=8,
            parse_cache=False,
        )
        progress.stage_done("discover", summary="3,523 files")
        progress.stage_start("parse", total=3_523)
        progress.starting(3_523)
        progress.file_progress(Path("very-large-session.jsonl"), 50_000_000, 100_000_000)

    transcript = console.export_text()
    assert "Caliper will read 3,523 files" in transcript
    assert "Using 8 parser workers" in transcript
    assert "parse-cache=off" in transcript
    assert "ETA appears after the first completed batch" in transcript
    assert "First runs" in transcript
    assert "few minutes" in transcript
    assert "current 50%" in transcript
    assert "very-large-session.jsonl" in transcript


def test_cli_report_progress_preserves_parse_callbacks_for_load_usage(tmp_path, monkeypatch):
    """The Rich-backed report progress still satisfies ParseProgress so
    load_usage callers don't need a second adapter."""
    from rich.console import Console
    from rich.progress import Progress

    from caliper.cli_progress import CliReportProgress
    from caliper.config import build_options
    from caliper.parser import load_usage

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    console = Console(file=io.StringIO(), color_system=None)
    with Progress(console=console, transient=False) as rich_progress:
        progress = CliReportProgress(rich_progress)
        options = build_options(
            session_root=tmp_path / "codex",
            state_db=tmp_path / "state.db",
            codex_config=tmp_path / "codex.toml",
            since="2026-04-01",
            until="2026-05-01",
        )
        # No files, but the callbacks must not crash.
        load_usage(options, progress=progress)


# ---------------------------------------------------------------------------
# Decision matrix: pure-function tests against `_should_show_progress`
# ---------------------------------------------------------------------------


def test_should_show_progress_quiet_wins_over_progress() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="table",
            output=None,
            progress=True,
            quiet=True,
            isatty=True,
        )
        is False
    )


def test_should_show_progress_progress_force_overrides_pipe() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="json",
            output=Path("/tmp/x.json"),
            progress=True,
            quiet=False,
            isatty=False,
        )
        is True
    )


def test_should_show_progress_default_silent_when_format_is_json() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="json",
            output=None,
            progress=False,
            quiet=False,
            isatty=True,
        )
        is False
    )


def test_should_show_progress_default_silent_when_output_path_given() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="table",
            output=Path("/tmp/report.html"),
            progress=False,
            quiet=False,
            isatty=True,
        )
        is False
    )


def test_should_show_progress_default_silent_on_pipe() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="table",
            output=None,
            progress=False,
            quiet=False,
            isatty=False,
        )
        is False
    )


def test_should_show_progress_default_active_on_tty_table() -> None:
    from caliper.cli_progress import _should_show_progress

    assert (
        _should_show_progress(
            output_format="table",
            output=None,
            progress=False,
            quiet=False,
            isatty=True,
        )
        is True
    )


# ---------------------------------------------------------------------------
# Context manager: quiet path returns the null singleton
# ---------------------------------------------------------------------------


def test_cli_report_progress_quiet_returns_null() -> None:
    """``--quiet`` overrides every other signal and yields NULL_PROGRESS."""
    from caliper.cli_progress import cli_report_progress

    with cli_report_progress(
        output_format="table",
        output=None,
        progress=False,
        quiet=True,
    ) as progress:
        assert progress is NULL_PROGRESS


def test_cli_report_progress_force_on_yields_widget() -> None:
    """``--progress`` activates the widget unconditionally."""
    from caliper.cli_progress import CliReportProgress, cli_report_progress

    with cli_report_progress(
        output_format="json",
        output=None,
        progress=True,
        quiet=False,
    ) as progress:
        assert isinstance(progress, CliReportProgress)


def test_cli_report_progress_quiet_overrides_force() -> None:
    """``--quiet`` wins over ``--progress`` when both are set."""
    from caliper.cli_progress import cli_report_progress

    with cli_report_progress(
        output_format="table",
        output=None,
        progress=True,
        quiet=True,
    ) as progress:
        assert progress is NULL_PROGRESS


# ---------------------------------------------------------------------------
# Backwards compatibility with the existing single-task widget
# ---------------------------------------------------------------------------


def test_cli_parse_progress_still_works_after_extension() -> None:
    """The original ``cli_parse_progress`` context manager keeps its
    single-task behaviour so older call sites compile while we migrate.

    In pytest's default capture mode stderr is non-TTY, so the legacy
    helper falls back to NULL_PROGRESS — that is itself the documented
    back-compat behaviour. The test asserts the yielded object satisfies
    the ``ParseProgress`` shape either way.
    """
    from caliper.cli_progress import CliParseProgress, cli_parse_progress

    with cli_parse_progress(output_format="table", output=None) as progress:
        # CliParseProgress is the legacy shape; new shape is a subclass or sibling
        assert hasattr(progress, "starting")
        assert hasattr(progress, "file_done")
        assert hasattr(progress, "cache_hit")
        assert hasattr(progress, "finished")
        # If the existing CliParseProgress now grows stage methods, that's fine
        if isinstance(progress, CliParseProgress):
            for method in ("stage_start", "stage_advance", "stage_done"):
                if hasattr(progress, method):
                    getattr(progress, method)("noop") if method != "stage_advance" else getattr(
                        progress, method
                    )()


# ---------------------------------------------------------------------------
# JSON output stdout byte-cleanness via Typer CLI (smoke)
# ---------------------------------------------------------------------------


def test_cli_progress_flag_keeps_json_stdout_clean(tmp_path, monkeypatch):
    """``caliper daily --format json --progress`` writes valid JSON to
    stdout. Stderr may contain progress lines; stdout must parse cleanly.

    Smoke test: run with an empty session root so there are no events; the
    JSON envelope is still emitted and parseable.
    """
    import json

    from typer.testing import CliRunner

    from caliper.cli import app

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    state_db = tmp_path / "state.db"
    codex_config = tmp_path / "codex.toml"
    codex_config.write_text("")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "daily",
            "--format",
            "json",
            "--session-root",
            str(codex_home),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(codex_config),
            "--since",
            "2026-04-01",
            "--until",
            "2026-05-01",
            "--progress",
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    # stdout must be valid JSON
    json.loads(result.stdout)
    assert "Caliper will read" in (result.stderr or "")
    assert "First runs" not in (result.stderr or "")


def test_cli_quiet_flag_silences_progress(tmp_path, monkeypatch):
    """``--quiet`` suppresses progress on stderr even when --progress is set."""
    from typer.testing import CliRunner

    from caliper.cli import app

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    state_db = tmp_path / "state.db"
    codex_config = tmp_path / "codex.toml"
    codex_config.write_text("")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "daily",
            "--format",
            "json",
            "--session-root",
            str(codex_home),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(codex_config),
            "--since",
            "2026-04-01",
            "--until",
            "2026-05-01",
            "--quiet",
            "--progress",
        ],
    )
    assert result.exit_code == 0
    # Progress widgets typically print "Reading" or stage names. With --quiet
    # winning over --progress, stderr should be empty (or at most warnings).
    stderr_text = result.stderr or ""
    for word in ("Reading", "Aggregating", "Parsing"):
        assert word not in stderr_text, f"--quiet did not suppress stderr: {stderr_text!r}"


def test_root_progress_flag_covers_reports_without_local_progress_option(tmp_path, monkeypatch):
    """Root-level ``--progress`` gives every usage-report command the same
    footprint preflight, even commands that predate the local progress flag."""
    import json

    from typer.testing import CliRunner

    from caliper.cli import app

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    codex_config = tmp_path / "codex.toml"
    codex_config.write_text("")

    result = CliRunner().invoke(
        app,
        [
            "--progress",
            "evidence",
            "--format",
            "json",
            "--session-root",
            str(codex_home),
            "--state-db",
            str(tmp_path / "state.db"),
            "--codex-config",
            str(codex_config),
            "--since",
            "2026-04-01",
            "--until",
            "2026-05-01",
        ],
    )

    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    json.loads(result.stdout)
    assert "Caliper will read" in (result.stderr or "")
