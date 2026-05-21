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
from typing import Any

from .data_models import (
    AdvisorRecommendation,
    Banner,
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
  --bg: #0a0d12;
  --bg-2: #0d1117;
  --panel: #12161e;
  --panel-2: #161b24;
  --panel-hover: #1a2029;
  --border: #1f242e;
  --border-strong: #2a313c;
  --grid: rgba(255,255,255,0.045);
  --bar-ghost: rgba(255,255,255,0.022);
  --hairline: rgba(255,255,255,0.06);

  --ink: #e8eaef;
  --ink-2: #c4c9d3;
  --mute: #858d9b;
  --ghost: #6c7383;

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
  --ghost: #6d7585;

  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --accent-soft: #93b8ff;
  --accent-tint: rgba(37,99,235,0.08);
  --accent-tint-2: rgba(37,99,235,0.16);

  --ok: #16a34a;
  --warn: #b45309;
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
  line-height: 1.45;
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

/* Hover on table rows */
.cal-table tbody tr { transition: background-color 80ms ease-out; }
.cal-table tbody tr:hover { background: var(--panel-hover); }

/* Section spacing */
section[id] { scroll-margin-top: 24px; }

/* Terminal left-rail link hover + :target highlight when an anchor is active */
.cal-rail-link:hover { color: var(--accent) !important; background: var(--accent-tint); }
section[id]:target > [class*="cal-section-head"] {
  box-shadow: inset 3px 0 0 var(--accent);
}

/* Mobile responsive — when wrapping element has data-viewport=mobile */
[data-viewport="mobile"] .cal-summary-row { grid-template-columns: 1fr 1fr !important; }
[data-viewport="mobile"] .cal-shape-grid,
[data-viewport="mobile"] .cal-forecast-grid { grid-template-columns: 1fr !important; }
[data-viewport="mobile"] .cal-table { font-size: 12px !important; }
[data-viewport="mobile"] table th:nth-child(n+5),
[data-viewport="mobile"] table td:nth-child(n+5) { display: none; }
[data-viewport="mobile"] aside { display: none !important; }
[data-viewport="mobile"] header { grid-template-columns: 1fr !important; }
[data-viewport="mobile"] header > div:last-child { text-align: left !important; align-items: flex-start !important; }
[data-viewport="mobile"] .cal-section-head.receipt { flex-wrap: wrap; row-gap: 4px; }
[data-viewport="mobile"] [class*="cal-verdict"] { font-size: 13px; }
[data-viewport="mobile"] main { padding: 16px 14px 48px !important; }
[data-viewport="mobile"] [data-screen-label] { min-width: 0; }
[data-viewport="mobile"] .cal-stat-card { padding: 12px !important; }
[data-viewport="mobile"] .cal-stat-card > div:nth-child(2) { font-size: 22px !important; }

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
  /* Hide stretch sections to make a 1-page receipt-style PDF */
  section#heatmap, section#anomalies, section#sessions, section#advisor,
  section#rate-limits, section#budgets { display: none !important; }
  section { break-inside: avoid; }
  .cal-stat-card, .cal-banner, .cal-table, [data-screen-label] { break-inside: avoid; }
  body { font-size: 12pt !important; line-height: 1.5 !important; }
}

/* Lift focus rings */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }

/* Selection */
::selection { background: var(--accent-tint-2); color: var(--ink); }

/* Variant-aware section header underline for receipt */
.cal-section-head.receipt {
  position: relative;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

/* Pretty wrap */
p, h1, h2, h3 { text-wrap: pretty; }

/* ============================================================================
   Hover polish — only on devices with real pointers, never during print.
   Disabled cleanly by the print theme + @media print blocks above. */
@media (hover: hover) and (pointer: fine) {
  /* Stat cards: subtle lift + brighter border, so hover feels alive. */
  .cal-stat-card {
    transition: transform 140ms ease-out, border-color 140ms ease-out,
                box-shadow 140ms ease-out;
  }
  .cal-stat-card:hover {
    transform: translateY(-2px);
    border-color: var(--border-strong);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
  }
  /* Bar chart rects: brighten the filled bar on hover so the tooltip
     (native SVG <title>) is preceded by a visible affordance. */
  .cal-bar-rect { transition: fill-opacity 120ms ease-out; }
  .cal-bar-rect:hover { fill-opacity: 0.78; }
  /* Verdict-strip pill links: existing <a> gets underline; lift the pill
     background a touch so the whole chip reads as interactive. */
  .cal-verdict-chip { display: inline-block; transition: transform 100ms ease-out; }
  .cal-verdict-chip:hover { transform: translateY(-1px); }
  .cal-verdict-chip:hover > span {
    background: var(--panel-hover) !important;
    border-color: var(--accent-tint-2) !important;
  }
  /* Heatmap cells: highlight the hovered cell so the user can scan
     the matrix without losing their place. */
  .cal-heatmap-cell {
    transition: box-shadow 100ms ease-out, transform 100ms ease-out;
  }
  .cal-heatmap-cell:hover {
    box-shadow: 0 0 0 1.5px var(--accent), 0 0 0 3px var(--accent-tint);
    transform: scale(1.15);
    z-index: 1;
    position: relative;
  }
  /* Tables: keep the existing row hover, add a sharper one-pixel accent
     line at the row's left edge so the user sees where they are. */
  .cal-table tbody tr { position: relative; }
  .cal-table tbody tr:hover::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 2px;
    background: var(--accent);
  }
  /* Pills/badges sitting outside the verdict strip — soft highlight. */
  a:hover > span[class=""], a:hover > span:not([class]) {
    background: var(--panel-hover);
  }
  /* Advisor recommendation rows — soft highlight on hover. */
  .cal-advisor-row { transition: background 120ms ease-out; }
  .cal-advisor-row:hover { background: var(--panel-hover); }
}

/* Disable any hover transforms during actual print so the PDF is static. */
@media print {
  .cal-stat-card:hover { transform: none !important; box-shadow: none !important; }
  .cal-heatmap-cell:hover { transform: none !important; box-shadow: none !important; }
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
.cal-tweaks-panel .cal-tweaks-section { display: flex; align-items: center; gap: 6px; }
.cal-tweaks-panel .cal-tweaks-label {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: .12em;
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
  transition: background 120ms ease-out, transform 80ms ease-out;
}
.cal-tweaks-panel .cal-tweaks-save:hover { background: var(--accent); color: var(--bg); }
.cal-tweaks-panel .cal-tweaks-save:active { transform: scale(0.97); }
.cal-tweaks-panel .cal-tweaks-arrow {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top: 0;
  border-right: 0;
  transform: rotate(-45deg) translate(1px, -1px);
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
"""


# ============================================================================
# Section definitions
# ============================================================================

# Numbered audit anchors. The order is the rendering order; renumbering is a
# breaking change for any external links into a generated dashboard.
SECTION_NUMBERS: dict[str, str] = {
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

_SECTION_TITLES: dict[str, str] = {
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
    "sessions": "Top sessions",
    "evidence": "Evidence",
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


def _should_render(section_id: str, d: Dashboard) -> bool:
    """Hide-when-empty rules. Sections not listed always render."""
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
        return d.forecast is not None
    if section_id == "advisor":
        return bool(d.advisor_recommendations)
    if section_id == "rate-limits":
        return d.rate_limit_pressure is not None
    if section_id == "heatmap":
        return d.recap is not None and bool(d.recap.hours)
    if section_id == "sessions":
        return bool(d.top_sessions)
    if section_id == "evidence":
        return bool(d.evidence)
    # overview / shape / insights always render (placeholder when empty)
    return True


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

    __slots__ = ("mode", "projects", "sessions", "path_label")

    def __init__(self, mode: str, projects: dict[str, str], sessions: dict[str, str]):
        self.mode = mode
        self.projects = projects
        self.sessions = sessions
        self.path_label = "[path]"


def _build_privacy_map(d: Dashboard, mode: str) -> _PrivacyMap:
    project_names = sorted({p.name for p in d.by_project if p.name})
    session_labels = sorted({s.label for s in d.top_sessions if s.label})
    return _PrivacyMap(
        mode=mode,
        projects={name: f"Project {i}" for i, name in enumerate(project_names, start=1)},
        sessions={label: f"Session {i}" for i, label in enumerate(session_labels, start=1)},
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
    data: list[tuple[str, float, str]] = []
    for d in daily:
        day = getattr(d, "day", "")
        label = day[5:] if len(day) > 5 else day
        data.append((label, float(d.cost_usd), (getattr(d, "shape", None) or "mixed")))
    mx = max((v for _, v, _ in data), default=1.0) or 1.0
    nice_max = _nice_ceil(mx)
    pad_l, pad_r, pad_t, pad_b = 44, 16, 18, 28
    inner_w = max(50, width - pad_l - pad_r)
    inner_h = height - pad_t - pad_b
    bar_w = inner_w / len(data)
    gap = max(2.0, min(8.0, bar_w * 0.18))
    y_ticks = 4
    parts = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" '
        f'role="img" aria-label="Daily cost bar chart" style="display:block;height:{height}px">',
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
    peak_value = -1.0
    peak_idx = -1
    for i, (label, value, shape) in enumerate(data):
        x = pad_l + i * bar_w + gap / 2
        bw = bar_w - gap
        bar_h = (value / nice_max) * inner_h
        y = pad_t + inner_h - bar_h
        if value > peak_value:
            peak_value = value
            peak_idx = i
        parts.append(
            f'<rect x="{x:.1f}" y="{pad_t}" width="{bw:.1f}" height="{inner_h:.1f}" '
            f'fill="var(--bar-ghost)" />'
        )
        if bar_h > 0.5:
            parts.append(
                f'<rect class="cal-bar-rect" x="{x:.1f}" y="{y:.1f}" '
                f'width="{bw:.1f}" height="{bar_h:.1f}" '
                f'fill="{accent}" rx="1"><title>{_esc(label)}: '
                f"{_esc(fmt_money(value))} · {_esc(shape)}</title></rect>"
            )
    for idx in {0, len(data) // 2, len(data) - 1}:
        if idx < 0 or idx >= len(data):
            continue
        label = data[idx][0]
        x = pad_l + idx * bar_w + bar_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{height - 10}" font-size="11" text-anchor="middle" '
            f'fill="var(--mute)">{_esc(label)}</text>'
        )
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
    parts = [
        '<div style="display:grid;grid-template-columns:auto 1fr;gap:8px;align-items:start">',
        f'<div style="display:grid;grid-template-rows:repeat(7,{cell_size}px);'
        f'gap:{gap}px;font-size:10px;color:var(--mute);padding-top:14px">',
    ]
    for label in day_labels:
        parts.append(
            f'<span style="line-height:{cell_size}px;text-align:right;padding-right:4px">{label}</span>'
        )
    parts.append("</div>")
    parts.append("<div>")
    parts.append(
        f'<div style="display:grid;grid-template-columns:repeat(24,1fr);column-gap:{gap}px;'
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
        parts.append(f'<div style="display:grid;grid-template-columns:repeat(24,1fr);gap:{gap}px">')
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
) -> str:
    pad = 12 if dense else 16
    delta_color = _tone_color(delta_tone)
    value_color = "var(--ghost)" if value == "—" else "var(--ink)"
    parts = [
        f'<div class="cal-stat-card" style="position:relative;background:var(--panel);'
        f'border:1px solid var(--border);border-radius:var(--r-md);padding:{pad}px;overflow:hidden">'
    ]
    if rail:
        parts.append(
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:2px;background:{rail}"></span>'
        )
    parts.append(
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">'
        f'<span style="font-size:11px;letter-spacing:.10em;color:var(--mute);'
        f'text-transform:uppercase;font-weight:500">{_esc(label)}</span>'
    )
    if delta:
        parts.append(
            f'<span style="font-size:11px;color:{delta_color};font-weight:500">{_esc(delta)}</span>'
        )
    parts.append("</div>")
    parts.append(
        f'<div style="font-size:var(--num-xl);line-height:1.05;font-weight:600;color:{value_color};'
        f'margin-bottom:4px;letter-spacing:-0.01em">{_esc(value)}</div>'
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
            f'<div style="margin-top:8px">'
            f"{_sparkline(sparkline, width=spark_w, height=spark_h, stroke=spark_color)}"
            f"</div>"
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
        f'padding-top:1px;letter-spacing:.10em">{label_text}</span>'
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
        '<span title="Evidence quality — click to jump to §14" '
        'style="display:inline-flex;align-items:baseline;gap:6px;padding:5px 10px;'
        "border-radius:3px;background:var(--panel-2);border:1px solid var(--border);"
        'font-family:var(--mono);font-size:12px;white-space:nowrap">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{color};align-self:center"></span>'
        '<span style="color:var(--mute);text-transform:uppercase;letter-spacing:.10em;font-size:10px">Evidence</span>'
        f'<span style="color:var(--ink);font-weight:600">{score}'
        '<span style="color:var(--mute);font-weight:400">/100</span></span>'
        f'<span style="color:{color};font-size:11px">{_esc(grade)}</span>'
        "</span></a>"
    )


def _window_badge(w: WindowMeta) -> str:
    return (
        '<span style="display:inline-flex;align-items:center;gap:10px;padding:5px 10px;'
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
    num = SECTION_NUMBERS[section_id]
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
            f'<span style="font-family:var(--mono);font-size:11px;color:var(--mute);'
            f'letter-spacing:.04em">§{num}</span>'
            f'<span style="font-family:var(--mono);font-size:12px;letter-spacing:.18em;'
            f"color:var(--accent);text-transform:uppercase;font-weight:600;"
            f'white-space:nowrap">{_esc(title)}</span>'
            "</div>"
            f"{meta_html}</div>"
        )
    meta_html = (
        f'<span style="font-size:12px;color:var(--mute);text-align:right;'
        f'white-space:nowrap;text-overflow:ellipsis;overflow:hidden">{_esc(meta)}</span>'
        if meta
        else ""
    )
    # Receipt header — §NN (no space) matches the design prototype.
    return (
        '<div class="cal-section-head receipt" '
        'style="display:flex;align-items:baseline;justify-content:space-between;'
        'margin-bottom:12px;gap:16px">'
        '<div style="display:flex;align-items:baseline;gap:12px;min-width:0">'
        f'<span style="font-family:var(--mono);font-size:11px;color:var(--ghost)">'
        f"§{num}</span>"
        f'<h2 style="margin:0;font-size:13px;font-weight:600;letter-spacing:.14em;'
        f"color:var(--accent);text-transform:uppercase;"
        f'white-space:nowrap">{_esc(title)}</h2>'
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
            f'<a href="#{_esc(f.anchor)}" class="cal-verdict-chip" style="text-decoration:none">'
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
            f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:.18em;'
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
            f'<a href="#{_esc(f.anchor)}" class="cal-verdict-chip" style="text-decoration:none">'
            f"{_pill(inner, tone=_pill_tone(f))}</a>"
        )
    return (
        '<div class="cal-verdict-strip" style="background:var(--panel);border:1px solid var(--border);'
        "border-radius:var(--r-md);"
        f'border-left:3px solid {tone_accent};padding:14px 18px">'
        '<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:10px;flex-wrap:wrap">'
        f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:.18em;'
        f'color:{tone_accent};text-transform:uppercase;font-weight:600;white-space:nowrap">Verdict</span>'
        f'<span style="font-size:17px;color:var(--ink);font-weight:600;letter-spacing:-0.005em">{_esc(eb.verdict)}</span>'
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
        '<div style="max-width:640px">Caliper is '
        '<span style="color:var(--ok)">offline-first</span>. '
        "This dashboard contains no external resources, scripts, or fetch calls. "
        "All data was parsed from local AI coding logs.</div>"
        '<div style="text-align:right;font-family:var(--mono)">'
        f"<div>caliper v{_esc(d.caliper.version)} · schema {_esc(d.caliper.schema_version)}</div>"
        f"<div>{_esc(d.generated_at)}</div>"
        f"{sha_line}"
        "</div></footer>"
    )


def _section_wrap(section_id: str, *, rhythm: str, body: str, meta: str | None = None) -> str:
    num = SECTION_NUMBERS[section_id]
    title = _SECTION_TITLES[section_id]
    return (
        f'<section id="{section_id}" data-screen-label="{num} {_esc(title)}">'
        f"{_section_head(section_id, rhythm=rhythm, meta=meta)}"
        f"{body}"
        "</section>"
    )


# ============================================================================
# Table helpers (used by render_models / render_projects / _section_sessions)
# ============================================================================


def _th(content: str, *, align: str = "left", aria_sort: str | None = None) -> str:
    sort_attr = f' aria-sort="{aria_sort}"' if aria_sort else ""
    return (
        f"<th{sort_attr} "
        f'style="text-align:{align};padding:10px 14px;font-size:11px;'
        f"font-weight:500;color:var(--mute);text-transform:uppercase;letter-spacing:.08em;"
        f'border-bottom:1px solid var(--border)">{content}</th>'
    )


def _td(
    content: str,
    *,
    align: str = "left",
    mono: bool = False,
    muted: bool = False,
) -> str:
    font = "var(--mono)" if mono else "inherit"
    color = "var(--mute)" if muted else "var(--ink-2)"
    return (
        f'<td style="text-align:{align};padding:10px 14px;vertical-align:middle;'
        f'font-family:{font};color:{color}">{content}</td>'
    )


# ============================================================================
# Section renderers
# ============================================================================


def _section_overview(d: Dashboard, *, dense: bool, rhythm: str) -> str:
    t: Totals = d.totals
    is_empty = (t.cost_usd is None) or (t.events == 0)

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
            ),
        ]
    )
    body = (
        '<div class="cal-summary-row" '
        'style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">' + cards + "</div>"
    )
    return _section_wrap("overview", rhythm=rhythm, body=body)


def _section_cost(d: Dashboard, *, rhythm: str) -> str:
    daily = d.daily
    if not daily:
        return ""
    total = sum(float(p.cost_usd) for p in daily)
    avg = total / len(daily) if daily else 0.0
    legend = _category_legend(
        [
            ("var(--explore)", "exploration"),
            ("var(--execute)", "execution"),
            ("var(--diagnose)", "diagnostic"),
            ("var(--mixed)", "mixed"),
        ]
    )
    summary = f"{len(daily)} active days · {fmt_money(total)} total · avg {fmt_money(avg)}/day"
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
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
        body = _empty_placeholder(
            "No tool-use signal yet in this window. Session shape is currently extracted from Claude Code only."
        )
        return _section_wrap("shape", rhythm=rhythm, body=body, meta=meta)
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
        share_cell = (
            '<div style="display:flex;align-items:center;gap:8px;justify-content:flex-end">'
            f'<span style="color:var(--mute);font-size:12px">{share_pct}%</span>'
            f'<span style="width:64px;display:inline-block">{_meter(r.cost_usd, mx)}</span></div>'
        )
        model_cell = (
            f'<span style="font-family:var(--mono);color:var(--ink)">{_esc(r.model)}</span>'
            f'<span style="color:var(--mute);margin-left:8px">· {_esc(r.tier)}</span>'
        )
        body_rows.append(
            '<tr style="border-top:1px solid var(--border)">'
            + _td(_pill(_esc(r.vendor), mono=True))
            + _td(model_cell)
            + _td(fmt_money(r.cost_usd), align="right", mono=True)
            + _td(share_cell, align="right")
            + _td(fmt_int(r.events), align="right", mono=True)
            + _td(fmt_tokens(r.tokens), align="right", mono=True)
            + _td(fmt_pct(r.cache_hit_rate, 0), align="right", mono=True)
            + _td(_sparkline(r.daily_cost_sparkline, width=80, height=18), align="right")
            + "</tr>"
        )
    return (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">'
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
    meta = f"{len(d.by_model)} models"
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
                '<div style="display:flex;align-items:center;gap:8px;justify-content:flex-end">'
                f'<span style="color:var(--mute);font-size:12px">{share_pct}%</span>'
                f'<span style="width:56px;display:inline-block">{_meter(r.cost_usd, mx)}</span></div>',
                align="right",
            )
            + _td(fmt_int(r.events), align="right", mono=True)
            + _td(fmt_int(r.sessions), align="right", mono=True)
            + _td(fmt_int(r.active_days), align="right", mono=True)
            + _td(f'<span style="color:{tone_color};font-size:12px">{_esc(r.trend_label)}</span>')
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
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">'
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
    meta = f"{len(d.by_project)} projects · sorted by cost"
    return _section_wrap("projects", rhythm=rhythm, body=body, meta=meta)


def _insight_row(it: Insight, *, dense: bool) -> str:
    sev = it.severity
    if sev == "critical":
        accent = "var(--bad)"
        tone = "var(--bad)"
    elif sev == "warn":
        accent = "var(--warn)"
        tone = "var(--warn)"
    else:
        accent = "var(--accent)"
        tone = "var(--mute)"
    pad = "10px 14px" if dense else "12px 16px"
    impact_html = (
        f'<span style="font-size:11px;color:var(--ink-2);background:var(--panel-2);'
        f"border:1px solid var(--border);border-radius:3px;padding:3px 8px;"
        f'white-space:nowrap">{_esc(it.impact)}</span>'
        if it.impact
        else ""
    )
    return (
        f'<div class="cal-insight-row" style="display:grid;grid-template-columns:auto 1fr auto;'
        f"gap:14px;align-items:baseline;padding:{pad};border-left:3px solid {accent};"
        f'background:var(--panel);border-top:1px solid var(--border)">'
        f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:{tone};'
        f'text-transform:uppercase;font-weight:600;min-width:56px">{_esc(sev)}</span>'
        '<div style="min-width:0">'
        f'<div style="color:var(--ink);font-size:13px;font-weight:500">{_esc(it.title)}</div>'
        f'<div style="color:var(--mute);font-size:12px;margin-top:3px;line-height:1.5">{_esc(it.detail)}</div>'
        "</div>"
        f"{impact_html}</div>"
    )


def _section_insights(d: Dashboard, *, dense: bool, rhythm: str) -> str:
    insights = list(d.insights)
    if not insights:
        body = _empty_placeholder("No insights for this window.")
        return _section_wrap("insights", rhythm=rhythm, body=body)
    order = {"critical": 0, "warn": 1, "info": 2}
    insights.sort(key=lambda it: order.get(it.severity, 9))
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">'
        + "".join(_insight_row(it, dense=dense) for it in insights)
        + "</div>"
    )
    return _section_wrap("insights", rhythm=rhythm, body=body)


def _section_anomalies(d: Dashboard, *, dense: bool, rhythm: str) -> str:
    if not d.anomalies:
        return ""
    pad = "10px 14px" if dense else "12px 16px"
    rows_html: list[str] = []
    for i, a in enumerate(d.anomalies):
        tone_color = "var(--bad)" if a.tone == "critical" else "var(--warn)"
        evidence_tone = "good" if a.evidence_status == "exact" else "warn"
        top = "none" if i == 0 else "1px solid var(--border)"
        rows_html.append(
            f'<div style="display:grid;grid-template-columns:auto 1fr auto auto;gap:14px;'
            f"align-items:baseline;padding:{pad};border-left:3px solid {tone_color};"
            f'border-top:{top}">'
            f'<span style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;'
            f'color:{tone_color};text-transform:uppercase;font-weight:600;min-width:56px">'
            f"{a.z_score:.1f}σ</span>"
            '<div style="min-width:0">'
            f'<div style="color:var(--ink);font-size:13px;font-weight:500">'
            f'{_esc(a.kind)} · <span style="font-family:var(--mono);color:var(--ink-2)">{_esc(a.label)}</span></div>'
            f'<div style="color:var(--mute);font-size:12px;margin-top:3px">'
            f"observed {fmt_money(a.observed_usd)} vs baseline {fmt_money(a.baseline_usd)} · "
            f"scale ${a.baseline_scale_usd:.1f} · {_esc(a.timestamp)}</div>"
            "</div>"
            f"{_pill(_esc(a.evidence_status), tone=evidence_tone)}"
            f'<span style="font-size:12px;color:{tone_color};font-family:var(--mono);'
            f'font-weight:500;white-space:nowrap">+{_esc(fmt_money(a.impact_usd))}</span>'
            "</div>"
        )
    body = (
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">' + "".join(rows_html) + "</div>"
    )
    meta = f"{len(d.anomalies)} outliers · z ≥ 4σ"
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
        f'<div style="font-size:11px;letter-spacing:.10em;color:var(--mute);'
        f'text-transform:uppercase;margin-bottom:6px">{_esc(label)}</div>'
        f'<div style="font-size:var(--num-lg);font-weight:600;color:var(--ink);margin-bottom:4px">{_esc(value)}</div>'
        f'<div style="font-size:12px;color:var(--mute)">{_esc(sub)}</div>'
        f"{band_html}</div>"
    )


def _section_forecast(d: Dashboard, *, rhythm: str) -> str:
    f: Forecast | None = d.forecast
    if f is None:
        return ""
    intro = (
        f'<div style="font-size:12px;color:var(--mute);margin-bottom:10px">'
        f"Based on {f.days_analyzed} days · projected through next {f.days_remaining} days.</div>"
    )
    band1 = f"1σ band: {fmt_money(f.linear_low)} – {fmt_money(f.linear_high)}"
    band2 = f"Δ vs linear: {fmt_money(f.ewma_total - f.linear_total)}"
    cards = _forecast_card(
        "Linear projection",
        fmt_money(f.linear_total),
        f"daily mean ${f.daily_mean:.0f} ± ${f.daily_stdev:.0f}",
        band1,
    ) + _forecast_card(
        "EWMA (recency-weighted)",
        fmt_money(f.ewma_total),
        "Weights recent days higher",
        band2,
    )
    body = (
        intro
        + '<div class="cal-forecast-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
        + cards
        + "</div>"
    )
    return _section_wrap("forecast", rhythm=rhythm, body=body)


def _section_advisor(d: Dashboard, *, rhythm: str) -> str:
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
            f'<div style="font-size:13px;color:var(--ink);font-weight:500">{_esc(r.title)}</div>'
            f'<div style="font-size:12px;color:var(--mute);margin-top:3px">{_esc(r.detail)}</div>'
            f'<code style="display:inline-block;margin-top:6px;font-family:var(--mono);'
            f'font-size:11px;color:var(--accent);background:transparent;padding:0">$ {_esc(r.action)}</code>'
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
        cost_cell = (
            '<div style="display:flex;gap:8px;justify-content:flex-end;align-items:center">'
            f'<span style="width:44px">{_meter(s.cost_usd, mx)}</span>'
            f"<span>{fmt_money(s.cost_usd)}</span></div>"
        )
        body_rows.append(
            '<tr style="border-top:1px solid var(--border)">'
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
        '<div style="background:var(--panel);border:1px solid var(--border);'
        'border-radius:var(--r-md);overflow:hidden">'
        '<table class="cal-table" style="width:100%;border-collapse:collapse;font-size:13px">'
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
    "overview",
    "cost",
    "shape",
    "models",
    "projects",
    "insights",
    "anomalies",
    "budgets",
    "forecast",
    "advisor",
    "rate-limits",
    "heatmap",
    "sessions",
    "evidence",
]


def _render_section(
    section_id: str, d: Dashboard, *, dense: bool, rhythm: str, pm: _PrivacyMap
) -> str:
    if section_id == "overview":
        return _section_overview(d, dense=dense, rhythm=rhythm)
    if section_id == "cost":
        return _section_cost(d, rhythm=rhythm)
    if section_id == "shape":
        return _section_shape(d, rhythm=rhythm)
    if section_id == "models":
        return _section_models(d, rhythm=rhythm)
    if section_id == "projects":
        return _section_projects(d, rhythm=rhythm, pm=pm)
    if section_id == "insights":
        return _section_insights(d, dense=dense, rhythm=rhythm)
    if section_id == "anomalies":
        return _section_anomalies(d, dense=dense, rhythm=rhythm)
    if section_id == "budgets":
        return _section_budgets(d, rhythm=rhythm)
    if section_id == "forecast":
        return _section_forecast(d, rhythm=rhythm)
    if section_id == "advisor":
        return _section_advisor(d, rhythm=rhythm)
    if section_id == "rate-limits":
        return _section_rate_limits(d, rhythm=rhythm)
    if section_id == "heatmap":
        return _section_heatmap(d, rhythm=rhythm)
    if section_id == "sessions":
        return _section_sessions(d, rhythm=rhythm, pm=pm)
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
    evidence_badge = _evidence_badge(ev) if ev and ev.score > 0 else ""
    gen_line = (d.generated_at or "").replace("T", " ")[:16]
    vendor_line = f"{len(d.window.vendors_active)} of {d.window.vendor_count_total} vendors"
    masthead = (
        '<header style="display:grid;grid-template-columns:1fr auto;gap:16px;'
        'align-items:start;padding-bottom:18px;border-bottom:1px solid var(--border)">'
        "<div>"
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">'
        f"{_caliper_mark(26)}"
        '<h1 style="margin:0;font-size:22px;font-weight:600;letter-spacing:-0.015em;color:var(--ink)">'
        f'Caliper <span style="color:var(--mute);font-size:12px;font-family:var(--mono);font-weight:400;margin-left:6px">v{_esc(d.caliper.version)}</span>'
        "</h1></div>"
        '<div style="color:var(--mute);font-size:12px">'
        "Cost layer for AI-assisted development · offline, auditable, no login</div></div>"
        '<div style="text-align:right;display:flex;flex-direction:column;gap:6px;align-items:flex-end">'
        f'<div style="display:flex;gap:8px;align-items:center">{evidence_badge}{_window_badge(d.window)}</div>'
        '<div style="font-size:11px;color:var(--mute);font-family:var(--mono);display:flex;gap:14px;align-items:center">'
        f"{_status_dot('good', 'offline')}<span>Generated {_esc(gen_line)}</span><span>{_esc(vendor_line)}</span></div>"
        f'<div style="font-size:11px;color:var(--ghost);font-family:var(--mono)">{_build_id(d)}</div>'
        "</div></header>"
    )
    banner_html = (
        f'<div style="margin-top:18px">{_banner_html(d.banner)}</div>'
        if d.banner is not None
        else ""
    )
    verdict_html = (
        f'<div style="margin-top:18px">{_verdict_strip(d, rhythm)}</div>'
        if d.executive_brief and d.executive_brief.findings
        else ""
    )
    sections = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm)
        for sid in _SECTION_ORDER
        if _should_render(sid, d)
    )
    return (
        '<div style="max-width:1180px;margin:0 auto;padding:32px 28px 64px;'
        'font-family:var(--font);color:var(--ink)">'
        f"{masthead}"
        f"{banner_html}"
        f"{verdict_html}"
        f'<div style="margin-top:24px;display:grid;gap:28px">{sections}</div>'
        f"{_caliper_footer(d)}"
        "</div>"
    )


def _terminal_masthead(d: Dashboard) -> str:
    ev = d.quality_score
    badge = _evidence_badge(ev) if ev and ev.score > 0 else ""
    gen_short = (d.generated_at or "").replace("T", " ")[:16]
    return (
        '<div style="border-bottom:1px solid var(--border-strong);background:var(--panel);'
        "padding:12px 28px;display:grid;grid-template-columns:auto 1fr auto;gap:24px;"
        'align-items:center;font-family:var(--mono)">'
        '<div style="display:flex;align-items:center;gap:12px">'
        f"{_caliper_mark(20)}"
        '<span style="font-size:16px;font-weight:700;letter-spacing:.05em;color:var(--ink)">CALIPER</span>'
        f'<span style="font-size:11px;color:var(--ghost);letter-spacing:.10em">v{_esc(d.caliper.version)} · schema {_esc(d.caliper.schema_version)}</span>'
        "</div>"
        '<div style="display:flex;align-items:center;gap:18px;font-size:11px;'
        'color:var(--mute);justify-content:center">'
        '<span style="display:flex;align-items:center;gap:6px">'
        '<span style="width:6px;height:6px;border-radius:50%;background:var(--ok)"></span>'
        '<span style="color:var(--ok)">OFFLINE</span></span>'
        '<span style="color:var(--ghost)">·</span>'
        f"<span>{len(d.window.vendors_active)} of {d.window.vendor_count_total} VENDORS</span>"
        '<span style="color:var(--ghost)">·</span>'
        f"<span>GENERATED {_esc(gen_short)}</span>"
        '<span style="color:var(--ghost)">·</span>'
        f"<span>{_esc(d.window.timezone)}</span></div>"
        f'<div style="text-align:right;display:flex;gap:8px;align-items:center">{badge}{_window_badge(d.window)}</div>'
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
            f'<span style="color:var(--mute);letter-spacing:.10em">{label}</span>'
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
        num = SECTION_NUMBERS[sid]
        title = _SECTION_TITLES[sid]
        items.append(
            "<li>"
            f'<a href="#{sid}" class="cal-rail-link" style="display:grid;'
            "grid-template-columns:26px 1fr;gap:6px;align-items:baseline;"
            "color:var(--ink-2);text-decoration:none;padding:5px 8px;"
            "border-radius:3px;font-size:12px;font-family:var(--mono);"
            "border-left:2px solid transparent;padding-left:8px;margin-left:-2px;"
            'transition:color 80ms, background-color 80ms">'
            f'<span style="color:var(--ghost);font-size:10px">§{num}</span>'
            f"<span>{_esc(title)}</span></a></li>"
        )
    sha = getattr(d.caliper, "build_sha", "") or ""
    sha_line = f"<div>sha {_esc(sha)}</div>" if sha else ""
    return (
        '<aside style="border-right:1px solid var(--border);'
        "padding:24px 8px 24px 20px;position:sticky;top:0;align-self:start;"
        'max-height:100vh;overflow-y:auto">'
        '<div style="font-family:var(--mono);font-size:10px;letter-spacing:.18em;'
        'color:var(--mute);text-transform:uppercase;margin-bottom:14px">Index</div>'
        '<ul style="list-style:none;padding:0;margin:0;display:grid;gap:2px">'
        + "".join(items)
        + "</ul>"
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);'
        'font-family:var(--mono);font-size:10px;color:var(--ghost);line-height:1.7">'
        f"<div>v{_esc(d.caliper.version)}</div>"
        f"<div>schema {_esc(d.caliper.schema_version)}</div>"
        f"{sha_line}"
        "</div></aside>"
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
    verdict_html = (
        f'<div style="margin-bottom:22px">{_verdict_strip(d, rhythm)}</div>'
        if d.executive_brief and d.executive_brief.findings
        else ""
    )
    sections = "".join(
        _render_section(sid, d, dense=dense, rhythm=rhythm, pm=pm)
        for sid in _SECTION_ORDER
        if _should_render(sid, d)
    )
    return (
        '<div style="background:var(--bg);color:var(--ink);font-family:var(--font)">'
        f"{_terminal_masthead(d)}"
        f"{ticker}"
        '<div style="display:grid;grid-template-columns:190px 1fr;gap:0;max-width:1320px;margin:0 auto">'
        f"{_terminal_index(d)}"
        '<main style="padding:24px 28px 64px;min-width:0">'
        f"{banner_html}"
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
  // Snapshot download — serialises the current DOM and offers it as a file
  // so the user can keep this exact playground state. Filename embeds the
  // active rhythm + mode for human-readable history.
  var saveBtn = document.getElementById('cal-save-snapshot');
  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      var html = '<!doctype html>' + document.documentElement.outerHTML;
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

    rhythm_btns = _btn("receipt", "Receipt", initial_rhythm == "receipt") + _btn(
        "terminal", "Terminal", initial_rhythm == "terminal"
    )
    mode_btns = (
        _btn("dark", "Dark", initial_mode == "dark")
        + _btn("light", "Light", initial_mode == "light")
        + _btn("safe-share", "Safe Share", initial_mode == "safe-share")
    )
    return (
        '<aside class="cal-tweaks-panel" role="toolbar" '
        'aria-label="Dashboard view controls">'
        '<div class="cal-tweaks-section">'
        '<span class="cal-tweaks-label">View</span>'
        '<div class="cal-tweaks-group" data-toggle="rhythm" role="radiogroup" '
        'aria-label="Layout rhythm">'
        f"{rhythm_btns}"
        "</div></div>"
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
) -> str:
    classes = [f"theme-{theme}"]
    if density == "compact":
        classes.append("density-compact")
    class_attr = " ".join(classes)
    share = "true" if share_safe else "false"
    script = f"<script>{_INTERACTIVE_SCRIPT}</script>" if interactive else ""
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
        f'data-mode="{mode}" data-interactive="{"true" if interactive else "false"}">'
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
    # Interactive mode needs BOTH spans in every sensitive cell so the
    # Safe Share toggle can swap visibility in-browser. We hand the renderer
    # a print-only privacy map regardless of the user's initial choice; the
    # actual visible mode is driven by the body's data-privacy attribute and
    # the CSS rules in INLINE_STYLES.
    render_privacy = "print-only" if interactive else privacy
    pm = _build_privacy_map(d, render_privacy)
    if interactive:
        # Embed both rhythms; CSS hides the inactive one. The wrapper class
        # is what the rhythm-swap rules ([data-rhythm="X"] .cal-rhythm-Y)
        # key off of.
        receipt_body = _render_receipt(d, dense=dense, pm=pm)
        terminal_body = _render_terminal(d, dense=dense, pm=pm)
        mode = _mode_from_state(theme, privacy)
        body = (
            f'<div class="cal-rhythm-receipt">{receipt_body}</div>'
            f'<div class="cal-rhythm-terminal">{terminal_body}</div>'
            + _render_tweaks_panel(initial_rhythm=rhythm, initial_mode=mode)
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
    )
