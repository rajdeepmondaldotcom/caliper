from __future__ import annotations

import datetime as dt
from decimal import Decimal
from os import utime

from caliper.aggregation import aggregate_total
from caliper.config import build_options
from caliper.models import VENDOR_AIDER
from caliper.parser import load_usage
from caliper.render import pricing_status


def test_aider_history_cost_line_round_trip(monkeypatch, tmp_path) -> None:
    history = tmp_path / "repo" / ".aider.chat.history.md"
    history.parent.mkdir(parents=True)
    history.write_text("Tokens: 1.5k sent, 250 received. Cost: $0.05 message, $0.20 session.\n")
    event_time = dt.datetime(2026, 5, 12, tzinfo=dt.UTC).timestamp()
    utime(history, (event_time, event_time))
    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_AIDER],
    )

    result = load_usage(options)
    total = aggregate_total(result, options)

    assert len(result.events) == 1
    assert result.events[0].vendor == VENDOR_AIDER
    assert result.events[0].usage.input_tokens == 1500
    assert result.events[0].vendor_reported_cost_usd == Decimal("0.05")
    assert total.costs.cost_usd == Decimal("0.05")
    assert pricing_status(total) == "vendor-reported"


def test_aider_vendor_reported_cost_survives_parse_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CALIPER_CACHE_DIR", str(tmp_path / "cache"))
    history = tmp_path / "repo" / ".aider.chat.history.md"
    history.parent.mkdir(parents=True)
    history.write_text("Tokens: 1.5k sent, 250 received. Cost: $0.05 message, $0.20 session.\n")
    event_time = dt.datetime(2026, 5, 12, tzinfo=dt.UTC).timestamp()
    utime(history, (event_time, event_time))
    monkeypatch.setenv("CALIPER_AIDER_ROOT", str(tmp_path))
    options = build_options(
        since="2026-05-12T00:00:00Z",
        until="2026-05-13T00:00:00Z",
        session_root=tmp_path / "missing-codex",
        vendors=[VENDOR_AIDER],
    )

    warmed = load_usage(options)

    assert warmed.events[0].vendor_reported_cost_usd == Decimal("0.05")

    def explode(*args, **kwargs):  # pragma: no cover - only called on cache miss
        raise AssertionError("Aider history was reparsed instead of read from cache")

    monkeypatch.setattr("caliper.vendors.aider._parse_history", explode)
    cached = load_usage(options)
    total = aggregate_total(cached, options)

    assert cached.events[0].vendor_reported_cost_usd == Decimal("0.05")
    assert total.costs.cost_usd == Decimal("0.05")
