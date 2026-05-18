from __future__ import annotations

import runpy
from pathlib import Path

import caliper.dashboards.sample_data as sample_data
from caliper import __version__
from caliper.dashboards import render_dashboard
from caliper.dashboards.data_models import Banner
from caliper.dashboards.sample_data import empty_dashboard, sample_dashboard

FORBIDDEN = ("://", "<link", " src=", "fetch(", "XMLHttpRequest", "import(")


def _assert_private_static_html(html: str) -> None:
    assert html.count("<script>") == 1
    assert html.count("</script>") == 1
    for needle in FORBIDDEN:
        assert needle not in html


def test_sample_dashboard_uses_current_version_and_renders_variants() -> None:
    dashboard = sample_dashboard(show_paths=True)

    assert dashboard.caliper.version == __version__
    assert dashboard.show_paths is True
    assert dashboard.heatmap is not None
    assert len(dashboard.heatmap.cells) == 365
    assert dashboard.recap is not None
    assert len(dashboard.recap.hours) == 168
    assert [window.label for window in dashboard.usage_windows] == [
        "Last 7 days",
        "Last 30 days",
        "Last 90 days",
    ]
    assert {card.label for card in dashboard.impact_cards} >= {"Budget risk", "Dedupe"}

    html = render_dashboard(dashboard)
    assert "Caliper Dashboard" in html
    assert "api-server" in html
    assert "Command center" in html
    assert "Usage windows" in html
    assert "Impact" in html
    assert "Savings advisor" in html
    assert "Session outliers" in html
    assert dashboard.command_center
    assert dashboard.advisor_recommendations
    assert dashboard.top_sessions
    assert dashboard.usage_mix
    assert dashboard.rate_limit_pressure is not None
    assert dashboard.quality_score is not None
    _assert_private_static_html(html)


def test_empty_sample_dashboard_renders_empty_state() -> None:
    dashboard = empty_dashboard()

    assert dashboard.caliper.version == __version__
    assert dashboard.totals.events == 0

    html = render_dashboard(dashboard, theme="print")
    assert 'data-theme="print"' in html
    assert "no data for this window" in html
    _assert_private_static_html(html)


def test_sample_dashboard_banner_variants_render() -> None:
    partial = render_dashboard(
        sample_dashboard(
            banner=Banner(
                kind="warn",
                label="PARTIAL",
                text="Showing 1 of 4 vendors. Run <code>caliper doctor</code>.",
            )
        )
    )
    stale = render_dashboard(
        sample_dashboard(
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


def test_sample_data_module_writes_six_static_variants(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    runpy.run_path(str(Path(sample_data.__file__)), run_name="__main__")

    out = tmp_path / "out"
    names = sorted(path.name for path in out.glob("*.html"))
    assert names == [
        "empty.html",
        "light.html",
        "print.html",
        "rich.html",
        "stale-banner.html",
        "vendor-banner.html",
    ]
    for path in out.glob("*.html"):
        _assert_private_static_html(path.read_text())
