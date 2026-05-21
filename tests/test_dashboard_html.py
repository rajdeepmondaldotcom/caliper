"""Renderer contract tests for the v2 dashboard.

Covers privacy invariants, theme/density/rhythm attributes, section markers,
empty-state placeholder, table sort stability, and the masthead build id.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.data_models import ModelRow, ProjectRow, ToolCount
from caliper.dashboards.html import (
    SECTION_NUMBERS,
    fmt_money,
    fmt_tokens,
    render_models,
    render_projects,
)
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage

SECRET = "REDACTED_SECRET_THAT_MUST_NEVER_LEAK"

# Privacy gate: no external resources, no network-capable script APIs.
FORBIDDEN = ("://", "<link", " src=", "fetch(", "XMLHttpRequest", "import(")


def _assert_private_html(html: str) -> None:
    # The v2 renderer ships at most one inline <script> tag — the
    # interactive toggle controller (Receipt/Terminal + Dark/Light/Safe
    # Share + Save snapshot). The script uses only DOM, localStorage,
    # Blob, and URL.createObjectURL — no network APIs.
    assert html.count("<script>") <= 1
    assert html.count("</script>") <= 1
    assert html.count("<script>") == html.count("</script>")
    for needle in FORBIDDEN:
        assert needle not in html, f"Privacy gate broken — dashboard contains {needle!r}"


def _write_session(tmp_path):
    projects = tmp_path / "claude" / "projects" / "-tmp-project-alpha"
    projects.mkdir(parents=True)
    rows = [
        {
            "type": "assistant",
            "sessionId": "claude-session-1",
            "uuid": f"event-{i}",
            "parentUuid": f"parent-{i}",
            "timestamp": f"2026-05-12T10:{i:02d}:00.000Z",
            "cwd": "/tmp/project-alpha",
            "requestId": f"req-{i}",
            "message": {
                "id": f"msg-{i}",
                "role": "assistant",
                "model": "claude-sonnet-4-6-20260501",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"secret": SECRET}},
                    {"type": "tool_use", "name": "Edit", "input": {"secret": SECRET}},
                    {"type": "text", "text": SECRET},
                ],
                "usage": {"input_tokens": 100 + i, "output_tokens": 25},
            },
        }
        for i in range(1, 4)
    ]
    (projects / "claude-session-1.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def _options(tmp_path):
    return build_options(
        since="2026-05-12",
        until="2026-05-13",
        timezone="UTC",
        session_root=tmp_path / "missing-codex",
        state_db=tmp_path / "missing-state.sqlite",
        codex_config=tmp_path / "missing-config.toml",
        vendors=[VENDOR_CLAUDE_CODE],
        no_parse_cache=True,
    )


def _render(
    monkeypatch,
    tmp_path,
    *,
    theme: str = "dark",
    density: str = "comfortable",
    rhythm: str = "receipt",
    share_safe: bool = False,
) -> str:
    _write_session(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    options = _options(tmp_path)
    result = load_usage(options)
    payload = build_handoff_dashboard(
        result,
        options,
        with_deltas=False,
        generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC),
    )
    return render_dashboard(
        payload,
        theme=theme,
        density=density,
        rhythm=rhythm,
        share_safe=share_safe,
    )


def test_dashboard_privacy_gate(monkeypatch, tmp_path) -> None:
    """No external resources, no scripts, no fetch APIs."""
    html = _render(monkeypatch, tmp_path)
    _assert_private_html(html)


def test_dashboard_does_not_leak_tool_use_input(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    assert SECRET not in html


def test_dashboard_renders_section_markers(monkeypatch, tmp_path) -> None:
    """§NN markers are the design's audit anchors."""
    html = _render(monkeypatch, tmp_path)
    # At minimum §01 (overview), §03 (shape), §06 (insights) — these always
    # render regardless of payload density. The mono prefix is rendered as
    # the literal "§NN" (no separator) to match the design prototype.
    for marker in ("§01", "§03", "§06"):
        assert f">{marker}<" in html, f"Section marker {marker!r} missing"
    # Every rendered section's id and data-screen-label come from SECTION_NUMBERS.
    for sid, num in SECTION_NUMBERS.items():
        if f'id="{sid}"' in html:
            assert f'data-screen-label="{num} ' in html, (
                f"Section {sid!r} rendered without its data-screen-label"
            )


def test_dashboard_renders_dark_theme_attribute(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="dark")
    assert 'data-theme="dark"' in html
    assert "theme-dark" in html


def test_dashboard_renders_light_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="light")
    assert 'data-theme="light"' in html
    assert "theme-light" in html
    _assert_private_html(html)


def test_dashboard_renders_print_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="print")
    assert 'data-theme="print"' in html
    assert "theme-print" in html
    _assert_private_html(html)


def test_dashboard_renders_compact_density(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, density="compact")
    assert 'data-density="compact"' in html
    assert "density-compact" in html


def test_dashboard_renders_terminal_rhythm(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, rhythm="terminal")
    # Terminal masthead surfaces the OFFLINE word and the section index rail.
    assert "OFFLINE" in html
    assert ">Index<" in html
    _assert_private_html(html)


def test_dashboard_renders_receipt_rhythm(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, rhythm="receipt")
    # Receipt masthead carries the wordmark + subtitle, not the OFFLINE ticker.
    assert "Cost layer for AI-assisted development" in html
    _assert_private_html(html)


def test_dashboard_renders_build_id(monkeypatch, tmp_path) -> None:
    """The masthead anchors a dated build id for audit trails."""
    html = _render(monkeypatch, tmp_path)
    assert "CALIPER-20260517-" in html


def test_dashboard_renders_when_no_events(tmp_path) -> None:
    options = _options(tmp_path)
    result = load_usage(options)
    payload = build_handoff_dashboard(
        result,
        options,
        with_deltas=False,
        generated_at=dt.datetime(2026, 5, 17, tzinfo=dt.UTC),
    )
    html = render_dashboard(payload)
    assert "<title>" in html
    assert "Caliper Dashboard" in html
    _assert_private_html(html)
    # Empty state surfaces a friendly placeholder in the summary cards.
    assert "No events for this window" in html


def test_dashboard_rejects_invalid_options() -> None:
    from caliper.dashboards.sample_data import sample_dashboard

    d = sample_dashboard()

    with pytest.raises(ValueError):
        render_dashboard(d, theme="bogus")
    with pytest.raises(ValueError):
        render_dashboard(d, density="bogus")
    with pytest.raises(ValueError):
        render_dashboard(d, rhythm="bogus")


def test_dashboard_formats_billion_tokens_but_not_costs() -> None:
    assert fmt_tokens(1_234_567_890) == "1.2B"
    assert fmt_tokens(234_567_890) == "234.6M"
    assert fmt_money(1_234_567_890) == "$1,234,567,890"


def test_dashboard_renderer_sorts_tables_by_cost() -> None:
    model_html = render_models(
        [
            ModelRow("anthropic", "model-b", "standard", 2, 2, 200, 0),
            ModelRow("anthropic", "model-a", "standard", 5, 1, 100, 0),
            ModelRow("anthropic", "model-c", "standard", 2, 2, 500, 0),
        ],
        total_cost=9,
    )
    assert model_html.index("model-a") < model_html.index("model-c")
    assert model_html.index("model-c") < model_html.index("model-b")
    assert 'aria-sort="descending"' in model_html

    project_html = render_projects(
        [
            ProjectRow("project-b", "/tmp/project-b", 2, 2, 1, []),
            ProjectRow(
                "project-a",
                "/tmp/project-a",
                5,
                1,
                1,
                [ToolCount("Read", 2, "explore")],
            ),
            ProjectRow("project-c", "/tmp/project-c", 2, 5, 1, []),
        ],
        show_paths=True,
        total_cost=10,
    )
    assert project_html.index("project-a") < project_html.index("project-c")
    assert project_html.index("project-c") < project_html.index("project-b")
    assert "selected-window cost" in project_html
    assert "Share of window" in project_html
    assert 'aria-sort="descending"' in project_html


def test_dashboard_models_table_includes_sortable_marker(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    # Both the models and projects tables advertise the sortable class so a
    # future static-HTML enhancement layer (if any) can find them.
    assert 'class="cal-table data data-sortable' in html


def test_dashboard_evidence_link_jumps_to_section(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    # The evidence badge in the masthead links to #evidence.
    assert 'href="#evidence"' in html


def test_dashboard_paths_hidden_by_default(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    assert "/tmp/project-alpha" not in html


def test_dashboard_section_numbers_are_stable() -> None:
    # Lock the section IDs and their numeric anchors. Any change here is a
    # breaking change for external links that point at a generated dashboard.
    assert SECTION_NUMBERS == {
        "overview": "01",
        "cost": "02",
        "shape": "03",
        "models": "04",
        "projects": "05",
        "insights": "06",
        "anomalies": "07",
        "budgets": "08",
        "forecast": "09",
        "advisor": "10",
        "rate-limits": "11",
        "heatmap": "12",
        "sessions": "13",
        "evidence": "14",
    }
