from __future__ import annotations

import json

from typer.testing import CliRunner

from codex_meter.cli import app

runner = CliRunner()


def test_init_writes_template(tmp_path) -> None:
    target = tmp_path / ".codex-meter.toml"
    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 0, result.output
    text = target.read_text()
    assert "default_days" in text
    assert "[budgets]" in text
    assert "daily_credits" in text


def test_init_refuses_to_overwrite_without_force(tmp_path) -> None:
    target = tmp_path / ".codex-meter.toml"
    target.write_text("preserved = 1\n")
    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 2
    assert "already exists" in result.output
    assert target.read_text() == "preserved = 1\n"


def test_init_with_force_overwrites(tmp_path) -> None:
    target = tmp_path / ".codex-meter.toml"
    target.write_text("old = 1\n")
    result = runner.invoke(app, ["init", "--path", str(target), "--force"])
    assert result.exit_code == 0, result.output
    assert "default_days" in target.read_text()


def test_doctor_table_lists_expected_checks(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    session_root.mkdir()
    state_db = tmp_path / "state.sqlite"
    state_db.write_text("")
    missing_cfg = tmp_path / "missing.toml"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code in {0, 1, 2}
    assert "Python" in result.output
    assert "Session root" in result.output
    assert "Rate card" in result.output


def test_doctor_json_emits_checks_and_worst(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    session_root.mkdir()
    state_db = tmp_path / "state.sqlite"
    state_db.write_text("")
    missing_cfg = tmp_path / "missing.toml"
    result = runner.invoke(
        app,
        [
            "doctor",
            "--format",
            "json",
            "--session-root",
            str(session_root),
            "--state-db",
            str(state_db),
            "--codex-config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code in {0, 1, 2}
    payload = json.loads(result.output)
    assert {"checks", "worst"} <= set(payload.keys())
    labels = {check["label"] for check in payload["checks"]}
    assert {"Python", "Session root", "Rate card", "Clock"} <= labels


def test_doctor_rejects_bad_format(tmp_path) -> None:
    result = runner.invoke(app, ["doctor", "--format", "xml"])
    assert result.exit_code == 2
    assert "table, json" in result.output
