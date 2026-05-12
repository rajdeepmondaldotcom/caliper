from __future__ import annotations

import datetime as dt

from codex_meter.config import build_options
from codex_meter.parser import load_usage

from .conftest import make_state_db, token_event, turn_context, write_session


def test_load_usage_streams_events_dedupes_and_joins_state(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 700,
        "output_tokens": 100,
        "reasoning_output_tokens": 40,
        "total_tokens": 1100,
    }
    event = token_event(now, usage)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [turn_context(model="gpt-5.5", service_tier="fast"), event, event],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.events) == 1
    assert result.duplicates == 1
    assert result.events[0].thread.cwd == "/tmp/project-alpha"
    assert result.events[0].model == "gpt-5.5"
    assert result.events[0].service_tier == "fast"
    assert result.tier_sources == {"logged": 1}
    assert result.plan_types == {"pro"}


def test_current_config_tier_is_labeled_as_inferred(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "output_tokens": 100,
        "total_tokens": 1100,
    }
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [token_event(now, usage)],
    )
    config = tmp_path / "config.toml"
    config.write_text('service_tier = "fast"\n')

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=config,
    )
    result = load_usage(options)

    assert result.events[0].service_tier == "fast"
    assert result.events[0].tier_source == "current-config"
