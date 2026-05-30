from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper.cli import app

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, Path]:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-launch.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="fast", cwd="/tmp/project-alpha"),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 600,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    return session_root, state_db, (now + dt.timedelta(seconds=1)).isoformat(), tmp_path / "x.toml"


def _args(tmp_path: Path, *, window: bool = False) -> list[str]:
    session_root, state_db, until, cfg = _fixture(tmp_path)
    args = [
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(cfg),
    ]
    if window:
        args = ["--days", "7", "--until", until, *args]
    return args


def test_version_output_does_not_report_caller_repo_sha() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert "rates checked" in result.output
    assert "commit " not in result.output


def test_json_redacts_absolute_paths_by_default(tmp_path: Path) -> None:
    result = runner.invoke(app, ["overview", *_args(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metadata"]["path_redaction"] == "redacted"
    assert str(tmp_path) not in result.output
    assert "/tmp/project-alpha" not in result.output
    assert "https://github.com/example/project-alpha" not in result.output
    assert "2026-05-12T00-00-00-launch" not in result.output
    assert "<redacted-path>" in result.output
    assert "<redacted-repo>" in result.output
    assert "<redacted-session>" in result.output


def test_json_show_paths_restores_absolute_paths(tmp_path: Path) -> None:
    result = runner.invoke(app, ["overview", *_args(tmp_path), "--show-paths", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metadata"]["path_redaction"] == "visible"
    assert str(tmp_path) in result.output
    assert "/tmp/project-alpha" in result.output
    assert "https://github.com/example/project-alpha" in result.output
    assert "2026-05-12T00-00-00-launch" in result.output


def test_human_overview_redacts_session_root_by_default(tmp_path: Path) -> None:
    args = _args(tmp_path)
    result = runner.invoke(app, ["overview", *args, "--width", "120"])

    assert result.exit_code == 0, result.output
    assert "Session root: <redacted-path>" in result.output
    assert str(tmp_path) not in result.output

    visible = runner.invoke(app, ["overview", *args, "--show-paths", "--width", "120"])
    assert visible.exit_code == 0, visible.output
    assert "Session root:" in visible.output
    assert "sessions" in visible.output
    assert "<redacted-path>" not in visible.output


def test_overview_accepts_scoped_days_window(tmp_path: Path) -> None:
    result = runner.invoke(app, ["overview", *_args(tmp_path, window=True), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["label"] for row in payload["breakdowns"]] == ["Last 7 days"]
    assert payload["totals"]["total_tokens"] == 1100


def test_empty_overview_is_onboarding_not_zero_table(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(
        app,
        [
            "overview",
            "--session-root",
            str(empty),
            "--state-db",
            str(tmp_path / "missing.sqlite"),
            "--codex-config",
            str(tmp_path / "missing.toml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "No AI coding usage logs found" in result.output
    assert "caliper doctor" in result.output
    assert "Last 7 days" not in result.output
    assert str(tmp_path) not in result.output

    visible = runner.invoke(
        app,
        [
            "overview",
            "--session-root",
            str(empty),
            "--state-db",
            str(tmp_path / "missing.sqlite"),
            "--codex-config",
            str(tmp_path / "missing.toml"),
            "--show-paths",
        ],
    )
    assert visible.exit_code == 0, visible.output
    assert str(empty) in visible.output


def test_insight_actions_are_copy_pasteable_commands(tmp_path: Path) -> None:
    result = runner.invoke(app, ["insights", *_args(tmp_path, window=True), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert "<cheaper>" not in result.output
    assert " against " not in result.output
    assert "caliper advise --strict" in result.output


def test_statusline_json_redacts_paths_and_session_identity_by_default(tmp_path: Path) -> None:
    result = runner.invoke(app, ["statusline", *_args(tmp_path, window=True), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert "/tmp/project-alpha" not in result.output
    assert "2026-05-12T00-00-00-launch" not in result.output
    assert "<redacted-path>" in result.output
    assert "<redacted-session>" in result.output


def test_release_smoke_scripts_isolate_external_vendor_roots() -> None:
    root = Path(__file__).parent.parent
    for name in ("release-smoke.sh", "live-release-smoke.sh"):
        text = (root / "scripts" / name).read_text()
        assert "CLAUDE_CONFIG_DIR" in text
