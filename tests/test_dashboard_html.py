"""Renderer contract tests for the v2 dashboard.

Covers privacy invariants, theme/density/rhythm attributes, section markers,
empty-state placeholder, table sort stability, and the masthead build id.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections import Counter
from html.parser import HTMLParser

import pytest

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.data_models import ModelRow, ProjectRow, ToolCount
from caliper.dashboards.html import (
    INLINE_STYLES,
    SECTION_NUMBERS,
    _agent_display_label,
    _anomaly_command,
    _compress_session_label,
    _favicon_link,
    fmt_money,
    fmt_tokens,
    render_models,
    render_projects,
)
from caliper.dashboards.sample_data import sample_dashboard
from caliper.models import VENDOR_CLAUDE_CODE
from caliper.parser import load_usage

SECRET = "REDACTED_SECRET_THAT_MUST_NEVER_LEAK"

# Privacy gate: no external resources, no network-capable script APIs.
# `://` already covers any external URL inside any tag (link/script/img/etc),
# so inline-data-URI elements like the favicon (`<link rel="icon" href="data:…">`)
# are safely allowed.
FORBIDDEN = ("://", " src=", "fetch(", "XMLHttpRequest", "import(")


class _DashboardLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        attr_map = dict(attrs)
        element_id = attr_map.get("id")
        href = attr_map.get("href")
        if element_id:
            self.ids.append(element_id)
        if href:
            self.hrefs.append(href)


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


def test_dashboard_a11y_landmarks_and_labels(monkeypatch, tmp_path) -> None:
    """0.0.59 a11y: labelled tables, contentinfo footer, focus-visible charts."""
    html = _render(monkeypatch, tmp_path)
    assert 'role="contentinfo"' in html
    assert 'aria-label="Cost by model"' in html
    assert 'aria-label="Cost by project"' in html
    # SVG bar groups must use :focus-visible (keyboard) not bare :focus (mouse).
    assert "cal-bar-group:focus-visible" in html
    assert ".cal-bar-group:focus " not in html


def test_dashboard_renders_section_markers(monkeypatch, tmp_path) -> None:
    """Phase-3 polish: visible numbering is sequential 1, 2, 3 … in tier
    render order. Section anchor IDs are still stable, so links keep
    working; only the display string changed."""
    html = _render(monkeypatch, tmp_path)
    # The first visible section carries the "1." label.
    assert ">1.<" in html
    # Every rendered section still emits a data-screen-label, but the
    # numeric prefix is now the *display* number (1..N) — not the legacy
    # §00..§19 audit-anchor map.
    import re

    labels = re.findall(r'data-screen-label="(\d+) [^"]+"', html)
    assert labels, "Sections must emit data-screen-label with a numeric prefix"
    nums = [int(n) for n in labels]
    # Sequential, no duplicates.
    assert nums == sorted(nums)
    assert len(nums) == len(set(nums))
    # Anchor IDs unchanged so external links still resolve.
    for sid in SECTION_NUMBERS:
        if f'id="{sid}"' in html:
            assert "data-screen-label=" in html  # any value present


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
    assert "What your AI coding cost and produced" in html
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
    assert 'id="shape"' not in html
    assert 'id="insights"' not in html
    assert "No insights for this window" not in html
    assert "No tool-use signal yet" not in html


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


def test_render_models_shows_other_row_when_rows_undersum() -> None:
    # Rows total $7 but the window cost is $10, so $3 (30%) is unaccounted for.
    # The table must name that tail instead of silently under-summing.
    html = render_models(
        [
            ModelRow("anthropic", "model-a", "standard", 5, 1, 100, 0),
            ModelRow("anthropic", "model-b", "standard", 2, 2, 200, 0),
        ],
        total_cost=10,
    )
    assert "Other models/tiers" in html
    assert "30%" in html


def test_render_models_no_other_row_when_rows_account_for_total() -> None:
    html = render_models(
        [ModelRow("anthropic", "model-a", "standard", 10, 1, 100, 0)],
        total_cost=10,
    )
    assert "Other models/tiers" not in html

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


def test_dashboard_hover_css_does_not_change_layout_geometry() -> None:
    """Hover / focus / active / target rules must never shift box geometry.

    The 'nothing jumps' contract: a user hovering, focusing, or anchor-
    targeting a row, card, or chip must see at most a color, background,
    box-shadow, border-color, opacity, or fill-opacity change. Anything
    that changes the box model (padding, margin, border-width, width,
    height, font-size) — or applies a transform — is a regression.

    Implemented as a scan over CSS rule blocks rather than an exhaustive
    enumeration so new hover rules inherit the same guardrail.
    """
    import re

    # Cheap rule-block tokenizer: split on "}", then keep selectors that
    # carry one of the interactive pseudo-classes.
    blocks = INLINE_STYLES.split("}")
    interactive = re.compile(r":(?:hover|focus|focus-visible|active|target)")
    # Properties that change box geometry — forbidden inside interactive
    # blocks. We allow ``border-color``, ``box-shadow``, ``outline``, and
    # similar non-layout-affecting overrides; we forbid the ones that do.
    forbidden_props = (
        "padding:",
        "padding-top:",
        "padding-right:",
        "padding-bottom:",
        "padding-left:",
        "margin:",
        "margin-top:",
        "margin-right:",
        "margin-bottom:",
        "margin-left:",
        "border-width:",
        "border-top-width:",
        "border-right-width:",
        "border-bottom-width:",
        "border-left-width:",
        # `border:` shorthand can change width — forbid it on hover.
        "border:",
        "border-top:",
        "border-right:",
        "border-bottom:",
        "border-left:",
        "font-size:",
        "line-height:",
        "width:",
        "height:",
        "min-width:",
        "min-height:",
        "transform:",
    )
    for block in blocks:
        if not interactive.search(block):
            continue
        # The selector list ends at "{"; the declarations follow.
        if "{" not in block:
            continue
        _selectors, _, body = block.partition("{")
        # Pseudo-element overlays (::before / ::after) live outside flow
        # when absolute-positioned — width/height there can't shift the
        # adjacent row. Skip them.
        if "::before" in _selectors or "::after" in _selectors:
            continue
        # Strip property values so a substring like "background-color"
        # doesn't trigger the "color" check by accident.
        # Look only at declaration left-hand sides.
        for decl in body.split(";"):
            lhs = decl.split(":", 1)[0].strip().lower()
            if not lhs:
                continue
            full = (lhs + ":").lower()
            if full in forbidden_props:
                raise AssertionError(
                    f"Hover-jump guard tripped: selector {_selectors.strip()!r} "
                    f"changes {lhs!r} inside an interactive rule. "
                    "Use background, color, border-color, box-shadow, or opacity instead."
                )
    # Belt-and-braces explicit checks (independent of the scanner).
    assert "translateY(" not in INLINE_STYLES
    assert "scale(" not in INLINE_STYLES


def test_dashboard_table_rows_are_static_on_hover() -> None:
    assert ".cal-table tbody tr:hover" not in INLINE_STYLES
    assert ".cal-table tbody tr:hover::before" not in INLINE_STYLES
    assert ".cal-session-row:hover" not in INLINE_STYLES
    assert ".cal-advisor-row:hover" not in INLINE_STYLES
    assert ".cal-session-row { cursor: help" not in INLINE_STYLES


def test_cost_chart_includes_average_line_and_hover_labels(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)

    assert "cal-chart-average-line" in html
    assert "cal-bar-hover-label" in html
    assert "overflow:visible" in html
    assert 'height="46"' in html
    assert "avg " in html
    assert "events · " in html


def test_cost_chart_uses_session_shape_colored_bars() -> None:
    html = render_dashboard(sample_dashboard())

    assert 'fill="var(--explore)"' in html
    assert 'fill="var(--execute)"' in html
    assert 'fill="var(--diagnose)"' in html


def test_dashboard_css_has_real_mobile_breakpoint() -> None:
    assert "@media (max-width: 720px)" in INLINE_STYLES
    assert ".cal-receipt-main > section {\n  min-width: 0;\n}" in INLINE_STYLES
    responsive_kpi_grid = "grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));"
    assert responsive_kpi_grid in INLINE_STYLES
    assert (
        '[data-viewport="mobile"] .cal-summary-row { grid-template-columns: 1fr !important; }'
        in INLINE_STYLES
    )
    assert "@media (max-width: 480px)" in INLINE_STYLES
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" not in render_dashboard(
        sample_dashboard()
    )
    assert ".cal-terminal-layout { grid-template-columns: 1fr !important; }" in INLINE_STYLES
    assert ".cal-stat-card-value { font-size: 22px !important; }" in INLINE_STYLES
    assert ".cal-receipt-main { overflow-x: hidden; }" in INLINE_STYLES
    assert ".cal-window-badge" in INLINE_STYLES
    assert "aside { display: none !important; }" not in INLINE_STYLES
    assert ".cal-tweaks-panel" in INLINE_STYLES
    hidden_controls_rule = (
        ".cal-tweaks-panel .cal-tweaks-section,\n  .cal-tweaks-panel .cal-tweaks-save"
    )
    assert hidden_controls_rule not in INLINE_STYLES
    assert ".cal-palette-input:focus-visible" in INLINE_STYLES
    assert "z-index: 11000" in INLINE_STYLES


def test_dashboard_landmarks_and_tweaks_have_accessible_names() -> None:
    html = render_dashboard(sample_dashboard(), interactive=True)

    assert '<main id="cal-main" class="cal-receipt-main" tabindex="-1">' in html
    assert '<section id="overview" aria-label=' in html
    assert 'data-value="safe-share" role="radio" aria-checked=' in html
    assert ">Redacted</button>" in html
    assert "Save copy</button>" in html
    assert "Safe Share" not in html


def test_top_sessions_rows_have_meaningful_accessible_copy(monkeypatch, tmp_path) -> None:
    html = _render(monkeypatch, tmp_path)

    assert 'class="cal-session-row"' in html
    assert 'class="cal-session-row" title=' not in html
    assert 'class="cal-session-row" aria-label=' in html
    assert "selected-window cost" in html
    assert "tool calls" in html
    assert "Reason:" in html


def test_agent_labels_hide_machine_ids() -> None:
    assert _agent_display_label("019e2058-9424-7360-ad06-e011ecff6b8c", 1) == "Agent 1"
    assert _agent_display_label('{"subagent": {"thread_spawn": true}}', 2) == "Agent 2"
    assert _agent_display_label("planner-agent", 3) == "planner-agent"
    assert (
        _agent_display_label(
            "direct:019e2058-9424-7360-ad06-e011ecff6b8c",
            4,
            source_category="direct",
            kind="direct-session",
        )
        == "Direct session 4"
    )
    assert (
        _agent_display_label("acompact-123", 5, source_category="overhead") == "Background agent 5"
    )


def test_anomaly_rows_use_constructive_copy_without_scale_noise() -> None:
    dashboard = sample_dashboard()
    dashboard = dataclasses.replace(
        dashboard,
        anomalies=[
            dataclasses.replace(
                dashboard.anomalies[0],
                comparison_scope="prior sessions in same project/model/tier cohort",
                baseline_sample_count=8,
                impact_percent=400.0,
            ),
            *dashboard.anomalies[1:],
        ],
    )
    html = render_dashboard(dashboard)

    assert "scale $" not in html
    assert "Spend spike" in html
    assert "Compared with 8 prior sessions in same project/model/tier cohort." in html
    assert "Actual spend" in html
    assert "Expected spend" in html
    assert "Cost impact" in html
    assert "Impact %" in html
    assert "+400%" in html
    assert 'class="cal-anomaly-row"' in html
    assert 'class="cal-metric-chip"' in html


def test_anomaly_command_maps_kind_to_the_drilldown_command() -> None:
    # Each anomaly kind points at the command that opens its source.
    assert _anomaly_command("Session spike") == "caliper session"
    assert _anomaly_command("Project-day spike") == "caliper project"
    assert _anomaly_command("Model cost spike") == "caliper models"
    assert _anomaly_command("Commit spike") == "caliper commit"
    # Anything else falls back to the single-day overview.
    assert _anomaly_command("Daily total spike") == "caliper overview --days 1"


def test_compress_session_label_friendly_timestamps_to_a_tight_summary() -> None:
    # Verbose human timestamps collapse to weekday + day + month + 24h time.
    assert _compress_session_label("3:02 am, Thursday 21 May 2026") == "Thu 21 May · 03:02"
    assert _compress_session_label("9:06 pm, Tuesday 19 May 2026") == "Tue 19 May · 21:06"
    assert _compress_session_label("12:00 am, Mon 1 Jan 2026") == "Mon 1 Jan · 00:00"
    assert _compress_session_label("12:30 pm, Fri 4 Jul 2025") == "Fri 4 Jul · 12:30"


def test_favicon_link_is_inline_data_uri_only() -> None:
    link = _favicon_link()
    assert 'rel="icon"' in link
    assert "data:image/svg+xml" in link
    # No external URLs — the favicon is fully embedded.
    assert "://" not in link


def test_compress_session_label_passes_through_non_timestamps() -> None:
    # Indexed, SHA-like, and arbitrary labels pass through unchanged so the
    # privacy-map lookup keys stay stable.
    for label in ("Session 4", "abc123def456", "morning refactor", "", "  spaced  "):
        assert _compress_session_label(label) == label


def test_anomaly_rows_carry_a_copyable_drilldown_command() -> None:
    dashboard = sample_dashboard()
    html = render_dashboard(dashboard)
    # Every anomaly row ends in the command that drills into its source.
    for anomaly in dashboard.anomalies:
        assert _anomaly_command(anomaly.kind) in html


def test_cost_section_names_the_peak_day_to_investigate() -> None:
    # The hint says "days worth investigating"; the summary names the date.
    dashboard = sample_dashboard()
    peak = max(dashboard.daily, key=lambda p: float(p.cost_usd))
    html = render_dashboard(dashboard)
    assert f"on {peak.day}" in html


def test_evidence_section_summarizes_the_grade_tally() -> None:
    # An at-a-glance trust posture sits in the section meta.
    html = render_dashboard(sample_dashboard())
    assert "dimensions ·" in html
    assert "exact" in html


def test_dashboard_renders_curated_sections_in_order() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True))

    # The curated set: overview, decision summary, coverage, flags, collapsed detail, trust.
    for section_id in (
        "overview",
        "action-center",
        "output",
        "cost",
        "models",
        "projects",
        "sessions",
        "anomalies",
        "inefficiencies",
        "attribution",
        "evidence",
    ):
        assert f'id="{section_id}"' in html

    assert "What this produced" in html
    assert "Decision summary" in html
    assert 'class="cal-decision-summary"' in html
    assert 'href="#cost"' in html  # legacy usage-windows finding lands on active cost evidence.
    assert "Avoidable spend" in html
    assert "Recommended changes" in html
    assert "Long-context boundary" in html
    assert 'class="cal-section-summary-grid"' in html

    # Pruned sections no longer render anywhere.
    for gone in (
        "usage-windows",
        "usage-mix",
        "forecast",
        "shape",
        "heatmap",
        "advisor",
        "outlook",
    ):
        assert f'id="{gone}"' not in html, f"{gone} should be pruned"

    # Order: descriptive core (trajectory) → flags (decisions) → collapsed
    # appendix → trust footer.
    section_order = [
        'id="overview"',
        'id="action-center"',
        'id="output"',
        'id="cost"',
        'id="models"',
        'id="projects"',
        'id="sessions"',
        'id="anomalies"',
        'id="inefficiencies"',
        'id="attribution"',
        'id="evidence"',
    ]
    positions = [html.index(marker) for marker in section_order]
    assert positions == sorted(positions), f"Tier ordering broken; got positions {positions}"
    assert "data-billboard-kind" not in html  # no manufactured "biggest fix" hero

    # Supporting detail (attribution) renders inside the collapsed appendix;
    # the descriptive core renders before it.
    appendix_start = html.index('class="cal-appendix"')
    assert html.index('id="sessions"') < appendix_start
    assert appendix_start < html.index('id="attribution"')


def test_dashboard_has_unique_ids_and_live_internal_links() -> None:
    """Guardrail for the signal-first dashboard: every visible jump target
    must exist exactly once, and legacy/pruned sections must not leak dead
    anchors back into the report."""
    html = render_dashboard(sample_dashboard(show_paths=True), interactive=True)
    parser = _DashboardLinkParser()
    parser.feed(html)

    duplicate_ids = {
        element_id: count for element_id, count in Counter(parser.ids).items() if count > 1
    }
    assert duplicate_ids == {}

    ids = set(parser.ids)
    broken = sorted(
        {
            href
            for href in parser.hrefs
            if href.startswith("#") and len(href) > 1 and href[1:] not in ids
        }
    )
    assert broken == []

    # These are still legacy SECTION_NUMBERS entries, but the curated
    # dashboard should route findings to active sections instead.
    for dead_anchor in (
        "#usage-windows",
        "#usage-mix",
        "#forecast",
        "#outlook",
        "#advisor",
        "#heatmap",
        "#shape",
    ):
        assert dead_anchor not in html


def test_dashboard_recommendations_show_ranked_model_alternatives() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True))

    assert "Test current alternatives:" in html
    assert "claude-sonnet-4.6" in html
    assert "GPT-5.5" in html
    assert "gpt-5.4" in html
    assert "cheaper)" in html
    assert "claude-haiku-4.5" not in html
    assert "claude-3-haiku" not in html


def test_new_dashboard_sections_obey_share_safe_redaction() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True), share_safe=True)

    assert "~/work/api-server" not in html
    assert "session-018" not in html
    assert "api-server is $412" not in html
    assert "Project " in html
    assert "Session " in html
    assert "Direct session 1" in html
    # Final polish adds extra vendor-attributed agents so the index of the
    # overhead row is no longer fixed at 2. Assert presence, not position.
    assert "Background agent" in html
    assert "Skill 1" in html


def test_demo_render_is_watermarked() -> None:
    # A --demo dashboard must visibly mark itself as synthetic so a screenshot
    # of the confident numbers can't be mistaken for real usage.
    demo_html = render_dashboard(sample_dashboard(), demo=True)
    assert '<div class="cal-demo-ribbon"' in demo_html
    assert "DEMO DATA" in demo_html
    assert 'data-demo="true"' in demo_html
    # A normal (real-data) render carries no ribbon.
    real_html = render_dashboard(sample_dashboard())
    assert '<div class="cal-demo-ribbon"' not in real_html
    assert 'data-demo="true"' not in real_html


def test_interactive_share_safe_file_embeds_no_real_values() -> None:
    # Regression: the interactive renderer used to force "print-only" even when
    # the caller asked for privacy=always, embedding real values in CSS-hidden
    # `cal-real` spans — so the "Safe Share" file was not actually safe to share.
    # An `always` file (interactive or not) must embed redacted text only.
    d = sample_dashboard(show_paths=True)
    html = render_dashboard(d, privacy="always", interactive=True)

    # No real project/session/path labels anywhere in the file...
    leaks = ("api-server", "frontend-app", "mobile-app", "data-pipeline", "~/work/", "session-018")
    for leak in leaks:
        assert leak not in html, f"Safe Share leaked real value {leak!r}"
    # ...and no real-value data spans for the toggle to un-hide (the CSS rule
    # `.cal-real {{...}}` may still appear; a `<span class="cal-real">` must not).
    assert '<span class="cal-real">' not in html
    # Redacted labels are present instead, including in the cmd+K palette index.
    assert "Project 1" in html
    assert '"type": "project", "label": "Project ' in html


def test_interactive_safe_share_snapshot_sanitizes_hidden_real_values() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True), privacy="off", interactive=True)

    assert '<span class="cal-real">' in html
    assert "snapshotRoot" in html
    assert "querySelectorAll('.cal-real')" in html
    assert 'script[type="application/json"]' in html
    assert "text.split(replacements" in html


def test_attribution_section_uses_truthful_labels_and_safe_layout() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True))

    assert "Source" in html
    assert "Skill / workflow" in html
    assert "Direct session 1" in html
    assert "Background agent" in html
    assert "skills/workflows" in html
    assert 'class="cal-attribution-grid"' in html
    assert 'class="cal-table-panel"' in html
    assert 'class="cal-table-scroll"' in html


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
        "action-center": "00",
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
        "heatmap": "12",
        "sessions": "13",
        "evidence": "14",
        "usage-windows": "15",
        "usage-mix": "16",
        "inefficiencies": "17",
        "outlook": "18",
        "attribution": "19",
        "output": "20",
    }


# ---------------------------------------------------------------------------
# Hero verdict — the single line a screenshot reader can quote.
# ---------------------------------------------------------------------------


def test_hero_verdict_renders_period_cost_trend_and_fixable() -> None:
    """Legacy hero verdict fallback (no billboard) carries the period,
    headline cost, and trend chip, all readable in one glance, with nothing
    prescriptive competing with the cost.
    """
    dashboard = sample_dashboard()
    html_text = render_dashboard(dashboard)
    _assert_private_html(html_text)
    # The class anchors the block and lets future tests find it.
    assert 'class="cal-hero-verdict"' in html_text
    # Period framing from WindowMeta.
    assert "Last 14 days" in html_text
    assert "2026-05-03 → 2026-05-17" in html_text
    # Headline cost is the selected window total (rounded above $1,000).
    assert "$1,243" in html_text
    # Trend chip: +8.2% with the prior-window label.
    assert "+8.2%" in html_text
    assert "vs prior" in html_text
    # The hero states what happened, nothing prescriptive. No manufactured
    # "biggest fix" or avoidable-spend dollar competes with the cost.
    assert "AVOIDABLE" not in html_text.split('id="inefficiencies"')[0]
    assert "Top fix" not in html_text.split('id="inefficiencies"')[0]


def test_hero_verdict_hidden_on_empty_dashboard() -> None:
    """The hero verdict is a "this is what changed" hero; on an empty
    window it would be a lie. It must be omitted."""
    from caliper.dashboards.sample_data import empty_dashboard

    html_text = render_dashboard(empty_dashboard())
    assert 'class="cal-hero-verdict"' not in html_text


def test_hero_verdict_renders_in_terminal_rhythm() -> None:
    """Terminal rhythm includes the hero verdict."""
    html_text = render_dashboard(sample_dashboard(), rhythm="terminal")
    assert 'class="cal-hero-verdict"' in html_text


# ---------------------------------------------------------------------------
# Billboard — Phase 1 UX overhaul: single above-the-fold "biggest fix"
# ---------------------------------------------------------------------------


def test_dashboard_has_no_billboard_hero() -> None:
    """The manufactured "biggest fix" billboard was removed. The dashboard
    leads with the honest verdict (period, cost, trend), not a prescriptive
    model-arbitrage headline."""
    html_text = render_dashboard(sample_dashboard())
    _assert_private_html(html_text)
    assert "data-billboard-kind" not in html_text
    assert "BIGGEST FIX" not in html_text
    assert 'class="cal-hero-verdict"' in html_text


def test_every_section_has_an_explicit_tier() -> None:
    """Guardrail: `_sections_by_tier` falls back to "appendix" via
    `.get(sid, "appendix")`, so a section added to `_SECTION_ORDER` but
    forgotten in `_SECTION_TIER` would silently land in the appendix with no
    warning. Require every renderable section to declare its tier explicitly
    so future additions are caught here instead of in production."""
    from caliper.dashboards.html import _SECTION_ORDER, _SECTION_TIER, _TIER_ORDER

    missing = [sid for sid in _SECTION_ORDER if sid not in _SECTION_TIER]
    assert not missing, f"sections missing a _SECTION_TIER entry: {missing}"
    bad_tier = {sid: t for sid, t in _SECTION_TIER.items() if t not in _TIER_ORDER}
    assert not bad_tier, f"sections mapped to an unknown tier: {bad_tier}"


def test_receipt_rhythm_renders_sticky_toc_grouped_by_tier() -> None:
    """Phase 2: the receipt rhythm includes a sticky right-rail TOC,
    grouped by tier. Each section anchor must appear as a TOC link with
    ``data-toc-target`` so the scroll-spy JS can resolve it."""
    html_text = render_dashboard(sample_dashboard(show_paths=True))
    assert 'class="cal-receipt-toc"' in html_text
    assert 'aria-label="Section navigation"' in html_text
    # Tier group labels are visible.
    assert ">What happened<" in html_text
    assert ">Worth a look<" in html_text
    assert ">More detail<" in html_text
    # Each rendered section has a corresponding TOC link with data-toc-target.
    for sid in ("overview", "action-center", "output", "cost", "anomalies", "inefficiencies"):
        assert f'data-toc-target="{sid}"' in html_text
    # The TOC must not duplicate the terminal-rhythm index.
    assert 'class="cal-rail-link"' not in html_text


def test_receipt_toc_omits_inactive_sections() -> None:
    """Disabled sections (advisor / outlook) must not surface in the TOC."""
    html_text = render_dashboard(sample_dashboard(show_paths=True))
    assert 'data-toc-target="advisor"' not in html_text
    assert 'data-toc-target="outlook"' not in html_text


def test_interactive_dashboard_emits_scroll_spy_and_auto_open_appendix() -> None:
    """The inline script extends with an IntersectionObserver-based
    scroll-spy and an anchor-click handler that opens the technical
    appendix when the target lives inside it."""
    html_text = render_dashboard(sample_dashboard(show_paths=True), interactive=True)
    assert "IntersectionObserver" in html_text
    assert "data-toc-target" in html_text
    assert "aria-current" in html_text
    assert "openAppendixIfTargets" in html_text


def test_interactive_dashboard_emits_palette_and_keyboard_shortcuts() -> None:
    """Phase 3: interactive mode ships a Cmd+K palette with a JSON index
    of searchable items and a global keyboard-shortcut handler (g a / g i /
    g m, /, ⌘K, e/c, etc.)."""
    html_text = render_dashboard(sample_dashboard(show_paths=True), interactive=True)
    assert 'id="cal-palette"' in html_text
    assert 'role="dialog"' in html_text
    assert 'role="combobox"' in html_text
    assert 'aria-controls="cal-palette-results"' in html_text
    assert "aria-activedescendant" in html_text
    assert "aria-selected" in html_text
    assert 'id="cal-palette-index"' in html_text
    assert "paletteOpen" in html_text
    # Palette index contains section, model, project, anomaly entries.
    assert '"type": "section"' in html_text
    assert '"type": "model"' in html_text
    assert '"type": "project"' in html_text
    # Keyboard shortcuts present.
    assert "metaKey" in html_text
    assert "ctrlKey" in html_text
    assert "gleader" in html_text


def test_non_interactive_dashboard_omits_palette() -> None:
    """Non-interactive snapshots stay byte-frugal: no palette markup or
    JSON index."""
    html_text = render_dashboard(sample_dashboard(show_paths=True), interactive=False)
    assert 'id="cal-palette"' not in html_text
    assert 'id="cal-palette-index"' not in html_text


def test_dashboard_renders_appendix_block_with_collapsed_diagnostic_sections() -> None:
    """The technical appendix wraps the diagnostic tier in a single
    <details> so the default view stays calm. ``models`` and
    ``attribution`` must live inside that block; ``inefficiencies`` and
    ``anomalies`` must not — they're decisions tier."""
    html_text = render_dashboard(sample_dashboard(show_paths=True))
    appendix_start = html_text.index('class="cal-appendix"')
    appendix_end = html_text.index("</details>", appendix_start)
    inside = html_text[appendix_start:appendix_end]
    # Supporting detail lives inside the collapsed appendix.
    assert 'id="attribution"' in inside
    # The descriptive core and the flags render BEFORE the appendix opens.
    assert html_text.index('id="action-center"') < appendix_start
    assert html_text.index('id="sessions"') < appendix_start
    assert html_text.index('id="inefficiencies"') < appendix_start
    assert html_text.index('id="anomalies"') < appendix_start


def test_print_css_forces_appendix_body_visible() -> None:
    assert (
        "details.cal-appendix > .cal-appendix-body { display: grid !important; }" in INLINE_STYLES
    )
    assert ".theme-print details.cal-appendix > .cal-appendix-body" in INLINE_STYLES


# ---------------------------------------------------------------------------
# Show-the-math <details> on KPI cards.
# ---------------------------------------------------------------------------


def test_overview_kpi_cards_include_show_the_math_details() -> None:
    """Every populated KPI card carries a <details> disclosure with the
    formula + sample-size lineage. Pure HTML — no extra <script> tags.

    HN's litmus test: 'show me how you computed cache_savings.' The page
    must answer that without leaving the dashboard."""
    html_text = render_dashboard(sample_dashboard())
    _assert_private_html(html_text)
    # Disclosure shell.
    assert 'class="cal-card-formula"' in html_text
    assert "show the math" in html_text
    # Formulas surface the actual math.
    assert "cost = Σ event_cost" in html_text
    assert "vendor-reported USD when present" in html_text
    assert "cache_creation_1h × rate_cache_creation_1h" in html_text
    assert "service-tier multiplier" in html_text
    assert "cache_savings = Σ max(0, cost_without_cache − actual_cost)" in html_text
    assert "cost_without_cache reprices the same input/output/reasoning" in html_text
    assert "cache_hit_rate = cached_input / input_tokens" in html_text
    assert "input_tokens = uncached_input + cached_input" in html_text
    assert "output_tokens = reported output tokens" in html_text
    assert "total_tokens = vendor-reported total_tokens" in html_text
    assert "total_tokens = uncached_input + cached_input + output + reasoning" not in html_text
    assert "cache_savings = Σ cached_input × (rate_in − rate_cached_in)" not in html_text
    # Token card renders input/output separately with cached and uncached input split.
    assert 'class="cal-token-split"' in html_text
    assert ">Input</div>" in html_text
    assert ">Output</div>" in html_text
    assert ">3.9M</div>" in html_text
    assert "2.8M cached · 1.1M uncached" in html_text
    assert ">258.0K</div>" in html_text
    assert "reported output" in html_text
    # Log-derived overview strip surfaces source quality and operational evidence.
    assert 'class="cal-log-signals"' in html_text
    assert "Cost source" in html_text
    assert "Mixed source" in html_text
    assert "2.4M read" in html_text
    assert "380.0K write" in html_text
    assert "18 errors" in html_text
    assert "4.2s median" in html_text
    assert "evidence 82/100" in html_text
    # Lineage — "across N events · M sessions" — proves the sample size.
    assert "across 480 events" in html_text
    # Source line cites the rate card.
    assert "Rate card:" in html_text


def test_show_the_math_details_omitted_on_empty_window() -> None:
    """Empty window → cards render '—' with no math disclosure. Avoids
    showing formulas the user can't act on."""
    from caliper.dashboards.sample_data import empty_dashboard

    html_text = render_dashboard(empty_dashboard())
    assert 'class="cal-card-formula"' not in html_text


# ---------------------------------------------------------------------------
# Sample-size chip on insights.
# ---------------------------------------------------------------------------


def test_insights_carry_sample_size_lineage() -> None:
    """Every insight that ships ``evidence_metrics`` (events / sessions /
    tokens) renders a lineage chip so the reader can verify the basis
    without trusting the headline alone."""
    import dataclasses

    # Insights are a legacy/lean payload section now. Rich operator dashboards
    # render the same findings through actions, anomalies, and savings instead.
    lean = dataclasses.replace(
        sample_dashboard(),
        advisor_recommendations=[],
        top_sessions=[],
        inefficiencies=[],
        anomalies=[],
    )
    html_text = render_dashboard(lean)
    # Class is the anchor; copy is the lineage prefix.
    assert 'class="cal-insight-meta"' in html_text
    # Sample data: the cache-reuse insight is computed over 480 events.
    assert "based on 480 events" in html_text
    # Sessions appear too, formatted with fmt_int.
    assert "32 sessions" in html_text


def test_rich_dashboard_suppresses_duplicate_insights() -> None:
    """When stronger finding sections exist, the generic insight list would
    repeat the same story. Keep it for lean payloads only."""
    html_text = render_dashboard(sample_dashboard())

    assert 'id="insights"' not in html_text
    assert 'class="cal-decision-summary"' in html_text


def test_insights_without_metrics_omit_the_lineage_chip() -> None:
    """An insight with empty evidence_metrics renders no meta chip — we
    show what we have and stay silent about what we don't."""
    from caliper.dashboards.data_models import (
        CaliperMeta,
        DailyPoint,
        Dashboard,
        EvidenceRow,
        Insight,
        Totals,
        WindowMeta,
    )

    # Minimal dashboard with one metric-less insight.
    minimal = Dashboard(
        caliper=CaliperMeta(version="0.0.0", schema_version=3),
        window=WindowMeta(
            start="2026-05-01",
            end="2026-05-08",
            label="Last 7 days",
            range="2026-05-01 → 2026-05-08",
            timezone="UTC",
            vendors_active=["claude-code"],
            vendor_count_total=2,
        ),
        generated_at="2026-05-08T00:00:00+00:00",
        totals=Totals(
            cost_usd=10.0,
            events=1,
            cache_savings_usd=0.0,
            cache_hit_rate=0.0,
            total_tokens=100,
            cached_input_tokens=0,
            uncached_input_tokens=50,
            output_tokens=50,
            sessions=1,
            turns=1,
            tools_per_turn=1.0,
        ),
        daily=[DailyPoint("2026-05-01", 10.0, 1, "execution")],
        by_model=[],
        by_project=[],
        anomalies=[],
        insights=[Insight("info", "Quiet week", "No notable findings.", impact=None)],
        evidence=[EvidenceRow("Usage completeness", "exact", "")],
    )
    html_text = render_dashboard(minimal, interactive=False)
    # Insight rendered, but no meta chip — evidence_metrics was empty.
    assert "Quiet week" in html_text
    assert 'class="cal-insight-meta"' not in html_text
    # And the privacy gate still holds for this lean payload.
    _assert_private_html(html_text)
