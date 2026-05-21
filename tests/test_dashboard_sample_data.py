"""Sample-data fixture tests for the v2 dashboard.

The v2 redesign dropped several sections (command-center, usage-windows,
impact cards, recap, agents, skills, forecast-drivers, decision-queue,
metric-glossary, lens controls). These tests verify that the sample data
still produces a self-contained, private HTML document with the new chrome.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import caliper.dashboards.sample_data as sample_data
from caliper import __version__
from caliper.dashboards import render_dashboard
from caliper.dashboards.data_models import Banner

FORBIDDEN = ("://", "<link", " src=", "fetch(", "XMLHttpRequest", "import(")


def _assert_private_static_html(html: str) -> None:
    # v2 produces zero <script> tags.
    assert html.count("<script>") == 0
    assert html.count("</script>") == 0
    for needle in FORBIDDEN:
        assert needle not in html


def test_sample_dashboard_uses_current_version_and_renders_variants() -> None:
    dashboard = sample_data.sample_dashboard(show_paths=True)

    assert dashboard.caliper.version == __version__
    assert dashboard.show_paths is True
    assert dashboard.heatmap is not None
    assert len(dashboard.heatmap.cells) == 365
    assert dashboard.recap is not None
    assert len(dashboard.recap.hours) == 168
    assert dashboard.executive_brief is not None

    html = render_dashboard(dashboard)
    assert "Caliper Dashboard" in html
    assert 'data-theme="dark"' in html
    assert "api-server" in html
    # New design chrome
    assert "CALIPER-" in html  # build id in masthead
    assert "Cost layer for AI-assisted development" in html
    # Verdict strip label is "Verdict" (CSS uppercases it for display).
    assert ">Verdict</span>" in html
    assert dashboard.advisor_recommendations
    assert dashboard.top_sessions
    assert dashboard.rate_limit_pressure is not None
    assert dashboard.quality_score is not None
    _assert_private_static_html(html)


def test_empty_sample_dashboard_renders_empty_state() -> None:
    dashboard = sample_data.empty_dashboard()

    assert dashboard.caliper.version == __version__
    assert dashboard.totals.events == 0

    html = render_dashboard(dashboard, theme="print")
    assert 'data-theme="print"' in html
    assert "No events for this window" in html
    _assert_private_static_html(html)


def test_sample_dashboard_banner_variants_render() -> None:
    partial = render_dashboard(
        sample_data.sample_dashboard(
            banner=Banner(
                kind="warn",
                label="PARTIAL",
                text="Showing 1 of 4 vendors. Run <code>caliper doctor</code>.",
            )
        )
    )
    stale = render_dashboard(
        sample_data.sample_dashboard(
            banner=Banner(
                kind="crit",
                label="STALE",
                text=(
                    "Pricing data is stale. Run <code>caliper rates refresh --allow-network</code>."
                ),
            )
        )
    )

    assert "PARTIAL" in partial
    assert "STALE" in stale
    _assert_private_static_html(partial)
    _assert_private_static_html(stale)


def test_sample_dashboard_share_safe_attribute() -> None:
    share_html = render_dashboard(sample_data.sample_dashboard(show_paths=True), share_safe=True)
    assert 'data-share-safe="true"' in share_html
    full_html = render_dashboard(sample_data.sample_dashboard(show_paths=True))
    assert 'data-share-safe="false"' in full_html
    _assert_private_static_html(share_html)
    _assert_private_static_html(full_html)


def test_sample_data_module_writes_static_variants(monkeypatch, tmp_path) -> None:
    """The sample-data module's ``__main__`` block emits static HTML variants
    for design review."""
    monkeypatch.chdir(tmp_path)

    runpy.run_path(str(Path(sample_data.__file__)), run_name="__main__")

    out = tmp_path / "out"
    names = sorted(path.name for path in out.glob("*.html"))
    # The exact set is sample_data's concern, but every emitted file must be
    # privacy-safe.
    assert names, "sample_data __main__ produced no HTML variants"
    for path in out.glob("*.html"):
        _assert_private_static_html(path.read_text())
