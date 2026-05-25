"""Renderer contract tests for the v2 dashboard.

Covers privacy invariants, theme/density/rhythm attributes, section markers,
empty-state placeholder, table sort stability, and the masthead build id.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import pytest

from caliper.config import build_options
from caliper.dashboards import build_handoff_dashboard, render_dashboard
from caliper.dashboards.data_models import ModelRow, ProjectRow, ToolCount
from caliper.dashboards.html import (
    INLINE_STYLES,
    SECTION_NUMBERS,
    _agent_display_label,
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
    # The first visible section (action-center) carries the "1." label.
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


def test_dashboard_renders_operator_first_sections() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True))

    for section_id in (
        "action-center",
        "cost",
        "usage-windows",
        "usage-mix",
        "anomalies",
        "inefficiencies",
        "forecast",
        "attribution",
        "evidence",
    ):
        assert f'id="{section_id}"' in html

    assert "Operator brief" not in html  # renamed to "Next actions"
    assert "Next actions" in html
    assert "Spend drivers" in html
    assert "Forecast" in html  # renamed from "Forward look"
    assert "Recommended changes" in html
    assert "Detected waste" in html
    assert 'id="advisor"' not in html
    assert 'id="outlook"' not in html
    assert 'id="insights"' not in html
    assert "Decision queue" not in html
    assert "Signals checked" not in html
    assert "Evidence-labelled findings" not in html
    assert "No insights for this window" not in html
    assert "No tool-use signal yet" not in html
    assert "Cost-weighted rhythm" in html
    assert "Long-context boundary" in html

    # Phase 1 UX overhaul: sections are grouped by tier
    # (decisions → trajectory → appendix → trust). Within each tier the
    # original _SECTION_ORDER is preserved, so the operator-first decision
    # cluster precedes trajectory diagrams and the diagnostic appendix.
    section_order = [
        'id="action-center"',  # decisions tier
        'id="anomalies"',  # decisions tier
        'id="inefficiencies"',  # decisions tier
        'id="overview"',  # trajectory tier
        'id="cost"',  # trajectory tier
        'id="usage-windows"',  # trajectory tier (promoted from appendix)
        'id="usage-mix"',  # trajectory tier
        'id="forecast"',  # trajectory tier
        'id="evidence"',  # trust tier (always last)
    ]
    positions = [html.index(marker) for marker in section_order]
    assert positions == sorted(positions), f"Tier ordering broken; got positions {positions}"

    # Spend windows (7/30/90-day trend) was promoted out of the appendix into
    # the trajectory tier, so it renders BEFORE the collapsible block.
    appendix_start = html.index('class="cal-appendix"')
    assert html.index('id="usage-windows"') < appendix_start, (
        "usage-windows should render in the trajectory tier, before the appendix"
    )
    # A genuine appendix section (heatmap) still renders inside the <details>
    # so the default view stays calm.
    assert appendix_start < html.index('id="heatmap"'), (
        "appendix sections must render inside the appendix <details> block"
    )


def test_dashboard_recommendations_show_ranked_model_alternatives() -> None:
    html = render_dashboard(sample_dashboard(show_paths=True))

    assert "Test current alternatives:" in html
    assert "claude-sonnet-4.6" in html
    assert "GPT-5.5" in html
    assert "gpt-5.4" in html
    assert "openai, saves" in html
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
        "rate-limits": "11",
        "heatmap": "12",
        "sessions": "13",
        "evidence": "14",
        "usage-windows": "15",
        "usage-mix": "16",
        "inefficiencies": "17",
        "outlook": "18",
        "attribution": "19",
    }


# ---------------------------------------------------------------------------
# Hero verdict — the single line a screenshot reader can quote.
# ---------------------------------------------------------------------------


def test_hero_verdict_renders_period_cost_trend_and_fixable() -> None:
    """Legacy hero verdict fallback (no billboard) carries the period,
    headline cost, trend chip, fixable sum, and the top advisor action —
    all readable in one glance.

    Phase 1 UX overhaul: when ``dashboard.billboard`` is populated, the
    billboard supplants the hero verdict as the page peak. The hero
    verdict still renders for payloads without a billboard (legacy /
    backwards compatibility), so we exercise it via ``billboard=None``.
    """
    dashboard = dataclasses.replace(sample_dashboard(), billboard=None)
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
    # Fixable sum: top-3 advisor recs = $96.40 + $61.24 + $19.00 = $176.64.
    assert "FIXABLE" in html_text
    assert "$176.64" in html_text
    # The top action title appears verbatim.
    assert "Move low-output fast tier calls to standard" in html_text
    # The CLI command for the top action is shown (copy-paste path).
    assert "caliper advise --rule fast-tier-low-output" in html_text


def test_hero_verdict_hidden_on_empty_dashboard() -> None:
    """The hero verdict is a "this is what changed" hero; on an empty
    window it would be a lie. It must be omitted."""
    from caliper.dashboards.sample_data import empty_dashboard

    html_text = render_dashboard(empty_dashboard())
    assert 'class="cal-hero-verdict"' not in html_text


def test_hero_verdict_renders_in_terminal_rhythm() -> None:
    """Terminal rhythm includes the legacy hero verdict (no billboard set)."""
    dashboard = dataclasses.replace(sample_dashboard(), billboard=None)
    html_text = render_dashboard(dashboard, rhythm="terminal")
    assert 'class="cal-hero-verdict"' in html_text


# ---------------------------------------------------------------------------
# Billboard — Phase 1 UX overhaul: single above-the-fold "biggest fix"
# ---------------------------------------------------------------------------


def test_billboard_renders_above_the_fold_with_headline_value_and_cta() -> None:
    """When ``dashboard.billboard`` is populated, the renderer emits a
    single above-the-fold peak with the BIGGEST FIX headline, the
    saveable amount, confidence chip, and the investigate CTA. This
    supplants the legacy hero verdict strip."""
    html_text = render_dashboard(sample_dashboard())
    _assert_private_html(html_text)
    # The class anchors the block and the data attributes carry the
    # selection (fix vs tidy fallback).
    assert 'class="cal-billboard"' in html_text
    assert 'data-billboard-kind="fix"' in html_text
    # Headline label + saveable value.
    assert "BIGGEST FIX" in html_text
    assert "$612/mo saveable" in html_text
    # Confidence chip rendered as a percentage.
    assert "92% confidence" in html_text
    # CTA anchors back to the savings section so a click lands on detail.
    assert 'href="#inefficiencies"' in html_text
    # When the billboard is present the legacy hero verdict is suppressed.
    assert 'class="cal-hero-verdict"' not in html_text


def test_billboard_tidy_fallback_when_no_fix_available() -> None:
    """When advisor recommendations and inefficiency rows are empty, the
    billboard uses positive framing (YOU'RE TIDY) and shows total spend
    rather than disappearing — Peak-End preserved on a healthy report."""
    tidy = dataclasses.replace(
        sample_dashboard(),
        advisor_recommendations=[],
        inefficiencies=[],
    )
    from caliper.dashboards.adapter import _build_billboard

    bb = _build_billboard(
        advisor_recommendations=tidy.advisor_recommendations,
        inefficiency_rows=tidy.inefficiencies,
        totals=tidy.totals,
        window=tidy.window,
    )
    assert bb is not None
    assert bb.kind == "tidy"
    assert "$1,243" in bb.value
    assert bb.tone == "good"


def test_billboard_hidden_on_empty_dashboard() -> None:
    """Empty window: no events, no billboard — same rule as the legacy
    hero verdict."""
    from caliper.dashboards.adapter import _build_billboard
    from caliper.dashboards.sample_data import empty_dashboard

    empty = empty_dashboard()
    bb = _build_billboard(
        advisor_recommendations=[],
        inefficiency_rows=[],
        totals=empty.totals,
        window=empty.window,
    )
    assert bb is None


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


def test_billboard_tidy_drops_cta_when_no_evidence_section() -> None:
    """The tidy-fallback billboard anchors its CTA at the evidence section.
    When there are no evidence rows that section won't render, so the CTA
    must be omitted rather than linking to a dead anchor."""
    from caliper.dashboards.adapter import _build_billboard
    from caliper.dashboards.html import _render_billboard
    from caliper.dashboards.sample_data import sample_dashboard

    window = sample_dashboard().window
    totals = sample_dashboard().totals
    # No advisor recs, no inefficiencies, no evidence → tidy with no CTA.
    card = _build_billboard(
        advisor_recommendations=[],
        inefficiency_rows=[],
        totals=totals,
        window=window,
        has_evidence=False,
    )
    assert card is not None and card.kind == "tidy"
    assert card.cta_anchor == ""
    html = _render_billboard(card, "receipt")
    assert "cal-billboard-cta" not in html  # no dangling link
    assert "TIDY" in html  # headline still renders (apostrophe is HTML-escaped)

    # With evidence present, the tidy CTA points at the evidence section.
    card_ev = _build_billboard(
        advisor_recommendations=[],
        inefficiency_rows=[],
        totals=totals,
        window=window,
        has_evidence=True,
    )
    assert card_ev is not None and card_ev.cta_anchor == "evidence"
    assert 'href="#evidence"' in _render_billboard(card_ev, "receipt")


def test_receipt_rhythm_renders_sticky_toc_grouped_by_tier() -> None:
    """Phase 2: the receipt rhythm includes a sticky right-rail TOC,
    grouped by tier. Each section anchor must appear as a TOC link with
    ``data-toc-target`` so the scroll-spy JS can resolve it."""
    html_text = render_dashboard(sample_dashboard(show_paths=True))
    assert 'class="cal-receipt-toc"' in html_text
    assert 'aria-label="Section navigation"' in html_text
    # Tier group labels are visible.
    assert ">Decisions<" in html_text
    assert ">Trajectory<" in html_text
    assert ">Appendix<" in html_text
    # Each rendered section has a corresponding TOC link with data-toc-target.
    for sid in ("action-center", "anomalies", "inefficiencies", "overview", "cost"):
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
    assert 'id="models"' in inside
    assert 'id="attribution"' in inside
    # Decisions tier must render BEFORE the appendix block opens.
    assert html_text.index('id="action-center"') < appendix_start
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
    assert "cost = Σ" in html_text
    assert "cache_savings = Σ" in html_text
    assert "total_tokens = uncached_input" in html_text
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
        command_center=[],
        decision_queue=[],
        advisor_recommendations=[],
        top_sessions=[],
        usage_mix=[],
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


def test_insights_without_metrics_omit_the_lineage_chip() -> None:
    """An insight with empty evidence_metrics renders no meta chip — we
    show what we have and stay silent about what we don't."""
    from caliper.dashboards.data_models import (
        CaliperMeta,
        DailyPoint,
        Dashboard,
        EvidenceRow,
        Insight,
        SessionShape,
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
            vendor_count_total=4,
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
        shape=SessionShape(1, 1, 0, 1.0, 1, 1, [], []),
        by_model=[],
        by_project=[],
        anomalies=[],
        insights=[Insight("info", "Quiet week", "No notable findings.", impact=None)],
        forecast=None,
        evidence=[EvidenceRow("Usage completeness", "exact", "")],
    )
    html_text = render_dashboard(minimal, interactive=False)
    # Insight rendered, but no meta chip — evidence_metrics was empty.
    assert "Quiet week" in html_text
    assert 'class="cal-insight-meta"' not in html_text
    # And the privacy gate still holds for this lean payload.
    _assert_private_html(html_text)
