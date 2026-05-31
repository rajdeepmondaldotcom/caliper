"""Browser-backed responsive layout guard for generated dashboard HTML.

Most dashboard tests validate HTML/CSS contracts statically. This one uses a
real browser engine for the failure mode that static tests miss: a grid item
can look valid in CSS but still overflow or collide once the browser lays out
real text at narrow desktop widths.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from caliper.dashboards.html import render_dashboard
from caliper.dashboards.sample_data import sample_dashboard

pytestmark = pytest.mark.skipif(
    os.environ.get("CALIPER_BROWSER_LAYOUT") != "1",
    reason="set CALIPER_BROWSER_LAYOUT=1 to run the browser layout regression",
)

if os.environ.get("CALIPER_BROWSER_LAYOUT") == "1":
    from playwright.sync_api import sync_playwright
else:  # pragma: no cover - import intentionally avoided in normal unit runs.
    sync_playwright = None


VIEWPORT_HEIGHT = 900
VIEWPORT_WIDTHS = tuple(
    sorted(
        {
            *range(320, 1921, 40),
            321,
            359,
            360,
            374,
            375,
            389,
            390,
            411,
            412,
            479,
            480,
            719,
            720,
            721,
            899,
            900,
            901,
            1099,
            1100,
            1101,
            1199,
            1200,
            1201,
            1239,
            1240,
            1241,
            1379,
            1380,
            1381,
            1599,
            1600,
            1601,
            1919,
            1920,
        }
    )
)
DENSITIES = ("comfortable", "compact")


def _stress_dashboard():
    dashboard = sample_dashboard(show_paths=True)
    long = "superlongprojectidentifierwithoutbreaks0123456789" * 2
    totals = dataclasses.replace(
        dashboard.totals,
        cost_usd=14121.0,
        events=91897,
        cache_savings_usd=86358.0,
        cache_hit_rate=0.992,
        total_tokens=16_900_000_000,
        cached_input_tokens=16_700_000_000,
        uncached_input_tokens=128_300_000,
        output_tokens=52_300_000,
        sessions=1013,
        turns=58641,
        tools_per_turn=0.23,
        delta_cost_pct=28.029,
        delta_cache_pct=-0.008,
        delta_tokens_pct=19.559,
        delta_sessions_pct=100.30,
    )
    return dataclasses.replace(
        dashboard,
        totals=totals,
        by_model=[
            dataclasses.replace(row, vendor=f"{row.vendor}-{long}", model=f"{row.model}-{long}")
            for row in dashboard.by_model
        ],
        by_project=[
            dataclasses.replace(
                row,
                name=f"{row.name}-{long}",
                path=f"/tmp/{long}/{row.name}/{long}/src/{long}.py",
            )
            for row in dashboard.by_project
        ],
        top_sessions=[
            dataclasses.replace(
                row,
                label=f"{row.label}-{long}",
                project=f"/tmp/{long}/{row.project}/{long}",
                reason=f"{row.reason} {long}",
                models=[f"{model}-{long}" for model in row.models],
            )
            for row in dashboard.top_sessions
        ],
        advisor_recommendations=[
            dataclasses.replace(
                row,
                title=f"{row.title} {long}",
                detail=f"{row.detail} {long}",
                action=f"{row.action} {long}",
            )
            for row in dashboard.advisor_recommendations
        ],
        inefficiencies=[
            dataclasses.replace(
                row,
                title=f"{row.title} {long}",
                detail=f"{row.detail} {long}",
                action=f"{row.action} {long}",
                baseline=f"{row.baseline}-{long}",
            )
            for row in dashboard.inefficiencies
        ],
        anomalies=[
            dataclasses.replace(
                row,
                label=f"{row.label} {long}",
                reason=f"{row.reason} {long}",
                comparison_scope=f"{row.comparison_scope}-{long}",
            )
            for row in dashboard.anomalies
        ],
        insights=[
            dataclasses.replace(
                row,
                title=f"{row.title} {long}",
                detail=f"{row.detail} {long}",
                impact=f"{row.impact} {long}" if row.impact else row.impact,
            )
            for row in dashboard.insights
        ],
        evidence=[
            dataclasses.replace(
                row,
                label=f"{row.label}-{long}",
                note=f"{row.note} {long}",
            )
            for row in dashboard.evidence
        ],
        budgets=[
            dataclasses.replace(row, period=f"{row.period}-{long[:24]}")
            for row in dashboard.budgets
        ],
    )


def _write_dashboard(tmp_path: Path, *, rhythm: str, interactive: bool, density: str) -> Path:
    mode = "interactive" if interactive else "static"
    path = tmp_path / f"dashboard-{rhythm}-{density}-{mode}.html"
    path.write_text(
        render_dashboard(
            _stress_dashboard(),
            rhythm=rhythm,
            interactive=interactive,
            density=density,
            privacy="off",
        )
    )
    return path


def test_dashboard_layout_has_no_unowned_horizontal_overflow(tmp_path: Path) -> None:
    assert sync_playwright is not None

    files = [
        _write_dashboard(
            tmp_path,
            rhythm=rhythm,
            interactive=interactive,
            density=density,
        )
        for rhythm in ("receipt", "terminal")
        for interactive in (False, True)
        for density in DENSITIES
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for file_path in files:
                page = browser.new_page(
                    viewport={"width": VIEWPORT_WIDTHS[0], "height": VIEWPORT_HEIGHT},
                    device_scale_factor=1,
                )
                page.goto(file_path.as_uri(), wait_until="load")
                try:
                    for width in VIEWPORT_WIDTHS:
                        page.set_viewport_size({"width": width, "height": VIEWPORT_HEIGHT})
                        page.wait_for_timeout(60)
                        failures = page.evaluate(
                            """() => {
                        const failures = [];
                        const rect = (selector) => {
                          const el = document.querySelector(selector);
                          if (!el) return null;
                          const r = el.getBoundingClientRect();
                          return {
                            left: r.left,
                            right: r.right,
                            width: r.width,
                          };
                        };
                        const fmt = (r) =>
                          r ? `${r.left.toFixed(1)}-${r.right.toFixed(1)}` : "missing";
                        const main = rect(".cal-receipt-main") || rect(".cal-terminal-main");
                        const summary = rect(".cal-summary-row");
                        const receiptToc = document.querySelector(".cal-receipt-toc");
                        const toc = rect(".cal-receipt-toc");
                        const tocVisible = receiptToc
                          && getComputedStyle(receiptToc).display !== "none"
                          && toc
                          && toc.width > 0;

                        if (main && summary && summary.right > main.right + 1) {
                          failures.push(`summary row escapes main: ${fmt(summary)} > ${fmt(main)}`);
                        }
                        if (main && tocVisible && main.right > toc.left + 1) {
                          failures.push(`main overlaps receipt toc: ${fmt(main)} vs ${fmt(toc)}`);
                        }
                        if (document.documentElement.scrollWidth > window.innerWidth + 2) {
                          failures.push(
                            `document has horizontal scrollWidth ` +
                            `${document.documentElement.scrollWidth} > ${window.innerWidth}`
                          );
                        }

                        const summaryEl = document.querySelector(".cal-summary-row");
                        if (summaryEl) {
                          const rowRect = summaryEl.getBoundingClientRect();
                          for (const card of summaryEl.children) {
                            const r = card.getBoundingClientRect();
                            if (r.left < rowRect.left - 1 || r.right > rowRect.right + 1) {
                              failures.push(
                                `summary card escapes row: ${fmt({
                                  left: r.left,
                                  right: r.right,
                                })} > ${fmt({
                                  left: rowRect.left,
                                  right: rowRect.right,
                                })}`
                              );
                            }
                          }
                        }

                        const hasOwnedHorizontalScroll = (el) => {
                          for (let node = el.parentElement; node; node = node.parentElement) {
                            const style = getComputedStyle(node);
                            if (style.overflowX === "auto" || style.overflowX === "scroll") {
                              return true;
                            }
                          }
                          return false;
                        };
                        for (const section of document.querySelectorAll("main section[id]")) {
                          const sectionRect = section.getBoundingClientRect();
                          for (const el of section.querySelectorAll("*")) {
                            if (hasOwnedHorizontalScroll(el)) continue;
                            const style = getComputedStyle(el);
                            if (style.display === "none" || style.visibility === "hidden") continue;
                            const r = el.getBoundingClientRect();
                            if (r.width <= 0 || r.height <= 0) continue;
                            if (
                              r.left < sectionRect.left - 1 ||
                              r.right > sectionRect.right + 1
                            ) {
                              failures.push(
                                `section #${section.id} child ` +
                                `${el.tagName.toLowerCase()}.${el.className || ""} ` +
                                `escapes section: ` +
                                `${r.left.toFixed(1)}-${r.right.toFixed(1)} > ` +
                                `${sectionRect.left.toFixed(1)}-${sectionRect.right.toFixed(1)}`
                              );
                              break;
                            }
                          }
                        }
                        const visibleElements = Array.from(document.body.querySelectorAll("*"));
                        for (const el of visibleElements) {
                          const style = getComputedStyle(el);
                          if (style.display === "none" || style.visibility === "hidden") continue;
                          if (hasOwnedHorizontalScroll(el)) continue;
                          const r = el.getBoundingClientRect();
                          if (r.width <= 0 || r.height <= 0) continue;
                          if (r.left < -1 || r.right > window.innerWidth + 1) {
                            failures.push(
                              `${el.tagName.toLowerCase()}.${el.className || ""} ` +
                              `escapes viewport: ` +
                              `${r.left.toFixed(1)}-${r.right.toFixed(1)} of ${window.innerWidth}`
                            );
                            if (failures.length > 20) break;
                          }
                        }
                        return failures;
                      }"""
                        )
                        assert not failures, (
                            f"{file_path.name} at {width}x{VIEWPORT_HEIGHT} has layout failures:\n"
                            + "\n".join(failures)
                        )
                finally:
                    page.close()
        finally:
            browser.close()
