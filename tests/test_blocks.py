from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from caliper.blocks import (
    UsageBlock,
    block_payload,
    build_blocks,
    calculate_burn_rate,
    filter_recent_blocks,
    project_block_usage,
)
from caliper.config import build_options
from caliper.models import LoadResult, ThreadMeta, Usage, UsageEvent
from caliper.pricing import RateCard


def _event(timestamp: dt.datetime, total: int = 1100) -> UsageEvent:
    return UsageEvent(
        timestamp=timestamp,
        path=Path("/tmp/session.jsonl"),
        session_id="session",
        usage=Usage(
            input_tokens=1000,
            cached_input_tokens=500,
            output_tokens=100,
            total_tokens=total,
        ),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/project"),
        model_source="turn_context",
    )


def _options(tmp_path):
    return build_options(
        days=1,
        session_root=tmp_path / "missing-sessions",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
    )


def test_build_blocks_inserts_gap_and_payload(tmp_path) -> None:
    now = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)
    events = [
        _event(now - dt.timedelta(hours=8)),
        _event(now - dt.timedelta(hours=1), total=900),
    ]
    result = LoadResult(
        events=events,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        credit_samples=[],
        warnings=[],
    )

    blocks = build_blocks(result, _options(tmp_path), RateCard.load(None), now=now)
    payloads = [block_payload(block, token_limit=2_000) for block in blocks]

    assert len(blocks) == 3
    assert blocks[1].is_gap is True
    assert payloads[0]["totalTokens"] == 1100
    assert payloads[0]["tokenLimitStatus"]["percent"] == pytest.approx(55)


def test_burn_rate_projection_and_recent_filter() -> None:
    now = dt.datetime.now(tz=dt.UTC)
    block = UsageBlock(
        id="active",
        start_time=now - dt.timedelta(minutes=30),
        end_time=now + dt.timedelta(hours=1),
        actual_end_time=now,
        is_active=True,
        is_gap=False,
        events=(_event(now - dt.timedelta(minutes=30)), _event(now)),
        input_tokens=1000,
        output_tokens=100,
        cache_creation_tokens=0,
        cache_read_tokens=500,
        total_tokens=1100,
        api_dollars=Decimal("1.00"),
        models=("gpt-5.5",),
    )
    old = UsageBlock(
        **{
            **block.__dict__,
            "id": "old",
            "start_time": now - dt.timedelta(days=10),
            "is_active": False,
        }
    )

    burn = calculate_burn_rate(block)
    projection = project_block_usage(block, burn)
    recent = filter_recent_blocks([old, block], now=now)

    assert burn and burn["tokensPerMinute"] > 0
    assert projection and projection["totalTokens"] >= block.total_tokens
    assert recent == [block]
    assert calculate_burn_rate(old) is not None
