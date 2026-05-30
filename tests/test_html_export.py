"""Shared HTML export helper — lens mapping, share-safe default, self-contained output."""

from __future__ import annotations

import datetime as dt

import pytest

from caliper.config import build_options
from caliper.html_export import (
    ALL_LENSES,
    build_command_dashboard,
    lens_for_command,
    render_command_html,
)
from caliper.parser import load_usage
from tests.conftest import token_event, write_session


@pytest.fixture
def small_load_result(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    codex_root = tmp_path / "codex" / "sessions" / "2026" / "05"
    codex_root.mkdir(parents=True)
    write_session(
        codex_root,
        "abc123.jsonl",
        [
            token_event(
                dt.datetime(2026, 5, 10, 12, 0, tzinfo=dt.UTC),
                {"input_tokens": 1000, "output_tokens": 200},
            ),
            token_event(
                dt.datetime(2026, 5, 11, 14, 0, tzinfo=dt.UTC),
                {"input_tokens": 500, "output_tokens": 80},
            ),
        ],
    )
    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-05-01",
        until="2026-06-01",
        no_parse_cache=True,
    )
    return load_usage(options), options


def test_lens_for_known_commands_returns_expected_audiences() -> None:
    assert lens_for_command("overview") == "executive"
    assert lens_for_command("models") == "finance"
    assert lens_for_command("project") == "audit"
    assert lens_for_command("daily") == "engineer"


def test_lens_for_unknown_command_falls_back_to_executive() -> None:
    assert lens_for_command("does-not-exist") == "executive"


def test_all_lenses_constant_matches_dashboard_lens_literal() -> None:
    assert set(ALL_LENSES) == {"executive", "engineer", "finance", "audit"}


def test_build_command_dashboard_emits_a_dashboard_payload(small_load_result) -> None:
    result, options = small_load_result
    payload = build_command_dashboard(result, options, command="daily")
    # Sanity: payload exposes the fields the renderer expects.
    assert payload.caliper.schema_version >= 1
    assert payload.window.start
    assert payload.window.end
    assert payload.totals is not None


def test_build_command_dashboard_skips_deltas_for_narrow_commands(small_load_result) -> None:
    result, options = small_load_result
    payload = build_command_dashboard(result, options, command="forecast")
    assert payload.totals.delta_cost_pct is None
    assert payload.totals.delta_tokens_pct is None


def test_render_command_html_outputs_self_contained_html(small_load_result) -> None:
    result, options = small_load_result
    html = render_command_html(result, options, command="daily")
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    # Self-contained: no external CSS/JS/image links.
    assert 'src="http' not in html
    assert "src='http" not in html
    assert 'href="http' not in html
    assert "href='http" not in html
    # No <link rel="stylesheet" ...> tags either — styles must be inlined.
    assert '<link rel="stylesheet"' not in html
    assert "<link rel='stylesheet'" not in html


def test_render_command_html_default_lens_is_command_specific(small_load_result) -> None:
    # v2 removed the audience-lens system. `lens_for_command` is preserved as
    # a label hint for callers, but the renderer no longer stamps a
    # ``data-lens`` attribute. The HTML output is identical regardless of
    # which command label is passed.
    result, options = small_load_result
    finance_html = render_command_html(result, options, command="models")
    engineer_html = render_command_html(result, options, command="daily")
    assert "data-lens=" not in finance_html
    assert "data-lens=" not in engineer_html
    # Both still render the same chrome scaffolding (header / sections / footer).
    assert "CALIPER-" in finance_html
    assert "CALIPER-" in engineer_html


def test_render_command_html_share_safe_is_default(small_load_result) -> None:
    result, options = small_load_result
    html = render_command_html(result, options, command="overview")
    assert 'data-share-safe="true"' in html


def test_render_command_html_share_safe_can_be_disabled(small_load_result) -> None:
    result, options = small_load_result
    html = render_command_html(result, options, command="overview", share_safe=False)
    assert 'data-share-safe="false"' in html


def test_render_command_html_theme_density_pass_through(small_load_result) -> None:
    result, options = small_load_result
    html = render_command_html(
        result, options, command="overview", theme="light", density="compact"
    )
    assert 'data-theme="light"' in html
    assert 'data-density="compact"' in html


def test_render_command_html_for_empty_result_still_renders(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    options = build_options(
        session_root=tmp_path / "codex",
        state_db=tmp_path / "state.db",
        codex_config=tmp_path / "codex.toml",
        since="2026-05-01",
        until="2026-06-01",
    )
    result = load_usage(options)
    html = render_command_html(result, options, command="overview")
    assert "<!doctype html>" in html
    # Empty-state copy is rendered by the dashboard renderer when there
    # are no events; the wrapper must not crash on the empty path.
    assert "</html>" in html
