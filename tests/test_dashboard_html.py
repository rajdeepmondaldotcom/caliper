from __future__ import annotations

import datetime as dt
import json

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.data_models import ImpactCard, ModelRow, ProjectRow, ToolCount, UsageWindow
from caliper.dashboards.html import (
    fmt_money,
    fmt_tokens,
    render_impact_cards,
    render_models,
    render_projects,
    render_usage_windows,
)
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage

SECRET = "REDACTED_SECRET_THAT_MUST_NEVER_LEAK"

# The privacy gate permits the dashboard's inline controls, but still forbids
# external resources and network-capable script APIs.
FORBIDDEN = ("://", "<link", " src=", "fetch(", "XMLHttpRequest", "import(")


def _assert_private_html(html: str) -> None:
    assert html.count("<script>") == 1
    assert html.count("</script>") == 1
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


def _render(monkeypatch, tmp_path, *, theme: str = "dark", density: str = "comfortable") -> str:
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
    return render_dashboard(payload, theme=theme, density=density)


def test_dashboard_privacy_gate(monkeypatch, tmp_path) -> None:
    """The CI privacy gate: inline controls only; no external resources."""
    html = _render(monkeypatch, tmp_path)
    _assert_private_html(html)


def test_dashboard_does_not_leak_tool_use_input(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    assert SECRET not in html


def test_dashboard_renders_section_markers(monkeypatch, tmp_path) -> None:
    """§ N markers are the design's audit-doc anchor."""
    html = _render(monkeypatch, tmp_path)
    # In non-empty rich state, we expect § 01 (cost) through § 09 (evidence).
    for marker in ("§&nbsp;01", "§&nbsp;02", "§&nbsp;03", "§&nbsp;04", "§&nbsp;07"):
        assert marker in html, f"Section marker {marker!r} missing"


def test_dashboard_renders_dark_theme_attribute(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="dark")
    assert 'data-theme="dark"' in html


def test_dashboard_renders_light_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="light")
    assert 'data-theme="light"' in html
    _assert_private_html(html)


def test_dashboard_renders_print_theme(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, theme="print")
    assert 'data-theme="print"' in html
    _assert_private_html(html)


def test_dashboard_renders_compact_density(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path, density="compact")
    assert 'data-density="compact"' in html


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
    # Empty state still renders the page header + footer + empty placeholders.
    assert "no data for this window" in html


def test_dashboard_formats_billion_tokens_but_not_costs() -> None:
    assert fmt_tokens(1_234_567_890) == "1.2B"
    assert fmt_tokens(234_567_890) == "234.6M"
    assert fmt_money(1_234_567_890) == "$1,234,567,890"


def test_dashboard_renderer_sorts_usage_windows_and_impact_cards() -> None:
    windows = [
        UsageWindow("Last 90 days", 90, "2026-02-12", "2026-05-13", "90", 3, 3, 3, 3, 0, 3),
        UsageWindow("Last 7 days", 7, "2026-05-06", "2026-05-13", "7", 1, 1, 1, 1, 0, 1),
        UsageWindow("Last 30 days", 30, "2026-04-13", "2026-05-13", "30", 2, 2, 2, 2, 0, 2),
    ]
    usage_html = render_usage_windows(windows)
    assert usage_html.index("Last 7 days") < usage_html.index("Last 30 days")
    assert usage_html.index("Last 30 days") < usage_html.index("Last 90 days")

    cards = [
        ImpactCard("Usage rhythm", "1 active day", "Peak hour 10 AM"),
        ImpactCard("Cache leverage", "$1", "Good cache", "good"),
        ImpactCard("Budget risk", "120%", "monthly cost", "critical"),
        ImpactCard("Cost driver", "api", "$9", "warn"),
    ]
    impact_html = render_impact_cards(cards)
    assert impact_html.index("Budget risk") < impact_html.index("Cost driver")
    assert impact_html.index("Cost driver") < impact_html.index("Cache leverage")
    assert impact_html.index("Cache leverage") < impact_html.index("Usage rhythm")


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
    )
    assert project_html.index("project-a") < project_html.index("project-c")
    assert project_html.index("project-c") < project_html.index("project-b")
    assert 'aria-sort="descending"' in project_html


def test_dashboard_renders_analysis_drilldowns(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)
    assert "Command center" in html
    assert "Usage mix" in html
    assert "Savings advisor" in html
    assert "Session outliers" in html
    assert "Rate limits" in html
    assert "Evidence quality" in html
    assert 'class="data data-sortable' in html
    assert 'data-mix-filter="all"' in html
