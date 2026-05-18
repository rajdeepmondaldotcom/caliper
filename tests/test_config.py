from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from caliper.config import build_options


def test_cli_paths_override_config_paths(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
session_root = "{tmp_path / "configured-sessions"}"
state_db = "{tmp_path / "configured.sqlite"}"
codex_config = "{tmp_path / "configured.toml"}"
timezone = "UTC"
service_tier = "fast"
unknown_service_tier = "standard"
pricing_mode = "flat"
default_model = "gpt-5.4"
top_threads = 3
"""
    )
    until = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)

    options = build_options(
        days=1,
        until=until.isoformat(),
        session_root=tmp_path / "cli-sessions",
        state_db=tmp_path / "cli.sqlite",
        codex_config=tmp_path / "cli.toml",
        config=config,
    )

    assert options.session_root == tmp_path / "cli-sessions"
    assert options.state_db == tmp_path / "cli.sqlite"
    assert options.config_path == tmp_path / "cli.toml"
    assert options.timezone == "UTC"
    assert options.service_tier == "fast"
    assert options.unknown_service_tier == "standard"
    assert options.pricing_mode == "flat"
    assert options.default_model == "gpt-5.4"
    assert options.top_threads == 3


def test_codex_home_sets_default_codex_paths(monkeypatch, tmp_path) -> None:
    codex_home = tmp_path / "custom-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    until = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)

    options = build_options(days=1, until=until.isoformat(), config=tmp_path / "missing.toml")

    assert options.session_root == codex_home / "sessions"
    assert options.state_db == codex_home / "state_5.sqlite"
    assert options.config_path == codex_home / "config.toml"


def test_blank_codex_home_is_ignored(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_HOME", "   ")
    until = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)

    options = build_options(days=1, until=until.isoformat(), config=tmp_path / "missing.toml")

    assert options.session_root == Path.home() / ".codex" / "sessions"
    assert options.state_db == Path.home() / ".codex" / "state_5.sqlite"
    assert options.config_path == Path.home() / ".codex" / "config.toml"


def test_date_only_windows_are_local_midnight_and_until_inclusive(tmp_path) -> None:
    options = build_options(
        since="20260512",
        until="20260512",
        timezone="Asia/Kolkata",
        config=tmp_path / "missing.toml",
    )

    assert options.start.astimezone(dt.UTC) == dt.datetime(2026, 5, 11, 18, 30, tzinfo=dt.UTC)
    assert options.end.astimezone(dt.UTC) == dt.datetime(2026, 5, 12, 18, 30, tzinfo=dt.UTC)


def test_build_options_rejects_invalid_choices(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('service_tier = "turbo"\n')

    with pytest.raises(ValueError, match="--service-tier"):
        build_options(days=1, config=config)


def test_pricing_source_is_case_insensitive(tmp_path) -> None:
    options = build_options(
        days=1,
        pricing_source=" LiteLLM ",
        config=tmp_path / "missing.toml",
    )

    assert options.pricing_source == "litellm"


def test_no_dedupe_option_is_ignored(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("no_dedupe = true\n")

    options = build_options(days=1, no_dedupe=True, config=config)

    assert options.dedupe is True
