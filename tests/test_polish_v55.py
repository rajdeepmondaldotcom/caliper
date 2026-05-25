"""Regression tests for the 0.0.55 critical-user polish pass.

Covers the verified fixes from the persona QA sweep:

* CLI: ``-f compat-json`` fails cleanly where unsupported (no silent table
  fallback) but still works on the session-style commands; the repeated Cursor
  token-coverage warning is condensed on the analytical table; a bad ``--since``
  value suggests parseable examples; ``-h`` is a help alias.
* Dashboard: a mobile jump-to-section nav, glossary affordances on jargon, a
  show-the-math chevron, and the verdict strip demoted under a present billboard.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from caliper import render as render_module
from caliper.aggregation import aggregate_total
from caliper.cli import app
from caliper.dashboards.html import _verdict_block, render_dashboard
from caliper.dashboards.sample_data import sample_dashboard
from caliper.evidence import parser_issue_warning
from caliper.models import (
    LoadResult,
    ParserIssue,
    ThreadMeta,
    Usage,
    UsageEvent,
)
from caliper.pricing import RateCard

from .conftest import make_state_db, token_event, turn_context, write_session

runner = CliRunner()


# --------------------------------------------------------------------------- #
# B1 — compat-json must not silently fall back to a table
# --------------------------------------------------------------------------- #


def test_overview_rejects_compat_json_cleanly() -> None:
    # Used to print the human table (breaking scripts that asked for JSON).
    result = runner.invoke(app, ["--format", "compat-json", "overview"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "compat-json" in result.stderr
    assert "session-style commands" in result.stderr


def _codex_args(tmp_path) -> list:
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-test.jsonl",
        [
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(
                now,
                {
                    "input_tokens": 1000,
                    "cached_input_tokens": 500,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                },
            ),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    state_db.unlink(missing_ok=True)
    make_state_db(state_db, session_path)
    return [
        "--days",
        "30",
        "--until",
        (now + dt.timedelta(seconds=1)).isoformat(),
        "--session-root",
        str(session_root),
        "--state-db",
        str(state_db),
        "--codex-config",
        str(tmp_path / "missing.toml"),
    ]


def test_grouped_still_supports_compat_json(tmp_path) -> None:
    # The session-style commands genuinely implement compat-json; keep it valid.
    result = runner.invoke(app, ["--format", "compat-json", *_codex_args(tmp_path), "daily"])
    assert result.exit_code == 0, result.output
    json.loads(result.output)  # raises if it ever regresses to a table


# --------------------------------------------------------------------------- #
# B2 — Cursor coverage warning condensed on the table, kept in the envelope
# --------------------------------------------------------------------------- #


def _cursor_event() -> UsageEvent:
    return UsageEvent(
        timestamp=dt.datetime(2026, 5, 13, 11, 30, tzinfo=dt.UTC),
        path=Path("/tmp/cursor.jsonl"),
        session_id="s1",
        usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        model="gpt-5.5",
        service_tier="standard",
        tier_source="logged",
        thread=ThreadMeta(cwd="/tmp/p", title="t"),
        model_source="logged",
        plan_type="pro",
        vendor="cursor",
    )


def _options(tmp_path):
    from caliper.config import build_options

    now = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)
    return build_options(
        days=1,
        until=now.isoformat(),
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "missing.toml",
    )


def test_cursor_coverage_warning_condensed_on_table(tmp_path) -> None:
    issue = ParserIssue(
        vendor="cursor",
        kind="unsupported:no_token_usage",
        message="Cursor files have no per-event token counts",
        count=42,
    )
    verbose = parser_issue_warning(issue)
    result = LoadResult(
        events=[_cursor_event()],
        duplicates=0,
        tier_sources={"logged": 1},
        plan_types={"pro"},
        rate_limit_samples=[],
        warnings=[verbose, "unrelated warning"],
        parser_issues=[issue],
    )
    options = _options(tmp_path)
    total = aggregate_total(result, options, rate_card=RateCard.load(None, "model"))
    text = render_module.render_table(
        result, options, [total], "Overview", rate_card=RateCard.load(None, "model")
    )
    # The verbose per-file form is gone; a single short pointer replaces it.
    assert "run `caliper doctor` for examples" not in text
    assert "limited token coverage" in text
    # Unrelated warnings still surface verbatim.
    assert "unrelated warning" in text
    # The raw warning is untouched in the structured result (envelope/doctor).
    assert verbose in result.warnings


# --------------------------------------------------------------------------- #
# B3 — bad --since suggests parseable examples
# --------------------------------------------------------------------------- #


def test_bad_since_error_suggests_examples() -> None:
    result = runner.invoke(app, ["overview", "--since", "notadate"])
    assert result.exit_code == 2
    assert "Try an ISO date" in result.output
    assert "last 7 days" in result.output


def test_since_examples_actually_parse(tmp_path) -> None:
    # The examples we advertise must themselves resolve, or the help lies.
    for value in ("2026-05-20", "last 7 days", "yesterday"):
        result = runner.invoke(
            app, ["overview", "--since", value, "--until", "2026-05-24", *_codex_args(tmp_path)]
        )
        assert result.exit_code == 0, f"{value!r}: {result.output}"


# --------------------------------------------------------------------------- #
# B4 — -h help alias at every level
# --------------------------------------------------------------------------- #


def test_help_shorthand_everywhere() -> None:
    for args in (["-h"], ["overview", "-h"], ["rates", "-h"], ["rates", "show", "-h"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args}: {result.output}"
        assert "Usage:" in result.output


# --------------------------------------------------------------------------- #
# A2/A3/A4/A1 — dashboard affordances
# --------------------------------------------------------------------------- #


def test_mobile_nav_renders_with_matching_toc_targets() -> None:
    d = sample_dashboard()
    html = render_dashboard(d)
    assert 'class="cal-mobile-nav"' in html
    assert 'class="cal-mobile-nav-tab"' in html
    # Tabs reuse the scroll-spy anchors the desktop TOC already exposes.
    assert "data-toc-target" in html


def test_glossary_affordance_present_and_terms_intact() -> None:
    html = render_dashboard(sample_dashboard())
    assert 'class="cal-gloss"' in html
    # Wrapping must not destroy the literal labels other code/tests rely on.
    assert "Tier source" in html
    assert "Cohort" in html


def test_show_the_math_has_chevron() -> None:
    html = render_dashboard(sample_dashboard())
    assert 'class="cal-card-chev"' in html
    assert "show the math" in html


def test_verdict_demoted_when_billboard_present() -> None:
    d = sample_dashboard()
    assert d.billboard is not None  # the sample exercises the billboard path
    block = _verdict_block(d, "receipt")
    assert "cal-secondary-verdict" in block
    assert "More signals" in block


def test_verdict_inline_without_billboard() -> None:
    d = dataclasses.replace(sample_dashboard(), billboard=None)
    block = _verdict_block(d, "receipt")
    # Legacy payloads keep the strip inline (no demotion disclosure).
    assert "cal-secondary-verdict" not in block
    assert "cal-verdict-strip" in block


def test_mobile_tap_targets_meet_44px() -> None:
    from caliper.dashboards.html import INLINE_STYLES

    assert "min-height: 44px" in INLINE_STYLES
    assert ".cal-mobile-nav-tab { min-height: 44px; }" in INLINE_STYLES


def test_rates_show_json_redacts_catalog_path() -> None:
    result = runner.invoke(app, ["rates", "show", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["catalog"]["path"] == "<redacted-path>"
    assert "/Users/" not in result.output
    assert "Embedded rate card" not in result.output


def test_empty_dashboard_quality_is_not_excellent(tmp_path) -> None:
    from caliper.config import build_options
    from caliper.dashboards.adapter import build_handoff_dashboard

    options = build_options(
        days=1,
        session_root=tmp_path / "sessions",
        state_db=tmp_path / "state.sqlite",
        codex_config=tmp_path / "config.toml",
    )
    dashboard = build_handoff_dashboard(
        LoadResult(
            events=[],
            duplicates=0,
            tier_sources={},
            plan_types=set(),
            rate_limit_samples=[],
            warnings=[],
        ),
        options,
        with_deltas=False,
    )

    assert dashboard.quality_score is not None
    assert dashboard.quality_score.grade == "No evidence yet"
    assert dashboard.quality_score.score == 0
