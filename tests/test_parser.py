from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing

from caliper.config import build_options
from caliper.parser import load_usage

from .conftest import (
    make_state_db,
    rate_limit_only_event,
    token_event,
    total_token_event,
    turn_context,
    user_message,
    write_session,
)


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
    assert result.events[0].model_source == "turn_context"
    assert result.events[0].model_is_fallback is False
    assert result.events[0].service_tier == "fast"
    assert result.tier_sources == {"logged": 1}
    assert result.plan_types == {"pro"}
    assert result.events[0].limit_id == "codex"


def test_parallel_codex_parse_matches_sequential_parse(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    base = dt.datetime(2026, 5, 12, tzinfo=dt.UTC)
    for index in range(300):
        write_session(
            session_root,
            f"rollout-2026-05-12T00-00-{index:03d}-parallel.jsonl",
            [
                turn_context(model="gpt-5.5", service_tier="standard"),
                token_event(
                    base + dt.timedelta(seconds=index),
                    {"input_tokens": index + 1, "output_tokens": 1, "total_tokens": index + 2},
                ),
            ],
        )
    common = dict(
        since=(base - dt.timedelta(seconds=1)).isoformat(),
        until=(base + dt.timedelta(minutes=10)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing.toml",
        vendors=["openai-codex"],
        no_parse_cache=True,
    )

    sequential = load_usage(build_options(**common, parse_workers=1))
    parallel = load_usage(build_options(**common, parse_workers=2))

    def event_key(event):
        return (
            event.session_id,
            event.timestamp,
            event.usage.input_tokens,
            event.usage.output_tokens,
            event.model,
            event.service_tier,
        )

    assert [event_key(event) for event in parallel.events] == [
        event_key(event) for event in sequential.events
    ]
    assert len(parallel.rate_limit_samples) == len(sequential.rate_limit_samples) == 300
    assert parallel.vendor_stats == sequential.vendor_stats


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


def test_current_config_tier_reads_fast_mode_feature_flag(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            )
        ],
    )
    config = tmp_path / "config.toml"
    config.write_text("[features]\nfast_mode = true\n")

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


def test_total_token_usage_fallback_uses_session_deltas(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-total-only.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            total_token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 300,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 40,
                    "total_tokens": 1100,
                },
            ),
            total_token_event(
                now + dt.timedelta(seconds=1),
                {
                    "input_tokens": 1600,
                    "cached_input_tokens": 500,
                    "output_tokens": 250,
                    "reasoning_output_tokens": 70,
                    "total_tokens": 1850,
                },
            ),
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=2)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert [event.usage.input_tokens for event in result.events] == [1000, 600]
    assert [event.usage.output_tokens for event in result.events] == [100, 150]
    assert {event.usage_source for event in result.events} == {"total_delta"}
    assert result.events[0].model_context_window == 258400


def test_total_token_usage_fallback_uses_prior_out_of_window_total(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-window.jsonl",
        [
            total_token_event(
                now - dt.timedelta(hours=2),
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
            total_token_event(
                now,
                {
                    "input_tokens": 1400,
                    "cached_input_tokens": 0,
                    "output_tokens": 125,
                    "total_tokens": 1525,
                },
            ),
        ],
    )

    options = build_options(
        since=(now - dt.timedelta(minutes=1)).isoformat(),
        until=(now + dt.timedelta(minutes=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.events) == 1
    assert result.events[0].usage.input_tokens == 400
    assert result.events[0].usage.output_tokens == 25


def test_rate_limit_only_event_is_kept_for_limits_not_totals(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-limits.jsonl",
        [rate_limit_only_event(now)],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert result.events == []
    assert len(result.rate_limit_samples) == 1
    assert result.rate_limit_samples[0].primary_window_minutes == 300
    assert result.rate_limit_samples[0].limit_id == "codex"
    assert result.plan_types == {"pro"}


def test_rate_limit_samples_preserve_model_specific_limit_bucket(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-limits-buckets.jsonl",
        [
            rate_limit_only_event(
                now,
                limit_id="codex_bengalfox",
                limit_name="GPT-5.3-Codex-Spark",
            )
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert result.rate_limit_samples[0].limit_id == "codex_bengalfox"
    assert result.rate_limit_samples[0].limit_name == "GPT-5.3-Codex-Spark"


def test_dedupe_keeps_identical_usage_from_different_sessions(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "output_tokens": 100,
        "total_tokens": 1100,
    }
    write_session(session_root, "rollout-2026-05-12T00-00-00-a.jsonl", [token_event(now, usage)])
    write_session(session_root, "rollout-2026-05-12T00-00-00-b.jsonl", [token_event(now, usage)])

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.events) == 2
    assert result.duplicates == 0


def test_dedupe_keeps_identical_usage_from_same_session_at_different_times(tmp_path) -> None:
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
        "rollout-2026-05-12T00-00-00-real-usage.jsonl",
        [
            turn_context(cwd="/tmp/project-alpha"),
            token_event(now, usage),
            token_event(now + dt.timedelta(seconds=1), usage),
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=2)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.events) == 2
    assert result.duplicates == 0


def test_dedupe_collapses_copied_codex_records_with_same_session_identity(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "output_tokens": 100,
        "total_tokens": 1100,
    }
    session_name = "rollout-2026-05-12T00-00-00-copy.jsonl"
    events = [turn_context(cwd="/tmp/project-alpha"), token_event(now, usage)]
    first = write_session(session_root, session_name, events)
    copied = session_root / "2026" / "05" / "13" / session_name
    copied.parent.mkdir(parents=True)
    copied.write_text(first.read_text())

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.events) == 1
    assert result.duplicates == 1
    assert result.dedupe_stats == {"semantic_usage": 1}


def test_rate_limit_samples_are_deduped(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    sample = rate_limit_only_event(now)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-limits-dupe.jsonl",
        [sample, sample],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert len(result.rate_limit_samples) == 1
    assert result.rate_limit_sample_duplicates == 1
    assert result.rate_limit_sample_dedupe_stats == {"rate_limit_sample": 1}


def test_state_db_loader_tolerates_missing_optional_columns(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-state.jsonl",
        [
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            )
        ],
    )
    state_db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(state_db)) as conn, conn:
        conn.execute("create table threads (rollout_path text, cwd text)")
        conn.execute("insert into threads values (?, ?)", (str(session_path), "/tmp/project-beta"))

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert result.events[0].thread.cwd == "/tmp/project-beta"
    assert result.events[0].thread.title == ""


def test_turn_context_cwd_tracks_workspace_without_state_db(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-context-cwd.jsonl",
        [
            turn_context(cwd="/tmp/workspace-from-jsonl", service_tier="standard"),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert result.events[0].thread.cwd == "/tmp/workspace-from-jsonl"
    assert result.events[0].model_source == "turn_context"


def test_state_db_loader_reads_extended_thread_metadata(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-extended-state.jsonl",
        [
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            )
        ],
    )
    state_db = tmp_path / "state.sqlite"
    with closing(sqlite3.connect(state_db)) as conn, conn:
        conn.execute(
            """
            create table threads (
                rollout_path text,
                cwd text,
                git_branch text,
                git_origin_url text,
                git_sha text,
                model text,
                reasoning_effort text,
                source text,
                model_provider text,
                cli_version text,
                agent_role text,
                agent_nickname text,
                memory_mode text,
                thread_source text
            )
            """
        )
        conn.execute(
            """
            insert into threads values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(session_path),
                "/tmp/project-gamma",
                "feature/granular",
                "https://github.com/example/project-gamma",
                "abc123",
                "gpt-5.5",
                "high",
                "cli",
                "openai",
                "0.120.0",
                "worker",
                "Builder",
                "enabled",
                "local",
            ),
        )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)
    thread = result.events[0].thread

    assert thread.cwd == "/tmp/project-gamma"
    assert thread.git_branch == "feature/granular"
    assert thread.git_origin_url == "https://github.com/example/project-gamma"
    assert thread.git_sha == "abc123"
    assert thread.source == "cli"
    assert thread.model_provider == "openai"
    assert thread.cli_version == "0.120.0"
    assert thread.agent_role == "worker"
    assert thread.agent_nickname == "Builder"
    assert thread.memory_mode == "enabled"
    assert thread.thread_source == "local"
    assert result.events[0].model_source == "state-db"
    assert result.events[0].model_is_fallback is False


def test_missing_model_uses_default_model_with_fallback_flag(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-missing-model.jsonl",
        [
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            )
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
        default_model="gpt-5.4",
    )
    result = load_usage(options)

    assert result.events[0].model == "gpt-5.4"
    assert result.events[0].model_source == "default"
    assert result.events[0].model_is_fallback is True


def test_slash_fast_commands_update_service_tier(tmp_path) -> None:
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
        "rollout-2026-05-12T00-00-00-fast.jsonl",
        [
            user_message("/fast on"),
            token_event(now, usage),
            user_message("/fast off"),
            token_event(now + dt.timedelta(seconds=1), usage),
        ],
    )

    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=2)).isoformat(),
        session_root=session_root,
        state_db=tmp_path / "missing.sqlite",
        codex_config=tmp_path / "missing.toml",
    )
    result = load_usage(options)

    assert [event.service_tier for event in result.events] == ["fast", "standard"]
    assert result.tier_sources == {"logged": 2}
