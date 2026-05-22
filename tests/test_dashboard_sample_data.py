"""Sample-data fixture tests for the v2 dashboard.

The v2 dashboard sample exercises the operator-first chrome, privacy modes,
and richer analysis sections while staying self-contained and private.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import caliper.dashboards.sample_data as sample_data
from caliper import __version__
from caliper.dashboards import render_dashboard
from caliper.dashboards.data_models import Banner
from caliper.dashboards.html import _hero_verdict_data

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
    assert dashboard.inefficiencies
    assert dashboard.model_forecasts
    assert dashboard.agents
    assert dashboard.skills
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


def test_sample_dashboard_hero_verdict_story_is_coherent() -> None:
    """The hero verdict numbers must agree with the underlying advisor /
    totals payload. If a designer changes one but not the other, the
    headline becomes a lie and a screenshot reposted on HN exposes it.

    Asserts:
    * recoverable sum is the top-three advisor recs by ``savings_usd``;
    * the top-action title matches the highest-savings recommendation;
    * the trend chip aligns with ``totals.delta_cost_pct``.
    """
    sample = sample_data.sample_dashboard()
    data = _hero_verdict_data(sample)
    assert data is not None, "hero verdict must be available for the populated sample"

    recs = sorted(
        sample.advisor_recommendations,
        key=lambda r: (-float(r.savings_usd or 0.0), -float(r.confidence or 0.0)),
    )
    top_three = [r for r in recs if (r.savings_usd or 0.0) > 0][:3]
    expected_recoverable = sum(float(r.savings_usd or 0.0) for r in top_three)
    assert data["recoverable_usd"] == expected_recoverable
    assert data["rec_count"] == len(top_three)

    top = top_three[0]
    assert data["top_action_title"] == top.title
    assert data["top_action_command"] == top.action
    assert data["top_action_confidence"] == top.confidence

    # Trend sign matches the delta the totals carry.
    delta = sample.totals.delta_cost_pct
    assert delta is not None
    assert data["delta_pct"] == delta
    if delta > 0.02:
        assert data["delta_tone"] == "warn"
    elif delta < -0.02:
        assert data["delta_tone"] == "good"


def test_sample_dashboard_insights_all_carry_evidence_metrics() -> None:
    """Every sample insight must ship evidence_metrics so the lineage
    chip renders. The skeptic-facing 'based on N events · M sessions'
    line is only honest if every insight has the data."""
    sample = sample_data.sample_dashboard()
    for insight in sample.insights:
        assert insight.evidence_metrics, (
            f"Insight {insight.title!r} has empty evidence_metrics — "
            "every sample insight must carry events/sessions/tokens lineage"
        )
        # At least one of the three lineage keys must populate.
        keys = set(insight.evidence_metrics)
        assert keys & {"events", "sessions", "tokens"}, (
            f"Insight {insight.title!r} evidence_metrics has no events/sessions/tokens"
        )


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
