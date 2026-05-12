from __future__ import annotations

import datetime as dt

import pytest

from codex_meter.config import build_options


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


def test_build_options_rejects_invalid_choices(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('service_tier = "turbo"\n')

    with pytest.raises(ValueError, match="--service-tier"):
        build_options(days=1, config=config)
