"""Pin the v0.0.7 per-vendor split on every grouped report.

When the user is on a TTY with the classic Rich table path and more
than one tool vendor is present in the window, every grouped report
must emit one Rich table per vendor. The implementation lives in
``caliper.cli._render_grouped_per_vendor`` and
``caliper.cli._render_overview_per_vendor``.

These tests guard against silent regression. They construct a fake
LoadResult that carries two vendors and assert the helper emits the
expected per-vendor headers.
"""

from __future__ import annotations

import datetime as dt
import io
from contextlib import redirect_stdout
from pathlib import Path

from caliper.aggregation import aggregate_daily, aggregate_weekly
from caliper.cli import _render_grouped_per_vendor, _render_overview_per_vendor
from caliper.config import build_options
from caliper.models import (
    VENDOR_CLAUDE_CODE,
    VENDOR_OPENAI_CODEX,
    LoadResult,
    ThreadMeta,
    Usage,
    UsageEvent,
)
from caliper.pricing import load_rate_card


def _event(*, vendor: str, when: dt.datetime, tokens: int = 1000) -> UsageEvent:
    return UsageEvent(
        timestamp=when,
        path=Path(f"/tmp/{vendor}.jsonl"),
        session_id=f"{vendor}-session",
        usage=Usage(
            input_tokens=tokens, output_tokens=tokens // 10, total_tokens=tokens + tokens // 10
        ),
        model="claude-opus-4.7" if vendor == VENDOR_CLAUDE_CODE else "gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project"),
        model_source="turn_context",
        plan_type="pro",
        vendor=vendor,
    )


def _two_vendor_result() -> LoadResult:
    now = dt.datetime.now(tz=dt.UTC)
    events = [
        _event(vendor=VENDOR_CLAUDE_CODE, when=now - dt.timedelta(days=1)),
        _event(vendor=VENDOR_CLAUDE_CODE, when=now - dt.timedelta(days=2)),
        _event(vendor=VENDOR_OPENAI_CODEX, when=now - dt.timedelta(days=1)),
    ]
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={"logged": 3},
        plan_types={"pro"},
        credit_samples=[],
        warnings=[],
    )


def _capture(fn) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        fn()
    return buffer.getvalue()


def test_grouped_per_vendor_split_daily_emits_one_table_per_vendor(tmp_path):
    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "cfg.toml",
        days=7,
    )
    result = _two_vendor_result()
    text = _capture(lambda: _render_grouped_per_vendor("daily", aggregate_daily, result, options))

    # Header line names tool vendors and event count.
    assert "by tool vendor" in text
    # Two vendors -> two per-vendor titles.
    assert text.count("Caliper - Daily  (Claude Code,") == 1
    assert text.count("Caliper - Daily  (OpenAI Codex,") == 1
    # Holistic split means no combined table.
    assert "All vendors" not in text


def test_grouped_per_vendor_split_weekly_emits_one_table_per_vendor(tmp_path):
    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "cfg.toml",
        days=30,
    )
    result = _two_vendor_result()
    text = _capture(lambda: _render_grouped_per_vendor("weekly", aggregate_weekly, result, options))

    assert "Caliper - Weekly  (Claude Code," in text
    assert "Caliper - Weekly  (OpenAI Codex," in text


def test_overview_per_vendor_split_emits_one_table_per_vendor(tmp_path):
    from caliper.aggregation import aggregate_overview_windows

    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "cfg.toml",
        days=90,
    )
    result = _two_vendor_result()
    rate_card = load_rate_card(options)
    now = dt.datetime.now(tz=dt.UTC)
    windows = [(f"Last {n} days", now - dt.timedelta(days=n)) for n in (7, 30, 90)]
    rows, total = aggregate_overview_windows(
        result, options, windows, rate_card=rate_card, detailed=False
    )

    text = _capture(
        lambda: _render_overview_per_vendor(result, options, windows, rate_card, total, rows)
    )

    assert "Caliper - Overview, by tool vendor" in text
    assert "Claude Code" in text
    assert "OpenAI Codex" in text


def test_single_vendor_skips_per_vendor_path(tmp_path):
    """One vendor in window -> classic single-table render. Not the split."""
    from caliper.cli import _has_multiple_tool_vendors

    now = dt.datetime.now(tz=dt.UTC)
    single = LoadResult(
        events=[_event(vendor=VENDOR_CLAUDE_CODE, when=now - dt.timedelta(days=1))],
        duplicates=0,
        tier_sources={"logged": 1},
        plan_types={"pro"},
        credit_samples=[],
        warnings=[],
    )
    assert _has_multiple_tool_vendors(single) is False
