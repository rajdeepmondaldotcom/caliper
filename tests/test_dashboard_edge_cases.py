"""Robustness suite: the dashboard must build + render without crashing on
empty, extreme, hostile, and high-cardinality inputs, across every theme,
rhythm, and interactivity mode.

These guard the "never fails" contract: a real user's logs can be sparse,
huge, or contain HTML/unicode in project and model names. Every combination
below was verified by hand during the 0.0.52 QA pass; this locks it in so a
future refactor can't reintroduce a crash or an XSS leak.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from caliper.config import build_options
from caliper.dashboards.adapter import build_handoff_dashboard
from caliper.dashboards.html import render_dashboard
from caliper.models import LoadResult, ThreadMeta, Usage, UsageEvent

_OPTIONS = build_options(days=90.0)
_GENERATED_AT = dt.datetime(2026, 5, 24, tzinfo=dt.UTC)


def _event(
    i: int = 0,
    *,
    model: str = "claude-opus-4-7",
    tier: str = "standard",
    inp: int = 1000,
    out: int = 200,
    proj: str = "api-server",
) -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 1, 12, i % 59, tzinfo=dt.UTC),
        path=Path("/tmp/session.jsonl"),
        session_id=f"s{i}",
        usage=Usage(input_tokens=inp, output_tokens=out),
        model=model,
        service_tier=tier,
        tier_source="logged",
        thread=ThreadMeta(cwd=proj),
    )


def _result(events: list[UsageEvent]) -> LoadResult:
    return LoadResult(
        events=events,
        duplicates=0,
        tier_sources={},
        plan_types=set(),
        rate_limit_samples=[],
        warnings=[],
    )


_XSS = "<script>alert(1)</script>"

# (name, events) — each is built once and rendered in every mode.
_CASES: list[tuple[str, list[UsageEvent]]] = [
    ("zero_events", []),
    ("single_event", [_event(0)]),
    ("two_events_same_day", [_event(0), _event(1)]),
    ("huge_values", [_event(i, inp=999_999_999, out=888_888_888) for i in range(3)]),
    ("tiny_tokens", [_event(0, inp=0, out=0), _event(1, inp=1, out=0)]),
    (
        "unknown_model_zero_cost",
        [_event(0, model="totally-unknown-xyz"), _event(1, model="totally-unknown-xyz")],
    ),
    (
        "unicode_emoji_names",
        [_event(0, proj="项目-🚀-café", model="модель-x"), _event(1, proj="项目-🚀-café")],
    ),
    ("many_projects", [_event(i, proj=f"proj-{i}") for i in range(1200)]),
    ("many_models", [_event(i, model=f"model-{i % 300}") for i in range(2000)]),
]


@pytest.mark.parametrize("name,events", _CASES, ids=[c[0] for c in _CASES])
@pytest.mark.parametrize("theme", ["dark", "light", "print"])
@pytest.mark.parametrize("rhythm", ["receipt", "terminal"])
def test_build_and_render_never_crashes(name, events, theme, rhythm) -> None:
    dashboard = build_handoff_dashboard(
        _result(events), _OPTIONS, with_deltas=True, generated_at=_GENERATED_AT
    )
    html = render_dashboard(
        dashboard, theme=theme, rhythm=rhythm, interactive=(rhythm == "receipt")
    )
    assert "<title>" in html
    assert "Caliper Dashboard" in html


def test_html_injection_in_names_is_escaped() -> None:
    """Project / model names containing markup must never reach the output
    unescaped — the privacy gate already forbids scripts, but user data is the
    untrusted boundary."""
    events = [
        _event(0, model=_XSS, proj=f"<b>{_XSS}</b>"),
        _event(1, model=_XSS, proj="P&<>'\""),
    ]
    dashboard = build_handoff_dashboard(
        _result(events), _OPTIONS, with_deltas=False, generated_at=_GENERATED_AT
    )
    for theme in ("dark", "light", "print"):
        for rhythm in ("receipt", "terminal"):
            html = render_dashboard(dashboard, theme=theme, rhythm=rhythm)
            assert "<script>alert(1)</script>" not in html
            assert "&lt;script&gt;" in html


def test_zero_events_billboard_is_absent_and_render_is_clean() -> None:
    dashboard = build_handoff_dashboard(
        _result([]), _OPTIONS, with_deltas=True, generated_at=_GENERATED_AT
    )
    assert dashboard.billboard is None
    html = render_dashboard(dashboard, interactive=True)
    assert "<title>" in html
