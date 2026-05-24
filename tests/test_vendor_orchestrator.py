from __future__ import annotations

import datetime as dt

from caliper.config import build_options
from caliper.models import (
    VENDOR_AIDER,
    VENDOR_CLAUDE_CODE,
    VENDOR_CURSOR,
    VENDOR_OPENAI_CODEX,
    LoadResult,
)
from caliper.parser import load_usage
from caliper.vendors import VENDORS, discover_usage_files, enabled_vendors, vendor_file_count

from .conftest import make_state_db, token_event, turn_context, write_session


def test_codex_vendor_is_registered() -> None:
    assert VENDOR_OPENAI_CODEX in VENDORS
    assert VENDORS[VENDOR_OPENAI_CODEX].schema_version == "1"


def test_enabled_vendors_respects_all_default(tmp_path) -> None:
    options = build_options(session_root=tmp_path / "missing")

    assert [vendor.id for vendor in enabled_vendors(options)] == [
        VENDOR_AIDER,
        VENDOR_CLAUDE_CODE,
        VENDOR_CURSOR,
        VENDOR_OPENAI_CODEX,
    ]


def test_load_usage_routes_through_registered_codex_parser(tmp_path) -> None:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-vendor.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    make_state_db(state_db, session_path)
    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
        vendors=[VENDOR_OPENAI_CODEX],
    )

    result = load_usage(options)

    assert isinstance(result, LoadResult)
    assert len(result.events) == 1
    assert result.events[0].vendor == VENDOR_OPENAI_CODEX


def test_discovery_dedupes_exact_duplicate_paths(monkeypatch, tmp_path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_text("{}\n")

    class DuplicateParser:
        id = "duplicate-test"
        label = "Duplicate Test"
        schema_version = "1"

        def discover(self, _options):
            return [path, path]

        def parse(self, _options, progress=None, paths=None):
            raise AssertionError("parse should not run during discovery")

    monkeypatch.setitem(VENDORS, "duplicate-test", DuplicateParser())
    options = build_options(
        days=1,
        session_root=tmp_path / "missing",
        vendors=["duplicate-test"],
    )

    discovery = discover_usage_files(options)

    assert discovery.total_files == 1
    assert discovery.total_bytes == path.stat().st_size
    assert vendor_file_count(options) == 1
