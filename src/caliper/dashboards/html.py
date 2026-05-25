"""
Caliper dashboard — HTML renderer (v2 redesign).

Produces a single, offline HTML report from a populated :class:`Dashboard`.
The renderer is a 1:1 port of the approved design prototype
(``caliper-design-handoff/``). It emits pure HTML + CSS + inline SVG — no
JavaScript, no external resources.

Two layout *rhythms* share the same section bodies:

* ``receipt`` — engineer-grade receipt (default).
* ``terminal`` — Bloomberg/audit-terminal feel with a sticky left index rail
  and a top ticker.

Themes (dark / light / print) are CSS classes stamped on the root.
Density (comfortable / compact) is a CSS class stamped on the root.
``@media print`` forces print tokens regardless of selected theme so
``Cmd+P`` always prints clean.

This module exports:

* :data:`INLINE_STYLES` — byte-equivalent of ``styles.css``. The on-disk file
  is the source the designer edits; this constant is the inlined copy that
  ships in the report. ``tests/test_handoff_styles.py`` guards the equality.
* :func:`render_dashboard` — public entrypoint.
* Small formatting helpers (``fmt_money``, ``fmt_tokens``, ``fmt_int``,
  ``fmt_pct``) — kept module-level so tests and external scripts can import.
* :func:`render_models`, :func:`render_projects` — table renderers exposed
  for unit tests; both return self-contained HTML fragments.
"""

from __future__ import annotations

import html
import math
from collections.abc import Iterable, Sequence
from contextvars import ContextVar
from typing import Any

from .data_models import (
    AdvisorRecommendation,
    AgentRow,
    Banner,
    BillboardCard,
    BriefFinding,
    Dashboard,
    Forecast,
    Insight,
    ModelRow,
    ProjectRow,
    QualityScore,
    RateLimitPressure,
    Recap,
    SessionRow,
    SessionShape,
    Totals,
    WindowMeta,
)

__all__ = [
    "INLINE_STYLES",
    "SECTION_NUMBERS",
    "fmt_money",
    "fmt_tokens",
    "fmt_int",
    "fmt_pct",
    "render_dashboard",
    "render_models",
    "render_projects",
]


# ============================================================================
# Inline stylesheet — must remain byte-equivalent to styles.css
# ============================================================================

INLINE_STYLES = """
/* Caliper dashboard — CSS tokens (dark / light / print) + accent variants + density. */

:root {
  /* dark by default */
  --bg: #090d13;
  --bg-2: #0d131b;
  --panel: #131922;
  --panel-2: #19212b;
  --panel-hover: #202a36;
  --border: #2a3340;
  --border-strong: #3a4654;
  --grid: rgba(255,255,255,0.065);
  --bar-ghost: rgba(255,255,255,0.022);
  --hairline: rgba(255,255,255,0.09);

  --ink: #f2f5f8;
  --ink-2: #d3d8e2;
  --mute: #a1a9b7;
  --ghost: #838d9d;

  --accent: #7cc4ff;
  --accent-strong: #54aef0;
  --accent-soft: #b3dcff;
  --accent-tint: rgba(124,196,255,0.10);
  --accent-tint-2: rgba(124,196,255,0.18);
  --accent-tint-3: rgba(124,196,255,0.06);

  --ok: #7be092;
  --warn: #f5c971;
  --bad: #f08585;
  --ok-tint: rgba(123,224,146,0.10);
  --warn-tint: rgba(245,201,113,0.10);
  --bad-tint: rgba(240,133,133,0.10);

  --card-rail-cost: var(--accent-tint-2);
  --card-rail-cache: rgba(123,224,146,0.32);
  --card-rail-tokens: var(--accent-tint-2);
  --card-rail-sessions: rgba(167,139,250,0.32);

  --explore: #7cc4ff;
  --execute: #a78bfa;
  --diagnose: #f5c971;
  --mixed: #858d9b;

  /* Type stack — premium system fallback chain.
     -apple-system → SF Pro (macOS), Segoe UI Variable → Windows 11,
     system-ui → Linux/everywhere else. No CDN. */
  --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
          "Segoe UI Variable Text", "Segoe UI", system-ui, "Helvetica Neue",
          "Inter", Roboto, "Liberation Sans", sans-serif;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code",
          "Cascadia Mono", Menlo, Consolas, monospace;

  --num-xl: 30px;
  --num-lg: 24px;
  --num-md: 19px;
  --num-sm: 15px;

  --r-sm: 3px;
  --r-md: 5px;
  --r-lg: 7px;

  --row-pad-y: 12px;
  --row-pad-x: 16px;

  /* Phase 1 UX overhaul — single spacing scale (4/8/12/16/24/32) used by
     billboard, severity chips, appendix block. Older sections still use
     their own paddings; new components should reach for these tokens. */
  --sp-xxs: 4px;
  --sp-xs: 8px;
  --sp-s: 12px;
  --sp-m: 16px;
  --sp-l: 24px;
  --sp-xl: 32px;
}

/* Light theme */
.theme-light {
  --bg: #f6f7f9;
  --bg-2: #fbfbfd;
  --panel: #ffffff;
  --panel-2: #fafbfc;
  --panel-hover: #f3f5f8;
  --border: #e6e8ec;
  --border-strong: #cfd3da;
  --grid: rgba(0,0,0,0.045);
  --bar-ghost: rgba(0,0,0,0.025);
  --hairline: rgba(0,0,0,0.07);

  --ink: #0e1116;
  --ink-2: #353a44;
  --mute: #5a626e;
  --ghost: #5f6775;

  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --accent-soft: #93b8ff;
  --accent-tint: rgba(37,99,235,0.08);
  --accent-tint-2: rgba(37,99,235,0.16);

  --ok: #0f7a37;
  --warn: #a84d07;
  --bad: #b91c1c;
  --ok-tint: rgba(22,163,74,0.08);
  --warn-tint: rgba(180,83,9,0.08);
  --bad-tint: rgba(185,28,28,0.08);

  --card-rail-cost: var(--accent-tint-2);
  --card-rail-cache: rgba(22,163,74,0.28);
  --card-rail-tokens: var(--accent-tint-2);
  --card-rail-sessions: rgba(124,58,237,0.28);

  --explore: #2563eb;
  --execute: #7c3aed;
  --diagnose: #b45309;
  --mixed: #6b7280;
}

/* Print theme */
.theme-print {
  --bg: #ffffff;
  --bg-2: #ffffff;
  --panel: #ffffff;
  --panel-2: #fafafa;
  --panel-hover: #ffffff;
  --border: #cccccc;
  --border-strong: #888888;
  --grid: rgba(0,0,0,0.10);
  --bar-ghost: rgba(0,0,0,0.04);
  --hairline: rgba(0,0,0,0.18);

  --ink: #000000;
  --ink-2: #1a1a1a;
  --mute: #4a4a4a;
  --ghost: #6a6a6a;

  --accent: #0050b3;
  --accent-strong: #003a82;
  --accent-soft: #2a72c2;
  --accent-tint: rgba(0,80,179,0.08);
  --accent-tint-2: rgba(0,80,179,0.15);

  --ok: #0050b3;
  --warn: #8a5a00;
  --bad: #b00020;
  --ok-tint: rgba(0,80,179,0.06);
  --warn-tint: rgba(138,90,0,0.06);
  --bad-tint: rgba(176,0,32,0.06);

  --card-rail-cost: var(--accent-tint-2);
  --card-rail-cache: rgba(0,80,179,0.20);
  --card-rail-tokens: var(--accent-tint-2);
  --card-rail-sessions: rgba(0,80,179,0.20);

  --explore: #0050b3;
  --execute: #6a4cb8;
  --diagnose: #8a5a00;
  --mixed: #4a4a4a;
}

/* Accent variants — override colors without changing theme */
.accent-blue   { --accent: #7cc4ff; --accent-strong: #54aef0; --explore: #7cc4ff; --accent-tint: rgba(124,196,255,0.10); --accent-tint-2: rgba(124,196,255,0.18); --card-rail-cost: var(--accent-tint-2); --card-rail-tokens: var(--accent-tint-2); }
.accent-teal   { --accent: #5eead4; --accent-strong: #2dd4bf; --explore: #5eead4; --accent-tint: rgba(94,234,212,0.10); --accent-tint-2: rgba(94,234,212,0.20); --card-rail-cost: var(--accent-tint-2); --card-rail-tokens: var(--accent-tint-2); }
.accent-purple { --accent: #c4b5fd; --accent-strong: #a78bfa; --explore: #c4b5fd; --accent-tint: rgba(196,181,253,0.10); --accent-tint-2: rgba(196,181,253,0.20); --card-rail-cost: var(--accent-tint-2); --card-rail-tokens: var(--accent-tint-2); }
.accent-mono   { --accent: #e8eaef; --accent-strong: #c4c9d3; --explore: #e8eaef; --accent-tint: rgba(232,234,239,0.06); --accent-tint-2: rgba(232,234,239,0.12); --card-rail-cost: var(--accent-tint-2); --card-rail-tokens: var(--accent-tint-2); }

.theme-light.accent-blue   { --accent: #2563eb; --accent-strong: #1d4ed8; --explore: #2563eb; --accent-tint: rgba(37,99,235,0.08); --accent-tint-2: rgba(37,99,235,0.16); }
.theme-light.accent-teal   { --accent: #0d9488; --accent-strong: #115e59; --explore: #0d9488; --accent-tint: rgba(13,148,136,0.08); --accent-tint-2: rgba(13,148,136,0.18); }
.theme-light.accent-purple { --accent: #7c3aed; --accent-strong: #5b21b6; --explore: #7c3aed; --accent-tint: rgba(124,58,237,0.08); --accent-tint-2: rgba(124,58,237,0.16); }
.theme-light.accent-mono   { --accent: #0e1116; --accent-strong: #000;    --explore: #0e1116; --accent-tint: rgba(14,17,22,0.05);  --accent-tint-2: rgba(14,17,22,0.12); }

/* Density variants */
.density-compact {
  --row-pad-y: 8px;
  --row-pad-x: 12px;
  --num-xl: 26px;
  --num-lg: 20px;
  --num-md: 17px;
}
.density-compact .cal-stat-card { padding: 12px !important; }
.density-compact .cal-table th, .density-compact .cal-table td { padding: 7px 10px !important; }
.density-compact .cal-insight-row { padding: 9px 12px !important; }
.density-compact section { gap: 18px; }

/* Base */
html, body { background: var(--bg); margin: 0; padding: 0; }
body {
  font-family: var(--font);
  font-size: 14px;
  line-height: 1.5;
  color: var(--ink);
  font-feature-settings: "kern" 1, "calt" 1, "liga" 1, "ss01" 1, "cv02" 1, "cv11" 1;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
* { box-sizing: border-box; }
*, *::before, *::after { font-variant-numeric: tabular-nums lining-nums; }

a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-strong); text-decoration: underline; text-underline-offset: 2px; }
code { font-family: var(--mono); font-size: 0.92em; }
table { font-variant-numeric: tabular-nums lining-nums; }

/* Layout primitives emitted by the Python renderer. These classes let the
   static report respond to real browser viewports, not only the prototype's
   data-viewport frame. */
.cal-dashboard-root { min-width: 0; }
.cal-receipt-root {
  max-width: 1240px;
  margin: 0 auto;
  padding: 36px 32px 72px;
  font-family: var(--font);
  color: var(--ink);
}
.cal-terminal-root {
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font);
}
.cal-terminal-layout {
  display: grid;
  grid-template-columns: 212px minmax(0, 1fr);
  gap: 0;
  max-width: 1400px;
  margin: 0 auto;
}
.cal-terminal-main {
  min-width: 0;
  padding: 32px 34px 72px;
}
.cal-summary-row {
  grid-auto-rows: 1fr;
  align-items: stretch;
}
.cal-stat-card {
  min-width: 0;
  min-height: 142px;
  display: flex;
  flex-direction: column;
}
.cal-stat-card-value { overflow-wrap: anywhere; }
.cal-card-sparkline {
  min-width: 0;
  margin-top: auto;
  padding-top: 8px;
}
.cal-cost-panel {
  min-width: 0;
  box-shadow: inset 0 0 0 1px var(--hairline);
}

/* Hero verdict — the single line a screenshot reader can quote. Reads the
   selected window cost, the trend chip, and the highest-leverage advisor
   savings. Hairline border with an accent left rail; no novel tokens so
   light/print themes inherit cleanly. */
.cal-hero-verdict {
  box-shadow: inset 0 0 0 1px var(--hairline);
  transition: background-color 120ms ease-out, border-color 120ms ease-out;
}
.cal-hero-verdict:hover { background: var(--panel-hover); }
.cal-hero-cost { font-variant-numeric: tabular-nums lining-nums; }
.cal-hero-action-command::selection { background: var(--accent-tint-2); }

/* Show-the-math disclosure on KPI cards. Hides the default summary marker
   so the eye reads our "?" affordance; otherwise styling stays inline. */
.cal-card-formula > summary { list-style: none; }
.cal-card-formula > summary::-webkit-details-marker { display: none; }
.cal-card-formula > summary::marker { display: none; }
.cal-card-formula > summary:hover { color: var(--ink-2) !important; }
.cal-card-formula[open] > summary { color: var(--ink-2) !important; }

/* Per-insight lineage chip ("based on N events · M sessions · X tokens").
   Only rendered when Insight.evidence_metrics carries those keys. */
.cal-insight-meta { font-variant-numeric: tabular-nums lining-nums; }

/* Tables are intentionally static: no row hover tint, rail, or native
   tooltip. Scanning dense spend data should not cause visual movement. */
.cal-table {
  min-width: 0;
  /* Auto layout so columns size to their content. Fixed layout was
     squeezing the model · tier column and forcing hyphen-breaks like
     "claude-/sonnet-4-6 ·/standard". */
  table-layout: auto;
}
.cal-table-panel,
.cal-attribution-grid > * {
  min-width: 0;
}
.cal-table-scroll {
  max-width: 100%;
}
.cal-table th,
.cal-table td {
  vertical-align: middle;
  line-height: 1.42;
}
.cal-table tbody tr:nth-child(even) { background: rgba(255,255,255,0.018); }
.cal-table td {
  /* Breaks at word boundaries only — never inside identifiers like
     "claude-sonnet-4-6" or numerics like "65%". */
  overflow-wrap: break-word;
  word-break: normal;
}
.cal-table td > div {
  min-width: 0;
}
/* Numeric / mono cells never wrap and align on their decimal column. */
.cal-table td[data-num="true"],
.cal-table th[data-num="true"] {
  white-space: nowrap;
  font-variant-numeric: tabular-nums lining-nums;
}
/* Model · tier cells: tokens stay whole; wrap only at the separator. */
.cal-cell-model { display: inline-flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.cal-cell-model > span { white-space: nowrap; }
/* Share cells: percentage and meter ride together; no orphan "%" lines. */
.cal-cell-share { white-space: nowrap; }

.cal-anomaly-row,
.cal-insight-row {
  min-width: 0;
}
.cal-anomaly-main {
  min-width: 0;
}
.cal-anomaly-side {
  min-width: max-content;
}
.cal-metric-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.cal-metric-chip {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--panel-2);
  padding: 4px 7px;
  white-space: nowrap;
}
.cal-metric-label {
  font-size: 10px;
  color: var(--mute);
  font-weight: 600;
}
.cal-metric-value {
  font-size: 11px;
  color: var(--ink);
  font-family: var(--mono);
  font-weight: 600;
}

/* Section spacing */
section[id] { scroll-margin-top: 36px; }

/* Terminal left-rail link hover. The legacy ``section[id]:target`` inset
   rail was removed because it visually collided with the section-number
   column at x=0. The TOC's ``aria-current="location"`` already shows the
   reader where they are; no need to double-mark inside the section. */
.cal-rail-link:hover { color: var(--accent) !important; background: var(--accent-tint); }

/* Mobile responsive — when wrapping element has data-viewport=mobile */
[data-viewport="mobile"] .cal-summary-row { grid-template-columns: 1fr 1fr !important; }
[data-viewport="mobile"] .cal-shape-grid,
[data-viewport="mobile"] .cal-forecast-grid { grid-template-columns: 1fr !important; }
[data-viewport="mobile"] .cal-table { font-size: 12px !important; }
[data-viewport="mobile"] .cal-receipt-toc,
[data-viewport="mobile"] .cal-terminal-index { display: none !important; }
[data-viewport="mobile"] header { grid-template-columns: 1fr !important; }
[data-viewport="mobile"] header > div:last-child { text-align: left !important; align-items: flex-start !important; }
[data-viewport="mobile"] .cal-section-head.receipt { flex-wrap: wrap; row-gap: 4px; }
[data-viewport="mobile"] [class*="cal-verdict"] { font-size: 13px; }
[data-viewport="mobile"] main { padding: 16px 14px 48px !important; }
[data-viewport="mobile"] [data-screen-label] { min-width: 0; }
[data-viewport="mobile"] .cal-stat-card { padding: 12px !important; }
[data-viewport="mobile"] .cal-stat-card-value { font-size: 22px !important; }
[data-viewport="mobile"] .cal-receipt-root { padding: 16px 14px 48px !important; }
[data-viewport="mobile"] .cal-receipt-main { overflow-x: hidden; }
[data-viewport="mobile"] .cal-terminal-layout { grid-template-columns: 1fr !important; }
[data-viewport="mobile"] .cal-terminal-main { padding: 20px 16px 64px !important; }

@media (max-width: 720px) {
  body { overflow-x: hidden; }
  .cal-receipt-root { padding: 16px 14px 48px !important; }
  .cal-receipt-main { overflow-x: hidden; }
  .cal-terminal-layout { grid-template-columns: 1fr !important; }
  .cal-terminal-main { padding: 20px 16px 64px !important; }
  .cal-summary-row {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 10px !important;
  }
  .cal-shape-grid,
  .cal-forecast-grid { grid-template-columns: 1fr !important; }
  .cal-table {
    font-size: 12px !important;
    width: 100%;
  }
  .cal-table th,
  .cal-table td {
    padding: 8px 9px !important;
  }
  .cal-anomaly-row {
    grid-template-columns: 1fr !important;
    gap: 12px !important;
    padding: 14px 16px !important;
  }
  .cal-anomaly-side {
    align-items: center !important;
    flex-direction: row !important;
    flex-wrap: wrap !important;
    justify-content: space-between !important;
    min-width: 0;
    width: 100%;
    gap: 8px !important;
  }
  .cal-anomaly-side > * { white-space: nowrap; }
  /* Metric chips fill the row two-up so users see all four metrics
     without horizontal scrolling. */
  .cal-metric-strip { gap: 8px !important; }
  .cal-metric-chip {
    flex: 1 1 calc(50% - 4px) !important;
    padding: 6px 9px !important;
  }
  .cal-metric-label { font-size: 11px !important; }
  .cal-metric-value { font-size: 12px !important; }
  .cal-insight-row {
    grid-template-columns: 1fr !important;
    gap: 8px !important;
  }
  .cal-metric-chip {
    flex: 1 1 132px;
  }
  /* Don't hide columns on mobile — the .cal-table-scroll wrapper provides
     horizontal scroll, so Cost/Tokens/Events stay reachable instead of being
     silently dropped. */
  .cal-receipt-toc,
  .cal-terminal-index { display: none !important; }
  header {
    grid-template-columns: 1fr !important;
    gap: 18px !important;
  }
  header > div:last-child {
    text-align: left !important;
    align-items: flex-start !important;
  }
  header > div:last-child > div {
    flex-wrap: wrap !important;
    justify-content: flex-start !important;
    max-width: 100%;
  }
  .cal-evidence-badge,
  .cal-window-badge {
    max-width: 100%;
  }
  .cal-window-badge {
    flex-wrap: wrap;
    white-space: normal !important;
    row-gap: 2px;
  }
  .cal-section-head.receipt {
    flex-wrap: wrap;
    row-gap: 4px;
  }
  .cal-section-head.receipt > * { min-width: 0; }
  .cal-section-head.receipt > span:last-child {
    width: 100%;
    text-align: left !important;
    white-space: normal !important;
  }
  [class*="cal-verdict"] { font-size: 13px; }
  main { padding: 16px 14px 48px !important; }
  [data-screen-label] { min-width: 0; }
  .cal-stat-card {
    padding: 12px !important;
    min-height: 136px;
  }
  .cal-stat-card-value { font-size: 22px !important; }
  .cal-terminal-mast {
    grid-template-columns: 1fr !important;
    gap: 10px !important;
    padding: 14px 16px !important;
  }
  .cal-terminal-mast .cal-terminal-brand,
  .cal-terminal-mast .cal-terminal-badges {
    border: 0 !important;
    padding: 0 !important;
    justify-content: flex-start !important;
  }
  .cal-terminal-mast .cal-terminal-stats {
    justify-content: flex-start !important;
  }
  .cal-tweaks-panel {
    left: 12px;
    right: 12px;
    bottom: 12px;
    flex-wrap: wrap;
    border-radius: var(--r-md);
    justify-content: center;
  }
}

/* Mobile viewport: render at 390px wide in a phone-shaped frame */
.viewport-mobile-frame {
  width: 390px; min-height: 844px;
  margin: 0 auto;
  border: 1px solid var(--border-strong);
  border-radius: 28px;
  overflow: hidden;
  box-shadow: 0 8px 40px rgba(0,0,0,0.25);
}

/* Print stylesheet (used when actually printing OR when theme-print is set) */
.theme-print, .theme-print * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
@media print {
  body { background: #fff !important; }
  /* Force print tokens regardless of selected theme so Cmd+P always prints clean. */
  :root, .theme-dark, .theme-light {
    --bg: #ffffff !important;
    --bg-2: #ffffff !important;
    --panel: #ffffff !important;
    --panel-2: #fafafa !important;
    --panel-hover: #ffffff !important;
    --border: #cccccc !important;
    --border-strong: #888888 !important;
    --grid: rgba(0,0,0,0.10) !important;
    --bar-ghost: rgba(0,0,0,0.04) !important;
    --hairline: rgba(0,0,0,0.18) !important;
    --ink: #000000 !important;
    --ink-2: #1a1a1a !important;
    --mute: #4a4a4a !important;
    --ghost: #6a6a6a !important;
    --accent: #0050b3 !important;
    --accent-strong: #003a82 !important;
    --accent-tint: rgba(0,80,179,0.08) !important;
    --accent-tint-2: rgba(0,80,179,0.15) !important;
    --ok: #0050b3 !important;
    --warn: #8a5a00 !important;
    --bad: #b00020 !important;
    --explore: #0050b3 !important;
    --execute: #6a4cb8 !important;
    --diagnose: #8a5a00 !important;
    --mixed: #4a4a4a !important;
  }
  .tweaks-host, .preview-chrome, [class*="twk-"] { display: none !important; }
  /* Print densification — every section stays visible so a board pack
     never quietly drops anomalies, advisor, or budget burn. We scale the
     tokens instead of hiding rows. Each section still gets break-inside:
     avoid so a card doesn't split across pages, but the page itself can
     grow to as many sheets as the content honestly needs. */
  :root, .theme-dark, .theme-light {
    --num-xl: 22px !important;
    --num-lg: 19px !important;
    --num-md: 16px !important;
    --num-sm: 13px !important;
    --row-pad-y: 6px !important;
    --row-pad-x: 10px !important;
  }
  .cal-stat-card {
    min-height: 0 !important;
    padding: 10px !important;
  }
  .cal-stat-card-value { font-size: 22px !important; }
  .cal-table th, .cal-table td { padding: 6px 10px !important; }
  .cal-section-head.receipt h2,
  .cal-section-head.term span { font-size: 11px !important; }
  /* Heatmap and per-day strips: keep them but scale the cells so the
     yearly grid prints as a compact ribbon, not a half-page mural. */
  .cal-heatmap-cell { width: 9px !important; height: 9px !important; }
  /* Sparklines: small but kept so the trend story prints. */
  .cal-card-sparkline svg { max-height: 18px !important; }
  /* Hide the show-the-math disclosure when printing — the formulas are
     intentionally interactive ink. The body stays legible without them. */
  .cal-card-formula { display: none !important; }
  /* Interactive toggle panel never belongs in PDF. */
  .cal-tweaks-panel { display: none !important; }
  section { break-inside: avoid; }
  .cal-stat-card, .cal-banner, .cal-table, [data-screen-label] { break-inside: avoid; }
  body { font-size: 10.5pt !important; line-height: 1.45 !important; }
}
@media print {
  details.cal-appendix > .cal-appendix-body { display: grid !important; }
  details.cal-appendix .cal-appendix-chev { transform: rotate(90deg); }
}
.theme-print details.cal-appendix > .cal-appendix-body { display: grid !important; }
.theme-print details.cal-appendix .cal-appendix-chev { transform: rotate(90deg); }

/* Lift focus rings */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }

/* Selection */
::selection { background: var(--accent-tint-2); color: var(--ink); }

/* Receipt section head — premium typography rhythm.
   The underline used to draw an extra hairline across every section
   header, doubling visual weight against the masthead's already-bold
   divider. Whitespace alone is enough to separate sections now that
   the vertical grid gap is generous (40px). */
.cal-section-head.receipt {
  position: relative;
  padding-bottom: 0;
  border-bottom: none;
  margin-bottom: 20px;
}
.cal-section-head.receipt h2 {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.005em;
  color: var(--ink);
}
.cal-section-head.receipt .cal-section-num {
  font-family: var(--mono);
  /* Size matches the section title so the "1." reads as a paired
     numeral, not an afterthought. Slightly muted colour + 600 weight
     keeps the title as the dominant element. */
  font-size: 17px;
  letter-spacing: -0.005em;
  color: var(--mute);
  font-weight: 600;
  /* Fixed column so titles align vertically across sections. The width
     fits "10." comfortably at 17px mono. */
  min-width: 30px;
  display: inline-block;
}

/* Pretty wrap */
p, h1, h2, h3 { text-wrap: pretty; }

/* ============================================================================
   Hover polish — only on devices with real pointers, never during print.
   Disabled cleanly by the print theme + @media print blocks above. */
@media (hover: hover) and (pointer: fine) {
  /* Stat cards: stable hover state that never changes layout geometry. */
  .cal-stat-card {
    transition: border-color 120ms ease-out, box-shadow 120ms ease-out,
                background-color 120ms ease-out;
  }
  .cal-stat-card:hover {
    border-color: var(--border-strong);
    background: var(--panel-hover);
    box-shadow: inset 0 0 0 1px var(--hairline);
  }
  /* Bar chart rects: brighten the filled bar and reveal the built-in
     SVG label without shifting anything around it. */
  .cal-bar-rect { transition: fill-opacity 120ms ease-out; }
  .cal-bar-group:hover .cal-bar-rect,
  .cal-bar-group:focus .cal-bar-rect { fill-opacity: 0.82; }
  .cal-bar-hover-label {
    opacity: 0;
    pointer-events: none;
    transition: opacity 80ms ease-out;
  }
  .cal-bar-group:hover .cal-bar-hover-label,
  .cal-bar-group:focus .cal-bar-hover-label { opacity: 1; }
  /* Verdict-strip pill links: existing <a> gets underline; the chip gets
     a stable contrast state. */
  .cal-verdict-chip { display: inline-block; }
  .cal-verdict-chip:hover > span {
    background: var(--panel-hover) !important;
    border-color: var(--accent-tint-2) !important;
  }
  /* Heatmap cells: highlight the hovered cell so the user can scan
     the matrix without losing their place. */
  .cal-heatmap-cell {
    transition: box-shadow 100ms ease-out, border-color 100ms ease-out;
  }
  .cal-heatmap-cell:hover {
    box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 2px var(--accent-tint);
    z-index: 1;
    position: relative;
  }
  /* Pills/badges sitting outside the verdict strip — soft highlight. */
  a:hover > span[class=""], a:hover > span:not([class]) {
    background: var(--panel-hover);
  }
}

/* Terminal masthead — three zones with hairline dividers, monospace,
   icon prominent. Keeps the brand / stats / badges from kissing each
   other on narrow viewports. */
.cal-terminal-mast {
  border-bottom: 1px solid var(--border-strong);
  background: var(--panel);
  padding: 14px 28px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 20px;
  align-items: center;
  font-family: var(--mono);
  min-width: 0;
}
.cal-terminal-mast .cal-terminal-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-right: 20px;
  border-right: 1px solid var(--border);
  min-width: 0;
  flex-wrap: wrap;
}
.cal-terminal-mast .cal-terminal-stats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  font-size: 11px;
  color: var(--mute);
  flex-wrap: wrap;
  row-gap: 4px;
  min-width: 0;
}
.cal-terminal-mast .cal-terminal-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  padding-left: 20px;
  border-left: 1px solid var(--border);
  min-width: 0;
  flex-wrap: wrap;
}
[data-viewport="mobile"] .cal-terminal-mast {
  grid-template-columns: 1fr;
  gap: 10px;
}
[data-viewport="mobile"] .cal-terminal-mast .cal-terminal-brand,
[data-viewport="mobile"] .cal-terminal-mast .cal-terminal-badges {
  border: 0;
  padding: 0;
  justify-content: flex-start;
}

/* Disable any hover transforms during actual print so the PDF is static. */
@media print {
  .cal-stat-card:hover { box-shadow: none !important; }
  .cal-heatmap-cell:hover { box-shadow: none !important; }
}

/* Interactive playground — rhythm swap, tweaks panel, save button.
   The renderer emits BOTH rhythm bodies when interactive mode is on, and
   the active one is selected by a root-level data-rhythm attribute. */
[data-rhythm="receipt"]  .cal-rhythm-terminal { display: none !important; }
[data-rhythm="terminal"] .cal-rhythm-receipt  { display: none !important; }

.cal-tweaks-panel {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.32);
  font-family: var(--font);
  font-size: 12px;
  color: var(--ink-2);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
body[data-interactive="true"] .cal-receipt-root,
body[data-interactive="true"] .cal-terminal-main {
  padding-bottom: 116px !important;
}
.cal-tweaks-panel .cal-tweaks-section { display: flex; align-items: center; gap: 6px; }
.cal-tweaks-panel .cal-tweaks-label {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0;
  text-transform: uppercase;
  color: var(--mute);
  margin-right: 2px;
}
.cal-tweaks-panel .cal-tweaks-group {
  display: inline-flex;
  align-items: center;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px;
  gap: 1px;
}
.cal-tweaks-panel .cal-tweaks-btn {
  appearance: none;
  background: transparent;
  border: 0;
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 120ms ease-out, color 120ms ease-out;
}
.cal-tweaks-panel .cal-tweaks-btn:hover { color: var(--ink); background: var(--panel-hover); }
.cal-tweaks-panel .cal-tweaks-btn.is-active {
  background: var(--accent-tint-2);
  color: var(--ink);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--accent-tint);
}
.cal-tweaks-panel .cal-tweaks-divider {
  width: 1px;
  height: 22px;
  background: var(--border);
  margin: 0 2px;
}
.cal-tweaks-panel .cal-tweaks-save {
  appearance: none;
  background: var(--accent-tint-2);
  border: 1px solid var(--accent-tint);
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 120ms ease-out, color 120ms ease-out;
}
.cal-tweaks-panel .cal-tweaks-save:hover { background: var(--accent); color: var(--bg); }
.cal-tweaks-panel .cal-tweaks-save:active { background: var(--accent-strong); color: var(--bg); }
.cal-tweaks-panel .cal-tweaks-arrow {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top: 0;
  border-right: 0;
  transform: rotate(-45deg) translate(1px, -1px);
}
/* Visible search button — touch users' entry to the cmd+K palette. */
.cal-tweaks-panel .cal-tweaks-search {
  appearance: none;
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  padding: 5px 10px 5px 8px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  transition: background-color 120ms ease-out, color 120ms ease-out,
              border-color 120ms ease-out;
}
.cal-tweaks-panel .cal-tweaks-search:hover {
  background: var(--accent-tint);
  color: var(--ink);
  border-color: var(--accent-tint-2);
}
.cal-tweaks-panel .cal-tweaks-search:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.cal-tweaks-search-icon {
  font-size: 14px;
  line-height: 1;
  color: var(--accent);
}
.cal-tweaks-search-hint {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ghost);
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 3px;
  margin-left: 2px;
}
/* Floating, never blocks printing or PDF export. */
@media print { .cal-tweaks-panel { display: none !important; } }
[data-viewport="mobile"] .cal-tweaks-panel {
  left: 12px;
  right: 12px;
  bottom: 12px;
  flex-wrap: wrap;
  border-radius: var(--r-md);
  justify-content: center;
}

/* Mobile responsive — tweaks panel + palette + billboard CTA.

   The tweaks panel docks to the bottom of the viewport on phones and
   compacts so it doesn't steal a third of the screen. The palette gets
   touch-friendly tap targets. The billboard CTA spans the full width so
   "Investigate" is a 44px+ touch target. */
@media (max-width: 720px) {
  .cal-tweaks-panel {
    left: 8px;
    right: 8px;
    bottom: 8px;
    padding: 8px 10px;
    gap: 8px;
    font-size: 11px;
    -webkit-backdrop-filter: blur(12px);
    backdrop-filter: blur(12px);
    background: color-mix(in srgb, var(--panel) 92%, transparent);
  }
  .cal-tweaks-panel .cal-tweaks-label,
  .cal-tweaks-search-hint,
  .cal-tweaks-search-label { display: none; }
  .cal-tweaks-panel .cal-tweaks-search {
    padding: 7px 10px;
    min-width: 44px;
    min-height: 44px;
    justify-content: center;
  }
  .cal-tweaks-panel .cal-tweaks-btn { padding: 6px 12px; min-height: 44px; }
  .cal-tweaks-panel .cal-tweaks-save { padding: 7px 14px; min-height: 44px; }
  .cal-tweaks-panel .cal-tweaks-divider { display: none; }
  /* Reserve space at the bottom of the page so the floating panel never
     covers the trust footer. */
  .cal-receipt-root { padding-bottom: 96px !important; }

  /* Heatmap: scroll horizontally with legible (>=13px) cells instead of
     squishing 24 hour columns into unreadable slivers. */
  .cal-heatmap-scroll { overflow-x: auto; }
  .cal-heatmap-cols { grid-template-columns: repeat(24, 13px) !important; }

  /* Palette dialog — bigger input, taller rows for thumbs. */
  .cal-palette { padding-top: 8vh; }
  .cal-palette-dialog { width: calc(100vw - 16px); border-radius: var(--r-md); }
  .cal-palette-input {
    font-size: 16px; /* prevents iOS zoom-on-focus */
    padding: 16px 18px;
  }
  .cal-palette-item {
    padding: 12px 16px;
    grid-template-columns: 60px minmax(0, 1fr) auto;
    min-height: 48px;
  }
  .cal-palette-hints { font-size: 10px; padding: 10px 16px; }

  /* Billboard — full-width CTA tap target. */
  .cal-billboard-cta {
    display: flex !important;
    width: 100%;
    justify-content: center;
    padding: 14px 18px !important;
    min-height: 48px;
  }
  .cal-billboard { padding: 20px 18px 22px !important; }
  .cal-billboard-value { font-size: 26px !important; }

  /* Source chips — slightly more compact so 4 chips fit two-up. */
  .cal-source-chip { padding: 3px 7px !important; font-size: 11px !important; }
  .cal-source-row {
    justify-content: flex-start !important;
    gap: 6px !important;
  }
}

/* Privacy mode — CSS-only swap between real and redacted labels.
   The renderer wraps every sensitive value (project name, session
   label, filesystem path) in a pair of sibling spans carrying the
   "real" and "redacted" labels respectively. Default rule below hides
   the redacted twin so the browser sees the real text. @media print
   and a root-level data-privacy=always attribute both flip the swap,
   producing redacted output without re-running the report. */
.cal-redacted { display: none; }
[data-privacy="always"] .cal-real { display: none !important; }
[data-privacy="always"] .cal-redacted { display: inline !important; }
@media print {
  .cal-real { display: none !important; }
  .cal-redacted { display: inline !important; }
}

/* ============================================================================
   Phase 1 UX overhaul — billboard + appendix + canonical severity token

   These components apply Krug-1 ("don't make me think"), Peak-End Rule,
   Von Restorff, and Progressive Disclosure. Visual rules:

   * Billboard is the page peak — one number, one action.
   * Appendix collapses everything diagnostic behind a single <details>.
   * Severity is colour + glyph + label (never colour alone). Critical
     gets a 1-shot pulse; everything else is calm.
   * All animations gated by prefers-reduced-motion.
   ============================================================================ */

.cal-billboard {
  box-shadow: inset 0 0 0 1px var(--hairline);
}
.cal-billboard-cta {
  transition: background-color 120ms ease-out, box-shadow 120ms ease-out;
}
.cal-billboard-cta:hover {
  background: var(--accent-strong) !important;
  text-decoration: none;
}
.cal-billboard-cta:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}
@media (prefers-reduced-motion: reduce) {
  .cal-billboard-cta { transition: none; }
}

/* Appendix block — single progressive disclosure that hides every
   non-actionable section behind one click. <details> is a native
   interactive element so no JS is required; the CI privacy gate stays
   green. */
.cal-appendix {
  background: var(--panel);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-s) var(--sp-m);
  margin: 0;
  transition: background-color 120ms ease-out, border-color 120ms ease-out,
              padding 120ms ease-out;
}
.cal-appendix[open] {
  background: transparent;
  border-color: transparent;
  border-style: solid;
  padding: 0;
}
.cal-appendix-summary {
  list-style: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0;
  color: var(--mute);
  text-transform: uppercase;
  font-weight: 600;
  user-select: none;
  padding: 4px 0;
}
.cal-appendix-summary::marker,
.cal-appendix-summary::-webkit-details-marker { display: none; }
.cal-appendix-summary:hover { color: var(--ink-2); }
.cal-appendix-chev {
  display: inline-block;
  font-size: 10px;
  color: var(--ghost);
  transition: transform 140ms ease-out;
  width: 8px;
}
.cal-appendix[open] .cal-appendix-chev { transform: rotate(90deg); }
.cal-appendix-count {
  color: var(--ghost);
  font-weight: 500;
}
.cal-appendix-body {
  display: grid;
  gap: 40px;
  margin-top: var(--sp-m);
}
@media (prefers-reduced-motion: reduce) {
  .cal-appendix,
  .cal-appendix-chev { transition: none; }
}

/* Canonical severity token — one shape per level. Pair the colour with
   a glyph and label so colour-blind users still parse the signal. */
.sev {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-family: var(--mono);
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
  text-transform: uppercase;
  border: 1px solid transparent;
}
.sev-glyph { font-size: 9px; line-height: 1; }
.sev-critical {
  color: var(--bad);
  background: var(--bad-tint);
  border-color: var(--bad-tint);
}
.sev-warn {
  color: var(--warn);
  background: var(--warn-tint);
  border-color: var(--warn-tint);
}
.sev-info {
  color: var(--ink-2);
  background: var(--panel-2);
  border-color: var(--border);
}
.sev-ok {
  color: var(--ok);
  background: var(--ok-tint);
  border-color: var(--ok-tint);
}
@media (prefers-reduced-motion: no-preference) {
  .sev-critical { animation: sev-pulse 1400ms ease-out 1; }
  @keyframes sev-pulse {
    0%   { box-shadow: 0 0 0 0 var(--bad-tint); }
    100% { box-shadow: 0 0 0 6px rgba(0,0,0,0); }
  }
}

/* ============================================================================
   Receipt scroll-spy TOC (Phase 2)

   The right-rail nav is rendered alongside the main content via a 2-col
   grid. Sticky positioning keeps it in view as the user scrolls; an
   IntersectionObserver toggles ``aria-current="location"`` on the link
   matching the visible section. Below 1100px we collapse to single-column
   so the content gets full width — the TOC has done its job by then.
   ============================================================================ */

.cal-receipt-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  gap: 36px;
  margin-top: 24px;
  align-items: start;
}
.cal-receipt-main {
  display: grid;
  gap: 40px;
  min-width: 0;
}
.cal-receipt-toc {
  position: sticky;
  top: 20px;
  align-self: start;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  font-family: var(--font);
  padding: var(--sp-xs) 0;
  scrollbar-width: thin;
}
.cal-toc-eyebrow {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0;
  color: var(--mute);
  text-transform: uppercase;
  margin-bottom: 12px;
  font-weight: 600;
}
.cal-toc-group { margin-bottom: 16px; }
.cal-toc-group:last-child { margin-bottom: 0; }
.cal-toc-group-label {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0;
  color: var(--ghost);
  text-transform: uppercase;
  font-weight: 700;
  padding: 0 8px 6px;
  border-bottom: 1px dotted var(--border);
  margin-bottom: 4px;
}
.cal-toc-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 1px;
}
.cal-toc-link {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 8px;
  align-items: baseline;
  padding: 5px 8px;
  border-radius: 3px;
  color: var(--ink-2);
  text-decoration: none;
  font-size: 12px;
  border-left: 2px solid transparent;
  transition: background-color 120ms ease-out, color 120ms ease-out,
              border-color 120ms ease-out;
}
.cal-toc-link:hover {
  color: var(--ink);
  background: var(--accent-tint);
  text-decoration: none;
  border-left-color: var(--accent-tint-2);
}
.cal-toc-link[aria-current="location"] {
  color: var(--ink);
  background: var(--accent-tint);
  border-left-color: var(--accent);
  font-weight: 600;
}
.cal-toc-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.cal-toc-num {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ghost);
  letter-spacing: 0;
}
.cal-toc-link[aria-current="location"] .cal-toc-num { color: var(--accent); }
.cal-toc-title {
  min-width: 0;
  overflow-wrap: break-word;
}
/* Compact desktop — keep the TOC but narrow it slightly. */
@media (max-width: 1380px) and (min-width: 1100px) {
  .cal-receipt-body {
    grid-template-columns: minmax(0, 1fr) 180px;
    gap: 28px;
  }
}
/* Narrow desktop / large tablet — drop the TOC. */
@media (max-width: 1099px) {
  .cal-receipt-body {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .cal-receipt-toc { display: none; }
  .cal-receipt-main { gap: 32px; }
}
/* Tablet — softer padding so content fills the page without crowding. */
@media (max-width: 900px) and (min-width: 721px) {
  .cal-receipt-root { padding: 28px 24px 64px; }
  .cal-receipt-main { gap: 28px; }
  .cal-anomaly-row,
  .cal-insight-row { padding: 14px 16px !important; }
}
@media print {
  .cal-receipt-toc { display: none; }
  .cal-receipt-body { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .cal-toc-link { transition: none; }
}

/* Whole-card click target (Fitts's Law). Wrap any card or row in an
   <a class="cal-card-link"> and the full block becomes the hit area.
   The hover/focus polish is colour-only — no padding, margin, border-
   width, or transform changes, so the hover-jump guard stays green. */
.cal-card-link {
  display: block;
  position: relative;
  border-radius: var(--r-md);
  transition: background-color 120ms ease-out, box-shadow 120ms ease-out;
}
.cal-card-link:hover {
  background: var(--accent-tint);
  box-shadow: 0 0 0 1px var(--accent-tint-2);
}
.cal-card-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  .cal-card-link { transition: none; }
}

/* Cmd+K command palette (Phase 3) — recognition over recall + Doherty.
   Single fixed-position modal; the inline JS controller toggles `[hidden]`
   and re-renders results on each keystroke. */
.cal-palette {
  position: fixed;
  inset: 0;
  z-index: 9000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}
.cal-palette[hidden] { display: none !important; }
.cal-palette-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
}
.cal-palette-dialog {
  position: relative;
  width: min(580px, 92vw);
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-md);
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
.cal-palette-input {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--border);
  padding: 14px 18px;
  font-size: 14px;
  font-family: var(--font);
  background: var(--panel);
  color: var(--ink);
  outline: none;
}
.cal-palette-input::placeholder { color: var(--ghost); }
.cal-palette-results {
  list-style: none;
  padding: 6px 0;
  margin: 0;
  max-height: 50vh;
  overflow-y: auto;
}
.cal-palette-item {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 9px 18px;
  font-size: 13px;
  align-items: baseline;
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: background-color 80ms ease-out;
}
.cal-palette-item.is-active {
  background: var(--accent-tint);
  border-left-color: var(--accent);
}
.cal-palette-item:hover {
  background: var(--accent-tint);
}
.cal-palette-type {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0;
  color: var(--mute);
  text-transform: uppercase;
  font-weight: 600;
}
.cal-palette-label {
  color: var(--ink);
  min-width: 0;
  overflow-wrap: anywhere;
}
.cal-palette-hint {
  color: var(--mute);
  font-family: var(--mono);
  font-size: 11px;
  white-space: nowrap;
}
.cal-palette-empty {
  list-style: none;
  padding: 14px 18px;
  color: var(--ghost);
  font-size: 13px;
  text-align: center;
}
.cal-palette-hints {
  padding: 9px 18px;
  border-top: 1px solid var(--border);
  background: var(--panel-2);
  font-size: 11px;
  color: var(--mute);
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.cal-palette-hints kbd {
  display: inline-flex;
  align-items: center;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ink-2);
  margin-right: 4px;
}
@media (prefers-reduced-motion: reduce) {
  .cal-palette-item { transition: none; }
}
@media print {
  .cal-palette { display: none !important; }
}

/* Skip-to-content link — keyboard-first accessibility (Phase 3).
   First focusable element on the page; visually hidden until focused,
   so sighted users never see it but keyboard users can jump straight
   to the main content. */
.cal-skip-link {
  position: fixed;
  top: -100px;
  left: 0;
  padding: 10px 16px;
  background: var(--accent);
  color: var(--bg);
  font-weight: 600;
  font-size: 13px;
  text-decoration: none;
  border-radius: 0 0 var(--r-md) 0;
  z-index: 10001;
  transition: top 140ms ease-out;
}
.cal-skip-link:focus,
.cal-skip-link:focus-visible {
  top: 0;
  outline: 2px solid var(--ink);
  outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  .cal-skip-link { transition: none; }
}
.cal-demo-ribbon {
  margin: 0;
  padding: 9px 16px;
  background: var(--warn-tint);
  border-bottom: 2px solid var(--warn);
  color: var(--ink);
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.02em;
  text-align: center;
}
.cal-demo-ribbon code {
  font-family: var(--mono);
  background: var(--warn-tint);
  padding: 1px 5px;
  border-radius: var(--r-sm);
}

"""


# ============================================================================
# Section definitions
# ============================================================================

# Numbered audit anchors. The order is the rendering order; renumbering is a
# breaking change for any external links into a generated dashboard.
SECTION_NUMBERS: dict[str, str] = {
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

_SECTION_TITLES: dict[str, str] = {
    "action-center": "Next actions",
    "overview": "Overview",
    "cost": "Cost over time",
    "shape": "Session shape",
    "models": "Models & tiers",
    "projects": "Projects",
    "insights": "Insights",
    "anomalies": "Anomalies",
    "budgets": "Budget burn",
    "forecast": "Forecast",
    "advisor": "Advisor",
    "rate-limits": "Rate-limit pressure",
    "heatmap": "Activity heatmap",
    "sessions": "Session drilldown",
    "evidence": "Trust & evidence",
    "usage-windows": "Spend windows",
    "usage-mix": "Spend drivers",
    "inefficiencies": "Savings opportunities",
    "outlook": "Outlook drivers",
    "attribution": "Attribution",
}

# Map session-shape categories to CSS color tokens.
_SHAPE_COLORS: dict[str, str] = {
    "exploration": "var(--explore)",
    "explore": "var(--explore)",
    "execution": "var(--execute)",
    "execute": "var(--execute)",
    "diagnostic": "var(--diagnose)",
    "diagnose": "var(--diagnose)",
    "mixed": "var(--mixed)",
    "no-tools": "var(--bar-ghost)",
}


def _has_rich_operator_findings(d: Dashboard) -> bool:
    """Return true when richer, more actionable sections supersede Insights."""
    return bool(
        d.decision_queue
        or d.advisor_recommendations
        or d.inefficiencies
        or d.anomalies
        or d.usage_mix
        or d.top_sessions
    )


def _command_card_is_useful(card: Any) -> bool:
    value = str(getattr(card, "value", "")).lower()
    label = str(getattr(card, "label", ""))
    tone = str(getattr(card, "tone", "neutral"))
    if value in {"none", "no budgets", "no samples", "$0.00"}:
        return False
    return not (label == "Evidence quality" and tone in {"neutral", "good"})


def _has_operator_brief(d: Dashboard) -> bool:
    return bool(
        d.decision_queue
        or any(_command_card_is_useful(card) for card in d.command_center)
        or d.impact_cards
    )


def _shape_is_useful(d: Dashboard) -> bool:
    shape = d.shape
    if not shape or not shape.top_tools or not shape.total_sessions:
        return False
    if shape.coverage_total_events <= 0:
        return bool(shape.tool_use_total)
    return (shape.coverage_events / shape.coverage_total_events) >= 0.25


def _rate_limit_is_actionable(d: Dashboard) -> bool:
    pressure = d.rate_limit_pressure
    if pressure is None:
        return False
    return pressure.tone in {"critical", "warn"} or pressure.reached_count > 0


def _heatmap_is_useful(d: Dashboard) -> bool:
    if d.recap is None or not d.recap.hours:
        return False
    # The hour grid earns its space when it helps plan around reliability or
    # spend rhythm; otherwise it is diagnostic noise for the default operator.
    return _rate_limit_is_actionable(d) or d.seasonality is not None


def _should_render(section_id: str, d: Dashboard) -> bool:
    """Hide sections unless they add action, explanation, or audit value."""
    if section_id == "action-center":
        return _has_operator_brief(d)
    if section_id == "overview":
        return True
    if section_id == "shape":
        return _shape_is_useful(d)
    if section_id == "insights":
        return bool(d.insights) and not _has_rich_operator_findings(d)
    if section_id == "cost":
        return bool(d.daily)
    if section_id == "models":
        return bool(d.by_model)
    if section_id == "projects":
        return bool(d.by_project)
    if section_id == "anomalies":
        return bool(d.anomalies)
    if section_id == "budgets":
        return bool(d.budgets)
    if section_id == "forecast":
        return bool(
            d.forecast or d.outlook or d.model_forecasts or d.forecast_drivers or d.seasonality
        )
    if section_id == "advisor":
        # Advisor recommendations are rendered inside Savings opportunities
        # so the same savings claim is not repeated in two sections.
        return False
    if section_id == "rate-limits":
        return _rate_limit_is_actionable(d)
    if section_id == "heatmap":
        return _heatmap_is_useful(d)
    if section_id == "sessions":
        return bool(d.top_sessions)
    if section_id == "evidence":
        return bool(d.evidence)
    if section_id == "usage-windows":
        return bool(d.usage_windows)
    if section_id == "usage-mix":
        return bool(d.usage_mix)
    if section_id == "inefficiencies":
        return bool(d.advisor_recommendations or d.inefficiencies or d.cache_leverage)
    if section_id == "outlook":
        return False
    if section_id == "attribution":
        return bool(d.agents or d.skills or d.tier_provenance or d.long_context_histogram)
    return False


# ============================================================================
# Formatting helpers (kept module-level for tests and CLI scripts)
# ============================================================================


def fmt_money(v: float | int | None) -> str:
    """Render a USD amount.

    Numbers ≥ 1000 are integer-formatted with thousand separators; smaller
    values keep two decimals. ``None`` renders as an em-dash.
    """
    if v is None:
        return "—"
    if v >= 1000:
        return "$" + format(int(round(v)), ",")
    return "$" + format(float(v), ".2f")


def _fmt_money_axis(v: float) -> str:
    """Compact axis label for bar-chart Y-ticks."""
    if v >= 10000:
        return "$" + format(int(round(v / 1000)), "d") + "K"
    if v >= 1000:
        return "$" + format(v / 1000, ".1f") + "K"
    return "$" + format(int(round(v)), "d")


def fmt_int(v: int | None) -> str:
    if v is None:
        return "—"
    return format(int(v), ",")


def fmt_tokens(v: int | None) -> str:
    """Compact token count: B / M / K / raw."""
    if v is None:
        return "—"
    av = int(v)
    if av >= 1_000_000_000:
        return format(av / 1_000_000_000, ".1f") + "B"
    if av >= 1_000_000:
        return format(av / 1_000_000, ".1f") + "M"
    if av >= 10_000:
        return format(av / 1000, ".1f") + "K"
    return format(av, ",")


def fmt_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return format(float(v) * 100, f".{digits}f") + "%"


def _fmt_delta(v: float | None) -> str | None:
    """Signed percent delta, or ``None`` to mean "don't render the chip"."""
    if v is None:
        return None
    pct = abs(v) * 100
    if v > 0:
        sign = "+"
    elif v < 0:
        sign = "−"
    else:
        sign = ""
    return f"{sign}{pct:.1f}%"


def _nice_ceil(v: float) -> float:
    """Round up to a "nice" axis maximum (1, 2, 5, or 10 × 10ⁿ)."""
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    norm = v / exp
    if norm <= 1:
        nice = 1
    elif norm <= 2:
        nice = 2
    elif norm <= 5:
        nice = 5
    else:
        nice = 10
    return float(nice * exp)


def _esc(s: Any) -> str:
    """``html.escape`` with ``None``-tolerance and string coercion."""
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


# ============================================================================
# Privacy mode — CSS-only swap between real and redacted labels
# ============================================================================

PRIVACY_MODES = ("off", "print-only", "always")


class _PrivacyMap:
    """Pre-computed mapping from real → redacted labels.

    Walks the :class:`Dashboard` once at render time and assigns stable,
    indexed placeholders so a reader can still cross-reference between
    sections ("Project 3" in the projects table is the same project as
    "Project 3" referenced by a top session). Paths are uniformly
    redacted to ``[path]`` because they leak filesystem layout.

    Lookups for unknown values fall back to ``Project ?`` / ``Session ?``
    rather than raising — the renderer is defensive about partial data.
    """

    __slots__ = ("mode", "projects", "sessions", "paths", "path_label")

    def __init__(
        self,
        mode: str,
        projects: dict[str, str],
        sessions: dict[str, str],
        paths: dict[str, str] | None = None,
    ):
        self.mode = mode
        self.projects = projects
        self.sessions = sessions
        self.paths = paths or {}
        self.path_label = "[path]"


def _build_privacy_map(d: Dashboard, mode: str) -> _PrivacyMap:
    project_names = sorted({p.name for p in d.by_project if p.name})
    session_labels = sorted({s.label for s in d.top_sessions if s.label})
    project_paths = sorted({p.path for p in d.by_project if p.path})
    return _PrivacyMap(
        mode=mode,
        projects={name: f"Project {i}" for i, name in enumerate(project_names, start=1)},
        sessions={label: f"Session {i}" for i, label in enumerate(session_labels, start=1)},
        paths={path: "[path]" for path in project_paths},
    )


def _private(real: str, redacted: str, pm: _PrivacyMap) -> str:
    """Emit a real-or-redacted span based on privacy mode.

    * ``off``: just the escaped real value (no wrapper, no class).
    * ``always``: just the escaped redacted value (no wrapper either —
      cheaper output when the user has committed to redaction).
    * ``print-only``: both spans, controlled by CSS. ``cal-real`` is the
      browser view; ``cal-redacted`` shows in print and when the root
      carries ``data-privacy="always"``.
    """
    if pm.mode == "off":
        return _esc(real)
    if pm.mode == "always":
        return _esc(redacted)
    return (
        f'<span class="cal-real">{_esc(real)}</span>'
        f'<span class="cal-redacted">{_esc(redacted)}</span>'
    )


def _private_project(name: str, pm: _PrivacyMap) -> str:
    if pm.mode == "off":
        return _esc(name)
    redacted = pm.projects.get(name, "Project ?")
    return _private(name, redacted, pm)


def _private_session(label: str, pm: _PrivacyMap) -> str:
    if pm.mode == "off":
        return _esc(label)
    redacted = pm.sessions.get(label, "Session ?")
    return _private(label, redacted, pm)


def _private_path(path: str | None, pm: _PrivacyMap) -> str:
    if not path:
        return ""
    if pm.mode == "off":
        return _esc(path)
    return _private(path, pm.path_label, pm)


def _private_text(text: str | None, pm: _PrivacyMap) -> str:
    """Escape arbitrary copy while swapping known sensitive labels.

    Many high-level findings are already composed by the adapter as human
    strings. Rather than parsing those strings for structure, replace exact
    known project names, session labels, and project paths with the same
    privacy spans used by the tables.
    """
    raw = "" if text is None else str(text)
    if not raw:
        return ""
    if pm.mode == "off":
        return _esc(raw)
    replacements: dict[str, str] = {}
    replacements.update(pm.paths)
    replacements.update(pm.projects)
    replacements.update(pm.sessions)
    keys = sorted((key for key in replacements if key), key=len, reverse=True)
    if not keys:
        return _esc(raw)
    out: list[str] = []
    pos = 0
    while pos < len(raw):
        match = next((key for key in keys if raw.startswith(key, pos)), None)
        if match is None:
            next_pos = min(
                [idx for key in keys if (idx := raw.find(key, pos + 1)) != -1],
                default=len(raw),
            )
            out.append(_esc(raw[pos:next_pos]))
            pos = next_pos
            continue
        out.append(_private(match, replacements[match], pm))
        pos += len(match)
    return "".join(out)


def _redact_plain(text: str | None, pm: _PrivacyMap) -> str:
    """Plain-text (no HTML span) redaction for data embedded as JSON.

    The command-palette search index is encoded as a JSON ``<script>`` block,
    so it can't use the dual-span ``_private`` mechanism. In ``always`` mode the
    file must never embed real labels, so swap any known project/session/path
    substring for its redacted form. In other modes the local viewer keeps real
    labels (the file is for the user's own machine), so this is a no-op.
    """
    raw = "" if text is None else str(text)
    if not raw or pm.mode != "always":
        return raw
    replacements: dict[str, str] = {}
    replacements.update(pm.paths)
    replacements.update(pm.projects)
    replacements.update(pm.sessions)
    keys = sorted((key for key in replacements if key), key=len, reverse=True)
    if not keys:
        return raw
    out: list[str] = []
    pos = 0
    while pos < len(raw):
        match = next((key for key in keys if raw.startswith(key, pos)), None)
        if match is None:
            next_pos = min(
                [idx for key in keys if (idx := raw.find(key, pos + 1)) != -1],
                default=len(raw),
            )
            out.append(raw[pos:next_pos])
            pos = next_pos
            continue
        out.append(replacements[match])
        pos += len(match)
    return "".join(out)


def _agent_display_label(
    agent_id: str,
    index: int,
    *,
    source_category: str = "",
    kind: str = "",
) -> str:
    raw = str(agent_id or "").strip()
    if source_category == "direct" or kind == "direct-session" or raw.startswith("direct:"):
        return f"Direct session {index}"
    if source_category == "overhead":
        return f"Background agent {index}"
    if source_category == "unknown":
        return f"Agent source {index}"
    if not raw:
        return f"Agent {index}"
    lowered = raw.lower()
    compact = lowered.replace("-", "").replace("_", "")
    looks_hex_id = len(compact) >= 24 and all(ch in "0123456789abcdef" for ch in compact)
    looks_thread_payload = (
        raw.startswith("{")
        or "parent_thread_id" in lowered
        or "thread_spawn" in lowered
        or "subagent" in lowered
    )
    if looks_hex_id or looks_thread_payload or len(raw) > 64:
        return f"Agent {index}"
    return raw


def _agent_private_label(row: AgentRow, index: int) -> str:
    if (
        row.source_category == "direct"
        or row.kind == "direct-session"
        or row.agent_id.startswith("direct:")
    ):
        return f"Direct session {index}"
    if row.source_category == "overhead":
        return f"Background agent {index}"
    if row.source_category == "unknown":
        return f"Agent source {index}"
    return f"Agent {index}"


def _skill_display_label(name: str, index: int, *, private: bool = False) -> str:
    raw = str(name or "").strip()
    if raw.startswith("workflow:"):
        workflow = raw.removeprefix("workflow:").replace("-", " ").replace("_", " ")
        return f"{workflow.capitalize()} workflow" if workflow else f"Workflow {index}"
    if private:
        return f"Skill {index}"
    return raw or f"Skill {index}"


_ANCHOR_ALIASES = {
    "command-center": "action-center",
    "impact": "action-center",
    "usage-windows": "usage-windows",
    "top-sessions": "sessions",
    "metric-glossary": "evidence",
    "advisor": "inefficiencies",
    "cost-over-time": "cost",
}


def _anchor_id(anchor: str | None) -> str:
    raw = (anchor or "").strip()
    if not raw:
        return "action-center"
    return _ANCHOR_ALIASES.get(raw, raw)


# ============================================================================
# SVG chart primitives — pure functions returning HTML/SVG strings
# ============================================================================


def _sparkline(
    values: Sequence[float],
    *,
    width: int = 84,
    height: int = 22,
    stroke: str = "var(--accent)",
    stroke_width: float = 1,
    fill: str = "none",
    show_zero_line: bool = False,
) -> str:
    """Hairline SVG sparkline. Returns an empty (decorative) svg if no values."""
    if not values:
        return f'<svg width="{width}" height="{height}" aria-hidden="true"></svg>'
    nums = [float(v) for v in values]
    mx = max(*nums, 1.0)
    mn = min(*nums, 0.0)
    rng = (mx - mn) or 1.0
    pad = 2
    w = width - pad * 2
    h = height - pad * 2
    step = w / max(1, len(nums) - 1)
    pts: list[tuple[float, float]] = [
        (pad + i * step, pad + h - ((v - mn) / rng) * h) for i, v in enumerate(nums)
    ]
    d_parts = [f"{'L' if i else 'M'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts)]
    d = " ".join(d_parts)
    area_d = f"{d} L{pts[-1][0]:.1f} {(pad + h):.1f} L{pts[0][0]:.1f} {(pad + h):.1f} Z"
    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" aria-hidden="true">',
    ]
    if show_zero_line:
        parts.append(
            f'<line x1="{pad}" y1="{pad + h}" x2="{pad + w}" y2="{pad + h}" '
            f'stroke="var(--hairline)" stroke-width="1" />'
        )
    if fill != "none":
        parts.append(f'<path d="{area_d}" fill="{fill}" />')
    parts.append(
        f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round" />'
    )
    parts.append("</svg>")
    return "".join(parts)


def _meter(
    value: float,
    maximum: float,
    *,
    color: str = "var(--accent)",
    height: int = 6,
    radius: int = 2,
    track: str = "var(--bar-ghost)",
) -> str:
    pct = min(100.0, (float(value) / float(maximum)) * 100) if maximum > 0 else 0.0
    return (
        f'<span style="display:block;width:100%;height:{height}px;background:{track};'
        f'border-radius:{radius}px;overflow:hidden">'
        f'<span style="display:block;width:{pct:.1f}%;height:100%;background:{color};'
        f'border-radius:{radius}px;transition:width 200ms ease-out"></span>'
        f"</span>"
    )


def _budget_bar(spent: float, cap: float, warn: float) -> str:
    pct = min(100.0, (spent / cap) * 100) if cap > 0 else 0.0
    warn_pct = (warn / cap) * 100 if cap > 0 else 0.0
    if spent >= cap:
        tone = "var(--bad)"
    elif spent >= warn:
        tone = "var(--warn)"
    else:
        tone = "var(--ok)"
    return (
        '<div style="position:relative;height:8px;background:var(--bar-ghost);'
        'border-radius:2px;overflow:visible">'
        f'<span style="position:absolute;left:0;top:0;bottom:0;width:{pct:.1f}%;'
        f'background:{tone};border-radius:2px"></span>'
        f'<span title="warn at {fmt_money(warn)}" style="position:absolute;top:-2px;'
        f'bottom:-2px;left:{warn_pct:.1f}%;width:1px;background:var(--warn)"></span>'
        "</div>"
    )


def _stacked_bar(
    segments: Sequence[tuple[str, float, str]],
    *,
    height: int = 14,
    gap: int = 2,
    radius: int = 3,
) -> str:
    """Horizontal stacked bar; segments are (label, value, color)."""
    total = sum(v for _, v, _ in segments) or 1.0
    parts = [
        f'<div style="display:flex;gap:{gap}px;width:100%;height:{height}px;'
        f'border-radius:{radius}px;overflow:hidden;background:var(--bar-ghost)">'
    ]
    for label, value, color in segments:
        share = (value / total) * 100
        parts.append(
            f'<span title="{_esc(label)} · {round((value / total) * 100)}%" '
            f'style="flex-basis:{share:.2f}%;background:{color};height:100%"></span>'
        )
    parts.append("</div>")
    return "".join(parts)


def _shape_strip(daily: Sequence[Any], *, height: int = 10) -> str:
    """One block per day, colored by dominant session shape."""
    if not daily:
        return ""
    parts = [
        f'<div style="display:grid;grid-template-columns:repeat({len(daily)},1fr);'
        f'gap:2px;margin-top:8px">'
    ]
    for d in daily:
        shape = (getattr(d, "shape", None) or "no-tools").lower()
        color = _SHAPE_COLORS.get(shape, "var(--mixed)")
        opacity = "0.4" if shape == "no-tools" else "1"
        parts.append(
            f'<span title="{_esc(d.day)} · {_esc(shape)}" '
            f'style="height:{height}px;background:{color};border-radius:1px;opacity:{opacity}"></span>'
        )
    parts.append("</div>")
    return "".join(parts)


def _bar_chart(
    daily: Sequence[Any],
    *,
    width: int = 1000,
    height: int = 220,
    accent: str = "var(--accent)",
) -> str:
    """Bar chart in real pixel coords. Uses ``xMinYMin meet`` so axis text never
    distorts. (Earlier dashboards used ``preserveAspectRatio="none"`` which
    stretched text — that mistake must not return.)

    Y-axis: 4 ticks + baseline, ``$0`` at the floor, nice-ceiled max at the top.
    X-axis labels: first, mid, last day (truncated to ``MM-DD``).
    """
    if not daily:
        return ""
    data: list[tuple[str, str, float, int, str]] = []
    for d in daily:
        day = getattr(d, "day", "")
        label = day[5:] if len(day) > 5 else day
        events = int(getattr(d, "events", 0) or 0)
        data.append((day, label, float(d.cost_usd), events, (getattr(d, "shape", None) or "mixed")))
    mx = max((v for _, _, v, _, _ in data), default=1.0) or 1.0
    nice_max = _nice_ceil(mx)
    total = sum(v for _, _, v, _, _ in data)
    avg = total / len(data) if data else 0.0
    pad_l, pad_r, pad_t, pad_b = 44, 16, 50, 28
    inner_w = max(50, width - pad_l - pad_r)
    inner_h = height - pad_t - pad_b
    bar_w = inner_w / len(data)
    gap = max(2.0, min(8.0, bar_w * 0.18))
    y_ticks = 4
    avg_y = pad_t + inner_h - (avg / nice_max) * inner_h if avg > 0 else None
    parts = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" '
        f'role="img" aria-label="Daily cost bar chart" style="display:block;height:{height}px;overflow:visible">',
    ]
    for i in range(y_ticks + 1):
        t = (nice_max / y_ticks) * i
        y = pad_t + inner_h - (t / nice_max) * inner_h
        dash = "" if i == 0 else 'stroke-dasharray="2 4"'
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1" {dash} />'
        )
        label = "$0" if i == 0 else _fmt_money_axis(t)
        parts.append(
            f'<text x="{pad_l - 10}" y="{y + 4:.1f}" font-size="11" text-anchor="end" '
            f'fill="var(--mute)">{label}</text>'
        )
    avg_overlay = ""
    if avg_y is not None:
        avg_label = f"avg {fmt_money(avg)}/day"
        avg_label_w = max(74, min(148, int(len(avg_label) * 6.2 + 14)))
        avg_label_x = width - pad_r - avg_label_w
        avg_label_y = max(8.0, avg_y - 19)
        avg_overlay = (
            f'<line class="cal-chart-average-line" x1="{pad_l}" y1="{avg_y:.1f}" '
            f'x2="{width - pad_r}" y2="{avg_y:.1f}" stroke="var(--warn)" '
            'stroke-width="1.5" stroke-dasharray="6 5" />'
            f'<rect x="{avg_label_x:.1f}" y="{avg_label_y:.1f}" '
            f'width="{avg_label_w}" height="16" rx="3" fill="var(--panel)" '
            'stroke="var(--border)" />'
            f'<text x="{width - pad_r - 7}" y="{avg_label_y + 11:.1f}" '
            'font-size="11" text-anchor="end" fill="var(--warn)" font-weight="600">'
            f"{_esc(avg_label)}</text>"
        )
    peak_value = -1.0
    peak_idx = -1
    for i, (day, label, value, events, shape) in enumerate(data):
        x = pad_l + i * bar_w + gap / 2
        bw = bar_w - gap
        bar_h = (value / nice_max) * inner_h
        y = pad_t + inner_h - bar_h
        center_x = x + bw / 2
        shape_key = shape.lower().replace("_", "-")
        bar_color = _SHAPE_COLORS.get(shape_key, accent)
        if value > peak_value:
            peak_value = value
            peak_idx = i
        delta = value - avg
        delta_label = (
            "at average"
            if abs(delta) < 0.005
            else (f"{fmt_money(abs(delta))} {'above' if delta > 0 else 'below'} avg")
        )
        aria_label = (
            f"{day or label}: {fmt_money(value)}, {fmt_int(events)} events, {shape}, {delta_label}"
        )
        tip_w, tip_h = 184, 46
        tip_x = min(max(pad_l, center_x - tip_w / 2), width - pad_r - tip_w)
        tip_y = y - tip_h - 8
        if tip_y < 4:
            tip_y = y + 8
        tip_y = min(max(4.0, tip_y), height - tip_h - 4)
        # The whole chart is one labelled image (role="img" on the <svg>), so
        # the bars are presentational rather than focusable list items — this
        # avoids the invalid role="listitem"-without-list-parent. Per-day values
        # remain available in the §02 summary and the cost-over-time table; the
        # <title> still gives a native hover tooltip.
        parts.append('<g class="cal-bar-group" aria-hidden="true">')
        parts.append(f"<title>{_esc(aria_label)}</title>")
        parts.append(
            f'<rect x="{x:.1f}" y="{pad_t}" width="{bw:.1f}" height="{inner_h:.1f}" '
            f'fill="var(--bar-ghost)" />'
        )
        if bar_h > 0.5:
            parts.append(
                f'<rect class="cal-bar-rect" x="{x:.1f}" y="{y:.1f}" '
                f'width="{bw:.1f}" height="{bar_h:.1f}" '
                f'fill="{bar_color}" rx="1"><title>{_esc(label)}: '
                f"{_esc(fmt_money(value))} · {fmt_int(events)} events · "
                f"{_esc(shape)} · {_esc(delta_label)}</title></rect>"
            )
        parts.append(
            f'<rect class="cal-bar-hit" x="{x:.1f}" y="{pad_t}" width="{bw:.1f}" '
            f'height="{inner_h:.1f}" fill="transparent" pointer-events="all" />'
        )
        parts.append(
            f'<g class="cal-bar-hover-label" aria-hidden="true">'
            f'<rect x="{tip_x:.1f}" y="{tip_y:.1f}" width="{tip_w}" height="{tip_h}" '
            'rx="4" fill="var(--panel)" stroke="var(--border-strong)" />'
            f'<text x="{tip_x + 8:.1f}" y="{tip_y + 16:.1f}" font-size="11" '
            f'fill="var(--ink)" font-weight="600">{_esc(label)} · {_esc(fmt_money(value))}</text>'
            f'<text x="{tip_x + 8:.1f}" y="{tip_y + 32:.1f}" font-size="10" '
            f'fill="var(--mute)">{fmt_int(events)} events · {_esc(delta_label)}</text>'
            "</g>"
        )
        parts.append("</g>")
    for idx in {0, len(data) // 2, len(data) - 1}:
        if idx < 0 or idx >= len(data):
            continue
        label = data[idx][1]
        x = pad_l + idx * bar_w + bar_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{height - 10}" font-size="11" text-anchor="middle" '
            f'fill="var(--mute)">{_esc(label)}</text>'
        )
    if avg_overlay:
        parts.append(avg_overlay)
    if peak_idx >= 0:
        parts.append(
            f'<text x="{width - pad_r}" y="{pad_t - 4}" font-size="11" text-anchor="end" '
            f'fill="var(--accent)" font-weight="600">peak {_esc(fmt_money(peak_value))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _heatmap_7x24(recap: Recap) -> str:
    """7×24 (day-of-week × hour) heatmap. Day 0 = Monday."""
    if not recap.hours:
        return ""
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    grid: list[list[int]] = [[0] * 24 for _ in range(7)]
    for c in recap.hours:
        d = max(0, min(6, c.day_of_week))
        h = max(0, min(23, c.hour))
        grid[d][h] = c.value
    flat = [v for row in grid for v in row]
    mx = max(flat, default=0) or 1
    cell_size = 14
    gap = 2
    # Screen readers can't read opacity; give the grid a role + summary so it
    # isn't silent. (WCAG 1.1.1 / 1.4.1 — value is otherwise colour-only.)
    peak_v = peak_d = peak_h = 0
    for dd in range(7):
        for hh in range(24):
            if grid[dd][hh] > peak_v:
                peak_v, peak_d, peak_h = grid[dd][hh], dd, hh
    heatmap_summary = (
        f"Activity heatmap by day of week and hour. Busiest: "
        f"{day_labels[peak_d]} {peak_h:02d}:00 with {peak_v} calls."
        if peak_v
        else "Activity heatmap by day of week and hour."
    )
    parts = [
        f'<div role="img" aria-label="{_esc(heatmap_summary)}" '
        'style="display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start">',
        f'<div style="display:grid;grid-template-rows:repeat(7,{cell_size}px);'
        f'gap:{gap}px;font-size:10px;color:var(--mute);padding-top:14px">',
    ]
    for label in day_labels:
        parts.append(
            f'<span style="line-height:{cell_size}px;text-align:right;padding-right:4px">{label}</span>'
        )
    parts.append("</div>")
    # cal-heatmap-scroll lets the grid scroll horizontally on phones (CSS pins
    # cal-heatmap-cols to a fixed cell size there) instead of squishing the
    # 24 hour columns into unreadable slivers.
    parts.append('<div class="cal-heatmap-scroll">')
    parts.append(
        f'<div class="cal-heatmap-cols" style="display:grid;grid-template-columns:repeat(24,1fr);column-gap:{gap}px;'
        f'margin-bottom:4px;font-size:10px;color:var(--mute)">'
    )
    for h in range(24):
        vis = "visible" if h % 3 == 0 else "hidden"
        parts.append(f'<span style="text-align:center;visibility:{vis}">{h:02d}</span>')
    parts.append("</div>")
    parts.append(
        f'<div style="display:grid;grid-template-rows:repeat(7,{cell_size}px);gap:{gap}px">'
    )
    for d in range(7):
        parts.append(
            f'<div class="cal-heatmap-cols" style="display:grid;grid-template-columns:repeat(24,1fr);gap:{gap}px">'
        )
        for h in range(24):
            v = grid[d][h]
            if v == 0:
                bg = "var(--bar-ghost)"
                op = 1.0
            else:
                bg = "var(--accent)"
                op = 0.18 + (v / mx) * 0.82
            parts.append(
                f'<span class="cal-heatmap-cell" '
                f'title="{day_labels[d]} {h:02d}:00 · {v} calls" '
                f'style="background:{bg};opacity:{op:.2f};border-radius:2px;'
                f'border:1px solid var(--hairline)"></span>'
            )
        parts.append("</div>")
    parts.append("</div>")
    parts.append(
        '<div style="display:flex;justify-content:flex-end;align-items:center;gap:8px;'
        'margin-top:8px;font-size:11px;color:var(--mute)"><span>less</span>'
    )
    for op in (0, 0.3, 0.55, 0.8, 1.0):
        bg = "var(--bar-ghost)" if op == 0 else "var(--accent)"
        op_str = "1" if op == 0 else f"{op:.2f}"
        parts.append(
            f'<span style="width:12px;height:12px;background:{bg};opacity:{op_str};'
            f'border-radius:2px;border:1px solid var(--hairline)"></span>'
        )
    parts.append("<span>more</span></div>")
    parts.append("</div></div>")
    return "".join(parts)


def _ranked_bars(items: Sequence[Any]) -> str:
    """Ranked horizontal bars; items expose ``name``, ``count``, ``category``."""
    if not items:
        return ""
    counts = [int(it.count) for it in items]
    mx = max(counts) if counts else 1
    parts = ['<ul style="display:grid;gap:8px;list-style:none;padding:0;margin:0">']
    for it in items:
        cat = getattr(it, "category", None) or "accent"
        color = f"var(--{cat})"
        dot = (
            f'<span style="width:8px;height:8px;border-radius:2px;background:{color};'
            f'display:inline-block"></span>'
        )
        parts.append(
            '<li style="display:grid;grid-template-columns:auto 1fr auto;align-items:center;'
            'gap:12px;font-size:13px">'
            f'<span style="display:inline-flex;align-items:center;gap:8px;min-width:96px">'
            f"{dot}"
            f'<span style="color:var(--ink);font-weight:500">{_esc(it.name)}</span>'
            "</span>"
            f"{_meter(it.count, mx, color=color)}"
            '<span style="color:var(--ink-2);min-width:32px;text-align:right;font-size:12px">'
            f"{_esc(fmt_int(it.count))}</span></li>"
        )
    parts.append("</ul>")
    return "".join(parts)


# ============================================================================
# Small component primitives
# ============================================================================

_TONE_COLOR = {
    "good": "var(--ok)",
    "warn": "var(--warn)",
    "bad": "var(--bad)",
    "critical": "var(--bad)",
    "accent": "var(--accent)",
    "default": "var(--mute)",
    "neutral": "var(--mute)",
}


def _tone_color(tone: str | None, default: str = "var(--mute)") -> str:
    if tone is None:
        return default
    return _TONE_COLOR.get(tone, default)


def _stat_card(
    *,
    label: str,
    value: str,
    sub: str | None = None,
    delta: str | None = None,
    delta_tone: str | None = None,
    sparkline: Sequence[float] | None = None,
    spark_color: str = "var(--accent)",
    rail: str | None = None,
    dense: bool = False,
    formula: str = "",
    formula_source: str = "",
) -> str:
    pad = 12 if dense else 16
    delta_color = _tone_color(delta_tone)
    value_color = "var(--ghost)" if value == "—" else "var(--ink)"
    parts = [
        f'<div class="cal-stat-card" style="position:relative;background:var(--panel);'
        f"border:1px solid var(--border);border-radius:var(--r-md);padding:{pad}px;"
        'overflow:hidden;display:flex;flex-direction:column;min-height:142px">'
    ]
    if rail:
        parts.append(
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:2px;background:{rail}"></span>'
        )
    parts.append(
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">'
        f'<span style="font-size:11px;letter-spacing:0;color:var(--mute);'
        f'text-transform:uppercase;font-weight:500">{_esc(label)}</span>'
    )
    if delta:
        parts.append(
            f'<span style="font-size:11px;color:{delta_color};font-weight:500">{_esc(delta)}</span>'
        )
    parts.append("</div>")
    parts.append(
        f'<div class="cal-stat-card-value" style="font-size:var(--num-xl);line-height:1.05;font-weight:600;color:{value_color};'
        f'margin-bottom:4px;letter-spacing:0">{_esc(value)}</div>'
    )
    if sub:
        margin = "10px" if sparkline else "0"
        parts.append(
            f'<div style="font-size:12px;color:var(--mute);margin-bottom:{margin}">{_esc(sub)}</div>'
        )
    if sparkline:
        spark_w = 100 if dense else 140
        spark_h = 22 if dense else 26
        parts.append(
            f'<div class="cal-card-sparkline">'
            f"{_sparkline(sparkline, width=spark_w, height=spark_h, stroke=spark_color)}"
            f"</div>"
        )
    if formula:
        # Pure-HTML disclosure. No JS, no aria roles needed — <details> is a
        # native interactive element and CI's "max 1 script tag" gate still
        # passes. The summary is a small "?" affordance the eye can dismiss
        # until the reader is curious.
        source_html = (
            f'<div style="color:var(--ghost);font-size:10px;margin-top:6px">{_esc(formula_source)}</div>'
            if formula_source
            else ""
        )
        parts.append(
            '<details class="cal-card-formula" style="margin-top:auto;padding-top:8px">'
            '<summary style="cursor:pointer;list-style:none;font-family:var(--mono);'
            "font-size:10px;letter-spacing:0;color:var(--ghost);"
            "user-select:none;display:inline-flex;align-items:center;gap:4px;"
            'outline:none" aria-label="Show the formula for this KPI">'
            '<span aria-hidden="true" style="display:inline-block;width:11px;height:11px;'
            "border:1px solid var(--border-strong);border-radius:50%;text-align:center;"
            'line-height:9px;font-size:9px;color:var(--mute)">?</span>'
            "<span>show the math</span></summary>"
            '<div style="margin-top:8px;padding:8px 10px;background:var(--panel-2);'
            "border:1px solid var(--border);border-radius:3px;"
            "font-family:var(--mono);font-size:11px;line-height:1.55;"
            f'color:var(--ink-2);white-space:pre-wrap;word-break:break-word">{_esc(formula)}</div>'
            f"{source_html}"
            "</details>"
        )
    parts.append("</div>")
    return "".join(parts)


def _banner_html(b: Banner) -> str:
    """Map the Caliper :class:`Banner` (kind/label/text) to the design banner."""
    tone = "bad" if b.kind == "crit" else "warn"
    accent = "var(--bad)" if tone == "bad" else "var(--warn)"
    bg = "var(--bad-tint)" if tone == "bad" else "var(--warn-tint)"
    label_text = "ALERT" if tone == "bad" else "NOTE"
    return (
        '<div class="cal-banner" style="display:flex;align-items:flex-start;gap:14px;'
        f"padding:12px 16px;border:1px solid var(--border);border-left:3px solid {accent};"
        f'background:{bg};border-radius:0 var(--r-sm) var(--r-sm) 0;font-size:13px">'
        f'<span aria-hidden="true" style="font-family:var(--mono);color:{accent};font-size:11px;'
        f'padding-top:1px;letter-spacing:0">{label_text}</span>'
        '<div style="flex:1;min-width:0">'
        f'<div style="color:var(--ink);font-weight:500">{_esc(b.label)}</div>'
        f'<div style="color:var(--mute);margin-top:2px">{b.text}</div>'
        "</div></div>"
    )


def _pill(content: str, *, tone: str = "default", mono: bool = False) -> str:
    color = _tone_color(tone)
    font = "var(--mono)" if mono else "inherit"
    return (
        f'<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 7px;'
        f"border-radius:3px;font-size:11px;font-weight:500;color:{color};"
        f"background:var(--panel-2);border:1px solid var(--border);font-family:{font};"
        f'white-space:nowrap">{content}</span>'
    )


def _evidence_badge(qs: QualityScore) -> str:
    score = qs.score
    grade = qs.grade
    if score >= 80:
        color = "var(--ok)"
    elif score >= 65:
        color = "var(--warn)"
    else:
        color = "var(--bad)"
    return (
        '<a href="#evidence" style="text-decoration:none">'
        '<span class="cal-evidence-badge" title="Evidence quality — click to jump to §14" '
        'style="display:inline-flex;align-items:baseline;gap:6px;padding:5px 10px;'
        "border-radius:3px;background:var(--panel-2);border:1px solid var(--border);"
        'font-family:var(--mono);font-size:12px;white-space:nowrap">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{color};align-self:center"></span>'
        '<span style="color:var(--mute);text-transform:uppercase;letter-spacing:0;font-size:10px">Evidence</span>'
        f'<span style="color:var(--ink);font-weight:600">{score}'
        '<span style="color:var(--mute);font-weight:400">/100</span></span>'
        f'<span style="color:{color};font-size:11px">{_esc(grade)}</span>'
        "</span></a>"
    )


def _window_badge(w: WindowMeta) -> str:
    return (
        '<span class="cal-window-badge" style="display:inline-flex;align-items:center;gap:10px;padding:5px 10px;'
        "border-radius:3px;background:var(--panel-2);border:1px solid var(--border);"
        'font-family:var(--mono);font-size:12px;white-space:nowrap">'
        f'<span style="color:var(--ink)">{_esc(w.label)}</span>'
        '<span style="color:var(--mute)">·</span>'
        f'<span style="color:var(--ink-2)">{_esc(w.range)}</span>'
        "</span>"
    )


def _status_dot(tone: str, label: str) -> str:
    color = _tone_color(tone, "var(--ok)")
    halo = "rgba(123,224,146,0.15)" if tone == "good" else "transparent"
    return (
        '<span style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-2)">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{color};'
        f'box-shadow:0 0 0 2px {halo}"></span>{_esc(label)}</span>'
    )


def _caliper_mark(size: int = 22) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;gap:10px">'
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M3 7v10M21 7v10M3 7l4 -3M21 7l-4 -3M3 17l4 3M21 17l-4 3M7 12h10" '
        'fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />'
        '<circle cx="12" cy="12" r="1.5" fill="var(--accent)" />'
        "</svg></span>"
    )


def _section_head(section_id: str, *, rhythm: str, meta: str | None = None) -> str:
    num = _display_num(section_id)
    title = _SECTION_TITLES[section_id]
    if rhythm == "terminal":
        meta_html = (
            f'<span style="font-family:var(--mono);font-size:11px;color:var(--mute);'
            f'white-space:nowrap;text-overflow:ellipsis;overflow:hidden">{_esc(meta)}</span>'
            if meta
            else ""
        )
        return (
            '<div class="cal-section-head term" '
            'style="display:flex;align-items:baseline;justify-content:space-between;'
            "padding:10px 16px;border-top:1px solid var(--border-strong);"
            "border-bottom:1px solid var(--border);background:var(--panel-2);"
            'margin-bottom:16px;gap:16px">'
            '<div style="display:flex;align-items:baseline;gap:12px;min-width:0">'
            f'<span aria-hidden="true" style="font-family:var(--mono);font-size:11px;color:var(--mute);'
            f'letter-spacing:0">{num}.</span>'
            # Real <h2> in terminal mode too — screen readers shouldn't have
            # to guess that this monospace, accent-coloured span is the
            # section heading.
            f'<h2 style="margin:0;font-family:var(--mono);font-size:13px;letter-spacing:0;'
            f"color:var(--ink);font-weight:650;"
            f'white-space:nowrap">{_esc(title)}</h2>'
            "</div>"
            f"{meta_html}</div>"
        )
    meta_html = (
        f'<span style="font-size:12px;color:var(--mute);text-align:right;'
        f'white-space:nowrap;text-overflow:ellipsis;overflow:hidden">{_esc(meta)}</span>'
        if meta
        else ""
    )
    # Receipt header — simple "N. Title" sequence (1, 2, 3 …) computed from
    # render order. Typography/spacing come from the .cal-section-head.receipt
    # CSS so headers stay consistent across themes and density.
    return (
        '<div class="cal-section-head receipt" '
        'style="display:flex;align-items:baseline;justify-content:space-between;'
        'gap:16px">'
        '<div style="display:flex;align-items:baseline;gap:12px;min-width:0">'
        f'<span class="cal-section-num">{num}.</span>'
        f'<h2 style="margin:0">{_esc(title)}</h2>'
        "</div>"
        f"{meta_html}</div>"
    )


def _empty_placeholder(text: str) -> str:
    return (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        "border-radius:var(--r-md);padding:20px 18px;display:flex;"
        'justify-content:space-between;align-items:center;gap:16px">'
        f'<span style="color:var(--mute);font-size:13px">{_esc(text)}</span></div>'
    )


def _category_legend(items: Iterable[tuple[str, str]]) -> str:
    parts = ['<div style="display:flex;flex-wrap:wrap;gap:14px;font-size:11px;color:var(--mute)">']
    for color, label in items:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:6px">'
            f'<span style="width:8px;height:8px;border-radius:2px;background:{color};display:inline-block"></span>'
            f'<span style="color:var(--ink-2)">{_esc(label)}</span></span>'
        )
    parts.append("</div>")
    return "".join(parts)


def _hero_verdict_data(d: Dashboard) -> dict[str, Any] | None:
    """Compute the headline numbers for the hero verdict strip.

    Returns ``None`` when the dashboard is empty (no events). All numeric
    fields come from existing ``Totals`` / ``AdvisorRecommendations`` /
    ``WindowMeta`` so this function adds no new state — it is purely a
    presentation projection of data the adapter already builds.

    Keys returned:
    * ``period_label`` — "Last 14 days"
    * ``period_range`` — "2026-05-03 → 2026-05-17"
    * ``cost`` — display string (``$1,243``)
    * ``delta_pct`` — signed float or None
    * ``delta_text`` — display string ("+8.2% vs prior 14d") or ""
    * ``delta_tone`` — "warn" | "good" | "default"
    * ``recoverable_usd`` — float (sum of top-3 advisor savings)
    * ``recoverable_text`` — "$184" / ""
    * ``rec_count`` — int (advisor recs counted toward recoverable)
    * ``top_action_title`` — str (highest-savings rec title) or ""
    * ``top_action_value`` — str (highest-savings rec value) or ""
    * ``top_action_command`` — str (rec.action — copy-pasteable CLI)
    * ``top_action_confidence`` — float in [0,1] or None
    """
    t = d.totals
    if t is None or t.events == 0:
        return None

    delta = t.delta_cost_pct
    delta_text = ""
    delta_tone = "default"
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        delta_text = f"{sign}{delta * 100:.1f}% vs prior {d.window.label.lower()}"
        if abs(delta) < 0.02:
            delta_tone = "default"
        elif delta > 0:
            delta_tone = "warn"
        else:
            delta_tone = "good"

    recs = list(d.advisor_recommendations or [])
    # Rank by dollar savings; the adapter already does this but we don't
    # assume order here (the dashboard data contract doesn't lock it).
    recs.sort(key=lambda r: (-float(r.savings_usd or 0.0), -float(r.confidence or 0.0)))
    top_three = [r for r in recs if (r.savings_usd or 0.0) > 0][:3]
    recoverable = sum(float(r.savings_usd or 0.0) for r in top_three)
    top = top_three[0] if top_three else None

    return {
        "period_label": d.window.label,
        "period_range": d.window.range,
        "cost": fmt_money(t.cost_usd),
        "delta_pct": delta,
        "delta_text": delta_text,
        "delta_tone": delta_tone,
        "recoverable_usd": recoverable,
        "recoverable_text": fmt_money(recoverable) if recoverable > 0 else "",
        "rec_count": len(top_three),
        "top_action_title": top.title if top else "",
        "top_action_value": top.value if top else "",
        "top_action_command": top.action if top else "",
        "top_action_confidence": top.confidence if top else None,
    }


def _hero_verdict_strip(d: Dashboard, rhythm: str) -> str:
    """Hero verdict strip — the single line a screenshot reader can quote.

    Rendered above the existing ``_verdict_strip`` (which surfaces the
    executive brief). Reads from existing ``Totals`` + ``WindowMeta`` +
    ``AdvisorRecommendations``; adds no new dashboard fields. Hidden when
    the window has no events.
    """
    data = _hero_verdict_data(d)
    if data is None:
        return ""

    delta_color = (
        "var(--warn)"
        if data["delta_tone"] == "warn"
        else "var(--ok)"
        if data["delta_tone"] == "good"
        else "var(--mute)"
    )
    delta_html = (
        f'<span class="cal-hero-delta" style="color:{delta_color};font-size:13px;'
        f'font-weight:500;margin-left:14px;letter-spacing:0">{_esc(data["delta_text"])}</span>'
        if data["delta_text"]
        else ""
    )

    if data["recoverable_text"]:
        rec_count = data["rec_count"]
        plural = "" if rec_count == 1 else "s"
        recoverable_html = (
            '<div class="cal-hero-savings" style="display:flex;align-items:baseline;gap:10px;'
            'flex-wrap:wrap;margin-top:8px">'
            f'<span style="color:var(--ok);font-family:var(--mono);font-size:11px;'
            'letter-spacing:0;text-transform:uppercase;font-weight:600">FIXABLE</span>'
            f'<span style="color:var(--ink);font-size:14px;font-weight:600">'
            f'{_esc(data["recoverable_text"])}<span style="color:var(--mute);'
            f'font-weight:400;margin-left:6px">across {rec_count} '
            f"recommendation{plural}</span></span>"
            "</div>"
        )
    else:
        recoverable_html = ""

    if data["top_action_title"]:
        conf = data["top_action_confidence"]
        conf_chip = (
            f' · <span style="color:var(--mute)">{int(round((conf or 0) * 100))}% confidence</span>'
            if conf is not None
            else ""
        )
        value_chip = (
            f' · <span style="color:var(--ok);font-weight:500">{_esc(data["top_action_value"])}</span>'
            if data["top_action_value"]
            else ""
        )
        command_html = (
            '<div class="cal-hero-action-command" style="font-family:var(--mono);'
            "font-size:11px;color:var(--accent);margin-top:6px;"
            'overflow-wrap:anywhere;word-break:break-word">'
            f'<span style="color:var(--ghost)">$ </span>'
            f"{_esc(data['top_action_command'])}</div>"
            if data["top_action_command"]
            else ""
        )
        top_action_html = (
            '<div class="cal-hero-action" style="margin-top:10px;padding-top:10px;'
            'border-top:1px solid var(--border)">'
            '<span style="color:var(--mute);font-family:var(--mono);font-size:10px;'
            'letter-spacing:0;text-transform:uppercase">Top fix</span>'
            f'<div style="color:var(--ink);font-size:13px;font-weight:500;margin-top:4px">'
            f"{_esc(data['top_action_title'])}{value_chip}{conf_chip}"
            "</div>"
            f"{command_html}"
            "</div>"
        )
    else:
        top_action_html = ""

    return (
        '<div class="cal-hero-verdict" '
        'style="background:var(--panel);border:1px solid var(--border);'
        "border-left:3px solid var(--accent);border-radius:0 var(--r-md) var(--r-md) 0;"
        'padding:16px 20px">'
        '<div class="cal-hero-headline" style="display:flex;align-items:baseline;gap:14px;'
        'flex-wrap:wrap">'
        '<span style="font-family:var(--mono);font-size:10px;letter-spacing:0;'
        'color:var(--accent);text-transform:uppercase;font-weight:600">Verdict</span>'
        f'<span class="cal-hero-period" style="color:var(--mute);font-size:12px">'
        f"{_esc(data['period_label'])} · {_esc(data['period_range'])}</span>"
        "</div>"
        '<div class="cal-hero-line" style="display:flex;align-items:baseline;gap:0;'
        'flex-wrap:wrap;margin-top:8px">'
        '<span class="cal-hero-cost" style="color:var(--ink);font-size:var(--num-lg);'
        f'font-weight:600;letter-spacing:0">{_esc(data["cost"])}</span>'
        f"{delta_html}"
        "</div>"
        f"{recoverable_html}"
        f"{top_action_html}"
        "</div>"
    )


def _verdict_strip(d: Dashboard, rhythm: str) -> str:
    eb = d.executive_brief
    if eb is None or not eb.findings:
        return ""
    if eb.tone == "critical":
        tone_accent = "var(--bad)"
    elif eb.tone == "warn":
        tone_accent = "var(--warn)"
    elif eb.tone == "good":
        tone_accent = "var(--ok)"
    else:
        tone_accent = "var(--accent)"
    findings = list(eb.findings)[:4]

    def _pill_tone(f: BriefFinding) -> str:
        return {
            "critical": "bad",
            "warn": "warn",
            "good": "good",
            "neutral": "default",
        }.get(f.tone, "default")

    if rhythm == "terminal":
        # 2-row layout (verdict + subtitle on row 1, pills on row 2) — same
        # structure as receipt with terminal-flavoured typography. The
        # prototype's 3-column grid collapsed when pill text was long
        # (every word wrapping). Stacking the pills below makes the row
        # robust against real-world finding strings.
        chips = "".join(
            f'<a href="#{_esc(_anchor_id(f.anchor))}" class="cal-verdict-chip" style="text-decoration:none">'
            f"{_pill(_esc(f.title) + ' · ' + _esc(f.impact), tone=_pill_tone(f))}</a>"
            for f in findings
        )
        return (
            '<div class="cal-verdict-strip cal-verdict-terminal" '
            'style="background:var(--panel);border:1px solid var(--border);'
            f"border-left:3px solid {tone_accent};"
            'border-radius:0 var(--r-md) var(--r-md) 0;padding:12px 16px">'
            '<div style="display:flex;align-items:baseline;gap:12px;'
            'margin-bottom:8px;flex-wrap:wrap">'
            f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:0;'
            f"color:{tone_accent};text-transform:uppercase;font-weight:600;"
            'white-space:nowrap">Verdict</span>'
            f'<span style="font-size:14px;color:var(--ink);font-weight:600">{_esc(eb.verdict)}</span>'
            f'<span style="font-size:12px;color:var(--mute)">· {_esc(eb.subtitle)}</span>'
            "</div>"
            f'<div style="display:flex;gap:6px;flex-wrap:wrap">{chips}</div>'
            "</div>"
        )
    chips_html = []
    for f in findings:
        inner = (
            '<span style="color:var(--mute);margin-right:6px">↳</span>'
            + _esc(f.title)
            + '<span style="color:var(--ink-2);margin-left:8px">'
            + _esc(f.impact)
            + "</span>"
        )
        chips_html.append(
            f'<a href="#{_esc(_anchor_id(f.anchor))}" class="cal-verdict-chip" style="text-decoration:none">'
            f"{_pill(inner, tone=_pill_tone(f))}</a>"
        )
    return (
        '<div class="cal-verdict-strip" style="background:var(--panel);border:1px solid var(--border);'
        "border-radius:var(--r-md);"
        f'border-left:3px solid {tone_accent};padding:14px 18px">'
        '<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:10px;flex-wrap:wrap">'
        f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:0;'
        f'color:{tone_accent};text-transform:uppercase;font-weight:600;white-space:nowrap">Verdict</span>'
        f'<span style="font-size:17px;color:var(--ink);font-weight:600;letter-spacing:0">{_esc(eb.verdict)}</span>'
        f'<span style="font-size:12px;color:var(--mute)">· {_esc(eb.subtitle)}</span>'
        "</div>"
        f'<div style="display:flex;gap:8px;flex-wrap:wrap">{"".join(chips_html)}</div>'
        "</div>"
    )


def _caliper_footer(d: Dashboard) -> str:
    sha = getattr(d.caliper, "build_sha", "") or ""
    sha_line = f"<div>sha {_esc(sha)}</div>" if sha else ""
    return (
        '<footer style="border-top:1px solid var(--border);padding-top:16px;margin-top:32px;'
        'display:grid;grid-template-columns:1fr auto;gap:16px;color:var(--mute);font-size:11px;line-height:1.6">'
        '<div style="max-width:640px;display:flex;flex-direction:column;gap:6px">'
        # The moat, said plainly. The voice rule (design-brief/03) is
        # "headers are nouns" — three short clauses, no marketing verbs.
        '<div style="color:var(--ink-2);font-size:12px;font-weight:500">'
        "Caliper reads logs already on your disk. "
        '<span style="color:var(--ok)">No proxy.</span> '
        '<span style="color:var(--ok)">No upload.</span> '
        '<span style="color:var(--ok)">No login.</span>'
        "</div>"
        '<div style="color:var(--mute)">'
        "Caliper is "
        '<span style="color:var(--ok)">offline-first</span>. '
        "This dashboard contains no external resources, no external scripts, "
        "and no fetch/XHR/import calls. "
        "All data was parsed from local AI coding logs."
        "</div></div>"
        '<div style="text-align:right;font-family:var(--mono)">'
        f"<div>caliper v{_esc(d.caliper.version)} · schema {_esc(d.caliper.schema_version)}</div>"
        f"<div>{_esc(d.generated_at)}</div>"
        f"{sha_line}"
        "</div></footer>"
    )


def _section_wrap(section_id: str, *, rhythm: str, body: str, meta: str | None = None) -> str:
    num = _display_num(section_id)
    title = _SECTION_TITLES[section_id]
    return (
        f'<section id="{section_id}" data-screen-label="{num} {_esc(title)}">'
        f"{_section_head(section_id, rhythm=rhythm, meta=meta)}"
        f"{body}"
        "</section>"
    )


# ============================================================================
# Operator-first section primitives
# ============================================================================


def _value_card(
    *,
    label: str,
    value: str,
    detail: str,
    tone: str = "neutral",
    foot: str = "",
    href: str | None = None,
    pm: _PrivacyMap | None = None,
) -> str:
    accent = _tone_color(tone, "var(--accent)")
    detail_html = _private_text(detail, pm) if pm else _esc(detail)
    foot_html = (
        f'<div style="font-size:11px;color:var(--ghost);margin-top:8px">{_esc(foot)}</div>'
        if foot
        else ""
    )
    open_tag = (
        f'<a class="cal-card-link" href="#{_esc(_anchor_id(href))}" '
        'style="text-decoration:none;color:inherit;display:block">'
        if href
        else ""
    )
    close_tag = "</a>" if href else ""
    return (
        f"{open_tag}"
        '<div style="background:var(--panel);border:1px solid var(--border);'
        f"border-left:3px solid {accent};border-radius:var(--r-md);padding:14px 15px;"
        'min-width:0;display:flex;flex-direction:column;gap:6px">'
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">'
        f'<span style="font-size:11px;letter-spacing:0;text-transform:uppercase;'
        f'color:var(--mute);font-weight:600">{_esc(label)}</span>'
        f"{_pill(_esc(tone), tone='bad' if tone == 'critical' else tone)}"
        "</div>"
        f'<div style="font-size:var(--num-md);line-height:1.1;font-weight:650;color:var(--ink);'
        f'overflow-wrap:anywhere">{_esc(value)}</div>'
        f'<div style="font-size:12px;color:var(--mute);line-height:1.45">{detail_html}</div>'
        f"{foot_html}</div>{close_tag}"
    )


def _compact_row(
    *,
    label: str,
    value: str,
    detail: str = "",
    tone: str = "neutral",
    href: str | None = None,
    pm: _PrivacyMap | None = None,
) -> str:
    accent = _tone_color(tone, "var(--mute)")
    link_open = (
        f'<a class="cal-card-link" href="#{_esc(_anchor_id(href))}" '
        'style="text-decoration:none;color:inherit;display:block">'
        if href
        else ""
    )
    link_close = "</a>" if href else ""
    detail_html = (
        f'<div style="font-size:12px;color:var(--mute);margin-top:3px;line-height:1.45">'
        f"{_private_text(detail, pm) if pm else _esc(detail)}</div>"
        if detail
        else ""
    )
    return (
        f"{link_open}"
        '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;'
        'align-items:start;padding:11px 13px;border-top:1px solid var(--border)">'
        '<div style="min-width:0">'
        f'<div style="font-size:13px;color:var(--ink);font-weight:550;overflow-wrap:anywhere">{_private_text(label, pm) if pm else _esc(label)}</div>'
        f"{detail_html}</div>"
        f'<div style="font-family:var(--mono);font-size:12px;color:{accent};font-weight:650;'
        f'white-space:nowrap">{_esc(value)}</div>'
        f"</div>{link_close}"
    )


def _small_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    empty: str = "No rows.",
) -> str:
    if not rows:
        return _empty_placeholder(empty)
    head = (
        '<thead><tr style="background:var(--panel-2)">'
        + "".join(_th(header, align="right" if i else "left") for i, header in enumerate(headers))
        + "</tr></thead>"
    )
    body = []
    for row in rows:
        body.append(
            '<tr style="border-top:1px solid var(--border)">'
            + "".join(_td(cell, align="right" if i else "left") for i, cell in enumerate(row))
            + "</tr>"
        )
    # Letting the table size to its natural content (min-width:max-content
    # on the inner table; overflow-x:auto on the scroll wrapper) means
    # short labels like "estimated" / "Delta" no longer get truncated when
    # the table sits inside a narrow grid column. The scroll wrapper
    # surfaces the missing content via a horizontal scroll bar rather than
    # silently clipping.
    return (
        '<div class="cal-table-panel" style="background:var(--panel);'
        "border:1px solid var(--border);border-radius:var(--r-md);"
        'min-width:0">'
        # tabindex=0 so keyboard-only users can scroll to clipped columns
        # (WCAG 2.1.1 / axe scrollable-region-focusable).
        '<div class="cal-table-scroll" tabindex="0" style="overflow-x:auto;max-width:100%;'
        'border-radius:var(--r-md)">'
        '<table class="cal-table" style="width:100%;min-width:max-content;'
        'border-collapse:collapse;font-size:13px">'
        + head
        + "<tbody>"
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def _section_action_center(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    priority_items = list(d.decision_queue)[:5]
    queue_rows = "".join(
        _compact_row(
            label=f"{item.rank}. {item.title}",
            value=item.evidence,
            detail=f"{item.detail} Action: {item.action}",
            tone=item.tone,
            href=item.anchor,
            pm=pm,
        )
        for item in priority_items
    )

    if queue_rows:
        # The section heading is already "Next actions", so no redundant inner
        # sub-header. Meta reads as a distinct fact ("ranked by impact") rather
        # than a second "priority …" count that competes with the verdict strip.
        body = (
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);overflow:hidden">'
            f"{queue_rows}</div>"
        )
        meta = f"{len(priority_items)} ranked by impact"
        return _section_wrap("action-center", rhythm=rhythm, body=body, meta=meta)

    cards = [card for card in d.command_center if _command_card_is_useful(card)][:4]
    if not cards and d.impact_cards:
        cards = [
            type(
                "Card",
                (),
                {
                    "label": card.label,
                    "value": card.value,
                    "detail": card.detail,
                    "tone": card.tone,
                    "metric": "impact",
                },
            )()
            for card in d.impact_cards[:4]
        ]
    card_html = "".join(
        _value_card(
            label=card.label,
            value=card.value,
            detail=card.detail,
            tone=card.tone,
            foot=getattr(card, "metric", ""),
            href="evidence" if card.label.lower().startswith("evidence") else None,
            pm=pm,
        )
        for card in cards
    )
    if not card_html:
        return ""
    body = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));'
        f'gap:10px">{card_html}</div>'
    )
    meta = f"{len(cards)} useful checks"
    return _section_wrap("action-center", rhythm=rhythm, body=body, meta=meta)


def _section_usage_windows(d: Dashboard, *, rhythm: str) -> str:
    if not d.usage_windows:
        return ""
    cards = []
    for window in d.usage_windows:
        daily = window.cost_usd / window.days if window.days else 0.0
        cards.append(
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);padding:14px;min-width:0">'
            '<div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:7px">'
            f'<span style="font-size:12px;color:var(--ink);font-weight:600">{_esc(window.label)}</span>'
            f'<span style="font-family:var(--mono);font-size:12px;color:var(--mute)">{_esc(window.range)}</span>'
            "</div>"
            f'<div style="font-size:var(--num-lg);font-weight:650;color:var(--ink);line-height:1.05">{fmt_money(window.cost_usd)}</div>'
            f'<div style="font-size:12px;color:var(--mute);margin-top:5px">{fmt_money(daily)}/day · '
            f"{fmt_int(window.events)} events · {fmt_pct(window.cache_hit_rate)} cache</div>"
            f'<div style="margin-top:10px">{_sparkline(window.daily_cost_sparkline, width=160, height=28)}</div>'
            "</div>"
        )
    body = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">'
        + "".join(cards)
        + "</div>"
    )
    return _section_wrap("usage-windows", rhythm=rhythm, body=body)


def _section_usage_mix(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    if not d.usage_mix:
        return ""
    by_dimension: dict[str, list[Any]] = {}
    for row in d.usage_mix:
        by_dimension.setdefault(row.dimension, []).append(row)
    dimension_labels = {
        "vendor": "Vendor spend",
        "model/tier": "Model and tier",
        "tier": "Service tier",
        "source": "Source",
    }
    panels: list[str] = []
    displayed = 0
    for dimension in ("vendor", "model/tier", "tier", "source"):
        rows = sorted(by_dimension.get(dimension, []), key=lambda r: -r.cost_usd)[:5]
        if not rows:
            continue
        displayed += len(rows)
        max_cost = max((row.cost_usd for row in rows), default=1.0) or 1.0
        row_html = []
        for row in rows:
            row_html.append(
                '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;'
                'align-items:center;padding:10px 12px;border-top:1px solid var(--border)">'
                '<div style="min-width:0">'
                f'<div style="font-size:13px;color:var(--ink);font-weight:550;overflow-wrap:anywhere">{_private_text(row.label, pm)}</div>'
                f'<div style="display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;margin-top:7px">'
                f"{_meter(row.cost_usd, max_cost)}"
                f'<span style="font-size:11px;color:var(--mute);font-family:var(--mono)">{fmt_pct(row.share, 0)}</span>'
                "</div></div>"
                '<div style="text-align:right">'
                f'<div style="font-family:var(--mono);font-size:13px;color:var(--ink)">{fmt_money(row.cost_usd)}</div>'
                f'<div style="font-size:11px;color:var(--mute);margin-top:3px">{fmt_tokens(row.total_tokens)} · {fmt_int(row.events)} events</div>'
                f"{_sparkline(row.daily_cost_sparkline, width=72, height=18)}"
                "</div></div>"
            )
        panels.append(
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);overflow:hidden">'
            f'<div style="padding:10px 12px;background:var(--panel-2);font-size:11px;'
            f'letter-spacing:0;text-transform:uppercase;color:var(--mute);font-weight:650">'
            f"{_esc(dimension_labels.get(dimension, dimension))}</div>"
            + "".join(row_html)
            + "</div>"
        )
    body = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px">'
        + "".join(panels)
        + "</div>"
    )
    meta = f"Top {displayed} spend drivers" if displayed else None
    return _section_wrap("usage-mix", rhythm=rhythm, body=body, meta=meta)


def _section_inefficiencies(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    recommendation_rows = []
    for row in d.advisor_recommendations[:5]:
        detail = (
            f"{row.detail} Action: {row.action} Confidence: {int(round(row.confidence * 100))}%."
        )
        recommendation_rows.append(
            _compact_row(
                label=row.title,
                value=fmt_money(row.savings_usd),
                detail=detail,
                tone=row.tone,
                pm=pm,
            )
        )
    recommendations = ""
    if recommendation_rows:
        recommendations = (
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);overflow:hidden">'
            '<div style="padding:10px 13px;background:var(--panel-2);font-size:12px;'
            'color:var(--ink-2);font-weight:600">Recommended changes</div>'
            f"{''.join(recommendation_rows)}</div>"
        )

    advisor_amounts = [row.savings_usd for row in d.advisor_recommendations]
    finding_rows = []
    for row in d.inefficiencies[:6]:
        if any(abs(row.impact_usd - savings) < 0.01 for savings in advisor_amounts):
            continue
        value = fmt_money(row.impact_usd)
        detail = (
            f"{row.detail} Action: {row.action} Confidence: {row.confidence}; "
            f"sample {row.sample_size}; baseline {row.baseline}."
        )
        finding_rows.append(
            _compact_row(
                label=row.title,
                value=value,
                detail=detail,
                tone="warn" if row.severity in {"warn", "fail", "critical"} else "neutral",
                pm=pm,
            )
        )
    findings = ""
    if finding_rows:
        findings = (
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);overflow:hidden">'
            '<div style="padding:10px 13px;background:var(--panel-2);font-size:12px;'
            'color:var(--ink-2);font-weight:600">Detected waste</div>'
            f"{''.join(finding_rows)}</div>"
        )
    cache_rows = []
    for row in d.cache_leverage[:6]:
        # Wrap the timestamp-style session label so it doesn't break
        # one-word-per-line inside the narrow cache-leverage column. The
        # span keeps the date intact while ``overflow-wrap`` and the table's
        # horizontal scroll handle very-narrow viewports gracefully.
        label_html = (
            '<span class="cal-cache-session" '
            'style="white-space:nowrap;font-variant-numeric:tabular-nums lining-nums">'
            f"{_private_text(row.session_label, pm)}"
            "</span>"
        )
        cache_rows.append(
            [
                label_html,
                fmt_money(row.savings_usd),
                fmt_pct(row.hit_rate),
                fmt_tokens(row.cached_input_tokens),
            ]
        )
    cache = (
        _small_table(["Cache leverage", "Savings", "Hit rate", "Cached tokens"], cache_rows)
        if cache_rows
        else ""
    )
    panels = "".join(panel for panel in (recommendations, findings, cache) if panel)
    if not panels:
        return ""
    body = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">'
        f"{panels}</div>"
    )
    total_savings = sum(row.savings_usd for row in d.advisor_recommendations)
    if total_savings > 0:
        meta = f"{fmt_money(total_savings)} estimated savings"
    else:
        meta = f"{len(finding_rows)} findings · {len(cache_rows)} cache rows"
    return _section_wrap("inefficiencies", rhythm=rhythm, body=body, meta=meta)


def _hour_bars(values: Sequence[float]) -> str:
    if not values:
        return ""
    max_value = max(values) or 1.0
    bars = []
    for hour, value in enumerate(values):
        color = "var(--accent)" if value == max_value else "var(--accent-tint-2)"
        bars.append(
            f'<span title="{hour:02d}:00 · {fmt_money(value)}" '
            f'style="display:block;height:{max(3, int((value / max_value) * 42))}px;'
            f'background:{color};border-radius:2px 2px 0 0"></span>'
        )
    return (
        '<div style="display:grid;grid-template-columns:repeat(24,1fr);gap:2px;'
        'align-items:end;height:48px">' + "".join(bars) + "</div>"
    )


def _section_outlook(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    panels: list[str] = []
    if d.outlook:
        out = d.outlook
        panels.append(
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">'
            + _value_card(
                label="30d outlook",
                value=fmt_money(out.horizon_30d.linear_total),
                detail=(
                    f"Band {fmt_money(out.horizon_30d.linear_low)} to "
                    f"{fmt_money(out.horizon_30d.linear_high)}; EWMA "
                    f"{fmt_money(out.horizon_30d.ewma_total)}."
                ),
                tone="warn"
                if out.horizon_30d.ewma_total > out.horizon_30d.linear_total
                else "neutral",
            )
            + _value_card(
                label="90d outlook",
                value=fmt_money(out.horizon_90d.linear_total),
                detail=(
                    f"Band {fmt_money(out.horizon_90d.linear_low)} to "
                    f"{fmt_money(out.horizon_90d.linear_high)} from {out.days_analyzed} days."
                ),
                tone="neutral",
            )
            + "</div>"
        )
    if d.model_forecasts:
        rows = []
        for row in d.model_forecasts[:6]:
            rows.append(
                [
                    _esc(row.model),
                    fmt_money(row.projected_30d_cost_usd),
                    _esc(row.trend_label),
                    _sparkline(row.daily_cost_sparkline, width=72, height=18),
                ]
            )
        panels.append(_small_table(["Model", "30d", "Trend", "Recent"], rows))
    if d.forecast_drivers:
        rows = []
        for row in d.forecast_drivers[:8]:
            rows.append(
                [
                    _private_text(f"{row.dimension}: {row.label}", pm),
                    fmt_money(row.projected_30d_cost_usd),
                    fmt_pct(row.share, 0),
                    _esc(row.evidence_status),
                ]
            )
        panels.append(_small_table(["Driver", "30d", "Share", "Evidence"], rows))
    if d.seasonality:
        s = d.seasonality
        panels.append(
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);padding:14px">'
            '<div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:10px">'
            '<span style="font-size:12px;color:var(--ink);font-weight:600">Cost-weighted rhythm</span>'
            f'<span style="font-family:var(--mono);font-size:12px;color:var(--mute)">peak {s.peak_hour:02d}:00 · off-peak {fmt_pct(s.off_peak_share, 0)}</span>'
            "</div>"
            f"{_hour_bars(s.by_hour_cost_usd)}"
            f'<div style="font-size:11px;color:var(--mute);margin-top:9px">{_esc(s.timezone)} · {fmt_money(s.total_cost_usd)} distributed by local hour</div>'
            "</div>"
        )
    body = '<div style="display:grid;gap:12px">' + "".join(panels) + "</div>"
    meta = f"{len(d.model_forecasts)} model forecasts · {len(d.forecast_drivers)} drivers"
    return _section_wrap("outlook", rhythm=rhythm, body=body, meta=meta)


def _histogram(values: Sequence[int], labels: Sequence[str]) -> str:
    if not values:
        return ""
    max_value = max(values) or 1
    cells = []
    for label, value in zip(labels, values, strict=False):
        cells.append(
            '<div style="display:grid;gap:5px;align-items:end">'
            f'<span style="height:{max(4, int((value / max_value) * 56))}px;background:var(--accent-tint-2);border-radius:3px 3px 0 0"></span>'
            f'<span style="font-size:10px;color:var(--mute);font-family:var(--mono);text-align:center">{_esc(label)}</span>'
            f'<span style="font-size:11px;color:var(--ink-2);font-family:var(--mono);text-align:center">{fmt_int(value)}</span>'
            "</div>"
        )
    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(42px,1fr));'
        f'gap:8px;align-items:end">{"".join(cells)}</div>'
    )


def _section_attribution(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    panels: list[str] = []
    if d.agents:
        rows = []
        for idx, row in enumerate(d.agents[:6], start=1):
            real_label = _agent_display_label(
                row.agent_id,
                idx,
                source_category=row.source_category,
                kind=row.kind,
            )
            label = (
                _esc(real_label)
                if pm.mode == "off"
                else _private(real_label, _agent_private_label(row, idx), pm)
            )
            rows.append(
                [
                    label,
                    fmt_money(row.cost_usd),
                    fmt_tokens(row.total_tokens),
                    _esc(row.evidence_status),
                ]
            )
        panels.append(_small_table(["Source", "Cost", "Tokens", "Evidence"], rows))
    if d.skills:
        rows = []
        for idx, row in enumerate(d.skills[:6], start=1):
            real_label = _skill_display_label(row.name, idx)
            private_label = _skill_display_label(row.name, idx, private=True)
            label = (
                _esc(real_label) if pm.mode == "off" else _private(real_label, private_label, pm)
            )
            rows.append(
                [
                    label,
                    fmt_money(row.estimated_cost_usd),
                    fmt_int(row.invocations),
                    _esc(row.evidence_status),
                ]
            )
        panels.append(_small_table(["Skill / workflow", "Cost", "Calls", "Evidence"], rows))
    if d.tier_provenance:
        t = d.tier_provenance
        rows = [
            [
                _esc(label),
                fmt_int(count),
                fmt_pct(count / t.total_events if t.total_events else 0, 0),
            ]
            for label, count in t.sources
        ]
        panels.append(_small_table(["Tier source", "Events", "Share"], rows))
    if d.long_context_histogram:
        h = d.long_context_histogram
        labels = [fmt_tokens(edge) for edge in h.bins]
        panels.append(
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);padding:14px;min-width:0;overflow:hidden">'
            '<div style="display:flex;justify-content:space-between;gap:12px;'
            'flex-wrap:wrap;align-items:baseline;margin-bottom:10px">'
            '<span style="font-size:12px;color:var(--ink);font-weight:600">Long-context boundary</span>'
            f'<span style="font-family:var(--mono);font-size:12px;color:var(--mute)">threshold {fmt_tokens(h.threshold_tokens)}</span>'
            "</div>"
            f"{_histogram(h.counts, labels)}"
            f'<div style="font-size:11px;color:var(--mute);margin-top:9px">{fmt_pct(h.share_above_threshold, 0)} of events and {fmt_pct(h.cost_share_above_threshold, 0)} of cost crossed the threshold.</div>'
            "</div>"
        )
    if d.cohort_deltas:
        rows = [
            [
                _esc(row.label),
                _esc(row.current_value),
                _esc(row.previous_value),
                _esc(_fmt_delta(row.delta_pct) or "n/a"),
            ]
            for row in d.cohort_deltas
        ]
        panels.append(_small_table(["Cohort", "Current", "Previous", "Delta"], rows))
    # Each attribution table has 3–4 columns. At 300px the tables were
    # squeezed and the Evidence / Delta columns clipped. 380px gives every
    # column room to breathe; the grid still fits two-up at ~800px main
    # width, and three-up only when the dashboard has the full 1100px+
    # receipt column available.
    body = (
        '<div class="cal-attribution-grid" style="display:grid;'
        "grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));"
        'gap:16px;min-width:0">' + "".join(panels) + "</div>"
    )
    meta = f"{len(d.agents)} sources · {len(d.skills)} skills/workflows"
    return _section_wrap("attribution", rhythm=rhythm, body=body, meta=meta)


# ============================================================================
# Table helpers (used by render_models / render_projects / _section_sessions)
# ============================================================================


def _th(
    content: str, *, align: str = "left", aria_sort: str | None = None, numeric: bool = False
) -> str:
    sort_attr = f' aria-sort="{aria_sort}"' if aria_sort else ""
    # Numeric headers carry data-num=true so the CSS rule that enforces
    # white-space:nowrap + tabular numerals applies. The class also keeps
    # cells from breaking "65%" across two visual lines.
    num_attr = ' data-num="true"' if numeric else ""
    return (
        f'<th scope="col"{sort_attr}{num_attr} '
        f'style="text-align:{align};padding:10px 14px;font-size:11px;'
        f"font-weight:500;color:var(--mute);text-transform:uppercase;letter-spacing:0;"
        f'border-bottom:1px solid var(--border)">{content}</th>'
    )


def _td(
    content: str,
    *,
    align: str = "left",
    mono: bool = False,
    muted: bool = False,
    numeric: bool | None = None,
) -> str:
    font = "var(--mono)" if mono else "inherit"
    color = "var(--mute)" if muted else "var(--ink-2)"
    # Right-aligned cells in a Caliper table are numeric by convention
    # (cost, share, events, tokens, days, etc.). Treat them as data-num
    # by default so the CSS rule that enforces white-space:nowrap +
    # tabular numerals applies — no orphan "%"s, no hyphen breaks in
    # mono identifiers, no row-height jitter. Callers can override by
    # passing numeric=False (e.g. for a right-aligned label that
    # genuinely needs to wrap).
    is_num = numeric if numeric is not None else (align == "right")
    num_attr = ' data-num="true"' if is_num else ""
    return (
        f'<td{num_attr} style="text-align:{align};padding:10px 14px;vertical-align:middle;'
        f'font-family:{font};color:{color}">{content}</td>'
    )


# ============================================================================
# Section renderers
# ============================================================================


def _section_overview(d: Dashboard, *, dense: bool, rhythm: str) -> str:
    t: Totals = d.totals
    is_empty = (t.cost_usd is None) or (t.events == 0)

    # Pricing/source footer for the show-the-math disclosure. Without a
    # concrete pricing-checked date we fall back to the schema-versioned
    # rate card label so the user still sees a citation.
    pricing_source = f"Rate card: caliper v{d.caliper.version} (schema {d.caliper.schema_version})"

    # Sample-size strings — every formula needs lineage so a sceptic can
    # see "across what?".
    sample_n = f"across {fmt_int(t.events)} events · {fmt_int(t.sessions)} sessions"
    cost_formula = (
        "cost = Σ (input × rate_in)\n"
        "         + (output × rate_out)\n"
        "         + (cached_input × rate_cached_in)\n"
        "per (model, tier), using Decimal arithmetic.\n"
        f"{sample_n}."
    )
    cache_formula = (
        "cache_savings = Σ cached_input × (rate_in − rate_cached_in)\n"
        "per (model, tier). Cached-input rate is vendor-published;\n"
        "counterfactual is the standard input rate for the same model.\n"
        f"{sample_n}."
    )
    tokens_formula = (
        "total_tokens = uncached_input + cached_input + output + reasoning.\n"
        "Cached + output reported separately because they price differently.\n"
        f"{sample_n}."
    )
    sessions_formula = (
        "session = continuous AI coding conversation.\n"
        "Caliper dedupes by upstream session identity, so a session is counted once\n"
        "even if it spans multiple JSONL files.\n"
        f"{fmt_int(t.sessions)} unique sessions across "
        f"{fmt_int(t.turns)} turns; {t.tools_per_turn:.2f} tools/turn."
    )

    def _card(
        *,
        label: str,
        value: str,
        sub: str,
        delta: float | None,
        delta_tone: str,
        spark: Sequence[float],
        spark_color: str,
        rail: str,
        formula: str = "",
    ) -> str:
        return _stat_card(
            label=label,
            value=value,
            sub=sub,
            delta=None if is_empty else _fmt_delta(delta),
            delta_tone=delta_tone,
            sparkline=spark if not is_empty else None,
            spark_color=spark_color,
            rail=rail,
            dense=dense,
            formula="" if is_empty else formula,
            formula_source="" if is_empty else pricing_source,
        )

    empty_sub = "No events for this window" if is_empty else ""
    cards = "".join(
        [
            _card(
                label="Cost",
                value="—" if is_empty else fmt_money(t.cost_usd),
                sub=empty_sub or f"{fmt_int(t.events)} events · {fmt_int(t.turns)} turns",
                delta=t.delta_cost_pct,
                delta_tone="bad" if (t.delta_cost_pct or 0) > 0 else "good",
                spark=t.daily_cost_sparkline,
                spark_color="var(--accent)",
                rail="var(--card-rail-cost)",
                formula=cost_formula,
            ),
            _card(
                label="Cache savings",
                value="—" if is_empty else fmt_money(t.cache_savings_usd),
                sub=empty_sub or f"{fmt_pct(t.cache_hit_rate)} hit rate",
                delta=t.delta_cache_pct,
                delta_tone="good" if (t.delta_cache_pct or 0) >= 0 else "warn",
                spark=t.daily_cache_sparkline,
                spark_color="var(--ok)",
                rail="var(--card-rail-cache)",
                formula=cache_formula,
            ),
            _card(
                label="Tokens",
                value="—" if is_empty else fmt_tokens(t.total_tokens),
                sub=empty_sub
                or f"{fmt_tokens(t.cached_input_tokens)} cached · {fmt_tokens(t.output_tokens)} output",
                delta=t.delta_tokens_pct,
                delta_tone="default",
                spark=t.daily_token_sparkline,
                spark_color="var(--accent)",
                rail="var(--card-rail-tokens)",
                formula=tokens_formula,
            ),
            _card(
                label="Sessions",
                value="—" if is_empty else fmt_int(t.sessions),
                sub=empty_sub or f"{t.tools_per_turn:.2f} tools/turn",
                delta=t.delta_sessions_pct,
                delta_tone="default",
                spark=t.daily_session_sparkline,
                spark_color="var(--accent-strong)",
                rail="var(--card-rail-sessions)",
                formula=sessions_formula,
            ),
        ]
    )
    body = (
        '<div class="cal-summary-row" '
        'style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:stretch">'
        + cards
        + "</div>"
    )
    return _section_wrap("overview", rhythm=rhythm, body=body)


def _section_cost(d: Dashboard, *, rhythm: str) -> str:
    daily = d.daily
    if not daily:
        return ""
    total = sum(float(p.cost_usd) for p in daily)
    avg = total / len(daily) if daily else 0.0
    active_days = sum(1 for p in daily if float(p.cost_usd) > 0 or int(p.events) > 0)
    legend = _category_legend(
        [
            ("var(--explore)", "exploration"),
            ("var(--execute)", "execution"),
            ("var(--diagnose)", "diagnostic"),
            ("var(--mixed)", "mixed"),
        ]
    )
    summary = (
        f"{active_days} active days across {len(daily)} days · "
        f"{fmt_money(total)} total · avg {fmt_money(avg)}/day"
    )
    body = (
        '<div class="cal-cost-panel" style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'flex-wrap:wrap;gap:12px;margin-bottom:6px;font-size:12px;color:var(--mute)">'
        f"<span>{_esc(summary)}</span>{legend}</div>"
        f"{_bar_chart(daily)}"
        f"{_shape_strip(daily)}"
        "</div>"
    )
    return _section_wrap("cost", rhythm=rhythm, body=body)


def _section_shape(d: Dashboard, *, rhythm: str) -> str:
    s: SessionShape = d.shape
    meta = (
        f"{s.total_sessions} sessions · {s.total_turns} turns" if s and s.total_sessions else None
    )
    if not s or not s.top_tools:
        return ""
    segments: list[tuple[str, float, str]] = []
    for c in s.categories:
        color = _SHAPE_COLORS.get(c.category, "var(--mixed)")
        segments.append((c.label or c.category, float(c.sessions), color))
    category_rows: list[str] = []
    for c in s.categories:
        color = _SHAPE_COLORS.get(c.category, "var(--mixed)")
        category_rows.append(
            '<li style="display:grid;grid-template-columns:auto 1fr auto auto;gap:10px;'
            'align-items:baseline;font-size:13px">'
            f'<span style="width:8px;height:8px;border-radius:2px;background:{color};display:inline-block"></span>'
            f'<span style="color:var(--ink)">{_esc(c.category)}</span>'
            f'<span style="color:var(--mute);font-size:11px">{int(round((c.share or 0) * 100))}%</span>'
            f'<span style="color:var(--ink-2)">{fmt_int(c.sessions)}</span></li>'
        )
    coverage_block = ""
    if s.coverage_events < s.coverage_total_events:
        coverage_block = (
            f'<div style="margin-top:4px">Coverage: {fmt_int(s.coverage_events)} of '
            f"{fmt_int(s.coverage_total_events)} events.</div>"
        )
    body = (
        '<div class="cal-shape-grid" '
        'style="display:grid;grid-template-columns:1.4fr 1fr;gap:16px">'
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<div style="font-size:12px;color:var(--ink-2);margin-bottom:12px;font-weight:500">Top tools</div>'
        f"{_ranked_bars(s.top_tools)}"
        "</div>"
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<div style="font-size:12px;color:var(--ink-2);margin-bottom:12px;font-weight:500">Shape distribution</div>'
        f"{_stacked_bar(segments, height=16)}"
        '<ul style="list-style:none;padding:0;margin:14px 0 0;display:grid;gap:8px">'
        + "".join(category_rows)
        + "</ul>"
        '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border);'
        'font-size:11px;color:var(--mute)">'
        f"{s.tool_use_total} tool calls · {s.tools_per_turn:.2f} tools/turn"
        f"{coverage_block}"
        "</div></div></div>"
    )
    return _section_wrap("shape", rhythm=rhythm, body=body, meta=meta)


def render_models(rows: Sequence[ModelRow], *, total_cost: float | None = None) -> str:
    """Render the §04 models table. Exposed for unit tests."""
    if not rows:
        return ""
    sorted_rows = sorted(rows, key=lambda r: (-r.cost_usd, -r.tokens))
    mx = max((r.cost_usd for r in sorted_rows), default=1.0) or 1.0
    total = float(total_cost) if total_cost else sum(r.cost_usd for r in sorted_rows) or 1.0
    head = (
        '<thead><tr style="background:var(--panel-2)">'
        f"{_th('Vendor')}{_th('Model · tier')}"
        f"{_th('Cost ↓', align='right', aria_sort='descending')}"
        f"{_th('Share', align='right')}{_th('Events', align='right')}"
        f"{_th('Tokens', align='right')}{_th('Cache', align='right')}"
        f"{_th('14d', align='right')}"
        "</tr></thead>"
    )
    body_rows: list[str] = []
    for r in sorted_rows:
        share = (r.cost_usd / total) if total else 0.0
        share_pct = int(round(share * 100))
        # Share cell: percentage + meter ride together inside a nowrap
        # block so the "%" never orphans onto a second line.
        share_cell = (
            '<span class="cal-cell-share" '
            'style="display:inline-flex;align-items:center;gap:8px;justify-content:flex-end">'
            f'<span style="color:var(--mute);font-size:12px">{share_pct}%</span>'
            f'<span style="width:64px;display:inline-block">{_meter(r.cost_usd, mx)}</span></span>'
        )
        # Model · tier cell: each token stays whole; wrap only at the gap
        # between model name and tier when the column is genuinely narrow.
        model_cell = (
            '<span class="cal-cell-model">'
            f'<span style="font-family:var(--mono);color:var(--ink)">{_esc(r.model)}</span>'
            f'<span style="color:var(--mute)">· {_esc(r.tier)}</span>'
            "</span>"
        )
        body_rows.append(
            '<tr style="border-top:1px solid var(--border)">'
            + _td(_pill(_esc(r.vendor), mono=True))
            + _td(model_cell)
            + _td(fmt_money(r.cost_usd), align="right", mono=True)
            + _td(share_cell, align="right", numeric=True)
            + _td(fmt_int(r.events), align="right", mono=True)
            + _td(fmt_tokens(r.tokens), align="right", mono=True)
            + _td(fmt_pct(r.cache_hit_rate, 0), align="right", mono=True)
            + _td(_sparkline(r.daily_cost_sparkline, width=80, height=18), align="right")
            + "</tr>"
        )
    return (
        # overflow-x:auto + tabindex so wide sortable tables scroll (and are
        # keyboard-scrollable) on narrow screens instead of clipping columns.
        '<div tabindex="0" style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow-x:auto">'
        '<table class="cal-table data data-sortable" '
        'style="width:100%;border-collapse:collapse;font-size:13px">'
        + head
        + "<tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def _section_models(d: Dashboard, *, rhythm: str) -> str:
    if not d.by_model:
        return ""
    body = render_models(d.by_model, total_cost=d.totals.cost_usd)
    meta = f"{len(d.by_model)} model/tier rows · sorted by cost"
    return _section_wrap("models", rhythm=rhythm, body=body, meta=meta)


def render_projects(
    rows: Sequence[ProjectRow],
    *,
    show_paths: bool = False,
    total_cost: float | None = None,
    pm: _PrivacyMap | None = None,
) -> str:
    """Render the §05 projects table. Exposed for unit tests.

    The ``pm`` parameter applies the privacy map (project names + paths).
    When omitted, defaults to an off-mode map so legacy callers (tests,
    external scripts) keep the unredacted behaviour they had before.
    """
    if pm is None:
        # Build an empty map in "off" mode — every value passes through unchanged.
        pm = _PrivacyMap(mode="off", projects={}, sessions={})
    if not rows:
        return ""
    sorted_rows = sorted(rows, key=lambda r: (-r.cost_usd, -r.events))
    mx = max((r.cost_usd for r in sorted_rows), default=1.0) or 1.0
    total = float(total_cost) if total_cost else sum(r.cost_usd for r in sorted_rows) or 1.0
    head = (
        '<thead><tr style="background:var(--panel-2)">'
        f"{_th('Project')}"
        f"{_th('selected-window cost ↓', align='right', aria_sort='descending')}"
        f"{_th('Share of window', align='right')}"
        f"{_th('Events', align='right')}{_th('Sessions', align='right')}"
        f"{_th('Days', align='right')}{_th('Trend')}{_th('Top tools')}"
        "</tr></thead>"
    )
    body_rows: list[str] = []
    for r in sorted_rows:
        share = (r.cost_usd / total) if total else 0.0
        share_pct = int(round(share * 100))
        path_block = (
            '<span style="color:var(--mute);font-family:var(--mono);font-size:11px">'
            f"{_private_path(r.path, pm)}</span>"
            if show_paths and r.path
            else ""
        )
        if r.trend_tone == "warn":
            tone_color = "var(--warn)"
        elif r.trend_tone == "good":
            tone_color = "var(--ok)"
        else:
            tone_color = "var(--mute)"
        top_tool_pills = "".join(
            f'<span title="{_esc(t.name)} · {fmt_int(t.count)}" '
            'style="display:inline-flex;align-items:center;gap:4px;padding:1px 6px;'
            f"border-radius:2px;font-size:11px;color:{_SHAPE_COLORS.get(t.category, 'var(--mixed)')};"
            'background:var(--panel-2);border:1px solid var(--border)">'
            f'{_esc(t.name)}<span style="color:var(--mute)">{fmt_int(t.count)}</span></span>'
            for t in (r.top_tools or [])
        )
        body_rows.append(
            '<tr style="border-top:1px solid var(--border)">'
            + _td(
                '<div style="display:flex;flex-direction:column;gap:2px">'
                f'<span style="color:var(--ink);font-weight:500">{_private_project(r.name, pm)}</span>'
                f"{path_block}</div>"
            )
            + _td(fmt_money(r.cost_usd), align="right", mono=True)
            + _td(
                '<span class="cal-cell-share" '
                'style="display:inline-flex;align-items:center;gap:8px;justify-content:flex-end">'
                f'<span style="color:var(--mute);font-size:12px">{share_pct}%</span>'
                f'<span style="width:56px;display:inline-block">{_meter(r.cost_usd, mx)}</span></span>',
                align="right",
                numeric=True,
            )
            + _td(fmt_int(r.events), align="right", mono=True)
            + _td(fmt_int(r.sessions), align="right", mono=True)
            + _td(fmt_int(r.active_days), align="right", mono=True)
            + _td(
                f'<span style="color:{tone_color};font-size:12px;white-space:nowrap">{_esc(r.trend_label)}</span>'
            )
            + _td(
                f'<div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap">{top_tool_pills}</div>'
            )
            + "</tr>"
        )
    other_share = max(0.0, 1.0 - sum(r.cost_usd for r in sorted_rows) / total) if total else 0.0
    other_row = ""
    if other_share > 0.01:
        other_row = (
            '<tr style="border-top:1px solid var(--border);color:var(--mute);font-style:italic">'
            + _td("Other selected-window usage")
            + _td(fmt_money(other_share * total), align="right", mono=True)
            + _td(f"{int(round(other_share * 100))}%", align="right")
            + _td("—", align="right")
            + _td("—", align="right")
            + _td("—", align="right")
            + _td("")
            + _td("")
            + "</tr>"
        )
    return (
        # overflow-x:auto + tabindex so wide sortable tables scroll (and are
        # keyboard-scrollable) on narrow screens instead of clipping columns.
        '<div tabindex="0" style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow-x:auto">'
        '<table class="cal-table data data-sortable" '
        'style="width:100%;border-collapse:collapse;font-size:13px">'
        + head
        + "<tbody>"
        + "".join(body_rows)
        + other_row
        + "</tbody></table></div>"
    )


def _section_projects(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    if not d.by_project:
        return ""
    body = render_projects(
        d.by_project, show_paths=d.show_paths, total_cost=d.totals.cost_usd, pm=pm
    )
    meta = f"{len(d.by_project)} cost-ranked projects"
    return _section_wrap("projects", rhythm=rhythm, body=body, meta=meta)


def _insight_sample_size_chip(it: Insight) -> str:
    """Render the per-insight lineage line ("based on N events · M sessions · X tokens").

    Reads from :attr:`Insight.evidence_metrics`. Only the ``events`` /
    ``sessions`` / ``tokens`` keys are surfaced; anything else stays in
    the dict for callers that need it but isn't shown on the page. Returns
    an empty string when none of the three keys are present — an insight
    that legitimately lacks lineage data renders clean rather than fake.
    """
    metrics = getattr(it, "evidence_metrics", None) or {}
    parts: list[str] = []
    events = metrics.get("events")
    if isinstance(events, int | float) and events:
        parts.append(f"{fmt_int(int(events))} events")
    sessions = metrics.get("sessions")
    if isinstance(sessions, int | float) and sessions:
        parts.append(f"{fmt_int(int(sessions))} sessions")
    tokens = metrics.get("tokens")
    if isinstance(tokens, int | float) and tokens:
        parts.append(f"{fmt_tokens(int(tokens))} tokens")
    if not parts:
        return ""
    return (
        '<div class="cal-insight-meta" style="color:var(--ghost);font-size:11px;'
        'margin-top:5px;font-family:var(--mono);letter-spacing:0">'
        f"based on {' · '.join(parts)}</div>"
    )


def _insight_row(it: Insight, *, dense: bool, pm: _PrivacyMap) -> str:
    sev = it.severity
    if sev == "critical":
        accent = "var(--bad)"
    elif sev == "warn":
        accent = "var(--warn)"
    else:
        accent = "var(--accent)"
    pad = "12px 16px" if dense else "16px 20px"
    impact_html = (
        f'<span style="font-size:11px;color:var(--ink-2);background:var(--panel-2);'
        f"border:1px solid var(--border);border-radius:3px;padding:3px 8px;"
        f'white-space:nowrap">{_private_text(it.impact, pm)}</span>'
        if it.impact
        else ""
    )
    sample_chip = _insight_sample_size_chip(it)
    return (
        f'<div class="cal-insight-row" style="display:grid;grid-template-columns:auto 1fr auto;'
        f"gap:16px;align-items:baseline;padding:{pad};border-left:2px solid {accent};"
        f'background:var(--panel);border-top:1px solid var(--border)">'
        f"{_severity_token(sev)}"
        '<div style="min-width:0">'
        f'<div style="color:var(--ink);font-size:13px;font-weight:500">{_private_text(it.title, pm)}</div>'
        f'<div style="color:var(--mute);font-size:12px;margin-top:3px;line-height:1.5">{_private_text(it.detail, pm)}</div>'
        f"{sample_chip}"
        "</div>"
        f"{impact_html}</div>"
    )


def _section_insights(d: Dashboard, *, dense: bool, rhythm: str, pm: _PrivacyMap) -> str:
    insights = list(d.insights)
    if not insights:
        return ""
    order = {"critical": 0, "warn": 1, "info": 2}
    insights.sort(key=lambda it: order.get(it.severity, 9))
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">'
        + "".join(_insight_row(it, dense=dense, pm=pm) for it in insights)
        + "</div>"
    )
    return _section_wrap("insights", rhythm=rhythm, body=body)


def _fmt_sigma(z: float) -> str:
    """Clamp the σ display so math artifacts don't render as wild numbers.

    The anomaly detector already caps σ at :data:`anomaly.SIGMA_DISPLAY_CAP`
    before populating the payload, but this guard handles legacy data
    paths (e.g. JSON snapshots from earlier versions) too. Anything past
    the cap reads as ``≥20σ extreme`` so the user sees "this is off the
    scale" instead of "354210.2σ" which reads as a bug.
    """
    if z >= 20.0:
        return "≥20σ extreme"
    return f"{z:.1f}σ"


def _anomaly_action(kind: str) -> str:
    normalized = kind.lower()
    if "session" in normalized:
        return "Inspect this session before repeating the workflow."
    if "project" in normalized:
        return "Check what changed in this project on that day."
    if "model" in normalized:
        return "Check model, tier, and prompt shape for that day."
    return "Review this day before using it as a run-rate baseline."


def _section_anomalies(d: Dashboard, *, dense: bool, rhythm: str, pm: _PrivacyMap) -> str:
    if not d.anomalies:
        return ""
    pad = "12px 16px" if dense else "16px 20px"
    rows_html: list[str] = []
    for i, a in enumerate(d.anomalies):
        tone_color = "var(--bad)" if a.tone == "critical" else "var(--warn)"
        evidence_tone = "good" if a.evidence_status == "exact" else "warn"
        top = "none" if i == 0 else "1px solid var(--border)"
        baseline = fmt_money(a.baseline_usd)
        observed = fmt_money(a.observed_usd)
        impact = fmt_money(a.impact_usd)
        sigma_label = _fmt_sigma(a.z_score)
        action = _anomaly_action(a.kind)
        anomaly_metrics = [
            ("Actual spend", observed),
            ("Expected spend", baseline),
            ("Cost impact", f"+{impact}"),
        ]
        # Only show the percentage when we actually have one — "n/a" next to a
        # labelled metric reads as a half-broken finding.
        if a.impact_percent is not None:
            anomaly_metrics.append(("Impact %", f"+{a.impact_percent:.0f}%"))
        metrics_html = (
            '<div class="cal-metric-strip">'
            + "".join(
                '<span class="cal-metric-chip">'
                f'<span class="cal-metric-label">{_esc(label)}</span>'
                f'<span class="cal-metric-value">{_esc(value)}</span></span>'
                for label, value in anomaly_metrics
            )
            + "</div>"
        )
        comparison = ""
        if a.baseline_sample_count and a.comparison_scope:
            comparison = f" Compared with {a.baseline_sample_count:,} {a.comparison_scope}."
        rows_html.append(
            f'<div class="cal-anomaly-row" style="display:grid;grid-template-columns:auto 1fr auto;gap:16px;'
            f"align-items:start;padding:{pad};border-left:2px solid {tone_color};"
            f'border-top:{top}">'
            f'<span class="cal-anomaly-label" style="padding-top:2px">'
            f"{_severity_token(a.tone, 'Spend spike')}</span>"
            '<div class="cal-anomaly-main">'
            f'<div style="color:var(--ink);font-size:13px;font-weight:500">'
            f'{_esc(a.kind)} · <span style="font-family:var(--mono);color:var(--ink-2)">{_private_text(a.label, pm)}</span></div>'
            f'<div style="color:var(--mute);font-size:12px;margin-top:3px">'
            f"Detected on {_esc(a.timestamp)}."
            f"{_esc(comparison)}</div>"
            f"{metrics_html}"
            f'<div style="color:var(--ink-2);font-size:12px;margin-top:5px">{_esc(action)}</div>'
            "</div>"
            '<div class="cal-anomaly-side" style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">'
            f'<span style="font-size:13px;color:{tone_color};font-family:var(--mono);'
            f'font-weight:600;white-space:nowrap">+{_esc(impact)}</span>'
            f"{_pill(_esc(a.evidence_status), tone=evidence_tone)}"
            f'<span style="font-size:11px;color:var(--mute);font-family:var(--mono);'
            f'white-space:nowrap">detector {_esc(sigma_label)}</span>'
            "</div>"
            "</div>"
        )
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">' + "".join(rows_html) + "</div>"
    )
    meta = f"{len(d.anomalies)} spend spikes over detector thresholds"
    return _section_wrap("anomalies", rhythm=rhythm, body=body, meta=meta)


def _fmt_money_locale(v: float) -> str:
    """Match the JSX prototype's ``$<n>.toLocaleString()`` shape.

    JavaScript's ``toLocaleString()`` drops trailing decimals on whole numbers
    (``37`` → ``"37"``, ``1640`` → ``"1,640"``) and only keeps decimals when
    the value carries them. The shared :func:`fmt_money` always emits two
    decimals below 1000 — that's right for chart axes but wrong in places
    that copy this convention (currently the budgets row trailing label).
    """
    av = float(v)
    if av == int(av):
        return "$" + format(int(av), ",")
    if av >= 1000:
        return "$" + format(int(round(av)), ",")
    return "$" + format(av, ".2f")


def _section_budgets(d: Dashboard, *, rhythm: str) -> str:
    if not d.budgets:
        return ""
    rows_html: list[str] = []
    for b in d.budgets:
        pct = (b.spent / b.cap) * 100 if b.cap else 0.0
        if b.spent >= b.cap:
            tone_color = "var(--bad)"
        elif b.spent >= b.warn:
            tone_color = "var(--warn)"
        else:
            tone_color = "var(--ok)"
        rows_html.append(
            '<li style="display:grid;grid-template-columns:100px 1fr auto auto;gap:14px;'
            'align-items:center;font-size:13px">'
            f'<span style="color:var(--ink);font-weight:500">{_esc(b.period)}</span>'
            f"{_budget_bar(b.spent, b.cap, b.warn)}"
            f'<span style="font-family:var(--mono);color:{tone_color};font-size:12px">{pct:.0f}%</span>'
            f'<span style="font-family:var(--mono);color:var(--ink-2);font-size:12px;'
            f'min-width:140px;text-align:right">'
            f"{_fmt_money_locale(b.spent)} / {_fmt_money_locale(b.cap)}</span>"
            "</li>"
        )
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<ul style="list-style:none;padding:0;margin:0;display:grid;gap:14px">'
        + "".join(rows_html)
        + "</ul></div>"
    )
    return _section_wrap("budgets", rhythm=rhythm, body=body)


def _forecast_card(label: str, value: str, sub: str, band: str | None) -> str:
    band_html = (
        f'<div style="font-size:12px;color:var(--ink-2);margin-top:6px">{_esc(band)}</div>'
        if band
        else ""
    )
    return (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        f'<div style="font-size:11px;letter-spacing:0;color:var(--mute);'
        f'text-transform:uppercase;margin-bottom:6px">{_esc(label)}</div>'
        f'<div style="font-size:var(--num-lg);font-weight:600;color:var(--ink);margin-bottom:4px">{_esc(value)}</div>'
        f'<div style="font-size:12px;color:var(--mute)">{_esc(sub)}</div>'
        f"{band_html}</div>"
    )


def _section_forecast(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    panels: list[str] = []
    f: Forecast | None = d.forecast
    if f is not None:
        intro = (
            f'<div style="font-size:12px;color:var(--mute);margin-bottom:10px">'
            f"Based on {f.days_analyzed} days · projected through next "
            f"{f.days_remaining} days.</div>"
        )
        band1 = f"1σ band: {fmt_money(f.linear_low)} to {fmt_money(f.linear_high)}"
        band2 = f"Delta vs linear: {fmt_money(f.ewma_total - f.linear_total)}"
        cards = _forecast_card(
            "Selected-window run rate",
            fmt_money(f.linear_total),
            f"daily mean ${f.daily_mean:.0f} ± ${f.daily_stdev:.0f}",
            band1,
        ) + _forecast_card(
            "Recent-days weighted",
            fmt_money(f.ewma_total),
            "Weights recent spend higher",
            band2,
        )
        panels.append(
            intro + '<div class="cal-forecast-grid" style="display:grid;'
            'grid-template-columns:1fr 1fr;gap:12px">' + cards + "</div>"
        )

    if d.outlook:
        out = d.outlook
        panels.append(
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">'
            + _value_card(
                label="30d outlook",
                value=fmt_money(out.horizon_30d.linear_total),
                detail=(
                    f"Band {fmt_money(out.horizon_30d.linear_low)} to "
                    f"{fmt_money(out.horizon_30d.linear_high)}; recency-weighted "
                    f"{fmt_money(out.horizon_30d.ewma_total)}."
                ),
                tone="warn"
                if out.horizon_30d.ewma_total > out.horizon_30d.linear_total
                else "neutral",
            )
            + _value_card(
                label="90d outlook",
                value=fmt_money(out.horizon_90d.linear_total),
                detail=(
                    f"Band {fmt_money(out.horizon_90d.linear_low)} to "
                    f"{fmt_money(out.horizon_90d.linear_high)} from {out.days_analyzed} days."
                ),
                tone="neutral",
            )
            + "</div>"
        )

    if d.model_forecasts:
        rows = []
        for row in d.model_forecasts[:6]:
            rows.append(
                [
                    _esc(row.model),
                    fmt_money(row.projected_30d_cost_usd),
                    _esc(row.trend_label),
                    _sparkline(row.daily_cost_sparkline, width=72, height=18),
                ]
            )
        panels.append(_small_table(["Model", "30d", "Trend", "Recent"], rows))
    if d.forecast_drivers:
        rows = []
        for row in d.forecast_drivers[:8]:
            rows.append(
                [
                    _private_text(f"{row.dimension}: {row.label}", pm),
                    fmt_money(row.projected_30d_cost_usd),
                    fmt_pct(row.share, 0),
                    _esc(row.evidence_status),
                ]
            )
        panels.append(_small_table(["Driver", "30d", "Share", "Evidence"], rows))
    if d.seasonality:
        s = d.seasonality
        panels.append(
            '<div style="background:var(--panel);border:1px solid var(--border);'
            'border-radius:var(--r-md);padding:14px">'
            '<div style="display:flex;justify-content:space-between;gap:12px;margin-bottom:10px">'
            '<span style="font-size:12px;color:var(--ink);font-weight:600">Cost-weighted rhythm</span>'
            f'<span style="font-family:var(--mono);font-size:12px;color:var(--mute)">peak {s.peak_hour:02d}:00 · off-peak {fmt_pct(s.off_peak_share, 0)}</span>'
            "</div>"
            f"{_hour_bars(s.by_hour_cost_usd)}"
            f'<div style="font-size:11px;color:var(--mute);margin-top:9px">{_esc(s.timezone)} · {fmt_money(s.total_cost_usd)} distributed by local hour</div>'
            "</div>"
        )
    if not panels:
        return ""
    body = '<div style="display:grid;gap:12px">' + "".join(panels) + "</div>"
    meta = f"{len(d.model_forecasts)} model forecasts · {len(d.forecast_drivers)} drivers"
    return _section_wrap("forecast", rhythm=rhythm, body=body, meta=meta)


def _section_advisor(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    rows: list[AdvisorRecommendation] = list(d.advisor_recommendations)
    if not rows:
        return ""
    total = sum(r.savings_usd for r in rows)
    header = (
        '<div style="padding:10px 16px;background:var(--panel-2);'
        "border-bottom:1px solid var(--border);display:flex;"
        'justify-content:space-between;font-size:12px;color:var(--mute)">'
        f"<span>{len(rows)} recommendations · estimated total savings</span>"
        f'<span style="color:var(--ok);font-family:var(--mono);font-weight:600">{fmt_money(total)}</span>'
        "</div>"
    )
    body_rows: list[str] = []
    for i, r in enumerate(rows):
        top = "none" if i == 0 else "1px solid var(--border)"
        conf_tone = "var(--ok)" if r.confidence >= 0.75 else "var(--warn)"
        body_rows.append(
            '<div class="cal-advisor-row" '
            'style="display:grid;grid-template-columns:1fr auto auto;gap:14px;'
            f'padding:12px 16px;border-top:{top};align-items:center">'
            '<div style="min-width:0">'
            f'<div style="font-size:13px;color:var(--ink);font-weight:500">{_private_text(r.title, pm)}</div>'
            f'<div style="font-size:12px;color:var(--mute);margin-top:3px">{_private_text(r.detail, pm)}</div>'
            f'<code style="display:inline-block;margin-top:6px;font-family:var(--mono);'
            f'font-size:11px;color:var(--accent);background:transparent;padding:0">$ {_private_text(r.action, pm)}</code>'
            "</div>"
            '<div style="text-align:right">'
            '<div style="font-size:11px;color:var(--mute);margin-bottom:2px">confidence</div>'
            f'<div style="font-family:var(--mono);color:{conf_tone};font-size:12px">{int(round(r.confidence * 100))}%</div>'
            "</div>"
            '<div style="text-align:right">'
            '<div style="font-size:11px;color:var(--mute);margin-bottom:2px">est. savings</div>'
            f'<div style="font-family:var(--mono);font-size:15px;color:var(--ok);font-weight:600">{fmt_money(r.savings_usd)}</div>'
            "</div></div>"
        )
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">' + header + "".join(body_rows) + "</div>"
    )
    return _section_wrap("advisor", rhythm=rhythm, body=body)


def _section_rate_limits(d: Dashboard, *, rhythm: str) -> str:
    r: RateLimitPressure | None = d.rate_limit_pressure
    if r is None:
        return ""

    def _meter_block(label: str, pct: float | None, note: str) -> str:
        if pct is None:
            return (
                "<div>"
                '<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">'
                f'<span style="color:var(--ink-2)">{_esc(label)}</span>'
                '<span style="color:var(--mute)">—</span></div>'
                f"{_meter(0, 1)}"
                f'<div style="font-size:11px;color:var(--mute);margin-top:6px">{_esc(note)}</div></div>'
            )
        if pct > 0.8:
            color = "var(--bad)"
        elif pct > 0.6:
            color = "var(--warn)"
        else:
            color = "var(--ok)"
        return (
            "<div>"
            '<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">'
            f'<span style="color:var(--ink-2)">{_esc(label)}</span>'
            f'<span style="font-family:var(--mono);color:{color}">{pct * 100:.0f}%</span></div>'
            f"{_meter(pct, 1, color=color, height=8)}"
            f'<div style="font-size:11px;color:var(--mute);margin-top:6px">{_esc(note)}</div>'
            "</div>"
        )

    peak_note = f"{r.sample_count} samples"
    latest_note = f"{r.latest_limit_name} · {r.latest_plan_type}"
    secondary_pct = (r.peak_secondary_pct or 0) * 100
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
        + _meter_block("Peak primary", r.peak_primary_pct, peak_note)
        + _meter_block("Latest primary", r.latest_primary_pct, latest_note)
        + "</div>"
        '<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border);'
        'font-size:11px;color:var(--mute);font-family:var(--mono)">'
        f"Resets at {_esc(r.latest_resets_at)} · peak secondary {secondary_pct:.0f}%"
        "</div></div>"
    )
    return _section_wrap("rate-limits", rhythm=rhythm, body=body)


def _section_heatmap(d: Dashboard, *, rhythm: str) -> str:
    if d.recap is None or not d.recap.hours:
        return ""
    total_calls = sum(c.value for c in d.recap.hours)
    # Peak-hour caption: surface the busiest hour-of-day across all weekdays.
    # The prototype hard-coded "peak hour: 15:00 · 16:00"; we derive the same
    # shape from data so the caption is accurate for real payloads too.
    by_hour: dict[int, int] = {}
    for c in d.recap.hours:
        by_hour[c.hour] = by_hour.get(c.hour, 0) + c.value
    if by_hour:
        peak1, peak2 = sorted(by_hour, key=lambda h: -by_hour[h])[:2]
        if peak2 is None:
            peak_caption = f"peak hour: {peak1:02d}:00"
        else:
            lo, hi = sorted((peak1, peak2))
            peak_caption = f"peak hour: {lo:02d}:00 · {hi:02d}:00"
    else:
        peak_caption = ""
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:16px">'
        '<div style="display:flex;justify-content:space-between;margin-bottom:12px;'
        'font-size:12px;color:var(--mute)">'
        f"<span>AI tool calls by hour of day · {fmt_int(total_calls)} total</span>"
        f'<span style="font-family:var(--mono)">{peak_caption}</span></div>'
        f"{_heatmap_7x24(d.recap)}"
        "</div>"
    )
    return _section_wrap("heatmap", rhythm=rhythm, body=body)


def _section_sessions(d: Dashboard, *, rhythm: str, pm: _PrivacyMap) -> str:
    rows: list[SessionRow] = sorted(d.top_sessions, key=lambda r: -r.cost_usd)
    if not rows:
        return ""
    mx = max((r.cost_usd for r in rows), default=1.0) or 1.0
    total_cost = float(d.totals.cost_usd or 0.0)
    head = (
        '<thead><tr style="background:var(--panel-2)">'
        f"{_th('Session')}{_th('Started')}{_th('Project')}"
        f"{_th('Cost ↓', align='right', aria_sort='descending')}"
        f"{_th('Tokens', align='right')}{_th('Events', align='right')}"
        f"{_th('Tools', align='right')}{_th('Models')}{_th('Reason')}"
        "</tr></thead>"
    )
    body_rows: list[str] = []
    for s in rows:
        models_html = "".join(_pill(_esc(m), mono=True) for m in (s.models or []))
        model_text = ", ".join(s.models) if s.models else "unknown model"
        title_session = pm.sessions.get(s.label, "Session ?") if pm.mode != "off" else s.label
        title_project = pm.projects.get(s.project, "Project ?") if pm.mode != "off" else s.project
        share = (s.cost_usd / total_cost) if total_cost > 0 else 0.0
        hover_label = (
            f"{title_session} in {title_project}: {fmt_money(s.cost_usd)} "
            f"({fmt_pct(share)} of selected-window cost), {fmt_tokens(s.total_tokens)}, "
            f"{fmt_int(s.events)} events, {fmt_int(s.tool_calls)} tool calls, "
            f"{model_text}. Reason: {s.reason or 'ranked by cost'}."
        )
        cost_cell = (
            '<div style="display:flex;gap:8px;justify-content:flex-end;align-items:center">'
            f'<span style="width:44px">{_meter(s.cost_usd, mx)}</span>'
            f"<span>{fmt_money(s.cost_usd)}</span></div>"
        )
        body_rows.append(
            f'<tr class="cal-session-row" aria-label="{_esc(hover_label)}" '
            'style="border-top:1px solid var(--border)">'
            + _td(
                f'<span style="font-family:var(--mono);color:var(--ink)">{_private_session(s.label, pm)}</span>'
            )
            + _td(_esc(s.started_at), mono=True, muted=True)
            + _td(f'<span style="color:var(--ink-2)">{_private_project(s.project, pm)}</span>')
            + _td(cost_cell, align="right", mono=True)
            + _td(fmt_tokens(s.total_tokens), align="right", mono=True)
            + _td(fmt_int(s.events), align="right", mono=True)
            + _td(fmt_int(s.tool_calls), align="right", mono=True)
            + _td(f'<div style="display:flex;gap:4px;flex-wrap:wrap">{models_html}</div>')
            + _td(_esc(s.reason), muted=True)
            + "</tr>"
        )
    body = (
        '<div tabindex="0" style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow-x:auto">'
        '<table class="cal-table" style="width:100%;border-collapse:collapse;'
        'font-size:13px;table-layout:fixed">'
        '<colgroup><col style="width:16%"><col style="width:12%"><col style="width:14%">'
        '<col style="width:11%"><col style="width:10%"><col style="width:8%">'
        '<col style="width:8%"><col style="width:13%"><col style="width:8%"></colgroup>'
        + head
        + "<tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )
    return _section_wrap("sessions", rhythm=rhythm, body=body)


def _section_evidence(d: Dashboard, *, dense: bool, rhythm: str) -> str:
    if not d.evidence:
        return ""
    pad = "8px 0" if dense else "10px 0"
    dots = {"exact": "●", "estimated": "◐", "partial": "◐", "unsupported": "○"}
    colors = {
        "exact": "var(--ok)",
        "estimated": "var(--warn)",
        "partial": "var(--warn)",
        "unsupported": "var(--bad)",
    }
    rows: list[str] = []
    for e in d.evidence:
        color = colors.get(e.status, "var(--mute)")
        dot = dots.get(e.status, "·")
        rows.append(
            f'<div style="display:grid;grid-template-columns:180px auto 1fr;gap:16px;'
            f'align-items:baseline;padding:{pad};border-bottom:1px solid var(--border)">'
            f'<span style="color:var(--ink);font-size:13px">{_esc(e.label)}</span>'
            f'<span style="display:inline-flex;gap:6px;align-items:baseline;color:{color};'
            f'font-size:12px;font-weight:500;font-family:var(--mono)">'
            f'<span aria-hidden="true">{dot}</span><span>{_esc(e.status)}</span></span>'
            f'<span style="color:var(--mute);font-size:12px;font-style:italic">{_esc(e.note)}</span>'
            "</div>"
        )
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);padding:8px 16px">' + "".join(rows) + "</div>"
    )
    return _section_wrap("evidence", rhythm=rhythm, body=body)


# ============================================================================
# Variant shells
# ============================================================================

_SECTION_ORDER: list[str] = [
    "action-center",
    "overview",
    "cost",
    "usage-windows",
    "usage-mix",
    "anomalies",
    "inefficiencies",
    "forecast",
    "budgets",
    "models",
    "projects",
    "sessions",
    "shape",
    "rate-limits",
    "heatmap",
    "attribution",
    "evidence",
    "insights",
    "outlook",
    "advisor",
]

# ----------------------------------------------------------------------------
# Tier system (Phase 1 UX overhaul)
#
# Section IDs and numbers (§00..§19) remain stable so anchor links keep
# working. Tiers control visual grouping and progressive disclosure only:
#
#   decisions  — what to act on (always visible, rendered first)
#   trajectory — what's happening (always visible)
#   appendix   — supporting evidence (collapsed in a single <details>)
#   trust      — evidence footer (always visible, terse)
# ----------------------------------------------------------------------------

_SECTION_TIER: dict[str, str] = {
    "action-center": "decisions",
    "inefficiencies": "decisions",
    "anomalies": "decisions",
    "budgets": "decisions",
    "rate-limits": "decisions",
    "insights": "decisions",
    "overview": "trajectory",
    "cost": "trajectory",
    "forecast": "trajectory",
    "projects": "trajectory",
    "usage-mix": "trajectory",
    "models": "appendix",
    "shape": "appendix",
    "sessions": "appendix",
    "heatmap": "appendix",
    # 7/30/90-day rolling spend is the headline trend (the CLI's "start with
    # caliper overview"), not buried supporting material — keep it visible.
    "usage-windows": "trajectory",
    "attribution": "appendix",
    "evidence": "trust",
    # Disabled (never rendered) — bucket assignment is irrelevant.
    "advisor": "appendix",
    "outlook": "appendix",
}

_TIER_ORDER: tuple[str, ...] = ("decisions", "trajectory", "appendix", "trust")


def _sections_by_tier(d: Dashboard) -> dict[str, list[str]]:
    """Group renderable section IDs by tier, preserving ``_SECTION_ORDER``."""
    out: dict[str, list[str]] = {tier: [] for tier in _TIER_ORDER}
    for sid in _SECTION_ORDER:
        if not _should_render(sid, d):
            continue
        out[_SECTION_TIER.get(sid, "appendix")].append(sid)
    return out


# Friendly display names for the canonical tool/vendor IDs. The parsers emit
# raw IDs like ``"claude-code"`` and ``"openai-codex"``; the masthead shows
# the human form. Order is the canonical "known sources" order — every tool
# Caliper can ingest, surfaced even when a particular run didn't detect logs
# from it (so the user can SEE that Codex was searched-for and not found).
KNOWN_SOURCES: tuple[tuple[str, str], ...] = (
    ("claude-code", "Claude Code"),
    ("openai-codex", "OpenAI Codex"),
    ("cursor", "Cursor"),
    ("aider", "Aider"),
)


# Phase-3 polish: visible numbering. The audit-anchor map (`SECTION_NUMBERS`)
# stays §00–§19 so external links keep resolving, but the *displayed* number
# on each section / TOC entry counts 1..N in tier render order, skipping
# disabled sections. This makes the index feel clean (1, 2, 3, …) instead of
# leaking "§07" / "§17" gaps to the reader.
_RENDER_NUM_MAP: ContextVar[dict[str, str] | None] = ContextVar(
    "caliper_render_num_map", default=None
)


def _compute_display_numbers(d: Dashboard) -> dict[str, str]:
    """Sequential 1..N labels in tier-respecting render order."""
    out: dict[str, str] = {}
    counter = 0
    tiered = _sections_by_tier(d)
    for tier in _TIER_ORDER:
        for sid in tiered[tier]:
            counter += 1
            out[sid] = str(counter)
    return out


def _display_num(section_id: str) -> str:
    """Resolve the visible number for a section. Falls back to the legacy
    ``§NN`` label when no render-time map is active (e.g., raw helper calls
    from tests)."""
    mapping = _RENDER_NUM_MAP.get()
    if mapping is not None and section_id in mapping:
        return mapping[section_id]
    return SECTION_NUMBERS.get(section_id, "")


_TIER_LABEL: dict[str, str] = {
    "decisions": "Decisions",
    "trajectory": "Trajectory",
    "appendix": "Appendix",
    "trust": "Trust",
}


def _palette_index(d: Dashboard, pm: _PrivacyMap) -> str:
    """Build a JSON search index for the cmd+K palette (Phase 3).

    Searches over: tier sections, top models, top projects, anomalies,
    advisor recommendations. The palette JS reads this as a `<script
    type="application/json">` block and filters on each keystroke. Labels are
    run through `_redact_plain` so a Safe Share (``always``) file never embeds
    real project/session names in this index.
    """
    import json

    items: list[dict[str, str]] = []
    for sid in _SECTION_ORDER:
        if _should_render(sid, d):
            items.append(
                {
                    "type": "section",
                    "label": _SECTION_TITLES[sid],
                    "anchor": sid,
                    "hint": _display_num(sid),
                }
            )
    for m in (d.by_model or [])[:20]:
        items.append(
            {
                "type": "model",
                "label": f"{m.vendor} · {m.model}",
                "anchor": "models",
                "hint": fmt_money(m.cost_usd),
            }
        )
    for p in (d.by_project or [])[:20]:
        items.append(
            {
                "type": "project",
                "label": _redact_plain(p.name, pm),
                "anchor": "projects",
                "hint": fmt_money(p.cost_usd),
            }
        )
    for a in (d.anomalies or [])[:20]:
        items.append(
            {
                "type": "anomaly",
                "label": _redact_plain(f"{a.kind} · {a.timestamp}", pm),
                "anchor": "anomalies",
                "hint": fmt_money(a.impact_usd),
            }
        )
    for r in (d.advisor_recommendations or [])[:10]:
        items.append(
            {
                "type": "fix",
                "label": _redact_plain(r.title, pm),
                "anchor": "inefficiencies",
                "hint": fmt_money(r.savings_usd),
            }
        )
    return json.dumps(items, ensure_ascii=False)


def _render_palette() -> str:
    """Static markup for the cmd+K palette. The inline JS toggles `[hidden]`
    and populates the results list on each keystroke."""
    return (
        '<div class="cal-palette" id="cal-palette" hidden '
        'role="dialog" aria-modal="true" aria-label="Search palette">'
        '<div class="cal-palette-backdrop" data-palette-close></div>'
        '<div class="cal-palette-dialog">'
        '<input class="cal-palette-input" type="search" '
        'placeholder="Search sections, models, projects, anomalies…" '
        'aria-label="Search query" autocomplete="off" spellcheck="false" '
        'role="combobox" aria-controls="cal-palette-results" '
        'aria-expanded="false" aria-activedescendant="">'
        '<ul class="cal-palette-results" id="cal-palette-results" role="listbox" '
        'aria-label="Search results"></ul>'
        '<div class="cal-palette-hints">'
        "<kbd>↑</kbd><kbd>↓</kbd> navigate · "
        "<kbd>↵</kbd> open · "
        "<kbd>Esc</kbd> close"
        "</div>"
        "</div></div>"
    )


def _render_receipt_toc(d: Dashboard) -> str:
    """Sticky right-rail table of contents for the Receipt rhythm.

    Grouped by tier; the scroll-spy script (`_INTERACTIVE_SCRIPT`) toggles
    `aria-current="location"` on the link whose section is in view. Renders
    even when interactive JS is off — clicking still scrolls, and `:target`
    handles the highlight without JS.
    """
    tiered = _sections_by_tier(d)
    has_any = any(tiered[t] for t in _TIER_ORDER)
    if not has_any:
        return ""
    groups: list[str] = []
    for tier in _TIER_ORDER:
        sids = tiered[tier]
        if not sids:
            continue
        items: list[str] = []
        for sid in sids:
            num = _display_num(sid)
            title = _SECTION_TITLES[sid]
            items.append(
                f'<li><a class="cal-toc-link" href="#{sid}" data-toc-target="{sid}">'
                f'<span class="cal-toc-num">{num}</span>'
                f'<span class="cal-toc-title">{_esc(title)}</span>'
                "</a></li>"
            )
        groups.append(
            '<div class="cal-toc-group">'
            f'<div class="cal-toc-group-label">{_esc(_TIER_LABEL[tier])}</div>'
            '<ul class="cal-toc-list">' + "".join(items) + "</ul>"
            "</div>"
        )
    return (
        '<nav class="cal-receipt-toc" aria-label="Section navigation">'
        '<div class="cal-toc-eyebrow">Index</div>' + "".join(groups) + "</nav>"
    )


# ----------------------------------------------------------------------------
# Severity token — single canonical chip used across the redesign
# (Von Restorff: critical = filled + 1-shot pulse; everything else neutral)
# ----------------------------------------------------------------------------

_SEV_GLYPH: dict[str, str] = {
    "critical": "●",
    "warn": "◐",
    "info": "○",
    "ok": "✓",
}


def _severity_token(level: str, label: str | None = None) -> str:
    """Render the canonical severity chip. ``level`` is one of the four tokens.

    ``label`` is the visible text — kept in its original case so screen
    readers and search/test tooling can see "Spend spike" rather than
    "SPEND SPIKE". The visual uppercase comes from CSS (text-transform).
    """
    lvl = (level or "info").lower()
    if lvl in ("bad", "critical", "fail"):
        lvl = "critical"
    elif lvl in ("warn", "warning"):
        lvl = "warn"
    elif lvl in ("good", "ok"):
        lvl = "ok"
    else:
        lvl = "info"
    text = _esc(label or lvl)
    glyph = _SEV_GLYPH[lvl]
    # No role="status": these are static styled labels, not live regions.
    # The colour-coded glyph is decorative (aria-hidden); the text label
    # carries the meaning for assistive tech.
    return (
        f'<span class="sev sev-{lvl}">'
        f'<span class="sev-glyph" aria-hidden="true">{glyph}</span>'
        f"<span>{text}</span></span>"
    )


# ----------------------------------------------------------------------------
# Billboard — single above-the-fold "biggest fix" peak (Peak-End Rule)
# ----------------------------------------------------------------------------


def _render_billboard(card: BillboardCard, rhythm: str) -> str:
    """Render the one-headline above-the-fold billboard.

    ``rhythm`` is reserved for future visual variants; today the same
    markup serves both receipt and terminal. The card is purposely larger
    and quieter than the existing ``_hero_verdict_strip`` so the eye lands
    here first (Aesthetic-Usability + Krug billboard test).
    """
    tone = card.tone or "neutral"
    rail = {
        "warn": "var(--warn)",
        "critical": "var(--bad)",
        "good": "var(--ok)",
    }.get(tone, "var(--accent)")
    headline_color = {
        "warn": "var(--warn)",
        "critical": "var(--bad)",
        "good": "var(--ok)",
    }.get(tone, "var(--accent)")

    confidence_html = ""
    if card.confidence_pct is not None:
        confidence_html = (
            '<span class="cal-billboard-confidence" '
            'style="display:inline-flex;align-items:center;gap:6px;padding:3px 9px;'
            "border:1px solid var(--border);border-radius:999px;"
            "font-family:var(--mono);font-size:11px;color:var(--mute);"
            'background:var(--panel-2)">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{rail}"></span>'
            f"<span>{card.confidence_pct}% confidence</span>"
            "</span>"
        )

    rationale_html = (
        f'<p class="cal-billboard-rationale" '
        'style="margin:0;color:var(--ink-2);font-size:14px;line-height:1.55;'
        f'max-width:62ch">{_esc(card.rationale)}</p>'
        if card.rationale
        else ""
    )

    command_html = (
        '<div class="cal-billboard-command" '
        'style="font-family:var(--mono);font-size:12px;color:var(--accent);'
        "margin-top:12px;padding:8px 12px;background:var(--panel-2);"
        "border:1px solid var(--border);border-radius:var(--r-sm);"
        'overflow-wrap:anywhere;word-break:break-word">'
        f'<span style="color:var(--ghost)">$ </span>{_esc(card.command)}</div>'
        if card.command
        else ""
    )

    cta_html = (
        f'<a class="cal-billboard-cta" href="#{_esc(card.cta_anchor or "")}" '
        'style="display:inline-flex;align-items:center;gap:8px;margin-top:18px;'
        "padding:11px 18px;background:var(--accent);color:var(--bg);"
        "border-radius:var(--r-md);font-weight:600;font-size:13px;"
        'text-decoration:none;letter-spacing:0">'
        f"<span>{_esc(card.cta_label or 'Investigate')}</span>"
        '<span class="cal-billboard-arrow" aria-hidden="true">→</span>'
        "</a>"
        if card.cta_label and card.cta_anchor
        else ""
    )

    return (
        '<div class="cal-billboard" '
        f'data-billboard-kind="{_esc(card.kind)}" '
        f'data-billboard-tone="{_esc(tone)}" '
        'role="region" aria-label="Top recommendation" '
        'style="position:relative;background:var(--panel);'
        "border:1px solid var(--border);border-radius:var(--r-md);"
        'padding:22px 26px 24px;overflow:hidden">'
        f'<span aria-hidden="true" style="position:absolute;left:0;top:0;bottom:0;'
        f'width:3px;background:{rail}"></span>'
        f'<span class="cal-billboard-headline" '
        'style="font-family:var(--mono);font-size:11px;letter-spacing:0;'
        f'color:{headline_color};text-transform:uppercase;font-weight:700">'
        f"{_esc(card.headline)}"
        "</span>"
        '<div class="cal-billboard-value-row" '
        'style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-top:8px">'
        '<span class="cal-billboard-value" '
        'style="font-size:var(--num-xl);font-weight:700;color:var(--ink);'
        'letter-spacing:0;line-height:1.05">'
        f"{_esc(card.value)}</span>"
        f"{confidence_html}"
        "</div>"
        f'<div style="margin-top:12px">{rationale_html}</div>'
        f"{command_html}"
        f"{cta_html}"
        "</div>"
    )


def _render_section(
    section_id: str, d: Dashboard, *, dense: bool, rhythm: str, pm: _PrivacyMap
) -> str:
    if section_id == "action-center":
        return _section_action_center(d, rhythm=rhythm, pm=pm)
    if section_id == "overview":
        return _section_overview(d, dense=dense, rhythm=rhythm)
    if section_id == "usage-windows":
        return _section_usage_windows(d, rhythm=rhythm)
    if section_id == "cost":
        return _section_cost(d, rhythm=rhythm)
    if section_id == "shape":
        return _section_shape(d, rhythm=rhythm)
    if section_id == "models":
        return _section_models(d, rhythm=rhythm)
    if section_id == "projects":
        return _section_projects(d, rhythm=rhythm, pm=pm)
    if section_id == "usage-mix":
        return _section_usage_mix(d, rhythm=rhythm, pm=pm)
    if section_id == "insights":
        return _section_insights(d, dense=dense, rhythm=rhythm, pm=pm)
    if section_id == "anomalies":
        return _section_anomalies(d, dense=dense, rhythm=rhythm, pm=pm)
    if section_id == "budgets":
        return _section_budgets(d, rhythm=rhythm)
    if section_id == "inefficiencies":
        return _section_inefficiencies(d, rhythm=rhythm, pm=pm)
    if section_id == "forecast":
        return _section_forecast(d, rhythm=rhythm, pm=pm)
    if section_id == "outlook":
        return _section_outlook(d, rhythm=rhythm, pm=pm)
    if section_id == "advisor":
        return _section_advisor(d, rhythm=rhythm, pm=pm)
    if section_id == "rate-limits":
        return _section_rate_limits(d, rhythm=rhythm)
    if section_id == "heatmap":
        return _section_heatmap(d, rhythm=rhythm)
    if section_id == "sessions":
        return _section_sessions(d, rhythm=rhythm, pm=pm)
    if section_id == "attribution":
        return _section_attribution(d, rhythm=rhythm, pm=pm)
    if section_id == "evidence":
        return _section_evidence(d, dense=dense, rhythm=rhythm)
    return ""


def _build_id(d: Dashboard) -> str:
    sha = getattr(d.caliper, "build_sha", "") or "00000000"
    sha4 = (sha or "0000")[:4]
    date_compact = (d.generated_at or "")[:10].replace("-", "") or "00000000"
    return f"CALIPER-{date_compact}-{sha4}"


def _render_receipt(d: Dashboard, *, dense: bool, pm: _PrivacyMap) -> str:
    rhythm = "receipt"
    ev = d.quality_score
    evidence_badge = _evidence_badge(ev) if ev else ""
    gen_line = (d.generated_at or "").replace("T", " ")[:16]
    vendor_count = len(d.window.vendors_active)
    vendor_total = d.window.vendor_count_total
    # Show EVERY known source as a chip with detected/missing status, so the
    # reader can confirm at a glance that Codex, Cursor, Aider, Claude Code
    # were all searched for — not just the ones that happened to be found.
    active_set = set(d.window.vendors_active or ())
    chips: list[str] = []
    for vid, label in KNOWN_SOURCES:
        detected = vid in active_set
        if detected:
            glyph = "✓"
            color = "var(--ok)"
            ink = "var(--ink)"
            weight = "600"
            border = "var(--ok-tint)"
            bg = "var(--ok-tint)"
            title = f"{label}: detected"
        else:
            glyph = "·"
            color = "var(--ghost)"
            ink = "var(--ghost)"
            weight = "500"
            border = "var(--border)"
            bg = "transparent"
            title = f"{label}: no logs found in this window"
        chips.append(
            '<span class="cal-source-chip" '
            f'title="{_esc(title)}" '
            'style="display:inline-flex;align-items:center;gap:5px;padding:3px 9px;'
            f"border:1px solid {border};border-radius:999px;background:{bg};"
            'font-family:var(--font);font-size:11px;white-space:nowrap">'
            f'<span aria-hidden="true" style="color:{color};font-weight:700;font-size:10px">{glyph}</span>'
            f'<span style="color:{ink};font-weight:{weight}">{_esc(label)}</span>'
            "</span>"
        )
    # Show extra vendors (anything beyond the known four) as plain chips
    # so unusual data doesn't silently disappear.
    known_ids = {vid for vid, _ in KNOWN_SOURCES}
    extras = sorted(v for v in active_set if v not in known_ids)
    for extra in extras:
        chips.append(
            '<span class="cal-source-chip" '
            f'title="{_esc(extra)}: detected (custom source)" '
            'style="display:inline-flex;align-items:center;gap:5px;padding:3px 9px;'
            "border:1px solid var(--accent-tint-2);border-radius:999px;"
            "background:var(--accent-tint);"
            'font-family:var(--font);font-size:11px;white-space:nowrap">'
            '<span aria-hidden="true" style="color:var(--accent);font-weight:700;font-size:10px">✓</span>'
            f'<span style="color:var(--ink);font-weight:600">{_esc(extra)}</span>'
            "</span>"
        )
    sources_row = (
        '<div class="cal-source-row" '
        'style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end">'
        f'<span style="color:var(--mute);font-family:var(--mono);font-size:10px;'
        f'letter-spacing:0;text-transform:uppercase;font-weight:600">Sources</span>'
        f'<span style="color:var(--ghost);font-family:var(--mono);font-size:11px">'
        f"{vendor_count}/{vendor_total}</span>" + "".join(chips) + "</div>"
    )
    masthead = (
        '<header role="banner" style="display:grid;grid-template-columns:1fr auto;gap:16px;'
        'align-items:start;padding-bottom:18px;border-bottom:1px solid var(--border)">'
        "<div>"
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">'
        f"{_caliper_mark(26)}"
        '<h1 style="margin:0;font-size:22px;font-weight:600;letter-spacing:0;color:var(--ink)">'
        f'Caliper <span style="color:var(--mute);font-size:12px;font-family:var(--mono);font-weight:400;margin-left:6px">v{_esc(d.caliper.version)}</span>'
        "</h1></div>"
        '<div style="color:var(--mute);font-size:12px">'
        "Cost layer for AI-assisted development · offline, auditable, no login</div></div>"
        '<div style="text-align:right;display:flex;flex-direction:column;gap:8px;align-items:flex-end;min-width:0">'
        f'<div style="display:flex;gap:8px;align-items:center">{evidence_badge}{_window_badge(d.window)}</div>'
        f"{sources_row}"
        '<div style="font-size:11px;color:var(--mute);font-family:var(--mono);display:flex;gap:14px;align-items:center;flex-wrap:wrap;justify-content:flex-end">'
        f"{_status_dot('good', 'offline')}<span>Generated {_esc(gen_line)}</span></div>"
        f'<div style="font-size:11px;color:var(--ghost);font-family:var(--mono)">{_build_id(d)}</div>'
        "</div></header>"
    )
    banner_html = (
        f'<div style="margin-top:18px">{_banner_html(d.banner)}</div>'
        if d.banner is not None
        else ""
    )
    billboard_html = (
        f'<div style="margin-top:22px">{_render_billboard(d.billboard, rhythm)}</div>'
        if d.billboard is not None
        else ""
    )
    # When a billboard is set, it replaces the hero verdict strip as the
    # above-the-fold peak. Keep the existing strip available for legacy
    # payloads that omit the billboard.
    hero_inner = "" if d.billboard is not None else _hero_verdict_strip(d, rhythm)
    hero_html = f'<div style="margin-top:18px">{hero_inner}</div>' if hero_inner else ""
    verdict_html = (
        f'<div style="margin-top:18px">{_verdict_strip(d, rhythm)}</div>'
        if d.executive_brief and d.executive_brief.findings
        else ""
    )
    # The above-the-fold banner/billboard/verdict carry the primary CTA and
    # verdict, so they must sit inside a landmark (otherwise screen-reader
    # landmark navigation skips the most important content).
    summary_inner = banner_html + billboard_html + hero_html + verdict_html
    summary_band = (
        f'<section class="cal-summary-band" aria-label="Summary">{summary_inner}</section>'
        if summary_inner
        else ""
    )
    tiered = _sections_by_tier(d)
    decisions_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["decisions"]
    )
    trajectory_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["trajectory"]
    )
    appendix_sections_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["appendix"]
    )
    trust_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["trust"]
    )
    appendix_count = len(tiered["appendix"])
    appendix_html = ""
    if appendix_sections_html:
        plural = "" if appendix_count == 1 else "s"
        appendix_html = (
            '<details class="cal-appendix">'
            '<summary class="cal-appendix-summary">'
            '<span class="cal-appendix-chev" aria-hidden="true">▸</span>'
            f'<span class="cal-appendix-label">Technical appendix</span>'
            f'<span class="cal-appendix-count">{appendix_count} section{plural}</span>'
            "</summary>"
            f'<div class="cal-appendix-body">{appendix_sections_html}</div>'
            "</details>"
        )
    main_html = decisions_html + trajectory_html + appendix_html + trust_html
    toc_html = _render_receipt_toc(d)
    body_html = (
        '<div class="cal-receipt-body">'
        f'<main id="cal-main" class="cal-receipt-main">{main_html}</main>'
        f"{toc_html}"
        "</div>"
        if toc_html
        else (
            '<main id="cal-main" class="cal-receipt-main" '
            'style="margin-top:24px">'
            f"{main_html}</main>"
        )
    )
    return (
        '<div class="cal-dashboard-root cal-receipt-root">'
        f"{masthead}"
        f"{summary_band}"
        f"{body_html}"
        f"{_caliper_footer(d)}"
        "</div>"
    )


def _terminal_masthead(d: Dashboard) -> str:
    """Top status bar for the Terminal rhythm.

    Three zones, separated by hairlines so the eye reads them cleanly:

    * **Brand** — Caliper icon (26px, matching the Receipt header) +
      wordmark + version. Right-padded so the wordmark doesn't kiss
      the divider.
    * **Stats** — OFFLINE indicator, vendor count, generated-at,
      timezone. Center-aligned, monospace, baseline-aligned.
    * **Badges** — Evidence-quality chip + window range.
    """
    ev = d.quality_score
    badge = _evidence_badge(ev) if ev else ""
    gen_short = (d.generated_at or "").replace("T", " ")[:16]
    return (
        '<div class="cal-terminal-mast">'
        '<div class="cal-terminal-brand">'
        f"{_caliper_mark(26)}"
        '<span style="font-size:16px;font-weight:700;letter-spacing:0;color:var(--ink)">CALIPER</span>'
        f'<span style="font-size:11px;color:var(--ghost);letter-spacing:0">v{_esc(d.caliper.version)} · schema {_esc(d.caliper.schema_version)}</span>'
        "</div>"
        '<div class="cal-terminal-stats">'
        '<span style="display:flex;align-items:center;gap:6px">'
        '<span style="width:6px;height:6px;border-radius:50%;background:var(--ok)"></span>'
        '<span style="color:var(--ok)">OFFLINE</span></span>'
        '<span style="color:var(--ghost)">·</span>'
        f"<span>{len(d.window.vendors_active)} of {d.window.vendor_count_total} VENDORS</span>"
        '<span style="color:var(--ghost)">·</span>'
        f"<span>GENERATED {_esc(gen_short)}</span>"
        '<span style="color:var(--ghost)">·</span>'
        f"<span>{_esc(d.window.timezone)}</span>"
        "</div>"
        '<div class="cal-terminal-badges">'
        f"{badge}{_window_badge(d.window)}"
        "</div>"
        "</div>"
    )


def _terminal_ticker(d: Dashboard) -> str:
    t = d.totals
    score = d.quality_score.score if d.quality_score else 0
    items: list[tuple[str, str, str, str | None, str | None]] = [
        (
            "COST",
            fmt_money(t.cost_usd),
            "default",
            _fmt_delta(t.delta_cost_pct),
            "bad" if (t.delta_cost_pct or 0) > 0 else "good",
        ),
        ("CACHE HIT", fmt_pct(t.cache_hit_rate, 1), "good", None, None),
        ("TOKENS", fmt_tokens(t.total_tokens), "default", None, None),
        ("SESSIONS", fmt_int(t.sessions), "default", None, None),
        ("EVENTS", fmt_int(t.events), "default", None, None),
        (
            "ANOMALIES",
            fmt_int(len(d.anomalies)),
            "warn" if d.anomalies else "good",
            None,
            None,
        ),
        (
            "EVIDENCE",
            f"{score}/100",
            "good" if score >= 80 else "warn",
            None,
            None,
        ),
    ]
    chips: list[str] = []
    for label, value, tone, delta, dtone in items:
        c = _tone_color(tone, "var(--ink)")
        dc = _tone_color(dtone)
        delta_html = (
            f'<span style="color:{dc};font-size:11px">{_esc(delta)}</span>' if delta else ""
        )
        chips.append(
            '<span style="display:inline-flex;align-items:baseline;gap:8px;font-size:12px">'
            f'<span style="color:var(--mute);letter-spacing:0">{label}</span>'
            f'<span style="color:{c};font-weight:600">{_esc(value)}</span>'
            f"{delta_html}</span>"
        )
    return (
        '<div style="border-bottom:1px solid var(--border);background:var(--bg-2);'
        "padding:10px 28px;display:flex;gap:28px;font-family:var(--mono);"
        'overflow-x:auto;white-space:nowrap">' + "".join(chips) + "</div>"
    )


def _terminal_index(d: Dashboard) -> str:
    items: list[str] = []
    for sid in _SECTION_ORDER:
        if not _should_render(sid, d):
            continue
        num = _display_num(sid)
        title = _SECTION_TITLES[sid]
        items.append(
            "<li>"
            f'<a href="#{sid}" class="cal-rail-link" style="display:grid;'
            "grid-template-columns:26px 1fr;gap:6px;align-items:baseline;"
            "color:var(--ink-2);text-decoration:none;padding:5px 8px;"
            "border-radius:3px;font-size:12px;font-family:var(--mono);"
            "border-left:2px solid transparent;padding-left:8px;margin-left:-2px;"
            'transition:color 80ms, background-color 80ms">'
            f'<span style="color:var(--ghost);font-size:10px">{num}.</span>'
            f"<span>{_esc(title)}</span></a></li>"
        )
    sha = getattr(d.caliper, "build_sha", "") or ""
    sha_line = f"<div>sha {_esc(sha)}</div>" if sha else ""
    return (
        '<nav class="cal-terminal-index" aria-label="Section navigation" '
        'style="border-right:1px solid var(--border);'
        "padding:24px 8px 24px 20px;position:sticky;top:0;align-self:start;"
        'max-height:100vh;overflow-y:auto">'
        '<div style="font-family:var(--mono);font-size:10px;letter-spacing:0;'
        'color:var(--mute);text-transform:uppercase;margin-bottom:14px">Index</div>'
        '<ul style="list-style:none;padding:0;margin:0;display:grid;gap:2px">'
        + "".join(items)
        + "</ul>"
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);'
        'font-family:var(--mono);font-size:10px;color:var(--ghost);line-height:1.7">'
        f"<div>v{_esc(d.caliper.version)}</div>"
        f"<div>schema {_esc(d.caliper.schema_version)}</div>"
        f"{sha_line}"
        "</div></nav>"
    )


def _render_terminal(d: Dashboard, *, dense: bool, pm: _PrivacyMap) -> str:
    rhythm = "terminal"
    is_empty = d.totals.events == 0
    ticker = "" if is_empty else _terminal_ticker(d)
    banner_html = (
        f'<div style="margin-bottom:18px">{_banner_html(d.banner)}</div>'
        if d.banner is not None
        else ""
    )
    billboard_html = (
        f'<div style="margin-bottom:22px">{_render_billboard(d.billboard, rhythm)}</div>'
        if d.billboard is not None
        else ""
    )
    hero_inner = "" if d.billboard is not None else _hero_verdict_strip(d, rhythm)
    hero_html = f'<div style="margin-bottom:22px">{hero_inner}</div>' if hero_inner else ""
    verdict_html = (
        f'<div style="margin-bottom:22px">{_verdict_strip(d, rhythm)}</div>'
        if d.executive_brief and d.executive_brief.findings
        else ""
    )
    tiered = _sections_by_tier(d)
    decisions_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["decisions"]
    )
    trajectory_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["trajectory"]
    )
    appendix_sections_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["appendix"]
    )
    trust_html = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm) for sid in tiered["trust"]
    )
    appendix_count = len(tiered["appendix"])
    appendix_html = ""
    if appendix_sections_html:
        plural = "" if appendix_count == 1 else "s"
        appendix_html = (
            '<details class="cal-appendix">'
            '<summary class="cal-appendix-summary">'
            '<span class="cal-appendix-chev" aria-hidden="true">▸</span>'
            f'<span class="cal-appendix-label">Technical appendix</span>'
            f'<span class="cal-appendix-count">{appendix_count} section{plural}</span>'
            "</summary>"
            f'<div class="cal-appendix-body">{appendix_sections_html}</div>'
            "</details>"
        )
    sections = decisions_html + trajectory_html + appendix_html + trust_html
    return (
        '<div class="cal-dashboard-root cal-terminal-root">'
        f"{_terminal_masthead(d)}"
        f"{ticker}"
        '<div class="cal-terminal-layout">'
        f"{_terminal_index(d)}"
        '<main id="cal-main" class="cal-terminal-main">'
        f"{banner_html}"
        f"{billboard_html}"
        f"{hero_html}"
        f"{verdict_html}"
        f'<div style="display:grid;gap:28px">{sections}</div>'
        f"{_caliper_footer(d)}"
        "</main></div></div>"
    )


# ============================================================================
# Interactive playground — toggle panel + inline controller
# ============================================================================

# The script is purposely tiny: it only reads/writes body data-attrs and
# triggers a Blob download. No fetch, no XHR, no dynamic imports — the CI
# privacy gate (see ``tests/test_dashboard_html.py``) enforces this.
_INTERACTIVE_SCRIPT = """
(function () {
  var body = document.body;
  var LS_KEY = 'caliper-dashboard:v2';
  function load() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function persist(state) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state)); }
    catch (e) { /* private mode / disabled storage — ignore */ }
  }
  function syncGroup(name, value) {
    var group = document.querySelector('[data-toggle="' + name + '"]');
    if (!group) return;
    var btns = group.querySelectorAll('.cal-tweaks-btn');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('is-active', btns[i].dataset.value === value);
      btns[i].setAttribute('aria-checked', btns[i].dataset.value === value ? 'true' : 'false');
    }
  }
  function setRhythm(r) {
    if (r !== 'receipt' && r !== 'terminal') return;
    body.dataset.rhythm = r;
    syncGroup('rhythm', r);
  }
  var MODE_TABLE = {
    'dark':       { theme: 'dark',  privacy: 'off',    label: 'Dark' },
    'light':      { theme: 'light', privacy: 'off',    label: 'Light' },
    'safe-share': { theme: 'print', privacy: 'always', label: 'Safe Share' }
  };
  function setMode(mode) {
    var entry = MODE_TABLE[mode];
    if (!entry) return;
    body.classList.remove('theme-dark', 'theme-light', 'theme-print');
    body.classList.add('theme-' + entry.theme);
    body.dataset.theme = entry.theme;
    body.dataset.mode = mode;
    body.dataset.privacy = entry.privacy;
    body.dataset.shareSafe = entry.privacy === 'always' ? 'true' : 'false';
    syncGroup('mode', mode);
  }
  function currentState() {
    return { rhythm: body.dataset.rhythm, mode: body.dataset.mode };
  }
  // Restore preferences from localStorage (if any) — falls back to the
  // server-rendered state. This lets a single generated file remember the
  // user's last view across reloads.
  var saved = load();
  setRhythm(saved.rhythm || body.dataset.rhythm || 'receipt');
  setMode(saved.mode || body.dataset.mode || 'dark');
  // Wire up clicks.
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('.cal-tweaks-btn');
    if (!btn) return;
    var group = btn.closest('[data-toggle]');
    if (!group) return;
    var name = group.dataset.toggle;
    var value = btn.dataset.value;
    if (name === 'rhythm') setRhythm(value);
    else if (name === 'mode') setMode(value);
    persist(currentState());
  });
  // Scroll-spy for the receipt TOC. IntersectionObserver tracks every
  // <section[id]> and toggles aria-current="location" on the matching
  // .cal-toc-link. The TOC itself is sticky in CSS; this only updates
  // which link gets the highlighted state. Falls back gracefully when no
  // TOC is present (e.g., terminal rhythm).
  var tocLinks = document.querySelectorAll('.cal-toc-link[data-toc-target]');
  if (tocLinks.length && 'IntersectionObserver' in window) {
    var tocMap = {};
    for (var i = 0; i < tocLinks.length; i++) {
      tocMap[tocLinks[i].dataset.tocTarget] = tocLinks[i];
    }
    var observed = [];
    for (var key in tocMap) {
      var sect = document.getElementById(key);
      if (sect) observed.push(sect);
    }
    var setCurrent = function (id) {
      for (var j = 0; j < tocLinks.length; j++) {
        if (tocLinks[j].dataset.tocTarget === id) {
          tocLinks[j].setAttribute('aria-current', 'location');
        } else {
          tocLinks[j].removeAttribute('aria-current');
        }
      }
    };
    var spy = new IntersectionObserver(function (entries) {
      // Pick the section whose top is closest to the viewport top while
      // still intersecting. This avoids flicker when several sections
      // overlap the viewport during a long scroll.
      var best = null;
      var bestTop = Infinity;
      for (var k = 0; k < entries.length; k++) {
        if (!entries[k].isIntersecting) continue;
        var top = entries[k].boundingClientRect.top;
        if (top >= 0 && top < bestTop) { best = entries[k].target; bestTop = top; }
      }
      if (best) setCurrent(best.id);
    }, { rootMargin: '-72px 0px -60% 0px', threshold: [0, 0.1, 0.5, 1] });
    for (var m = 0; m < observed.length; m++) spy.observe(observed[m]);
  }

  // Anchor-click → open the technical appendix if the target lives inside
  // it. Without this, clicking #models on a fresh load would scroll into
  // the empty space above the collapsed <details>. The browser already
  // auto-opens <details> for :target focus, but only after navigation —
  // we open eagerly so the scroll lands on a rendered section.
  var appendix = document.querySelector('details.cal-appendix');
  function openAppendixIfTargets(hash) {
    if (!appendix || !hash || hash.length < 2) return;
    var target = document.getElementById(hash.slice(1));
    if (target && appendix.contains(target) && !appendix.open) {
      appendix.open = true;
    }
  }
  openAppendixIfTargets(window.location.hash);
  document.addEventListener('click', function (event) {
    var a = event.target.closest('a[href^="#"]');
    if (!a) return;
    openAppendixIfTargets(a.getAttribute('href'));
  }, true);

  // Cmd+K / "/" command palette — fuzzy search over sections, models,
  // projects, anomalies, recommendations. The static markup is always
  // rendered (in interactive mode); this controller handles open/close
  // and selection. Keyboard nav: ↑↓ Enter Esc.
  var palette = document.getElementById('cal-palette');
  var paletteInput = palette && palette.querySelector('.cal-palette-input');
  var paletteList = palette && palette.querySelector('.cal-palette-results');
  var paletteIndexEl = document.getElementById('cal-palette-index');
  var paletteIndex = [];
  if (paletteIndexEl) {
    try { paletteIndex = JSON.parse(paletteIndexEl.textContent || '[]'); }
    catch (e) { paletteIndex = []; }
  }
  var paletteSelected = 0;
  var paletteResults = [];
  var paletteLastFocus = null;

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"]/g, function(c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function paletteRender() {
    if (!paletteList) return;
    var html = '';
    for (var i = 0; i < paletteResults.length; i++) {
      var r = paletteResults[i];
      var active = i === paletteSelected ? ' is-active' : '';
      var selected = i === paletteSelected ? 'true' : 'false';
      var optionId = 'cal-palette-option-' + i;
      html += '<li class="cal-palette-item' + active + '" role="option"' +
              ' id="' + optionId + '" aria-selected="' + selected + '"' +
              ' data-idx="' + i + '" data-anchor="' + escapeHtml(r.anchor) + '">' +
              '<span class="cal-palette-type">' + escapeHtml(r.type) + '</span>' +
              '<span class="cal-palette-label">' + escapeHtml(r.label) + '</span>' +
              '<span class="cal-palette-hint">' + escapeHtml(r.hint) + '</span>' +
              '</li>';
    }
    if (!paletteResults.length) {
      html = '<li class="cal-palette-empty">No matches.</li>';
    }
    paletteList.innerHTML = html;
    if (paletteInput) {
      if (paletteResults.length) {
        paletteInput.setAttribute('aria-activedescendant', 'cal-palette-option-' + paletteSelected);
      } else {
        paletteInput.removeAttribute('aria-activedescendant');
      }
    }
  }
  function paletteUpdate(query) {
    var q = (query || '').toLowerCase().trim();
    paletteResults = paletteIndex.filter(function(it) {
      if (!q) return true;
      return (it.label || '').toLowerCase().indexOf(q) !== -1
          || (it.hint || '').toLowerCase().indexOf(q) !== -1
          || (it.type || '').toLowerCase().indexOf(q) !== -1;
    }).slice(0, 30);
    paletteSelected = 0;
    paletteRender();
  }
  function paletteOpen() {
    if (!palette) return;
    // Remember where focus was so we can return it when the dialog closes
    // (WCAG 2.4.3). Don't capture if the palette is already open.
    if (palette.hidden) paletteLastFocus = document.activeElement;
    palette.hidden = false;
    paletteInput.setAttribute('aria-expanded', 'true');
    paletteInput.value = '';
    paletteUpdate('');
    paletteInput.focus();
  }
  function paletteClose() {
    if (!palette || palette.hidden) return;
    palette.hidden = true;
    if (paletteInput) {
      paletteInput.setAttribute('aria-expanded', 'false');
      paletteInput.removeAttribute('aria-activedescendant');
    }
    // Restore focus so keyboard users aren't dropped at the top of the
    // document. Prefer where focus was; if that was the body (e.g. opened via
    // ⌘K), land on the palette trigger button instead.
    var target = paletteLastFocus;
    if (!target || target === document.body || !target.focus) {
      target = document.getElementById('cal-open-palette');
    }
    if (target && target.focus) {
      try { target.focus(); } catch (err) {}
    }
    paletteLastFocus = null;
  }
  function jumpToAnchor(anchor) {
    if (!anchor) return;
    openAppendixIfTargets('#' + anchor);
    var el = document.getElementById(anchor);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    history.replaceState(null, '', '#' + anchor);
  }
  function paletteCommit() {
    var r = paletteResults[paletteSelected];
    if (!r) return;
    paletteClose();
    jumpToAnchor(r.anchor);
  }
  if (palette) {
    paletteInput.addEventListener('input', function(e) { paletteUpdate(e.target.value); });
    // Visible "Search" button — touch / non-keyboard users get a tappable
    // entry point; keyboard users still have ⌘K and "/".
    var openBtn = document.getElementById('cal-open-palette');
    if (openBtn) {
      openBtn.addEventListener('click', function (e) {
        e.preventDefault();
        paletteOpen();
      });
    }
    paletteInput.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        paletteSelected = Math.min(paletteResults.length - 1, paletteSelected + 1);
        paletteRender();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        paletteSelected = Math.max(0, paletteSelected - 1);
        paletteRender();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        paletteCommit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        paletteClose();
      } else if (e.key === 'Tab') {
        // Trap focus inside the dialog: the input is the only focusable
        // control (results are arrow-key navigated), so keep focus here.
        e.preventDefault();
        paletteInput.focus();
      }
    });
    paletteList.addEventListener('click', function(e) {
      var item = e.target.closest('.cal-palette-item');
      if (!item) return;
      paletteSelected = parseInt(item.dataset.idx, 10) || 0;
      paletteCommit();
    });
    palette.addEventListener('click', function(e) {
      if (e.target && e.target.hasAttribute('data-palette-close')) paletteClose();
    });
  }

  // Global keyboard shortcuts. Cmd/Ctrl+K and "/" open the palette;
  // a g-leader prefix (vim-style) jumps to sections: g a, g i, g m,
  // g s, g o. e/c expand or collapse the technical appendix.
  var gleader = false;
  var gtimer = null;
  function inEditableTarget(t) {
    if (!t || !t.matches) return false;
    return t.matches('input, textarea, [contenteditable], [contenteditable="true"]');
  }
  document.addEventListener('keydown', function(e) {
    // Escape always closes an open palette, wherever focus is (defence in
    // depth alongside the input's own Escape handler).
    if (e.key === 'Escape' && palette && !palette.hidden) {
      e.preventDefault();
      paletteClose();
      return;
    }
    if (inEditableTarget(e.target)) return;
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      paletteOpen();
      return;
    }
    if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && palette) {
      e.preventDefault();
      paletteOpen();
      return;
    }
    if (gleader) {
      var jumpMap = {
        'a': 'anomalies', 'i': 'inefficiencies', 'm': 'models',
        's': 'sessions', 'o': 'overview', 'p': 'projects',
        'c': 'cost', 'f': 'forecast', 'e': 'evidence',
      };
      var target = jumpMap[e.key];
      if (target) {
        e.preventDefault();
        jumpToAnchor(target);
      }
      gleader = false;
      if (gtimer) clearTimeout(gtimer);
      return;
    }
    if (e.key === 'g' && !e.metaKey && !e.ctrlKey && !e.altKey) {
      gleader = true;
      if (gtimer) clearTimeout(gtimer);
      gtimer = setTimeout(function() { gleader = false; }, 900);
      return;
    }
    if (e.key === 'e' && appendix && !appendix.open) {
      e.preventDefault();
      appendix.open = true;
    } else if (e.key === 'c' && appendix && appendix.open) {
      e.preventDefault();
      appendix.open = false;
    }
  });

  // Snapshot download — serialises the current DOM and offers it as a file
  // so the user can keep this exact playground state. Filename embeds the
  // active rhythm + mode for human-readable history.
  var saveBtn = document.getElementById('cal-save-snapshot');
  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      var snapshotRoot = document.documentElement.cloneNode(true);
      var snapshotBody = snapshotRoot.querySelector('body');
      if (snapshotBody && snapshotBody.dataset.privacy === 'always') {
        var replacements = [];
        var realNodes = snapshotRoot.querySelectorAll('.cal-real');
        for (var i = 0; i < realNodes.length; i++) {
          var realNode = realNodes[i];
          var redactedNode = realNode.nextElementSibling;
          if (redactedNode && redactedNode.classList.contains('cal-redacted')) {
            replacements.push([realNode.textContent || '', redactedNode.textContent || '']);
          }
          realNode.remove();
        }
        var redactedNodes = snapshotRoot.querySelectorAll('.cal-redacted');
        for (var j = 0; j < redactedNodes.length; j++) {
          redactedNodes[j].classList.remove('cal-redacted');
        }
        var jsonBlocks = snapshotRoot.querySelectorAll('script[type="application/json"]');
        for (var k = 0; k < jsonBlocks.length; k++) {
          var text = jsonBlocks[k].textContent || '';
          for (var r = 0; r < replacements.length; r++) {
            if (replacements[r][0]) text = text.split(replacements[r][0]).join(replacements[r][1]);
          }
          jsonBlocks[k].textContent = text;
        }
        snapshotBody.dataset.shareSafe = 'true';
        snapshotBody.dataset.privacy = 'always';
        snapshotBody.dataset.mode = 'safe-share';
      }
      var html = '<!doctype html>' + snapshotRoot.outerHTML;
      var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      var now = new Date();
      var pad = function (n) { return (n < 10 ? '0' : '') + n; };
      var ts = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) +
               '-' + pad(now.getHours()) + '-' + pad(now.getMinutes());
      var state = currentState();
      a.href = url;
      a.download = 'caliper-dashboard-' + ts + '-' + state.rhythm + '-' + state.mode + '.html';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        a.remove();
        URL.revokeObjectURL(url);
      }, 0);
    });
  }
})();
""".strip()


def _render_tweaks_panel(*, initial_rhythm: str, initial_mode: str) -> str:
    """Render the interactive toggle panel.

    Initial-active classes mirror the server-rendered state so the panel
    renders without a flash. The inline script then takes over and applies
    any per-user override from ``localStorage``.
    """

    def _btn(value: str, label: str, active: bool) -> str:
        cls = "cal-tweaks-btn is-active" if active else "cal-tweaks-btn"
        aria = "true" if active else "false"
        return (
            f'<button type="button" class="{cls}" data-value="{value}" '
            f'role="radio" aria-checked="{aria}">{label}</button>'
        )

    del initial_rhythm  # Terminal mode is no longer surfaced in the UI; the
    # tweaks panel only exposes Dark / Light / Safe Share now. The underlying
    # render_dashboard(rhythm="terminal") CLI flag stays functional for
    # backwards compatibility but never appears as a visible toggle.
    mode_btns = (
        _btn("dark", "Dark", initial_mode == "dark")
        + _btn("light", "Light", initial_mode == "light")
        + _btn("safe-share", "Safe Share", initial_mode == "safe-share")
    )
    # Visible search affordance — opens the cmd+K palette. Touch / non-
    # keyboard users get a tappable surface; desktop users see the ⌘K hint.
    search_btn = (
        '<button id="cal-open-palette" class="cal-tweaks-search" type="button" '
        'aria-label="Search sections, models, projects, anomalies (Cmd+K)" '
        'title="Search sections, models, projects, anomalies (Cmd+K)">'
        '<span class="cal-tweaks-search-icon" aria-hidden="true">⌕</span>'
        '<span class="cal-tweaks-search-label">Search</span>'
        '<span class="cal-tweaks-search-hint" aria-hidden="true">⌘K</span>'
        "</button>"
    )
    return (
        # Keep <aside> as a complementary landmark (role="toolbar" both removed
        # the landmark and was a disallowed role override). The inner
        # role="radiogroup" already groups the mode/rhythm controls.
        '<aside class="cal-tweaks-panel" aria-label="Dashboard view controls">'
        f"{search_btn}"
        '<div class="cal-tweaks-divider" aria-hidden="true"></div>'
        '<div class="cal-tweaks-section">'
        '<span class="cal-tweaks-label">Mode</span>'
        '<div class="cal-tweaks-group" data-toggle="mode" role="radiogroup" '
        'aria-label="Color and privacy mode">'
        f"{mode_btns}"
        "</div></div>"
        '<div class="cal-tweaks-divider" aria-hidden="true"></div>'
        '<button id="cal-save-snapshot" class="cal-tweaks-save" type="button" '
        'aria-label="Save snapshot of the current view as a new HTML file">'
        '<span class="cal-tweaks-arrow" aria-hidden="true"></span>'
        "Save snapshot</button></aside>"
    )


def _mode_from_state(theme: str, privacy: str) -> str:
    """Pick the toggle mode that matches the initial theme+privacy combo.

    Falls back to ``"dark"`` so the panel always has an active button —
    even when the CLI was invoked with an unusual combination the renderer
    accepts (e.g. ``--theme light --privacy always``), the panel reflects
    the closest match without confusing the user.
    """
    if theme == "print" or privacy == "always":
        return "safe-share"
    if theme == "light":
        return "light"
    return "dark"


# ============================================================================
# Document wrapper + public entrypoint
# ============================================================================


def _wrap_document(
    body: str,
    *,
    theme: str,
    density: str,
    share_safe: bool,
    privacy: str,
    rhythm: str,
    mode: str,
    interactive: bool,
    title: str = "Caliper Dashboard",
    demo: bool = False,
) -> str:
    classes = [f"theme-{theme}"]
    if density == "compact":
        classes.append("density-compact")
    class_attr = " ".join(classes)
    share = "true" if share_safe else "false"
    script = f"<script>{_INTERACTIVE_SCRIPT}</script>" if interactive else ""
    # Skip-to-content link — first focusable element so keyboard users can
    # jump past the masthead/TOC straight into the main content. Visible
    # only when focused (CSS) so it doesn't disrupt sighted users.
    skip_link = '<a class="cal-skip-link" href="#cal-main">Skip to main content</a>'
    # Demo renders carry synthetic numbers; mark the file so a screenshot can
    # never be mistaken for real usage.
    demo_ribbon = (
        '<div class="cal-demo-ribbon" role="note">'
        "DEMO DATA — synthetic sample, not your usage. "
        "Run <code>caliper dashboard</code> on your own logs for real numbers."
        "</div>"
        if demo
        else ""
    )
    interactive_attr = "true" if interactive else "false"
    demo_attr = ' data-demo="true"' if demo else ""
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        f"<style>{INLINE_STYLES}</style>"
        "</head>"
        f'<body class="{class_attr}" data-theme="{theme}" data-density="{density}" '
        f'data-share-safe="{share}" data-privacy="{privacy}" data-rhythm="{rhythm}" '
        f'data-mode="{mode}" data-interactive="{interactive_attr}"'
        f"{demo_attr}>"
        f"{skip_link}"
        f"{demo_ribbon}"
        f"{body}"
        f"{script}"
        "</body></html>"
    )


def render_dashboard(
    d: Dashboard,
    *,
    theme: str = "dark",
    density: str = "comfortable",
    rhythm: str = "receipt",
    privacy: str = "off",
    share_safe: bool = False,
    interactive: bool = False,
    demo: bool = False,
) -> str:
    """Render the dashboard as a single offline HTML string.

    Parameters
    ----------
    d:
        The populated :class:`Dashboard` payload from the adapter.
    theme:
        ``"dark"`` (default), ``"light"``, or ``"print"``. Selects the
        token palette.
    density:
        ``"comfortable"`` (default) or ``"compact"`` — tightens padding and
        shrinks numeric type.
    rhythm:
        ``"receipt"`` (default) or ``"terminal"`` — picks the layout shell.
    privacy:
        ``"off"`` (default): show real project / session / path values.
        ``"print-only"``: show real values in the browser, swap to indexed
        redactions (``Project 1``, ``Session 2``, ``[path]``) on print.
        ``"always"``: indexed redactions everywhere.
    share_safe:
        Legacy alias for ``privacy="always"``. If passed truthy, takes
        precedence over the ``privacy`` argument so existing callers keep
        working.
    interactive:
        When ``True``, embed *both* layout rhythms and a floating tweaks
        panel so the recipient can flip between Receipt / Terminal and
        Dark / Light / Safe Share without re-running the CLI. The Safe
        Share toggle forces ``data-privacy="always"`` on the body, so the
        renderer always emits the redacted span twin too (otherwise the
        toggle would have nothing to swap to). A small inline script
        powers the toggles and the snapshot-download button — it uses no
        network APIs (the privacy gate enforces this).
    """
    if theme not in ("dark", "light", "print"):
        raise ValueError(f"theme must be one of 'dark', 'light', 'print' — got {theme!r}")
    if density not in ("comfortable", "compact"):
        raise ValueError(f"density must be one of 'comfortable', 'compact' — got {density!r}")
    if rhythm not in ("receipt", "terminal"):
        raise ValueError(f"rhythm must be one of 'receipt', 'terminal' — got {rhythm!r}")
    if share_safe:
        privacy = "always"
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"privacy must be one of {PRIVACY_MODES!r} — got {privacy!r}")
    dense = density == "compact"
    # Compute the per-render numbering so headings / TOC / palette show
    # clean sequential numbers (1, 2, 3 …) in tier render order rather than
    # the audit-anchor map's §00..§19 with disabled-section gaps.
    _RENDER_NUM_MAP.set(_compute_display_numbers(d))
    # Interactive mode needs BOTH spans in every sensitive cell so the
    # Safe Share toggle can swap visibility in-browser. We hand the renderer
    # a print-only privacy map regardless of the user's initial choice; the
    # actual visible mode is driven by the body's data-privacy attribute and
    # the CSS rules in INLINE_STYLES.
    #
    # Exception: a caller who explicitly asked for `always` wants a file that
    # is SAFE TO SHARE — the real values must never be embedded, not merely
    # CSS-hidden. So `always` is honoured verbatim even when interactive; the
    # renderer emits redacted text only (no `cal-real` spans), and the theme
    # toggles simply restyle that already-redacted text.
    if privacy == "always":
        render_privacy = "always"
    else:
        render_privacy = "print-only" if interactive else privacy
    pm = _build_privacy_map(d, render_privacy)
    if interactive:
        # Phase 3 polish: the Terminal rhythm is no longer surfaced as a
        # toggle, so the interactive snapshot only embeds whichever rhythm
        # the caller actually requested. Both rhythms still work via the
        # CLI --rhythm flag for backwards compatibility.
        if rhythm == "terminal":
            rendered = _render_terminal(d, dense=dense, pm=pm)
            wrapper_class = "cal-rhythm-terminal"
        else:
            rendered = _render_receipt(d, dense=dense, pm=pm)
            wrapper_class = "cal-rhythm-receipt"
        mode = _mode_from_state(theme, privacy)
        palette_index = _palette_index(d, pm)
        palette_data = (
            '<script type="application/json" id="cal-palette-index">'
            f"{palette_index}</script>"
            f"{_render_palette()}"
        )
        body = (
            f'<div class="{wrapper_class}">{rendered}</div>'
            + _render_tweaks_panel(initial_rhythm=rhythm, initial_mode=mode)
            + palette_data
        )
    else:
        mode = _mode_from_state(theme, privacy)
        body = (
            _render_terminal(d, dense=dense, pm=pm)
            if rhythm == "terminal"
            else _render_receipt(d, dense=dense, pm=pm)
        )
    return _wrap_document(
        body,
        theme=theme,
        density=density,
        share_safe=(privacy == "always"),
        privacy=privacy,
        rhythm=rhythm,
        mode=mode,
        interactive=interactive,
        demo=demo,
    )
