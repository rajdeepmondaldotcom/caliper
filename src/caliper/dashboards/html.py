"""
Caliper dashboard — HTML renderer.

Generates the entire dashboard as one self-contained HTML string. No template
engine; pure string concatenation + f-strings. The shape contract lives in
`data_models.py`; the data adapter that maps `LoadResult` to it lives in
`adapter.py`. Source-of-truth CSS lives in `styles.css` and is mirrored into
`INLINE_STYLES` below (kept byte-identical by `tests/test_handoff_styles.py`).

Public entrypoint:

    render_dashboard(dashboard: Dashboard) -> str

Render plan (top to bottom):
    1. <head> with inline <style>          ← see styles.css
    2. Page header (wordmark, window badge, meta, serial)
    3. Optional banner (vendor coverage or stale pricing)
    4. Summary cards row (Cost / Cache / Tokens / Sessions)
    5. § 01 Usage windows           (7 / 30 / 90 day rollups)
    6. § 02 Impact                  (risk and leverage cards)
    7. § 03 Cost over time          (chart + dominant-shape strip)
    8. § 04 Activity                (yearly heatmap)
    9. § 05 Recap                   (hour-of-week heatmap + stats)
   10. § 06 Session shape           (top tools + category distribution)
   11. § 07 Models & tiers          (table)
   12. § 08 Projects                (table with mini-bars)
   13. § 09 Insights                (severity rails)
   14. § 10 Forecast                (linear + EWMA cards with band)
   15. § 11 Evidence                (status table)
   16. Page footer

Every section degrades to a per-section empty placeholder. The 14-day "rich"
state and the "empty window" state share this same renderer; the data is
what differs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
from datetime import datetime

from caliper.dashboards.data_models import (
    AdvisorRecommendation,
    Banner,
    CommandCenterCard,
    DailyPoint,
    Dashboard,
    EvidenceRow,
    Forecast,
    ImpactCard,
    Insight,
    MixRow,
    ModelRow,
    ProjectRow,
    QualityScore,
    RateLimitPressure,
    Recap,
    SessionRow,
    SessionShape,
    Totals,
    UsageWindow,
    YearlyHeatmap,
)

# ===========================================================================
# Constants — keep in sync with `styles.css` design tokens
# ===========================================================================

# Tool category → CSS custom property (mirrors :root in styles.css)
CAT_COLOR = {
    "explore": "var(--explore)",
    "execute": "var(--execute)",
    "diagnose": "var(--diagnose)",
    "mixed": "var(--mixed)",
}

# Section shape name → tool category (so daily.shape maps to a color)
SHAPE_TO_CAT = {
    "exploration": "explore",
    "execution": "execute",
    "diagnostic": "diagnose",
    "mixed": "mixed",
    "no-tools": "mixed",
}

# Sections labelled "§ 01" through "§ 16". Order is binding.
SECTION_NUMBERS = {
    "command-center": "01",
    "usage-windows": "02",
    "impact": "03",
    "cost-over-time": "04",
    "activity-heatmap": "05",
    "recap": "06",
    "session-shape": "07",
    "usage-mix": "08",
    "advisor": "09",
    "top-sessions": "10",
    "models": "11",
    "projects": "12",
    "rate-limits": "13",
    "insights": "14",
    "forecast": "15",
    "evidence": "16",
}


# ===========================================================================
# Formatters — keep in sync with `fmt` object in `components.jsx`
# ===========================================================================


def fmt_money(n: float | None) -> str:
    """`$42.18` under $1,000; `$1,243` at/above."""
    if n is None:
        return "—"
    if n == 0:
        return "$0"
    if abs(n) >= 1000:
        return f"${round(n):,}"
    return f"${n:.2f}"


def fmt_tokens(n: int | None) -> str:
    """`8,400` / `12.4K` / `1.2M` / `1.2B`."""
    if n is None:
        return "—"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def fmt_pct(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{p * 100:.1f}%"


def fmt_pct_round(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{round(p * 100)}%"


def fmt_int(n: int | None) -> str:
    return f"{(n or 0):,}"


def esc(s: str) -> str:
    """Always-escape user-derived strings."""
    return html.escape(str(s), quote=True)


# ===========================================================================
# Atomic primitives
# ===========================================================================


def sparkline(values: list[float], color: str, aria: str, width: int = 84, height: int = 22) -> str:
    """Inline SVG sparkline. Same geometry as `<Sparkline>` in components.jsx."""
    if not values:
        return '<span class="spark-empty" aria-hidden="true">—</span>'

    vmax = max(values + [0.0001])
    vmin = min(values + [0.0])
    vrange = (vmax - vmin) or 1
    n = len(values)
    step_x = width / max(n - 1, 1)
    pts = [
        (i * step_x, height - 2 - ((v - vmin) / vrange) * (height - 4))
        for i, v in enumerate(values)
    ]
    line = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    area = f"{line} L{width:.1f} {height} L0 {height} Z"
    lx, ly = pts[-1]

    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="{esc(aria)}" '
        f'preserveAspectRatio="none">'
        f'<path d="{area}" fill="{color}" opacity="0.12"/>'
        f'<path d="{line}" fill="none" stroke="{color}" stroke-width="1.25" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="1.6" fill="{color}"/>'
        f"</svg>"
    )


def delta_chip(value: float | None, polarity: str = "more-is-bad") -> str:
    """
    polarity:
      "more-is-bad"  — used for cost (up = bad/red)
      "more-is-good" — used for cache hit rate (up = good/green)
      "neutral"      — never colored
    """
    if value is None:
        return ""
    tip = "vs. previous equal window"
    if value == 0:
        return (
            f'<span class="delta delta-flat" data-tip="flat &mdash; {esc(tip)}">·&nbsp;0.0%</span>'
        )
    up = value > 0
    if polarity == "neutral" or polarity == "more-is-good":
        good = up
    else:  # more-is-bad
        good = not up
    cls = "delta-ok" if good else "delta-bad"
    arrow = "↑" if up else "↓"
    sign = "+" if value > 0 else ""
    direction = "up" if up else "down"
    return (
        f'<span class="delta {cls}" '
        f'data-tip="{direction} {sign}{value * 100:.1f}% {esc(tip)}">'
        f"{arrow}&nbsp;{sign}{value * 100:.1f}%</span>"
    )


_SEVERITY_TIPS = {
    "info": "info — worth knowing",
    "warn": "warn — review when convenient",
    "critical": "critical — needs attention",
}
_STATUS_TIPS = {
    "exact": "exact — sourced from the underlying log",
    "estimated": "estimated — inferred when the log is silent",
    "partial": "partial — some events lack this detail",
    "unsupported": "unsupported — this vendor does not record it",
}


def severity_pill(severity: str) -> str:
    label = "CRIT" if severity == "critical" else severity.upper()
    tip = _SEVERITY_TIPS.get(severity, severity)
    return f'<span class="sev sev-{esc(severity)}" data-tip="{esc(tip)}">{label}</span>'


def status_word(status: str) -> str:
    tip = _STATUS_TIPS.get(status, status)
    return f'<span class="status status-{esc(status)}" data-tip="{esc(tip)}">{esc(status)}</span>'


def vendor_badge(vendor: str) -> str:
    return f'<span class="vendor-badge" data-tip="vendor: {esc(vendor)}">{esc(vendor)}</span>'


def category_legend() -> str:
    parts = []
    for cat, label in [
        ("explore", "explore"),
        ("execute", "execute"),
        ("diagnose", "diagnose"),
        ("mixed", "mixed"),
    ]:
        parts.append(
            f'<span class="legend-chip">'
            f'<span class="dot" style="background:{CAT_COLOR[cat]}"></span>'
            f"{label}</span>"
        )
    return f'<div class="legend" aria-label="Tool categories">{"".join(parts)}</div>'


def meter_row(name: str, count: int, max_count: int, category: str) -> str:
    pct = (count / max_count * 100) if max_count > 0 else 0
    color = CAT_COLOR.get(category, "var(--accent)")
    tip = f"{name} · {count:,} calls · {category}"
    return (
        f'<div class="meter-row" data-tip="{esc(tip)}">'
        f'<div class="meter-name">'
        f'<span class="dot" style="background:{color}"></span>{esc(name)}'
        f"</div>"
        f'<div class="meter-track">'
        f'<span style="width:{pct:.4f}%;background:{color}"></span>'
        f"</div>"
        f'<div class="meter-count">{count}</div>'
        f"</div>"
    )


def mini_bar(name: str, count: int, max_count: int, category: str) -> str:
    """Mini meter used in Projects table → top tools column."""
    pct = max(8, (count / max_count * 100)) if max_count > 0 else 0
    color = CAT_COLOR.get(category, "var(--accent)")
    tip = f"{name} · {count:,} ({category})"
    return (
        f'<span class="mini-bar" data-tip="{esc(tip)}">'
        f'<span class="mini-bar-name">{esc(name)}</span>'
        f'<span class="mini-bar-track">'
        f'<span style="width:{pct:.4f}%;background:{color}"></span>'
        f"</span></span>"
    )


def inline_share_bar(share: float) -> str:
    """The right-aligned share% cell in tables."""
    pct = share * 100
    return (
        f'<span class="inline-bar" data-tip="{pct:.1f}% of total">'
        f'<span class="inline-bar-track">'
        f'<span style="width:{pct:.4f}%"></span>'
        f"</span>"
        f'<span class="inline-bar-label">{round(pct)}%</span>'
        f"</span>"
    )


# ===========================================================================
# Sections
# ===========================================================================


def section_head(section_id: str, title: str, hint: str = "") -> str:
    """Standard <header> block with § number + title + optional right-side hint."""
    num = SECTION_NUMBERS.get(section_id, "")
    num_html = f'<span class="sec-num">§&nbsp;{num}</span>' if num else ""
    hint_html = f'<span class="sec-hint">{esc(hint)}</span>' if hint else ""
    return (
        f'<header class="sec-head">'
        f'<div class="sec-head-left">'
        f"{num_html}"
        f'<h2 class="sec-title">{esc(title)}</h2>'
        f"</div>"
        f"{hint_html}"
        f"</header>"
    )


# CSS-only tooltip can't measure its rendered width, so it can't avoid
# clipping near the page edges on its own. We pick a horizontal anchor at
# render time based on the trigger's position within its row/strip:
#
#   pos < 0.15  → anchor LEFT  (tooltip extends to the right of the trigger)
#   pos > 0.85  → anchor RIGHT (tooltip extends to the left of the trigger)
#   otherwise   → anchor CENTER (default in CSS, no attribute emitted)
#
# Returns an attribute fragment ready to splice into a tag: either an
# empty string or ` data-tip-anchor="left"`/`"right"`.
def _tip_anchor(pos: float) -> str:
    if pos < 0.15:
        return ' data-tip-anchor="left"'
    if pos > 0.85:
        return ' data-tip-anchor="right"'
    return ""


# 1. Page header --------------------------------------------------------------


def render_header(d: Dashboard) -> str:
    """Wordmark, window badge, meta line, receipt-style serial."""
    w = d.window
    t = datetime.fromisoformat(d.generated_at)
    # Prefer the window's IANA timezone over Python's tzname() — on 3.11+
    # fromisoformat returns "UTC-07:00" style names, which read worse than
    # "America/Los_Angeles" in a receipt header.
    date = t.strftime("%Y-%m-%d")
    time = t.strftime("%H:%M")
    tz = w.timezone or t.tzname() or "UTC"
    stamp = f"{date} {time} {tz}"
    serial = f"caliper-{date.replace('-', '')}-{time.replace(':', '')}"

    return (
        f'<header class="page-head">'
        f'<div class="page-head-left">'
        f'<div class="wordmark">{wordmark_svg()}'
        f'<span class="wordmark-text">Caliper</span>'
        f'<span class="wordmark-version">v{esc(d.caliper.version)}</span>'
        f"</div>"
        f'<div class="page-head-tagline">'
        f"cost layer for AI-assisted development · offline, auditable, no login"
        f"</div>"
        f"</div>"
        f'<div class="page-head-right">'
        f'<span class="window-badge">'
        f'<span class="window-badge-label">{esc(w.label)}</span>'
        f'<span class="window-badge-sep">·</span>'
        f'<span class="window-badge-range">{esc(w.range)}</span>'
        f"</span>"
        f'<div class="page-meta">'
        f"<span>Generated {esc(stamp)}</span>"
        f'<span class="dot-sep">·</span>'
        f'<span class="meta-offline" title="No external resources, no fetches.">'
        f'<span class="meta-dot"></span>offline'
        f"</span>"
        f'<span class="dot-sep">·</span>'
        f"<span>{len(w.vendors_active)} of {w.vendor_count_total} vendors</span>"
        f'<span class="dot-sep">·</span>'
        f"<span>Installed v{esc(d.caliper.version)}</span>"
        f"</div>"
        f'<div class="serial">{esc(serial)}</div>'
        f"</div>"
        f"</header>"
    )


def wordmark_svg() -> str:
    """The Caliper jaw mark. 24px square, inherits color."""
    return (
        '<svg viewBox="0 0 28 28" width="24" height="24" aria-hidden="true">'
        '<rect x="3" y="6" width="22" height="2" fill="currentColor" opacity="0.85"/>'
        '<rect x="3" y="20" width="22" height="2" fill="currentColor" opacity="0.85"/>'
        '<rect x="3" y="6" width="2" height="8" fill="currentColor" opacity="0.85"/>'
        '<rect x="23" y="14" width="2" height="8" fill="currentColor" opacity="0.85"/>'
        '<g fill="currentColor" opacity="0.55">'
        '<rect x="7"  y="13" width="1" height="3"/>'
        '<rect x="11" y="13" width="1" height="3"/>'
        '<rect x="15" y="13" width="1" height="3"/>'
        '<rect x="19" y="13" width="1" height="3"/>'
        "</g>"
        "</svg>"
    )


# 2. Banner -------------------------------------------------------------------


def render_banner(b: Banner | None) -> str:
    if b is None:
        return ""
    return (
        f'<div class="banner banner-{esc(b.kind)}" role="status">'
        f'<span class="banner-bar"></span>'
        f'<span class="banner-label">{esc(b.label)}</span>'
        # `text` may contain inline <code>; do NOT escape here. Caller is
        # responsible for ensuring banner content is safe.
        f'<span class="banner-text">{b.text}</span>'
        f"</div>"
    )


# 3. Summary cards ------------------------------------------------------------


def render_cards(t: Totals, empty: bool) -> str:
    if empty:
        cards = []
        for label in ("Cost", "Cache savings", "Tokens", "Sessions"):
            cards.append(
                f'<div class="card stat" role="group" aria-label="{esc(label)}">'
                f'<div class="stat-label">{label}</div>'
                f'<div class="stat-value stat-empty">—</div>'
                f'<div class="stat-sub">no data for this window</div>'
                f"</div>"
            )
        return f'<div class="cards">{"".join(cards)}</div>'

    def card(accent, label, value, sub, tip, delta, polarity, spark, spark_color, spark_label):
        return (
            f'<div class="card stat" data-accent="{accent}" '
            f'data-tip="{esc(tip)}" data-tip-pos="bottom" '
            f'role="group" aria-label="{esc(label)}">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{esc(value)}</div>'
            f'<div class="stat-sub">{esc(sub)}</div>'
            f'<div class="stat-foot">'
            f"{delta_chip(delta, polarity)}"
            f"{sparkline(spark, spark_color, spark_label)}"
            f"</div>"
            f"</div>"
        )

    cost_tip = f"Total spend across all vendors in this window. Events: {fmt_int(t.events)}."
    cache_tip = (
        f"Estimated savings from cached input tokens. Hit rate: {fmt_pct(t.cache_hit_rate)}."
    )
    tokens_tip = (
        f"Input + output tokens consumed. Cached input: "
        f"{fmt_tokens(t.cached_input_tokens)} · uncached: "
        f"{fmt_tokens(t.uncached_input_tokens)} · output: "
        f"{fmt_tokens(t.output_tokens)}."
    )
    sessions_tip = (
        f"Distinct sessions in window. Turns: {t.turns} · tools/turn: {t.tools_per_turn:.2f}."
    )

    return (
        '<div class="cards">'
        + card(
            "cost",
            "Cost",
            fmt_money(t.cost_usd),
            f"{fmt_int(t.events)} events",
            cost_tip,
            t.delta_cost_pct,
            "more-is-bad",
            t.daily_cost_sparkline,
            "var(--accent)",
            "14-day daily cost",
        )
        + card(
            "cache",
            "Cache savings",
            fmt_money(t.cache_savings_usd),
            f"{fmt_pct(t.cache_hit_rate)} hit rate",
            cache_tip,
            t.delta_cache_pct,
            "more-is-good",
            t.daily_cache_sparkline,
            "var(--ok)",
            "14-day cache hit rate",
        )
        + card(
            "tokens",
            "Tokens",
            fmt_tokens(t.total_tokens),
            f"{fmt_tokens(t.cached_input_tokens)} cached",
            tokens_tip,
            t.delta_tokens_pct,
            "neutral",
            t.daily_token_sparkline,
            "var(--accent)",
            "14-day token volume",
        )
        + card(
            "sessions",
            "Sessions",
            str(t.sessions),
            f"{t.turns} turns · {t.tools_per_turn:.2f}/turn",
            sessions_tip,
            t.delta_sessions_pct,
            "neutral",
            t.daily_session_sparkline,
            "var(--mute)",
            "14-day sessions",
        )
        + "</div>"
    )


# 4. Dashboard nav ------------------------------------------------------------


def render_dashboard_nav(d: Dashboard) -> str:
    links = [
        ("command-center", "Command", bool(d.command_center)),
        ("usage-windows", "Windows", bool(d.usage_windows)),
        ("impact", "Impact", bool(d.impact_cards)),
        ("cost-over-time", "Cost", bool(d.daily)),
        ("usage-mix", "Mix", bool(d.usage_mix)),
        ("advisor", "Advisor", True),
        ("top-sessions", "Sessions", bool(d.top_sessions)),
        ("rate-limits", "Limits", d.rate_limit_pressure is not None),
        ("evidence", "Evidence", bool(d.evidence or d.quality_score)),
    ]
    body = "".join(
        f'<a class="dash-nav-link{" is-muted" if not enabled else ""}" href="#{esc(anchor)}">'
        f"{esc(label)}</a>"
        for anchor, label, enabled in links
    )
    return f'<nav class="dash-nav" aria-label="Dashboard sections">{body}</nav>'


# 5. Command center -----------------------------------------------------------


def render_command_center(cards: list[CommandCenterCard]) -> str:
    sec_id = "command-center"
    if not cards:
        return ""
    body = "".join(
        f'<article class="command-card command-card-{esc(card.tone)}">'
        f'<div class="command-top">'
        f'<span class="command-label">{esc(card.label)}</span>'
        f'<span class="command-metric">{esc(card.metric)}</span>'
        f"</div>"
        f'<div class="command-value">{esc(card.value)}</div>'
        f'<div class="command-detail">{esc(card.detail)}</div>'
        f"</article>"
        for card in cards
    )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Command center', 'what needs attention first')}"
        f'<div class="sec-body">'
        f'<div class="command-grid">{body}</div>'
        f"</div></section>"
    )


# 6. Rolling usage windows ----------------------------------------------------


def render_usage_windows(windows: list[UsageWindow]) -> str:
    sec_id = "usage-windows"
    if not windows:
        return ""
    cards: list[str] = []
    for window in sorted(windows, key=lambda item: (item.days, item.label)):
        has_events = window.events > 0
        meta = (
            f"{fmt_tokens(window.total_tokens)} tokens · "
            f"{fmt_int(window.events)} events · {fmt_int(window.sessions)} sessions"
            if has_events
            else "no usage in this rolling window"
        )
        tip = (
            f"{window.label} · {window.range} · "
            f"{fmt_money(window.cost_usd)} · {fmt_tokens(window.total_tokens)} tokens"
        )
        cards.append(
            f'<article class="usage-window-card" data-tip="{esc(tip)}" data-tip-pos="bottom">'
            f'<div class="usage-window-top">'
            f'<div class="usage-window-label">{esc(window.label)}</div>'
            f'<div class="usage-window-range">{esc(window.range)}</div>'
            f"</div>"
            f'<div class="usage-window-value">{fmt_money(window.cost_usd)}</div>'
            f'<div class="usage-window-meta">{esc(meta)}</div>'
            f'<div class="usage-window-stats">'
            f"<span>{fmt_pct_round(window.cache_hit_rate)} cache</span>"
            f"<span>{fmt_int(window.active_days)} active days</span>"
            f"</div>"
            f'<div class="usage-window-foot">'
            f"{sparkline(window.daily_cost_sparkline, 'var(--accent)', window.label + ' cost')}"
            f"{sparkline(window.daily_token_sparkline, 'var(--mute)', window.label + ' tokens')}"
            f"</div>"
            f"</article>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Usage windows', '7d → 30d → 90d · deduped')}"
        f'<div class="sec-body">'
        f'<div class="usage-window-grid">{"".join(cards)}</div>'
        f"</div></section>"
    )


# 5. Impact cards -------------------------------------------------------------


def render_impact_cards(cards: list[ImpactCard]) -> str:
    sec_id = "impact"
    if not cards:
        return ""
    tone_order = {"critical": 0, "warn": 1, "good": 2, "neutral": 3}
    label_order = {
        "Budget risk": 0,
        "Cost driver": 1,
        "Cache leverage": 2,
        "Usage rhythm": 3,
        "Dedupe": 4,
    }
    ordered_cards = sorted(
        cards,
        key=lambda card: (
            label_order.get(card.label, 99),
            tone_order.get(card.tone, 3),
            card.label,
        ),
    )
    body = "".join(
        f'<article class="impact-card impact-card-{esc(card.tone)}">'
        f'<div class="impact-label">{esc(card.label)}</div>'
        f'<div class="impact-value">{esc(card.value)}</div>'
        f'<div class="impact-detail">{esc(card.detail)}</div>'
        f"</article>"
        for card in ordered_cards
    )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Impact', 'risk, drivers, leverage')}"
        f'<div class="sec-body">'
        f'<div class="impact-grid">{body}</div>'
        f"</div></section>"
    )


# 6. Cost over time -----------------------------------------------------------


def _nice_max(v: float) -> float:
    """Round up to a nice Y-axis ceiling: 1, 2, 5, 10 × 10^k."""
    if v <= 0:
        return 1
    exp = 10 ** int(_log10(v))
    f = v / exp
    if f <= 1:
        nice = 1
    elif f <= 2:
        nice = 2
    elif f <= 5:
        nice = 5
    else:
        nice = 10
    return nice * exp


def _log10(v: float) -> float:
    import math

    return math.floor(math.log10(v))


def render_cost_over_time(daily: list[DailyPoint], empty: bool) -> str:
    sec_id = "cost-over-time"
    if empty or not daily:
        return (
            f'<section class="sec" id="{sec_id}">'
            f"{section_head(sec_id, 'Cost over time')}"
            f'<div class="sec-body">'
            f'<div class="panel empty-panel">'
            f"No events for this window. Run <code>caliper doctor</code> to "
            f"verify your local setup."
            f"</div></div></section>"
        )

    W, H = 1000, 220
    PAD_L, PAD_R, PAD_T, PAD_B = 60, 24, 14, 28
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    n = len(daily)
    max_cost = max((d.cost_usd for d in daily), default=1)
    y_max = _nice_max(max(max_cost, 1))
    total = sum(d.cost_usd for d in daily)
    mean = total / n
    mean_y = PAD_T + plot_h - (mean / y_max) * plot_h
    peak = max(daily, key=lambda d: d.cost_usd)

    bar_gap = 4
    slot_w = plot_w / n
    bar_w = max(4, slot_w - bar_gap)

    parts = [
        f'<svg class="chart cost-chart" viewBox="0 0 {W} {H}" '
        f'preserveAspectRatio="none" role="img" aria-label="Daily cost over {n} days">'
    ]

    # Gridlines at 25/50/75% of yMax (per spec)
    for p in (0.25, 0.5, 0.75):
        y = PAD_T + plot_h - p * plot_h
        parts.append(
            f'<g><line x1="{PAD_L}" y1="{y:.2f}" x2="{W - PAD_R}" y2="{y:.2f}" '
            f'stroke="var(--grid)" stroke-dasharray="2 4"/>'
            f'<text x="{PAD_L - 10}" y="{y + 4:.2f}" text-anchor="end" '
            f'fill="var(--mute)" font-size="11" font-family="ui-monospace, '
            f'SF Mono, Menlo, Consolas, monospace">{fmt_money(p * y_max)}</text>'
            f"</g>"
        )

    # Baseline
    parts.append(
        f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" '
        f'y2="{PAD_T + plot_h}" stroke="var(--border-strong)"/>'
    )
    # Top edge (y-max label)
    parts.append(
        f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{W - PAD_R}" y2="{PAD_T}" '
        f'stroke="var(--border)"/>'
        f'<text x="{PAD_L - 10}" y="{PAD_T + 4}" text-anchor="end" '
        f'fill="var(--mute)" font-size="11" font-family="ui-monospace, '
        f'SF Mono, Menlo, Consolas, monospace">{fmt_money(y_max)}</text>'
    )

    # Bars
    for i, d in enumerate(daily):
        h = (d.cost_usd / y_max) * plot_h
        x = PAD_L + i * slot_w + bar_gap / 2
        y = PAD_T + plot_h - h
        fill = "var(--accent-strong)" if d is peak else "var(--accent)"
        parts.append(
            f"<g><title>{esc(d.day)} · {fmt_money(d.cost_usd)} · "
            f"{d.events} events · {esc(d.shape)}</title>"
            # ghost full-height bar — keeps empty days legible
            f'<rect x="{x:.2f}" y="{PAD_T}" width="{bar_w:.2f}" height="{plot_h}" '
            f'fill="var(--bar-ghost)" opacity="0.35" rx="1"/>'
        )
        if h > 0:
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" '
                f'height="{h:.2f}" fill="{fill}" rx="1.5"/>'
            )
            if d is peak:
                parts.append(
                    f'<rect x="{x - 0.5:.2f}" y="{y - 0.5:.2f}" '
                    f'width="{bar_w + 1:.2f}" height="{h + 1:.2f}" '
                    f'fill="none" stroke="var(--accent-strong)" '
                    f'stroke-width="0.5" opacity="0.6" rx="1.5"/>'
                )
        parts.append("</g>")

    # X-axis labels: first / mid / last
    for i in (0, n // 2, n - 1):
        d = daily[i]
        x = PAD_L + i * slot_w + slot_w / 2
        parts.append(
            f'<text x="{x:.2f}" y="{H - 10}" text-anchor="middle" '
            f'fill="var(--mute)" font-size="11" font-family="ui-monospace, '
            f'SF Mono, Menlo, Consolas, monospace">{esc(d.day[5:])}</text>'
        )

    # Daily mean reference line (drawn after bars so it stays visible)
    parts.append(
        f'<line x1="{PAD_L}" y1="{mean_y:.2f}" x2="{W - PAD_R}" '
        f'y2="{mean_y:.2f}" stroke="var(--accent)" stroke-dasharray="3 4" '
        f'stroke-width="1.25" opacity="0.7"/>'
        f'<rect class="mean-label-bg" x="{W - PAD_R - 138:.0f}" '
        f'y="{mean_y - 16:.2f}" width="134" '
        f'height="14" fill="var(--panel)" stroke="var(--border-strong)" '
        f'stroke-width="0.5" rx="3"/>'
        f'<text class="mean-label-text" x="{W - PAD_R - 6}" '
        f'y="{mean_y - 5:.2f}" text-anchor="end" '
        f'fill="var(--accent)" font-size="10" font-weight="600" '
        f'font-family="ui-monospace, SF Mono, Menlo, Consolas, monospace">'
        f"mean&nbsp;{fmt_money(mean)}&nbsp;/&nbsp;day</text>"
    )
    parts.append("</svg>")

    # Per-day dominant-shape strip
    _strip_n = max(1, len(daily) - 1)
    cells = "".join(
        f'<span class="shape-cell shape-{SHAPE_TO_CAT.get(d.shape, "mixed")}"'
        f"{_tip_anchor(i / _strip_n)}"
        f' data-tip="{esc(d.day)} · {esc(d.shape)} · {fmt_money(d.cost_usd)}"></span>'
        for i, d in enumerate(daily)
    )

    # HTML hit-overlay so each daily bar gets a styled tooltip on hover.
    # The SVG uses preserveAspectRatio="none" → both axes stretch to fill the
    # container. We map x/width from viewBox units to percentages so the
    # hit-zones stay aligned at any container width.
    hit_zones: list[str] = []
    for i, d in enumerate(daily):
        zone_left = (PAD_L + i * slot_w) / W * 100
        zone_w = slot_w / W * 100
        zone_center = zone_left + zone_w / 2
        events_label = f"{d.events:,} event{'s' if d.events != 1 else ''}"
        peak_tag = " · peak" if d is peak else ""
        tip = f"{d.day} · {fmt_money(d.cost_usd)} · {events_label} · {d.shape}{peak_tag}"
        anchor = _tip_anchor(zone_center / 100.0)
        hit_zones.append(
            f'<div class="chart-hit" data-tip="{esc(tip)}"'
            f"{anchor}"
            f' style="left:{zone_left:.4f}%;width:{zone_w:.4f}%"></div>'
        )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Cost over time', f'peak {fmt_money(peak.cost_usd)} · {peak.day}')}"
        f'<div class="sec-body">'
        f'<div class="chart-panel">'
        f'<div class="chart-wrap">'
        + "".join(parts)
        + '<div class="chart-hit-layer" aria-hidden="true">'
        + "".join(hit_zones)
        + "</div>"
        + "</div>"
        + f'<div class="shape-strip" role="img" aria-label="Daily dominant work shape">'
        f"{cells}</div>"
        f'<div class="shape-strip-row">'
        f'<span class="label">dominant work per day</span>'
        f'<div class="shape-strip-legend">'
        f'<span class="leg-explore"><span class="dot"></span>explore</span>'
        f'<span class="leg-execute"><span class="dot"></span>execute</span>'
        f'<span class="leg-diagnose"><span class="dot"></span>diagnose</span>'
        f'<span class="leg-mixed"><span class="dot"></span>mixed</span>'
        f"</div></div>"
        f"</div></div></section>"
    )


# 5. Activity heatmap (yearly contribution grid) ------------------------------


_DAY_OF_WEEK_SHORT = ("M", "T", "W", "T", "F", "S", "S")
_MONTH_LETTERS = ("J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D")


def render_yearly_heatmap(h: YearlyHeatmap | None) -> str:
    """GitHub-style 53×7 contribution grid with bottom stats.

    Rendered as a CSS grid of HTML divs (not SVG) so each cell can carry a
    styled hover tooltip via the [data-tip] system.
    """
    sec_id = "activity-heatmap"
    if h is None or not h.cells:
        return ""

    # Pad the head with blanks so day-of-week rows align with the calendar
    # grid (Monday-first). The cells then flow column-by-column via CSS
    # grid-auto-flow: column.
    first_date = dt.date.fromisoformat(h.cells[0].date)
    lead_blanks = first_date.weekday()  # 0..6
    total_with_padding = lead_blanks + len(h.cells)
    weeks = -(-total_with_padding // 7)  # ceil

    # Determine which week-column each calendar month begins on so we can
    # place the month letters above the right columns.
    month_marks: dict[int, int] = {}
    for i, cell in enumerate(h.cells):
        slot = lead_blanks + i
        week = slot // 7
        date_obj = dt.date.fromisoformat(cell.date)
        if date_obj.day <= 7 and date_obj.month not in month_marks.values():
            month_marks[week] = date_obj.month

    # Month label row (placed at the right column via grid-column-start)
    month_labels: list[str] = []
    for week, month in sorted(month_marks.items()):
        letter = _MONTH_LETTERS[month - 1]
        month_labels.append(
            f'<span class="heat-month" style="grid-column:{week + 1}">{letter}</span>'
        )

    # Cells (lead blanks first, then real cells)
    cell_html: list[str] = []
    for _ in range(lead_blanks):
        cell_html.append('<div class="heat-cell heat-cell-blank"></div>')
    weeks_denom = max(1, weeks - 1)
    for i, cell in enumerate(h.cells):
        date_obj = dt.date.fromisoformat(cell.date)
        tip = (
            f"{date_obj.strftime('%A, %B')} {date_obj.day}, {date_obj.year} · "
            f"{cell.value:,} {h.metric_label.lower()}"
        )
        week = (lead_blanks + i) // 7
        anchor = _tip_anchor(week / weeks_denom)
        cell_html.append(
            f'<div class="heat-cell heat-level-{cell.level}"{anchor} data-tip="{esc(tip)}"></div>'
        )
    # Trailing blanks so the last column always has 7 rows
    remainder = (lead_blanks + len(h.cells)) % 7
    if remainder:
        for _ in range(7 - remainder):
            cell_html.append('<div class="heat-cell heat-cell-blank"></div>')

    # Day-of-week labels (M, W, F at rows 1, 3, 5 — Monday-first)
    dow_labels = "".join(
        f'<span class="heat-dow" style="grid-row:{row}">{letter}</span>'
        for row, letter in ((1, "M"), (3, "W"), (5, "F"))
    )

    # Legend
    legend_levels = "".join(
        f'<span class="heat-cell heat-level-{level}"></span>' for level in range(5)
    )

    svg = (
        f'<div class="heat-grid-wrap">'
        f'<div class="heat-month-row" style="grid-template-columns:repeat({weeks}, 1fr)">'
        f"{''.join(month_labels)}"
        f"</div>"
        f'<div class="heat-dow-col">{dow_labels}</div>'
        f'<div class="heat-grid" '
        f'style="grid-template-columns:repeat({weeks}, 1fr)">'
        f"{''.join(cell_html)}"
        f"</div>"
        f'<div class="heat-legend">'
        f'<span class="heat-legend-label">Fewer</span>'
        f"{legend_levels}"
        f'<span class="heat-legend-label">More</span>'
        f"</div>"
        f"</div>"
    )

    # Bottom stats
    stat_cells = [
        ("Most active month", h.most_active_month),
        ("Most active day", h.most_active_day),
        ("Longest streak", f"{h.longest_streak}d"),
        ("Current streak", f"{h.current_streak}d"),
    ]
    stat_html = "".join(
        '<div class="heat-stat">'
        f'<div class="heat-stat-label">{esc(label)}</div>'
        f'<div class="heat-stat-value">{esc(value)}</div>'
        "</div>"
        for label, value in stat_cells
    )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Activity', f'{h.metric_total:,} {h.metric_label.lower()} · last 365 days')}"
        f'<div class="sec-body">'
        f'<div class="panel heat-panel">'
        f'<div class="heat-header">'
        f'<div class="heat-headline">'
        f'<div class="heat-headline-label">{esc(h.metric_label)}</div>'
        f'<div class="heat-headline-value">{h.metric_total:,}</div>'
        f"</div>"
        f"</div>"
        f"{svg}"
        f'<div class="heat-stats">{stat_html}</div>'
        f"</div>"
        f"</div></section>"
    )


# 6. Recap card (hour-of-week heatmap + 2x4 stat grid + comparison) -----------


_DAY_OF_WEEK_FULL = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def render_recap(recap: Recap | None) -> str:
    sec_id = "recap"
    if recap is None or not recap.hours:
        return ""

    # 2x4 stat grid
    stat_html = "".join(
        '<div class="recap-stat">'
        f'<div class="recap-stat-label">{esc(s.label)}</div>'
        f'<div class="recap-stat-value">{esc(s.value)}</div>'
        "</div>"
        for s in recap.stats[:8]
    )

    # 7×24 hour-of-week heatmap rendered as a CSS grid of divs so each cell
    # carries a styled hover tooltip.
    hour_cells: list[str] = []
    # Order cells by (day_of_week, hour) for row-major grid flow.
    by_key = {(c.day_of_week, c.hour): c for c in recap.hours}
    for dow in range(7):
        for hour in range(24):
            c = by_key.get((dow, hour))
            level = c.level if c else 0
            value = c.value if c else 0
            tip_value = f"{value:,} event{'s' if value != 1 else ''}" if value else "no events"
            hour_label = (
                "12 AM"
                if hour == 0
                else "12 PM"
                if hour == 12
                else f"{hour} AM"
                if hour < 12
                else f"{hour - 12} PM"
            )
            tip = f"{_DAY_OF_WEEK_FULL[dow]} · {hour_label} · {tip_value}"
            anchor = _tip_anchor(hour / 23.0)
            hour_cells.append(
                f'<div class="hour-cell hour-level-{level}"{anchor} data-tip="{esc(tip)}"></div>'
            )

    # Day labels (left column): M T W T F S S
    day_labels = "".join(
        f'<span class="hour-dow">{_DAY_OF_WEEK_FULL[dow][:1]}</span>' for dow in range(7)
    )

    # Hour labels (top row): 12 AM / 6 AM / 12 PM / 6 PM placed at grid cols 1/7/13/19
    hour_labels_list = []
    for hour, label in ((0, "12 AM"), (6, "6 AM"), (12, "12 PM"), (18, "6 PM")):
        hour_labels_list.append(
            f'<span class="hour-axis" style="grid-column:{hour + 1}">{label}</span>'
        )

    svg = (
        f'<div class="hour-grid-wrap">'
        f'<div class="hour-axis-row">'
        f"{''.join(hour_labels_list)}"
        f"</div>"
        f'<div class="hour-dow-col">{day_labels}</div>'
        f'<div class="hour-grid">'
        f"{''.join(hour_cells)}"
        f"</div>"
        f"</div>"
    )

    # The card carries the larger recap title; the section header keeps the
    # dashboard's scan pattern consistent with the surrounding sections.
    sec_anchor = section_head(sec_id, "Recap")
    panel_header = (
        '<div class="recap-header">'
        f'<h3 class="recap-headline">{esc(recap.title)}</h3>'
        '<div class="recap-comparison-inline">'
        f"{esc(recap.comparison)}"
        "</div>"
        "</div>"
    )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{sec_anchor}"
        f'<div class="sec-body">'
        f'<div class="panel recap-panel">'
        f"{panel_header}"
        f'<div class="recap-stat-grid">{stat_html}</div>'
        f"{svg}"
        f"</div>"
        f"</div></section>"
    )


# 7. Session shape ------------------------------------------------------------


def render_session_shape(shape: SessionShape | None, empty: bool) -> str:
    sec_id = "session-shape"
    if empty or shape is None or shape.total_sessions == 0:
        return (
            f'<section class="sec" id="{sec_id}">'
            f"{section_head(sec_id, 'Session shape')}"
            f'<div class="sec-body">'
            f'<div class="panel empty-panel">'
            f"No tool-use signal yet in this window. Session shape is "
            f"currently extracted from Claude Code only."
            f"</div></div></section>"
        )

    max_tool = max((t.count for t in shape.top_tools), default=1)
    meters = "".join(meter_row(t.name, t.count, max_tool, t.category) for t in shape.top_tools)

    stacked_segs = "".join(
        f'<span class="stacked-seg seg-{SHAPE_TO_CAT.get(c.category, "mixed")}" '
        f'title="{esc(c.label)} · {fmt_pct_round(c.share)}" '
        f'style="width:{c.share * 100:.4f}%">'
        f"{fmt_pct_round(c.share) if c.share >= 0.10 else ''}</span>"
        for c in shape.categories
    )

    cat_rows = "".join(
        f"<tr><td>"
        f'<span class="dot dot-inline" style="background:{CAT_COLOR[SHAPE_TO_CAT.get(c.category, "mixed")]}"></span>'
        f'<span class="cat-label">{esc(c.label)}</span></td>'
        f'<td class="num">{c.sessions}</td>'
        f'<td class="num mute">{fmt_pct_round(c.share)}</td></tr>'
        for c in shape.categories
    )

    partial = shape.coverage_events < shape.coverage_total_events
    footnote = (
        f'<div class="sec-foot">Coverage: {shape.coverage_events} of '
        f"{shape.coverage_total_events} events carry tool-use detail "
        f"(Claude Code only today).</div>"
        if partial
        else ""
    )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Session shape', f'{shape.total_sessions} sessions · {shape.total_turns} turns')}"
        f'<div class="sec-body">'
        f'<div class="shape-grid">'
        # Top tools panel
        f'<div class="panel shape-tools">'
        f'<div class="panel-head">'
        f'<h3 class="panel-title">Top tools</h3>'
        f"{category_legend()}"
        f"</div>"
        f'<div class="meters">{meters}</div>'
        f"</div>"
        # Categories panel
        f'<div class="panel shape-cats">'
        f'<h3 class="panel-title">Shape distribution</h3>'
        f'<div class="stacked" role="img" aria-label="{esc(", ".join(c.category + " " + fmt_pct_round(c.share) for c in shape.categories))}">'
        f"{stacked_segs}"
        f"</div>"
        f'<table class="tight"><tbody>{cat_rows}</tbody></table>'
        f"</div>"
        f"</div>"
        f"{footnote}"
        f"</div></section>"
    )


# 8. Usage mix ----------------------------------------------------------------


_MIX_DIMENSION_LABELS = {
    "vendor": "Vendor",
    "model/tier": "Model / tier",
    "tier": "Tier",
    "source": "Source",
}


def render_usage_mix(rows: list[MixRow]) -> str:
    sec_id = "usage-mix"
    if not rows:
        return ""
    dimension_order = ["vendor", "model/tier", "tier", "source"]
    filters = [
        '<button class="mix-filter is-active" type="button" data-mix-filter="all">All</button>'
    ]
    for dim in dimension_order:
        if any(row.dimension == dim for row in rows):
            filters.append(
                f'<button class="mix-filter" type="button" data-mix-filter="{esc(dim)}">'
                f"{esc(_MIX_DIMENSION_LABELS.get(dim, dim.title()))}</button>"
            )

    panels: list[str] = []
    for dim in dimension_order:
        group = sorted(
            [row for row in rows if row.dimension == dim],
            key=lambda row: (-row.cost_usd, -row.total_tokens, -row.events, row.label),
        )
        if not group:
            continue
        items = []
        for row in group:
            items.append(
                f'<div class="mix-row" data-mix-dimension="{esc(dim)}">'
                f'<div class="mix-main">'
                f'<div class="mix-label">{esc(row.label)}</div>'
                f'<div class="mix-meta">{fmt_money(row.cost_usd)} · '
                f"{fmt_tokens(row.total_tokens)} tokens · {fmt_int(row.events)} events</div>"
                f"</div>"
                f'<div class="mix-spark">'
                f"{sparkline(row.daily_cost_sparkline, 'var(--accent)', row.label + ' cost')}"
                f"</div>"
                f'<div class="mix-share">'
                f"{inline_share_bar(row.share)}"
                f"</div>"
                f"</div>"
            )
        panels.append(
            f'<article class="mix-panel" data-mix-panel="{esc(dim)}">'
            f'<header class="mix-panel-head">'
            f'<h3 class="panel-title">{esc(_MIX_DIMENSION_LABELS.get(dim, dim.title()))}</h3>'
            f'<span class="mix-count">{len(group)} rows</span>'
            f"</header>"
            f'<div class="mix-list">{"".join(items)}</div>'
            f"</article>"
        )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Usage mix', 'model, tier, vendor, source')}"
        f'<div class="sec-body">'
        f'<div class="mix-controls" role="group" aria-label="Usage mix filter">'
        f"{''.join(filters)}</div>"
        f'<div class="mix-grid">{"".join(panels)}</div>'
        f"</div></section>"
    )


# 9. Savings advisor ----------------------------------------------------------


def render_advisor(rows: list[AdvisorRecommendation]) -> str:
    sec_id = "advisor"
    if not rows:
        return (
            f'<section class="sec" id="{sec_id}">'
            f"{section_head(sec_id, 'Savings advisor', 'model and tier swap checks')}"
            f'<div class="sec-body">'
            f'<div class="panel empty-panel">No high-confidence savings recommendations.</div>'
            f"</div></section>"
        )
    cards = []
    for row in sorted(rows, key=lambda item: (-item.savings_usd, -item.confidence, -item.events)):
        cards.append(
            f'<article class="advisor-card advisor-card-{esc(row.tone)}">'
            f'<div class="advisor-card-top">'
            f'<h3 class="advisor-title">{esc(row.title)}</h3>'
            f'<span class="advisor-value">{esc(row.value)}</span>'
            f"</div>"
            f'<p class="advisor-detail">{esc(row.detail)}</p>'
            f'<div class="advisor-meta">'
            f"<span>{fmt_pct_round(row.confidence)} confidence</span>"
            f"<span>{fmt_int(row.events)} events</span>"
            f"<span>{fmt_int(row.sessions)} sessions</span>"
            f"</div>"
            f'<code class="advisor-command">{esc(row.action)}</code>'
            f"</article>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Savings advisor', 'estimated avoidable spend')}"
        f'<div class="sec-body">'
        f'<div class="advisor-grid">{"".join(cards)}</div>'
        f"</div></section>"
    )


# 10. Session outliers --------------------------------------------------------


def render_top_sessions(rows: list[SessionRow]) -> str:
    sec_id = "top-sessions"
    if not rows:
        return ""
    body = []
    ordered = sorted(
        rows,
        key=lambda row: (-row.cost_usd, -row.total_tokens, -row.tool_calls, -row.events, row.label),
    )
    for row in ordered:
        body.append(
            f"<tr>"
            f'<td><span class="session-label">{esc(row.label)}</span>'
            f'<div class="mono mute">{esc(row.started_at)}</div></td>'
            f'<td class="num strong" data-value="{row.cost_usd:.8f}">{fmt_money(row.cost_usd)}</td>'
            f'<td class="num" data-value="{row.total_tokens}">{fmt_tokens(row.total_tokens)}</td>'
            f'<td class="num" data-value="{row.events}">{fmt_int(row.events)}</td>'
            f'<td class="num" data-value="{row.tool_calls}">{fmt_int(row.tool_calls)}</td>'
            f"<td>{esc(row.project)}</td>"
            f'<td><span class="reason-chip">{esc(row.reason)}</span></td>'
            f'<td class="mono mute">{esc(", ".join(row.models) or "—")}</td>'
            f"</tr>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Session outliers', 'sorted by spend impact')}"
        f'<div class="sec-body">'
        f'<div class="panel pad-0 table-scroll">'
        f'<table class="data data-sortable session-table">'
        f"<thead><tr>"
        f'<th data-sort="text">Session</th>'
        f'<th class="num th-cost" data-sort="number" aria-sort="descending">Cost <span class="sort-glyph">↓</span></th>'
        f'<th class="num" data-sort="number">Tokens</th>'
        f'<th class="num" data-sort="number">Events</th>'
        f'<th class="num" data-sort="number">Tools</th>'
        f'<th data-sort="text">Project</th>'
        f'<th data-sort="text">Reason</th>'
        f'<th data-sort="text">Models</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        f"</table></div></div></section>"
    )


# 13. Rate limits -------------------------------------------------------------


def render_rate_limits(pressure: RateLimitPressure | None) -> str:
    sec_id = "rate-limits"
    if pressure is None:
        return ""
    peak = max(
        [
            value
            for value in (pressure.peak_primary_pct, pressure.peak_secondary_pct)
            if value is not None
        ],
        default=None,
    )
    stats = [
        ("Peak pressure", fmt_pct_round(peak) if peak is not None else "No samples"),
        ("Latest primary", fmt_pct_round(pressure.latest_primary_pct)),
        ("Latest secondary", fmt_pct_round(pressure.latest_secondary_pct)),
        ("Reached", fmt_int(pressure.reached_count)),
    ]
    stat_html = "".join(
        f'<div class="limit-stat"><div class="limit-label">{esc(label)}</div>'
        f'<div class="limit-value">{esc(value)}</div></div>'
        for label, value in stats
    )
    meta = " · ".join(
        part
        for part in (
            pressure.latest_limit_name,
            pressure.latest_plan_type,
            f"resets {pressure.latest_resets_at}" if pressure.latest_resets_at else "",
        )
        if part
    )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Rate limits', 'pressure and reset signal')}"
        f'<div class="sec-body">'
        f'<div class="panel limit-panel limit-panel-{esc(pressure.tone)}">'
        f'<div class="limit-panel-head">'
        f'<div><h3 class="panel-title">Limit pressure</h3>'
        f'<div class="limit-sub">{esc(meta or "No rate-limit samples in this window.")}</div></div>'
        f'<span class="limit-samples">{fmt_int(pressure.sample_count)} samples</span>'
        f"</div>"
        f'<div class="limit-stats">{stat_html}</div>'
        f"</div></div></section>"
    )


# 11. Models & tiers -----------------------------------------------------------


def render_models(rows: list[ModelRow], total_cost: float) -> str:
    sec_id = "models"
    if not rows:
        return ""  # section hidden when empty (per spec)
    body = []
    ordered_rows = sorted(
        rows,
        key=lambda row: (-row.cost_usd, -row.tokens, -row.events, row.vendor, row.model, row.tier),
    )
    for r in ordered_rows:
        share = r.cost_usd / total_cost if total_cost > 0 else 0
        body.append(
            f"<tr>"
            f"<td>{vendor_badge(r.vendor)}</td>"
            f'<td><span class="mono">{esc(r.model)}</span>'
            f'<span class="mute"> · {esc(r.tier)}</span></td>'
            f'<td class="num strong" data-value="{r.cost_usd:.8f}">{fmt_money(r.cost_usd)}</td>'
            f'<td class="num">{inline_share_bar(share)}</td>'
            f'<td class="num" data-value="{r.events}">{r.events}</td>'
            f'<td class="num" data-value="{r.tokens}">{fmt_tokens(r.tokens)}</td>'
            f'<td class="num" data-value="{r.cache_hit_rate:.8f}">{fmt_pct_round(r.cache_hit_rate)}</td>'
            f"</tr>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Models & tiers', 'sorted by cost')}"
        f'<div class="sec-body">'
        f'<div class="panel pad-0 table-scroll"><table class="data data-sortable">'
        f"<thead><tr>"
        f'<th class="th-vendor" data-sort="text">Vendor</th>'
        f'<th class="th-model" data-sort="text">Model · tier</th>'
        f'<th class="num th-cost" data-sort="number" aria-sort="descending">Cost <span class="sort-glyph">↓</span></th>'
        f'<th class="num">Share</th>'
        f'<th class="num" data-sort="number">Events</th>'
        f'<th class="num" data-sort="number">Tokens</th>'
        f'<th class="num th-cache" data-sort="number">Cache</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        f"</table></div></div></section>"
    )


# 7. Projects -----------------------------------------------------------------


def render_projects(rows: list[ProjectRow], show_paths: bool) -> str:
    sec_id = "projects"
    if not rows:
        return ""
    ordered_rows = sorted(
        rows,
        key=lambda row: (-row.cost_usd, -row.events, -row.sessions, row.name, row.path or ""),
    )
    # Global tool max so mini-bars are comparable across rows
    max_tool = max((t.count for r in ordered_rows for t in r.top_tools), default=1)
    total = sum(r.cost_usd for r in ordered_rows)

    body = []
    for r in ordered_rows:
        share = r.cost_usd / total if total > 0 else 0
        path_html = (
            f'<div class="mono mute proj-path">{esc(r.path)}</div>' if show_paths and r.path else ""
        )
        tools_html = "".join(mini_bar(t.name, t.count, max_tool, t.category) for t in r.top_tools)
        body.append(
            f"<tr>"
            f'<td><span class="proj-name">{esc(r.name)}</span>{path_html}</td>'
            f'<td class="num strong" data-value="{r.cost_usd:.8f}">{fmt_money(r.cost_usd)}</td>'
            f'<td class="num">{inline_share_bar(share)}</td>'
            f'<td class="num" data-value="{r.events}">{r.events}</td>'
            f'<td class="num" data-value="{r.sessions}">{r.sessions}</td>'
            f'<td class="col-tools">{tools_html}</td>'
            f"</tr>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Projects', 'sorted by cost')}"
        f'<div class="sec-body">'
        f'<div class="panel pad-0 table-scroll"><table class="data data-sortable">'
        f"<thead><tr>"
        f'<th data-sort="text">Project</th>'
        f'<th class="num th-cost" data-sort="number" aria-sort="descending">Cost <span class="sort-glyph">↓</span></th>'
        f'<th class="num">Share</th>'
        f'<th class="num" data-sort="number">Events</th>'
        f'<th class="num" data-sort="number">Sessions</th>'
        f'<th class="th-tools">Top tools</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        f"</table></div></div></section>"
    )


# 8. Insights -----------------------------------------------------------------


def render_insights(rows: list[Insight]) -> str:
    sec_id = "insights"
    if not rows:
        return (
            f'<section class="sec" id="{sec_id}">'
            f"{section_head(sec_id, 'Insights')}"
            f'<div class="sec-body">'
            f'<div class="panel empty-panel">No insights for this window.</div>'
            f"</div></section>"
        )
    items = []
    for ins in rows:
        impact = f'<span class="impact-chip">{esc(ins.impact)}</span>' if ins.impact else ""
        items.append(
            f'<li class="insight insight-{esc(ins.severity)}">'
            f'<span class="insight-rail"></span>'
            f'<div class="insight-head">'
            f"{severity_pill(ins.severity)}"
            f'<h3 class="insight-title">{esc(ins.title)}</h3>'
            f"{impact}"
            f"</div>"
            f'<p class="insight-detail">{esc(ins.detail)}</p>'
            f"</li>"
        )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Insights')}"
        f'<div class="sec-body">'
        f'<ul class="insight-list">{"".join(items)}</ul>'
        f"</div></section>"
    )


# 9. Forecast -----------------------------------------------------------------


def _forecast_band(
    low: float,
    high: float,
    mid: float,
    vmin: float,
    vmax: float,
    *,
    accent: bool = False,
    off_band: bool = False,
) -> str:
    """Render a single forecast band against a *shared* domain.

    ``low`` / ``high`` are the ±1σ linear-projection edges; ``mid`` is the
    estimate plotted on this card (linear or EWMA). ``vmin`` / ``vmax``
    define the shared domain so both cards in the section render on the
    same scale and their dots are directly comparable.

    When ``mid`` falls outside ``[low, high]`` (``off_band``), the dot keeps
    its true position on the shared axis and a dashed connector bridges
    band-edge → dot.

    The geometry is drawn in SVG (it stretches gracefully under
    ``preserveAspectRatio="none"``) but the numeric labels are HTML —
    SVG ``<text>`` would get squeezed/stretched non-uniformly when the
    aspect ratio changes, leading to overlapping labels at narrow widths.
    """
    H = 22
    TRACK_Y = 11
    vspan = (vmax - vmin) or 1.0

    def to_pct(v: float) -> float:
        # clamp to [0, 100] in case mid pads beyond the visible domain.
        t = max(0.0, min(1.0, (v - vmin) / vspan))
        return t * 100.0

    band_p1 = to_pct(low)
    band_p2 = to_pct(high)
    band_w_pct = max(0.5, band_p2 - band_p1)
    mid_pct = to_pct(mid)
    fill = "var(--accent-tint-2)" if accent else "var(--accent-tint)"

    # SVG uses width=100, height=H, then stretches via CSS — preserves
    # band positions cleanly across any container width.
    svg_parts: list[str] = [
        f'<svg viewBox="0 0 100 {H}" preserveAspectRatio="none" '
        f'class="forecast-band-svg" role="img" '
        f'aria-label="Forecast confidence band">',
        # track baseline (full width)
        f'<line x1="0" y1="{TRACK_Y}" x2="100" y2="{TRACK_Y}" '
        f'stroke="var(--hairline)" stroke-width="0.4" '
        f'vector-effect="non-scaling-stroke"/>',
        # band rect
        f'<rect x="{band_p1:.3f}" y="{TRACK_Y - 3}" width="{band_w_pct:.3f}" '
        f'height="6" rx="3" fill="{fill}"/>',
        # edge ticks
        f'<line x1="{band_p1:.3f}" y1="{TRACK_Y - 6}" x2="{band_p1:.3f}" '
        f'y2="{TRACK_Y + 6}" stroke="var(--border-strong)" stroke-width="0.8" '
        f'vector-effect="non-scaling-stroke" opacity="0.85"/>',
        f'<line x1="{band_p2:.3f}" y1="{TRACK_Y - 6}" x2="{band_p2:.3f}" '
        f'y2="{TRACK_Y + 6}" stroke="var(--border-strong)" stroke-width="0.8" '
        f'vector-effect="non-scaling-stroke" opacity="0.85"/>',
    ]
    if off_band:
        anchor = band_p1 if mid < low else band_p2
        p1, p2 = sorted((anchor, mid_pct))
        svg_parts.append(
            f'<line x1="{p1:.3f}" y1="{TRACK_Y}" x2="{p2:.3f}" y2="{TRACK_Y}" '
            f'stroke="var(--warn)" stroke-width="1" stroke-dasharray="2 2" '
            f'vector-effect="non-scaling-stroke" opacity="0.8"/>'
        )
    svg_parts.append(
        # We intentionally avoid using `r` on the dot — under
        # `preserveAspectRatio="none"` it would render as an ellipse.
        # Two thin rects centered at (mid_pct, TRACK_Y) read as a dot
        # at any aspect ratio, but the visual would lose the round
        # affordance. Instead, the dot is a CSS-positioned HTML
        # element (see below) so it stays circular at any container
        # width.
        ""
    )
    svg_parts.append("</svg>")

    # HTML overlay for the dot (true circle at any width) plus the two
    # numeric labels below the track.
    low_label = fmt_money(low)
    high_label = fmt_money(high)

    # Decide label layout. When the band edges land too close together on
    # the shared scale, fold the labels into one centered range label.
    LABEL_GAP_PCT = 18.0  # heuristic — leaves room for two ~7-char numbers
    if band_w_pct < LABEL_GAP_PCT:
        center_pct = (band_p1 + band_p2) / 2
        label_html = (
            f'<span class="forecast-band-label" '
            f'style="left:{center_pct:.3f}%">{low_label}–{high_label}</span>'
        )
    else:
        label_html = (
            f'<span class="forecast-band-label" '
            f'style="left:{band_p1:.3f}%">{low_label}</span>'
            f'<span class="forecast-band-label" '
            f'style="left:{band_p2:.3f}%">{high_label}</span>'
        )

    dot_cls = "forecast-dot" + (" is-warn" if off_band else "")
    return (
        '<div class="forecast-band">'
        + "".join(svg_parts)
        + f'<span class="{dot_cls}" style="left:{mid_pct:.3f}%"></span>'
        + f'<div class="forecast-band-labels">{label_html}</div>'
        + "</div>"
    )


def render_forecast(f: Forecast | None) -> str:
    sec_id = "forecast"
    if f is None:
        return ""

    # Shared domain across both cards so the dots are directly comparable.
    # We use the band edges + both projection points as anchors and pad
    # 10% on each side; we only force-include 0 if the data already sits
    # near it (otherwise we'd waste most of the strip on empty headroom).
    points = (f.linear_low, f.linear_high, f.linear_total, f.ewma_total)
    vmin = min(points)
    vmax = max(points)
    if vmin > 0 and vmin < (vmax - vmin) * 0.5:
        # Data is close enough to 0 that the reader will want it on-axis.
        vmin = 0.0
    span = (vmax - vmin) or 1.0
    pad = span * 0.10
    vmin -= pad
    vmax += pad

    linear_off = f.linear_total < f.linear_low or f.linear_total > f.linear_high
    ewma_off = f.ewma_total < f.linear_low or f.ewma_total > f.linear_high

    delta = f.ewma_total - f.linear_total
    delta_pct = (delta / f.linear_total) * 100 if f.linear_total else 0
    delta_cls = "delta-bad" if delta >= 0 else "delta-ok"
    delta_arr = "↑" if delta >= 0 else "↓"
    delta_sign = "+" if delta > 0 else ""

    off_chip = (
        '<span class="off-band-chip" title="EWMA falls outside the ±1σ '
        'linear band — recent days diverge sharply from the window average.">'
        "off-band</span>"
        if ewma_off
        else ""
    )

    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Forecast', f'based on {f.days_analyzed} days · projected through next {f.days_remaining} days')}"
        f'<div class="sec-body">'
        f'<div class="cards forecast-cards">'
        # Linear card
        f'<div class="card forecast-card">'
        f'<div class="forecast-card-head">'
        f'<div class="stat-label">Linear projection</div>'
        f'<div class="forecast-tag">mean × days</div>'
        f"</div>"
        f'<div class="stat-value">{fmt_money(f.linear_total)}</div>'
        f"{_forecast_band(f.linear_low, f.linear_high, f.linear_total, vmin, vmax, off_band=linear_off)}"
        f'<div class="forecast-sub">'
        f'<span class="forecast-sub-key">±1σ</span> '
        f"{fmt_money(f.linear_low)} – {fmt_money(f.linear_high)}"
        f"</div>"
        f"</div>"
        # EWMA card
        f'<div class="card forecast-card">'
        f'<div class="forecast-card-head">'
        f'<div class="stat-label">EWMA · recency-weighted</div>'
        f'<div class="forecast-tag">α = 0.3</div>'
        f"</div>"
        f'<div class="stat-value">{fmt_money(f.ewma_total)}{off_chip}</div>'
        f"{_forecast_band(f.linear_low, f.linear_high, f.ewma_total, vmin, vmax, accent=True, off_band=ewma_off)}"
        f'<div class="forecast-sub">'
        f'<span class="forecast-sub-key">daily</span> '
        f"{fmt_money(f.daily_mean)}"
        f'&nbsp;&nbsp;<span class="forecast-sub-key">σ</span> {fmt_money(f.daily_stdev)}'
        f'<span class="delta {delta_cls} forecast-delta">'
        f"{delta_arr}&nbsp;{delta_sign}{delta_pct:.1f}% vs linear</span>"
        f"</div>"
        f"</div>"
        f"</div></div></section>"
    )


# 10. Evidence ----------------------------------------------------------------


def render_evidence(rows: list[EvidenceRow], quality: QualityScore | None = None) -> str:
    sec_id = "evidence"
    if not rows and quality is None:
        return ""
    quality_html = ""
    if quality is not None:
        signals = "".join(
            f'<li class="quality-signal quality-signal-{esc(signal.tone)}">'
            f'<span class="quality-signal-label">{esc(signal.label)}</span>'
            f'<span class="quality-signal-status">{esc(signal.status)}</span>'
            f'<span class="quality-signal-note">{esc(signal.note)}</span>'
            f"</li>"
            for signal in quality.signals
        )
        quality_html = (
            f'<div class="quality-panel quality-panel-{esc(quality.tone)}">'
            f'<div class="quality-score">'
            f'<span class="quality-number">{quality.score}</span>'
            f'<span class="quality-denom">/100</span>'
            f"</div>"
            f'<div class="quality-copy">'
            f'<h3 class="panel-title">Evidence quality · {esc(quality.grade)}</h3>'
            f'<ul class="quality-list">{signals}</ul>'
            f"</div></div>"
        )
    body = "".join(
        f"<tr>"
        f'<td class="evidence-dim">{esc(r.label)}</td>'
        f"<td>{status_word(r.status)}</td>"
        f'<td class="mute evidence-note">{esc(r.note)}</td>'
        f"</tr>"
        for r in rows
    )
    return (
        f'<section class="sec" id="{sec_id}">'
        f"{section_head(sec_id, 'Evidence', 'how trustworthy each number is')}"
        f'<div class="sec-body">'
        f"{quality_html}"
        f'<div class="panel pad-0">'
        f'<table class="data evidence"><tbody>{body}</tbody></table>'
        f"</div></div></section>"
    )


# 11. Footer ------------------------------------------------------------------


def render_footer(d: Dashboard) -> str:
    # Cosmetic "signed receipt" short hash. The engineer can swap in a real
    # content hash if desired.
    h = hashlib.sha256(
        (
            json.dumps(d.totals, default=lambda o: o.__dict__, sort_keys=True) + d.generated_at
        ).encode()
    ).hexdigest()[:8]
    return (
        f'<footer class="page-foot">'
        f'<div class="page-foot-row">'
        f'<div class="page-foot-left">'
        f'<span class="page-foot-fact">No external resources</span>'
        f'<span class="page-foot-sep">·</span>'
        f'<span class="page-foot-fact">No telemetry</span>'
        f'<span class="page-foot-sep">·</span>'
        f'<span class="page-foot-fact">Inline controls only</span>'
        f'<span class="page-foot-sep">·</span>'
        f'<span class="page-foot-fact">Parsed locally from your AI coding logs</span>'
        f"</div>"
        f'<div class="page-foot-right">'
        f'<span><span class="mute">caliper</span>&nbsp;&nbsp;'
        f"v{esc(d.caliper.version)}&nbsp;&nbsp;"
        f'<span class="mute">schema</span>&nbsp;{d.caliper.schema_version}</span>'
        f"<span>{esc(d.generated_at)}</span>"
        f'<span class="page-foot-checksum">sha&nbsp;{h}</span>'
        f"</div></div></footer>"
    )


# ===========================================================================
# Public entrypoint
# ===========================================================================

# Inline stylesheet. Source of truth on disk is `styles.css` next to this
# module; the two are kept byte-identical by `tests/test_handoff_styles.py`.
# Inlining preserves the offline invariant: no external resources, no file
# I/O at render time, and ``pip install caliper-ai`` ships the styles even
# when ``styles.css`` is not bundled as package_data.
INLINE_SCRIPT = r"""
(() => {
  const toNumber = (cell) => {
    const raw = cell ? (cell.dataset.value || cell.textContent || "") : "";
    const cleaned = raw.replace(/[$,%\s]/g, "").replace(/[KMB]$/i, "");
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : 0;
  };

  document.querySelectorAll(".data-sortable th[data-sort]").forEach((th) => {
    th.tabIndex = 0;
    th.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        th.click();
      }
    });
    th.addEventListener("click", () => {
      const table = th.closest("table");
      const tbody = table ? table.tBodies[0] : null;
      if (!table || !tbody) return;
      const headers = Array.from(th.parentElement.children);
      const index = headers.indexOf(th);
      const numeric = th.dataset.sort === "number";
      const current = th.getAttribute("aria-sort") === "ascending" ? "ascending" : "descending";
      const next = current === "ascending" ? "descending" : "ascending";
      headers.forEach((header) => {
        header.removeAttribute("aria-sort");
        const glyph = header.querySelector(".sort-glyph");
        if (glyph) glyph.textContent = "";
      });
      th.setAttribute("aria-sort", next);
      const glyph = th.querySelector(".sort-glyph");
      if (glyph) glyph.textContent = next === "ascending" ? "↑" : "↓";
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {
        const av = numeric ? toNumber(a.cells[index]) : (a.cells[index]?.textContent || "");
        const bv = numeric ? toNumber(b.cells[index]) : (b.cells[index]?.textContent || "");
        const result = numeric ? av - bv : String(av).localeCompare(String(bv));
        return next === "ascending" ? result : -result;
      });
      rows.forEach((row) => tbody.appendChild(row));
    });
  });

  const filterButtons = Array.from(document.querySelectorAll(".mix-filter"));
  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.mixFilter || "all";
      filterButtons.forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      document.querySelectorAll("[data-mix-panel]").forEach((panel) => {
        const show = filter === "all" || panel.dataset.mixPanel === filter;
        panel.hidden = !show;
      });
    });
  });

  const navLinks = Array.from(document.querySelectorAll(".dash-nav-link[href^='#']"));
  const sections = navLinks
    .map((link) => document.getElementById(link.getAttribute("href").slice(1)))
    .filter(Boolean);
  if ("IntersectionObserver" in window && sections.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        navLinks.forEach((link) => {
          link.classList.toggle("is-current", link.getAttribute("href") === `#${entry.target.id}`);
        });
      });
    }, { rootMargin: "-35% 0px -60% 0px", threshold: 0.01 });
    sections.forEach((section) => observer.observe(section));
  }
})();
"""

INLINE_STYLES = r"""
/* ============================================================================
   Caliper Dashboard — visual system v2 (premium)
   System-stack typography honed with OpenType features.
   Strict 8pt rhythm. Hairline borders. Audit-receipt elegance.
   ========================================================================== */

:root {
  /* — Surface (dark) — slightly warmer, deeper for premium feel */
  --bg:           #0a0d12;
  --bg-2:         #0d1117;
  --panel:        #12161e;
  --panel-2:      #161b24;
  --panel-hover:  #1a2029;
  --border:       #1f242e;
  --border-strong:#2a313c;
  --grid:         rgba(255,255,255,0.045);
  --bar-ghost:    rgba(255,255,255,0.022);
  --hairline:     rgba(255,255,255,0.06);
  /* Divider tone used inside coloured tracks (stacked bar, etc.) — must read
     as a line on top of any tool-category fill, in any theme. */
  --seg-divider:  rgba(0,0,0,0.32);

  /* Ink — --ghost bumped from #545b67 (3.1:1) to clear WCAG AA on small text. */
  --ink:    #e8eaef;
  --ink-2:  #c4c9d3;
  --mute:   #858d9b;
  --ghost:  #6c7383;

  /* Accent — same #7cc4ff but with broader tints */
  --accent:        #7cc4ff;
  --accent-strong: #54aef0;
  --accent-soft:   #b3dcff;
  --accent-tint:   rgba(124,196,255,0.10);
  --accent-tint-2: rgba(124,196,255,0.18);
  --accent-tint-3: rgba(124,196,255,0.06);

  /* Status — desaturated, audit-grade */
  --ok:   #7be092;
  --warn: #f5c971;
  --bad:  #f08585;

  --ok-tint:   rgba(123,224,146,0.10);
  --warn-tint: rgba(245,201,113,0.10);
  --bad-tint:  rgba(240,133,133,0.10);

  /* Per-card accent hairlines — one source of truth, picked by [data-accent] */
  --card-rail-cost:     var(--accent-tint-2);
  --card-rail-cache:    rgba(123,224,146,0.22);
  --card-rail-tokens:   var(--accent-tint-2);
  --card-rail-sessions: rgba(167,139,250,0.22);

  /* Tool categories */
  --explore:  #7cc4ff;
  --execute:  #a78bfa;
  --diagnose: #f5c971;
  --mixed:    #858d9b;

  /* — Type — system stack tuned with OpenType features.
     Engineer note: this is a target. Geist/Inter Tight/SF Pro substitute well. */
  --font:  -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
           "Segoe UI Variable", "Segoe UI", system-ui, Roboto, "Helvetica Neue",
           sans-serif;
  --mono:  ui-monospace, "SF Mono", "JetBrains Mono", "Fira Code",
           Menlo, Consolas, monospace;

  /* OpenType */
  --otf-text:    "cv11" 1, "ss01" 1, "cv02" 1, "kern" 1, "calt" 1, "liga" 1;
  --otf-num:     "tnum" 1, "lnum" 1, "ss03" 1;

  /* Strict 8pt rhythm */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px;
  --s6: 32px; --s7: 48px; --s8: 64px; --s9: 96px;

  /* Numeric type scale — one ladder for every hero number on the page.
     xl  → primary KPI cards
     lg  → hero headlines (activity total)
     md  → recap stat tiles
     sm  → heatmap stat strip, table strong cell  */
  --num-xl: 32px;
  --num-lg: 26px;
  --num-md: 20px;
  --num-sm: 15px;

  /* Radii — small, audit-doc feeling */
  --r-sm: 3px; --r-md: 5px; --r-lg: 7px;

  /* Density (8pt-aligned) */
  --row-pad-y: 12px;
  --row-pad-x: 16px;
}

[data-density="compact"] {
  --row-pad-y: 8px;
  --row-pad-x: 12px;
}

/* — Light theme — Stripe-receipt clean */
[data-theme="light"] {
  --bg:           #f6f7f9;
  --bg-2:         #fbfbfd;
  --panel:        #ffffff;
  --panel-2:      #fafbfc;
  --panel-hover:  #f3f5f8;
  --border:       #e6e8ec;
  --border-strong:#cfd3da;
  --grid:         rgba(0,0,0,0.045);
  --bar-ghost:    rgba(0,0,0,0.025);
  --hairline:     rgba(0,0,0,0.07);
  --seg-divider:  rgba(255,255,255,0.55);

  --ink:   #0e1116;
  --ink-2: #353a44;
  --mute:  #5a626e;
  --ghost: #6d7585;

  --accent:        #2563eb;
  --accent-strong: #1d4ed8;
  --accent-soft:   #93b8ff;
  --accent-tint:   rgba(37,99,235,0.08);
  --accent-tint-2: rgba(37,99,235,0.16);
  --accent-tint-3: rgba(37,99,235,0.04);

  --ok:   #16a34a;
  --warn: #b45309;
  --bad:  #b91c1c;

  --ok-tint:   rgba(22,163,74,0.10);
  --warn-tint: rgba(180,83,9,0.10);
  --bad-tint:  rgba(185,28,28,0.10);

  --card-rail-cost:     var(--accent-tint-2);
  --card-rail-cache:    rgba(22,163,74,0.28);
  --card-rail-tokens:   var(--accent-tint-2);
  --card-rail-sessions: rgba(124,58,237,0.28);

  --explore:  #2563eb;
  --execute:  #7c3aed;
  --diagnose: #b45309;
  --mixed:    #6b7280;
}

/* — Print theme (preview) */
[data-theme="print"] {
  --bg:           #ffffff;
  --bg-2:         #ffffff;
  --panel:        #ffffff;
  --panel-2:      #ffffff;
  --panel-hover:  #ffffff;
  --border:       #cccccc;
  --border-strong:#888888;
  --grid:         rgba(0,0,0,0.10);
  --bar-ghost:    rgba(0,0,0,0.04);
  --hairline:     rgba(0,0,0,0.18);
  --seg-divider:  rgba(255,255,255,0.65);

  --ink:   #000000;
  --ink-2: #1a1a1a;
  --mute:  #4a4a4a;
  --ghost: #6a6a6a;

  --accent:        #0050b3;
  --accent-strong: #003a82;
  --accent-soft:   #2a72c2;
  --accent-tint:   rgba(0,80,179,0.08);
  --accent-tint-2: rgba(0,80,179,0.15);

  --ok:   #0050b3;
  --warn: #0050b3;
  --warn-tint: rgba(0,80,179,0.08);
  --bad:  #b00020;

  --card-rail-cost:     var(--accent-tint-2);
  --card-rail-cache:    rgba(0,80,179,0.25);
  --card-rail-tokens:   var(--accent-tint-2);
  --card-rail-sessions: rgba(0,80,179,0.25);

  --explore:  #0050b3;
  --execute:  #6a4cb8;
  --diagnose: #8a5a00;
  --mixed:    #4a4a4a;
}

/* — Base ----------------------------------------------------------------- */

* { box-sizing: border-box; }

html { background: var(--bg); }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.5 var(--font);
  font-feature-settings: var(--otf-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-variant-numeric: tabular-nums lining-nums;
  text-rendering: optimizeLegibility;
  min-height: 100vh;
}

/* Frame the "page" so it feels like a discrete document */
[data-theme="print"] body { background: #eceef2; }

.page-wrap {
  min-height: 100vh;
  background:
    radial-gradient(1200px 600px at 50% -200px, rgba(124,196,255,0.025), transparent 70%),
    var(--bg);
}
[data-theme="light"] .page-wrap {
  background:
    radial-gradient(1200px 600px at 50% -200px, rgba(37,99,235,0.025), transparent 70%),
    var(--bg);
}
[data-theme="print"] .page-wrap { background: #eceef2; padding: 32px 0 64px; }

.page {
  max-width: 1180px;
  margin: 0 auto;
  /* 48 top / 32 sides / 48 bottom — sides bumped from 24 to breathe at 1180px */
  padding: var(--s7) var(--s6) var(--s7);
  position: relative;
  min-width: 0;
}
[data-theme="print"] .page {
  background: #fff;
  border: 1px solid #d4d4d4;
  box-shadow:
    0 1px 0 rgba(0,0,0,0.02),
    0 12px 40px rgba(0,0,0,0.08);
  padding: 72px 72px 56px;
  max-width: 920px;
}

code, .mono {
  font-family: var(--mono);
  font-feature-settings: "zero" 1, "ss02" 1, "calt" 1;
}
code { color: var(--accent); font-size: 0.92em; }
.mute { color: var(--mute); }
.strong { font-weight: 600; color: var(--ink); }

::selection { background: var(--accent-tint-2); color: var(--ink); }

/* — Wordmark + Page header --------------------------------------------- */

.page-head {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: var(--s5);
  padding-bottom: var(--s5);
  margin-bottom: var(--s7);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.page-head::after {
  /* premium "double rule" — a hairline under the main rule */
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: -4px;
  border-bottom: 1px solid var(--hairline);
}

.page-head-left {
  display: flex; flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.wordmark {
  display: inline-flex; align-items: center;
  gap: 12px;
  color: var(--ink);
  letter-spacing: -0.02em;
}
.wordmark-text {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1;
}
.wordmark-version {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--mute);
  margin-left: 4px;
  letter-spacing: 0;
  font-feature-settings: "tnum" 1;
}
.page-head-tagline {
  font-size: 12px;
  color: var(--mute);
  letter-spacing: 0.01em;
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.page-head-right {
  text-align: right;
  display: flex; flex-direction: column; gap: 8px;
  align-items: flex-end;
  min-width: 0;
}
.window-badge {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 6px 12px 6px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
  color: var(--ink-2);
  white-space: nowrap;
}
.window-badge-label {
  font-weight: 600; color: var(--ink);
  letter-spacing: 0.01em;
}
.window-badge-sep { color: var(--ghost); }
.window-badge-range {
  font-family: var(--mono);
  color: var(--mute);
  font-size: 11.5px;
  letter-spacing: 0.01em;
}

.page-meta {
  font-size: 11.5px;
  color: var(--mute);
  font-family: var(--mono);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  letter-spacing: 0.01em;
}
.dot-sep { color: var(--ghost); opacity: 0.7; }
.meta-offline {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--ink-2);
}
.meta-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-tint);
}

/* Receipt-style serial line, sits over the page-head's right side */
.serial {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--ghost);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  overflow-wrap: anywhere;
}

/* — Banner -------------------------------------------------------------- */

.banner {
  display: flex; align-items: flex-start; gap: var(--s3);
  margin-bottom: var(--s6);
  /* Banner-bar is absolute-positioned at left:0; the left content offset is
     absorbed by .banner-label's margin so the bar reads as a real left rail. */
  padding: var(--s3) var(--s4) var(--s3) 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
  overflow: hidden;
  position: relative;
}
.banner code { font-size: 12px; }
.banner-bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px;
}
.banner-warn .banner-bar { background: var(--warn); }
.banner-crit .banner-bar { background: var(--bad); }
.banner-label {
  margin-left: var(--s4);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  font-family: var(--mono);
  flex-shrink: 0;
  margin-top: 1px;
}
.banner-warn .banner-label { color: var(--warn); }
.banner-crit .banner-label { color: var(--bad); }
.banner-text { padding-right: var(--s2); }

/* — Section ------------------------------------------------------------- */

.sec {
  margin-top: var(--s7);
  position: relative;
}
.sec:first-of-type { margin-top: 0; }

.sec-head {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: var(--s4);
  gap: var(--s5);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--hairline);
}
.sec-head-left {
  display: inline-flex;
  align-items: baseline;
  gap: var(--s3);
  flex-wrap: nowrap;
  white-space: nowrap;
}
.sec-num {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ghost);
  letter-spacing: 0.18em;
  font-weight: 500;
  white-space: nowrap;
}
.sec-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  display: inline;
}
.sec-head.sec-head--bare {
  border-bottom: 0;
  padding-bottom: 0;
  margin-bottom: var(--s3);
}
.sec-hint {
  font-size: 12px;
  color: var(--mute);
  font-family: var(--mono);
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.sec-foot {
  margin-top: var(--s3);
  font-size: 12px;
  color: var(--mute);
  font-style: italic;
}
.sec-body > * + * { margin-top: var(--s4); }

/* — Panel --------------------------------------------------------------- */

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--s5);
  /* `overflow: visible` so absolutely-positioned tooltips (data-tip) can
     escape the panel. The rounded corners still look right because
     internal tables clamp their first/last-row backgrounds to the radius
     (see .data thead th:first-child / :last-child below). */
  overflow: visible;
  min-width: 0;
}
.panel.pad-0 {
  padding: 0;
  overflow: auto;
}
.panel-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--s4);
  margin-bottom: var(--s4);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--hairline);
}
.panel-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.005em;
}
.empty-panel {
  color: var(--mute);
  font-size: 13px;
  padding: var(--s5);
}
.empty-panel code { color: var(--accent); }

/* — Summary cards ------------------------------------------------------- */

.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s3);
}
.forecast-cards { grid-template-columns: repeat(2, 1fr); gap: var(--s3); }

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--s4) var(--s5) var(--s4);
  position: relative;
  /* overflow: visible so hover tooltips can escape the card */
  overflow: visible;
  transition: border-color 120ms ease-out, transform 120ms ease-out;
}
.card:hover { border-color: var(--border-strong); }
.card.stat {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.card.stat::before {
  /* Per-card semantic hairline. Color resolves from --card-rail-* via the
     [data-accent] attribute. */
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 1px;
  background: linear-gradient(
    to right,
    transparent,
    var(--card-rail, var(--accent-tint-2)) 12%,
    var(--card-rail, var(--accent-tint-2)) 88%,
    transparent
  );
}
.card.stat[data-accent="cost"]     { --card-rail: var(--card-rail-cost); }
.card.stat[data-accent="cache"]    { --card-rail: var(--card-rail-cache); }
.card.stat[data-accent="tokens"]   { --card-rail: var(--card-rail-tokens); }
.card.stat[data-accent="sessions"] { --card-rail: var(--card-rail-sessions); }

.stat-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--mute);
}
.stat-value {
  font-size: var(--num-xl);
  font-weight: 600;
  line-height: 1.04;
  letter-spacing: -0.025em;
  color: var(--ink);
  margin-top: var(--s1);
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: var(--otf-num);
}
.stat-empty { color: var(--ghost); font-weight: 500; letter-spacing: 0; }
.stat-sub {
  margin-top: var(--s1);
  font-size: 11.5px;
  color: var(--mute);
  font-family: var(--mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.01em;
}
.stat-foot {
  margin-top: auto;
  padding-top: var(--s3);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}

/* sparkline polish */
.spark { display: block; }
.spark-empty { color: var(--ghost); font-size: 14px; }

/* Delta — refined chip */
.delta {
  font-size: 10.5px;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  padding: 3px 7px;
  border-radius: 3px;
  white-space: nowrap;
  letter-spacing: 0.02em;
}
.delta-ok  { color: var(--ok);   background: var(--ok-tint); }
.delta-bad { color: var(--bad);  background: var(--bad-tint); }
.delta-flat { color: var(--ghost); }

/* — Rolling usage windows --------------------------------------------- */

.usage-window-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}
.usage-window-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--s4) var(--s5);
  min-width: 0;
  overflow: visible;
  position: relative;
}
.usage-window-card::before {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--accent-tint-2), transparent);
}
.usage-window-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
  min-width: 0;
}
.usage-window-label {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
  white-space: nowrap;
}
.usage-window-range {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--ghost);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.usage-window-value {
  margin-top: var(--s3);
  font-size: 28px;
  font-weight: 650;
  line-height: 1.05;
  font-variant-numeric: tabular-nums lining-nums;
  font-feature-settings: var(--otf-num);
  color: var(--ink);
}
.usage-window-meta {
  margin-top: var(--s1);
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--mute);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.usage-window-stats {
  display: flex;
  gap: var(--s3);
  margin-top: var(--s3);
  color: var(--ink-2);
  font-family: var(--mono);
  font-size: 11px;
  flex-wrap: wrap;
}
.usage-window-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  margin-top: var(--s4);
  padding-top: var(--s3);
  border-top: 1px solid var(--hairline);
}

/* — Impact cards ------------------------------------------------------- */

.impact-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--s3);
}
.impact-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border-strong);
  border-radius: var(--r-md);
  padding: var(--s4);
  min-width: 0;
}
.impact-card-good { border-left-color: var(--ok); }
.impact-card-warn { border-left-color: var(--warn); }
.impact-card-critical { border-left-color: var(--bad); }
.impact-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--mute);
}
.impact-value {
  margin-top: var(--s2);
  color: var(--ink);
  font-weight: 650;
  font-size: 19px;
  line-height: 1.15;
  overflow-wrap: anywhere;
}
.impact-detail {
  margin-top: var(--s2);
  color: var(--mute);
  font-size: 12px;
  line-height: 1.45;
}

/* — Cost chart ---------------------------------------------------------- */

.chart-panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  /* 24 top / 24 sides / 16 bottom — sides bumped 2px to land on the 8pt grid */
  padding: var(--s5) var(--s5) var(--s4);
}
.chart {
  width: 100%;
  display: block;
  height: 240px;
  font-family: var(--mono);
  overflow: visible;
}
.shape-strip {
  margin-top: var(--s3);
  display: flex;
  align-items: center;
  gap: var(--s1);
  /* Aligned to the chart's PAD_L=60 / PAD_R=24 plus the chart-panel padding.
     Math: panel pad 24 + chart pad 60 = 84 inside, but the chart fills the
     panel content box, so strip alignment uses 60 / 24 to land under the bars. */
  padding-left: 60px;
  padding-right: 24px;
}
.shape-cell {
  flex: 1;
  height: 10px;
  border-radius: 2px;
  background: var(--mixed);
  opacity: 0.85;
}
.shape-explore  { background: var(--explore); }
.shape-execute  { background: var(--execute); }
.shape-diagnose { background: var(--diagnose); }
.shape-mixed    { background: var(--mixed); opacity: 0.5; }
.shape-strip-row {
  display: flex; align-items: center;
  gap: var(--s4);
  margin-top: var(--s2);
  padding-left: 60px;
  padding-right: 24px;
}
.shape-strip-row .label {
  font-size: 11px;
  color: var(--mute);
  font-family: var(--mono);
  letter-spacing: 0.02em;
}
.shape-strip-legend {
  display: inline-flex;
  gap: var(--s4);
  font-size: 11px;
  color: var(--mute);
  font-family: var(--mono);
  margin-left: auto;
  letter-spacing: 0.01em;
}
.shape-strip-legend > span {
  display: inline-flex; align-items: center; gap: 6px;
}
.shape-strip-legend .dot {
  width: 8px; height: 8px; border-radius: 2px; display: inline-block;
}
.shape-strip-legend .leg-explore .dot  { background: var(--explore); }
.shape-strip-legend .leg-execute .dot  { background: var(--execute); }
.shape-strip-legend .leg-diagnose .dot { background: var(--diagnose); }
.shape-strip-legend .leg-mixed .dot    { background: var(--mixed); opacity: 0.55; }

/* — Two-col session shape ---------------------------------------------- */

.shape-grid {
  display: grid;
  grid-template-columns: 1.35fr 1fr;
  gap: var(--s3);
}

.legend {
  display: inline-flex; gap: var(--s4); flex-wrap: wrap;
}
.legend-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--mute);
  font-family: var(--mono);
  letter-spacing: 0.01em;
}
.legend-chip .dot {
  width: 8px; height: 8px; border-radius: 50%;
  display: inline-block;
}

/* Meter row */
.meters { display: flex; flex-direction: column; gap: var(--s2); }
.meter-row {
  display: grid;
  grid-template-columns: 100px 1fr 56px;
  align-items: center;
  gap: var(--s4);
}
.meter-name {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px;
  color: var(--ink);
  font-weight: 500;
}
.meter-name .dot {
  width: 7px; height: 7px; border-radius: 50%;
  display: inline-block;
}
.meter-track {
  background: var(--bar-ghost);
  height: 10px;
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}
.meter-track > span {
  display: block;
  height: 100%;
  border-radius: 2px;
}
.meter-count {
  text-align: right;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--mute);
  font-weight: 500;
}

/* Stacked horizontal bar */
.stacked {
  display: flex; height: 28px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--bar-ghost);
  margin: var(--s2) 0 var(--s4);
}
.stacked-seg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(0,0,0,0.78);
  font-size: 11px;
  font-weight: 600;
  font-family: var(--mono);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: clip;
  /* Theme-aware divider: dark seam on coloured fills in dark mode, light
     seam in light/print. Was `var(--bg)` which gave invisible seams on light. */
  border-right: 1px solid var(--seg-divider);
}
.stacked-seg:last-child { border-right: 0; }
[data-theme="light"] .stacked-seg, [data-theme="print"] .stacked-seg { color: #fff; }
.seg-explore  { background: var(--explore); }
.seg-execute  { background: var(--execute); }
.seg-diagnose { background: var(--diagnose); }
.seg-mixed    { background: var(--mixed); }

/* Cat table */
.tight { width: 100%; border-collapse: collapse; }
.tight td {
  padding: var(--s2) 0;
  font-size: 13px;
  border-bottom: 1px solid var(--hairline);
}
.tight tr:last-child td { border-bottom: 0; }
.tight .num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
.tight .dot-inline {
  width: 7px; height: 7px; border-radius: 50%;
  display: inline-block;
  margin-right: 10px;
  vertical-align: middle;
}
.cat-label { color: var(--ink); }

/* — Data tables --------------------------------------------------------- */

.data {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data thead th {
  text-align: left;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--mute);
  padding: 14px var(--row-pad-x);
  border-bottom: 1px solid var(--border);
  background: var(--panel-2);
  white-space: nowrap;
}
.data thead th:first-child {
  padding-left: 20px;
  /* Round the upper-left to match the panel's border-radius so the
     thead's --panel-2 fill doesn't square off the corner. */
  border-top-left-radius: var(--r-md);
}
.data thead th:last-child {
  padding-right: 20px;
  border-top-right-radius: var(--r-md);
}

.data tbody td {
  padding: var(--row-pad-y) var(--row-pad-x);
  border-bottom: 1px solid var(--hairline);
  vertical-align: middle;
  color: var(--ink-2);
}
.data tbody td:first-child { padding-left: 20px; }
.data tbody td:last-child { padding-right: 20px; }
.data tbody tr:last-child td { border-bottom: 0; }
.data tbody tr { transition: background-color 80ms ease-out; }
.data tbody tr:hover { background: var(--panel-hover); }

.data .num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
.data .strong { color: var(--ink); font-weight: 600; font-size: 13.5px; }

.sort-glyph {
  color: var(--accent);
  display: inline-block;
  font-size: 12px;
  line-height: 1;
  margin-left: 4px;
  transform: translateY(-1px);
}

.th-cost { width: 110px; }
.th-cache { width: 80px; }
.th-tools { width: 280px; }
.th-vendor { width: 96px; }

.vendor-badge {
  display: inline-block;
  padding: 3px 8px;
  font-size: 10.5px;
  font-family: var(--mono);
  font-weight: 600;
  letter-spacing: 0.04em;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  color: var(--mute);
  background: var(--panel-2);
}

.proj-name {
  font-weight: 600;
  color: var(--ink);
  font-size: 14px;
  letter-spacing: -0.005em;
}
.proj-path {
  font-size: 11.5px;
  margin-top: 3px;
  color: var(--mute);
}

/* Inline-bar (share column) */
.inline-bar {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}
.inline-bar-track {
  width: 72px;
  height: 6px;
  background: var(--bar-ghost);
  border-radius: 2px;
  overflow: hidden;
  display: inline-block;
}
.inline-bar-track > span {
  display: block;
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}
.inline-bar-label {
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--mute);
  min-width: 32px;
  text-align: right;
}

/* Mini bars (Projects → top tools) */
.col-tools {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-top: 9px !important;
  padding-bottom: 9px !important;
}
.mini-bar {
  display: grid;
  grid-template-columns: 64px 1fr;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
}
.mini-bar-name {
  font-family: var(--mono);
  color: var(--mute);
  font-size: 11px;
}
.mini-bar-track {
  height: 5px;
  background: var(--bar-ghost);
  border-radius: 2px;
  overflow: hidden;
}
.mini-bar-track > span {
  display: block;
  height: 100%;
  border-radius: 2px;
}

/* — Insights ----------------------------------------------------------- */

.insight-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.insight {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--s4) var(--s4) var(--s4) var(--s5);
  position: relative;
  /* overflow visible so impact-chip / severity pill tooltips can escape */
  overflow: visible;
  transition: background-color 100ms ease-out;
}
.insight:hover { background: var(--panel-hover); }
.insight-rail {
  /* Inset so the rail floats inside the rounded corner instead of clipping
     it. The 8px inset matches the 5px corner radius + 3px breathing room. */
  position: absolute;
  left: 8px; top: 12px; bottom: 12px;
  width: 2px;
  border-radius: 2px;
}
.insight-info     .insight-rail { background: var(--accent); }
.insight-warn     .insight-rail { background: var(--warn); }
.insight-critical .insight-rail { background: var(--bad); }

.insight-head {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 6px;
}
.insight-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: -0.005em;
}
.insight-detail {
  margin: 0;
  font-size: 13px;
  color: var(--mute);
  line-height: 1.55;
  max-width: 76ch;
  text-wrap: pretty;
}

.sev {
  display: inline-block;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  padding: 3px 7px;
  border-radius: 3px;
  font-family: var(--mono);
}
.sev-info     { color: var(--accent); background: var(--accent-tint); }
.sev-warn     { color: var(--warn);   background: var(--warn-tint); }
.sev-critical { color: var(--bad);    background: var(--bad-tint); }

.impact-chip {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--ink-2);
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 3px;
  background: var(--panel-2);
  white-space: nowrap;
  letter-spacing: 0.01em;
}
.insight-critical .impact-chip {
  border-color: rgba(240,133,133,0.35);
  color: var(--bad);
  background: var(--bad-tint);
}
.insight-warn .impact-chip {
  border-color: rgba(245,201,113,0.32);
  color: var(--warn);
  background: var(--warn-tint);
}
.insight-info .impact-chip {
  border-color: var(--accent-tint-2);
  color: var(--accent);
  background: var(--accent-tint);
}

/* — Forecast ----------------------------------------------------------- */

.forecast-card {
  padding: var(--s5) var(--s5) var(--s4);
}
.forecast-card-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: var(--s1);
}
.forecast-card .stat-label { margin-bottom: 0; }
.forecast-tag {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--mute);
  letter-spacing: 0.04em;
}
.forecast-card .stat-value {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: var(--num-lg);
  margin: var(--s1) 0 var(--s3);
}
.forecast-band {
  position: relative;
  display: block;
  margin: var(--s3) 0 var(--s2);
  height: 38px;
}
.forecast-band-svg {
  display: block;
  width: 100%;
  height: 22px;
}
.forecast-dot {
  position: absolute;
  top: 11px;
  width: 9px;
  height: 9px;
  margin-top: -4.5px;
  margin-left: -4.5px;
  border-radius: 50%;
  background: var(--accent-strong);
  box-shadow:
    inset 0 0 0 2px var(--accent-strong),
    inset 0 0 0 3.5px var(--panel),
    0 0 0 2px color-mix(in srgb, var(--panel) 65%, transparent);
  z-index: 1;
}
.forecast-dot.is-warn {
  background: var(--warn);
  box-shadow:
    inset 0 0 0 2px var(--warn),
    inset 0 0 0 3.5px var(--panel),
    0 0 0 2px color-mix(in srgb, var(--panel) 65%, transparent);
}
.forecast-band-labels {
  position: absolute;
  left: 0; right: 0;
  top: 22px;
  height: 14px;
  pointer-events: none;
}
.forecast-band-label {
  position: absolute;
  transform: translateX(-50%);
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--mute);
  white-space: nowrap;
  /* Edge-aware clamp so labels at 0% / 100% don't get cropped. */
  max-width: 50%;
}
.forecast-band-label:where([style*="left:0"]),
.forecast-band-label:where([style*="left:0.000%"]) {
  transform: none;
}
.forecast-band-label:where([style*="left:100"]) {
  transform: translateX(-100%);
}
.forecast-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
  color: var(--mute);
  font-family: var(--mono);
  letter-spacing: 0.01em;
}
.forecast-sub-key {
  color: var(--mute);
  opacity: 0.75;
  letter-spacing: 0.04em;
  text-transform: lowercase;
  margin-right: 2px;
}
.forecast-delta { margin-left: auto; }
.off-band-chip {
  align-self: center;
  font-family: var(--mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--warn);
  background: var(--warn-tint);
  border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
  padding: 2px 7px;
  border-radius: 999px;
  cursor: help;
}

/* — Evidence ----------------------------------------------------------- */

.data.evidence tbody td {
  font-size: 13px;
  padding: var(--s3) var(--row-pad-x);
}
.evidence-dim {
  width: 220px;
  font-weight: 500;
  color: var(--ink);
}
.evidence-note { font-style: italic; font-size: 12.5px; }

.status {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--mono);
  letter-spacing: 0.04em;
  padding: 3px 9px;
  border-radius: 3px;
  text-transform: lowercase;
}
.status-exact       { color: var(--ok);   background: var(--ok-tint); }
.status-estimated   { color: var(--warn); background: var(--warn-tint); }
.status-partial     { color: var(--warn); background: var(--warn-tint); }
.status-unsupported { color: var(--bad);  background: var(--bad-tint); }

/* — Footer ------------------------------------------------------------- */

.page-foot {
  margin-top: var(--s8);
  padding-top: var(--s5);
  border-top: 1px solid var(--border);
  color: var(--mute);
  font-size: 11.5px;
  position: relative;
}
.page-foot::before {
  /* receipt double-rule */
  content: "";
  position: absolute;
  left: 0; right: 0; top: 4px;
  border-top: 1px solid var(--hairline);
}
.page-foot-row {
  display: flex; justify-content: space-between; gap: var(--s5);
  flex-wrap: wrap;
  align-items: center;
}
.page-foot-left {
  display: inline-flex; align-items: center;
  gap: var(--s2);
  font-family: var(--mono);
  font-size: 11px;
  color: var(--mute);
  letter-spacing: 0.02em;
}
.page-foot-fact { color: var(--mute); }
.page-foot-sep { color: var(--ghost); opacity: 0.7; }
.page-foot-right {
  font-family: var(--mono);
  display: flex; flex-direction: column; gap: var(--s1);
  align-items: flex-end;
  flex-shrink: 0;
  color: var(--ghost);
  letter-spacing: 0.02em;
}
.page-foot-checksum {
  font-size: 10.5px;
  color: var(--ghost);
  letter-spacing: 0.06em;
}

/* — Yearly activity heatmap (GitHub-style 53×7 grid) ------------------- */

.heat-panel {
  padding: var(--s5);
  --heat-cell-size: 11px;
  --heat-gap: 3px;
}
.heat-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s4);
  margin-bottom: var(--s4);
}
.heat-headline-label {
  color: var(--mute);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  margin-bottom: var(--s1);
}
.heat-headline-value {
  color: var(--ink);
  font-size: var(--num-lg);
  font-weight: 600;
  line-height: 1.1;
  font-variant-numeric: tabular-nums lining-nums;
  letter-spacing: -0.02em;
}
/* HTML CSS-grid heatmap (no SVG — each cell is a div with data-tip) */
.heat-grid-wrap {
  display: grid;
  grid-template-columns: 18px 1fr;
  grid-template-rows: 18px 1fr auto;
  column-gap: 6px;
  row-gap: 4px;
  margin: var(--s3) 0 var(--s4);
  font-family: var(--mono);
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.06em;
}
.heat-month-row {
  grid-column: 2;
  grid-row: 1;
  display: grid;
  align-items: end;
  padding-bottom: 2px;
}
.heat-month {
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.04em;
}
.heat-dow-col {
  grid-column: 1;
  grid-row: 2;
  display: grid;
  grid-template-rows: repeat(7, 1fr);
  row-gap: 3px;
  font-size: 10px;
  color: var(--mute);
  align-items: center;
  justify-items: end;
  padding-right: 2px;
}
.heat-grid {
  grid-column: 2;
  grid-row: 2;
  display: grid;
  grid-template-rows: repeat(7, var(--heat-cell-size));
  grid-auto-flow: column;
  gap: var(--heat-gap);
}
.heat-cell {
  width: 100%;
  height: 100%;
  min-width: 0;
  border-radius: 2px;
  background: var(--heat-0);
  display: inline-block;
  transition: outline-width 80ms ease-out, transform 100ms ease-out;
  outline: 0 solid var(--accent);
  outline-offset: 1px;
}
.heat-cell-blank { visibility: hidden; }
.heat-cell:hover {
  outline-width: 1.5px;
  transform: scale(1.4);
  z-index: 3;
  position: relative;
}
.heat-level-0 { background: var(--heat-0); }
.heat-level-1 { background: var(--heat-1); }
.heat-level-2 { background: var(--heat-2); }
.heat-level-3 { background: var(--heat-3); }
.heat-level-4 { background: var(--heat-4); }
.heat-legend {
  grid-column: 2;
  grid-row: 3;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
  padding-top: var(--s2);
}
.heat-legend .heat-cell {
  width: var(--heat-cell-size);
  height: var(--heat-cell-size);
  min-width: var(--heat-cell-size);
}
.heat-legend-label {
  font-size: 10px;
  color: var(--mute);
  margin: 0 4px;
}
.heat-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s3);
  padding-top: var(--s4);
  border-top: 1px solid var(--hairline);
}
.heat-stat-label {
  color: var(--mute);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  margin-bottom: var(--s1);
}
.heat-stat-value {
  color: var(--ink);
  font-size: var(--num-sm);
  font-weight: 600;
  font-variant-numeric: tabular-nums lining-nums;
  letter-spacing: -0.005em;
}

/* Heat color scale (green; tuned for dark surface) */
:root {
  --heat-0: rgba(255, 255, 255, 0.035);
  --heat-1: #103a1f;
  --heat-2: #1e6b34;
  --heat-3: #2ea043;
  --heat-4: #3fd959;
  --hour-0: rgba(255, 255, 255, 0.035);
  --hour-1: #1e3a8a;
  --hour-2: #2563eb;
  --hour-3: #3b82f6;
  --hour-4: #60a5fa;
}
[data-theme="light"] {
  --heat-0: rgba(0, 0, 0, 0.045);
  --heat-1: #c8e6cc;
  --heat-2: #82d18a;
  --heat-3: #2ea043;
  --heat-4: #1b6e2e;
  --hour-0: rgba(0, 0, 0, 0.045);
  --hour-1: #bcd5ff;
  --hour-2: #7aaaff;
  --hour-3: #2563eb;
  --hour-4: #1d4ed8;
}
[data-theme="print"] {
  --heat-0: #f1f1f1;
  --heat-1: #d6d6d6;
  --heat-2: #999999;
  --heat-3: #555555;
  --heat-4: #1a1a1a;
  --hour-0: #f1f1f1;
  --hour-1: #d6d6d6;
  --hour-2: #999999;
  --hour-3: #555555;
  --hour-4: #1a1a1a;
}

/* — Recap card (hour-of-week heatmap + 2×4 stat grid) ------------------ */

.recap-panel {
  padding: var(--s5);
}
.recap-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s4);
  margin-bottom: var(--s4);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--hairline);
  flex-wrap: wrap;
}
.recap-headline {
  margin: 0;
  font-size: var(--num-md);
  font-weight: 600;
  color: var(--ink);
  letter-spacing: -0.015em;
}
.recap-comparison-inline {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--mute);
  letter-spacing: 0.01em;
}
.recap-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s5);
  margin-bottom: var(--s5);
}
.recap-stat {
  /* Flat statlets — match heat-stat language, no boxed chrome. */
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.recap-stat-label {
  color: var(--mute);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.14em;
}
.recap-stat-value {
  color: var(--ink);
  font-size: var(--num-md);
  font-weight: 600;
  font-variant-numeric: tabular-nums lining-nums;
  letter-spacing: -0.01em;
}
/* HTML grid hour-of-week heatmap */
.hour-grid-wrap {
  display: grid;
  grid-template-columns: 22px 1fr;
  grid-template-rows: 18px 1fr;
  column-gap: 6px;
  row-gap: 4px;
  font-family: var(--mono);
}
.hour-axis-row {
  grid-column: 2;
  grid-row: 1;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  align-items: end;
  padding-bottom: 2px;
}
.hour-axis {
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.04em;
}
.hour-dow-col {
  grid-column: 1;
  grid-row: 2;
  display: grid;
  grid-template-rows: repeat(7, 1fr);
  row-gap: 4px;
  font-size: 10px;
  color: var(--mute);
  align-items: center;
  justify-items: end;
  padding-right: 2px;
}
.hour-grid {
  grid-column: 2;
  grid-row: 2;
  display: grid;
  grid-template-rows: repeat(7, 14px);
  grid-template-columns: repeat(24, 1fr);
  gap: 4px;
}
.hour-cell {
  border-radius: 3px;
  background: var(--hour-0);
  transition: outline-width 80ms ease-out, transform 100ms ease-out;
  outline: 0 solid var(--accent);
  outline-offset: 1px;
}
.hour-cell:hover {
  outline-width: 1.5px;
  transform: scale(1.25);
  z-index: 3;
  position: relative;
}
.hour-level-0 { background: var(--hour-0); }
.hour-level-1 { background: var(--hour-1); }
.hour-level-2 { background: var(--hour-2); }
.hour-level-3 { background: var(--hour-3); }
.hour-level-4 { background: var(--hour-4); }

/* — Interactive hover affordances ------------------------------------- */

/* CSS-only tooltip. Opt in with `data-tip="..."`. Horizontal placement
   is set at render time via `data-tip-anchor`:
     center (default) — tooltip centered on the trigger
     left             — tooltip's LEFT edge at the trigger's left edge
                        (use for triggers near the page LEFT edge)
     right            — tooltip's RIGHT edge at the trigger's right edge
                        (use for triggers near the page RIGHT edge)
   The arrow always sits at the trigger's horizontal center, regardless
   of which anchor is chosen, so it keeps pointing at the source. */
[data-tip] { position: relative; }
[data-tip]:hover { z-index: 5; }

[data-tip]::before,
[data-tip]::after {
  content: none;
  position: absolute;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, 2px);
  transition: opacity 90ms ease-out, transform 90ms ease-out;
  z-index: 50;
}
[data-tip]::after {
  bottom: calc(100% + 8px);
  left: 50%;
  background: var(--panel-2);
  color: var(--ink);
  border: 1px solid var(--border-strong);
  border-radius: 5px;
  padding: 6px 10px;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.4;
  letter-spacing: 0.01em;
  white-space: pre;
  max-width: min(360px, 92vw);
  box-shadow:
    0 1px 0 rgba(0,0,0,0.04),
    0 12px 32px rgba(0,0,0,0.45);
}
[data-tip]::before {
  bottom: calc(100% + 4px);
  left: 50%;
  width: 0; height: 0;
  border: 5px solid transparent;
  border-top-color: var(--border-strong);
  z-index: 51;
}
[data-tip]:hover::before,
[data-tip]:hover::after {
  opacity: 1;
  transform: translate(-50%, 0);
}
[data-tip]:hover::before { content: ""; }
[data-tip]:hover::after { content: attr(data-tip); }

/* Horizontal anchor variants — switch the tooltip body's reference point.
   The arrow stays anchored at the trigger center. */
[data-tip][data-tip-anchor="left"]::after {
  left: 0;
  transform: translate(0, 2px);
}
[data-tip][data-tip-anchor="left"]:hover::after {
  transform: translate(0, 0);
}
[data-tip][data-tip-anchor="right"]::after {
  left: auto;
  right: 0;
  transform: translate(0, 2px);
}
[data-tip][data-tip-anchor="right"]:hover::after {
  transform: translate(0, 0);
}

/* Vertical: place below for elements near the page top. */
[data-tip][data-tip-pos="bottom"]::after {
  top: calc(100% + 8px); bottom: auto;
}
[data-tip][data-tip-pos="bottom"]::before {
  top: calc(100% + 4px); bottom: auto;
  border-top-color: transparent;
  border-bottom-color: var(--border-strong);
}

/* Smaller emphasis variant for in-cell chips */
[data-tip].tip-sm::after { font-size: 11px; padding: 4px 8px; }

@media print {
  [data-tip]::after, [data-tip]::before { display: none !important; }
}

/* Cost-chart HTML hit-overlay — invisible boxes positioned over each SVG
   bar so we can carry a styled tooltip. The bars stay in SVG for the
   gridlines / mean line / axis labels; this layer just captures hover. */
.chart-wrap {
  position: relative;
}
.chart-hit-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.chart-hit {
  position: absolute;
  top: 0;
  bottom: 0;
  pointer-events: auto;
  cursor: default;
  border-radius: 1px;
  transition: background-color 100ms ease-out;
}
.chart-hit:hover {
  background-color: rgba(124,196,255,0.06);
}
[data-theme="light"] .chart-hit:hover { background-color: rgba(37,99,235,0.06); }
[data-theme="print"] .chart-hit:hover { background-color: rgba(0,80,179,0.06); }

.shape-cell { transition: transform 80ms ease-out, filter 80ms ease-out; transform-origin: center; cursor: default; }
.shape-cell:hover { filter: brightness(1.25); transform: scaleY(1.4); }

/* Card hover — small lift + ink border to feel responsive */
.card.stat { transition: transform 120ms ease-out, border-color 120ms ease-out, box-shadow 120ms ease-out; }
.card.stat:hover {
  transform: translateY(-1px);
  border-color: var(--border-strong);
  box-shadow: 0 1px 0 rgba(0,0,0,0.04), 0 10px 24px rgba(0,0,0,0.18);
}

/* Insight rows — show the rail breathes on hover */
.insight { transition: background-color 100ms ease-out, transform 120ms ease-out; }
.insight:hover { transform: translateX(2px); }

/* Meter rows / project rows highlight on hover for scanning */
.meter-row { transition: background-color 80ms ease-out; border-radius: 3px; padding: 2px 4px; margin: -2px -4px; }
.meter-row:hover { background: var(--panel-hover); }

/* Severity / status pills — outline on hover so they read as info-on-demand */
.sev, .status, .vendor-badge, .impact-chip, .delta {
  cursor: help;
}
.sev:hover, .status:hover, .vendor-badge:hover, .impact-chip:hover {
  filter: brightness(1.12);
}

.dash-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  gap: 6px;
  align-items: center;
  margin: calc(var(--s2) * -1) 0 var(--s5);
  padding: var(--s2);
  overflow-x: auto;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  backdrop-filter: blur(14px);
}

.dash-nav-link {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 var(--s3);
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: 6px;
}
.dash-nav-link:hover,
.dash-nav-link.is-current {
  color: var(--ink);
  background: var(--panel-hover);
  border-color: var(--border);
}
.dash-nav-link.is-muted { opacity: 0.55; }

.command-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s4);
}
.command-card {
  position: relative;
  min-height: 142px;
  padding: var(--s4);
  overflow: hidden;
  background: linear-gradient(180deg, var(--panel), var(--panel-2));
  border: 1px solid var(--border);
  border-radius: 8px;
}
.command-card::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--mute);
}
.command-card-good::before { background: var(--ok); }
.command-card-warn::before { background: var(--warn); }
.command-card-critical::before { background: var(--danger); }
.command-top {
  display: flex;
  justify-content: space-between;
  gap: var(--s3);
  align-items: center;
  min-width: 0;
}
.command-label {
  color: var(--mute);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0;
  text-transform: uppercase;
}
.command-metric {
  max-width: 42%;
  overflow: hidden;
  color: var(--ghost);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.command-value {
  margin-top: var(--s4);
  color: var(--ink);
  font-size: clamp(24px, 3vw, 36px);
  font-weight: 780;
  line-height: 0.95;
  overflow-wrap: anywhere;
}
.command-detail {
  margin-top: var(--s3);
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.45;
}

.mix-controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-bottom: var(--s4);
}
.mix-filter {
  min-height: 30px;
  padding: 0 var(--s3);
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
}
.mix-filter:hover,
.mix-filter.is-active {
  color: var(--ink);
  background: var(--panel-hover);
  border-color: var(--border-strong);
}
.mix-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
}
.mix-panel {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.mix-panel-head {
  display: flex;
  justify-content: space-between;
  gap: var(--s3);
  align-items: center;
  padding: var(--s4);
  border-bottom: 1px solid var(--hairline);
}
.mix-count {
  color: var(--ghost);
  font-size: 11px;
  white-space: nowrap;
}
.mix-list { display: grid; }
.mix-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 92px 92px;
  gap: var(--s3);
  align-items: center;
  min-height: 64px;
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--hairline);
}
.mix-row:last-child { border-bottom: 0; }
.mix-label {
  color: var(--ink);
  font-size: 13px;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.mix-meta {
  margin-top: 3px;
  color: var(--mute);
  font-size: 11px;
}
.mix-spark {
  justify-self: end;
  width: 92px;
}
.mix-share { justify-self: end; }

.advisor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
}
.advisor-card {
  position: relative;
  min-width: 0;
  padding: var(--s4);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.advisor-card::before {
  content: "";
  position: absolute;
  inset: var(--s4) auto var(--s4) 0;
  width: 3px;
  border-radius: 3px;
  background: var(--mute);
}
.advisor-card-good::before { background: var(--ok); }
.advisor-card-warn::before { background: var(--warn); }
.advisor-card-critical::before { background: var(--danger); }
.advisor-card-top {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  align-items: baseline;
}
.advisor-title {
  margin: 0;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.25;
}
.advisor-value {
  color: var(--ok);
  font-family: ui-monospace, SF Mono, Menlo, Consolas, monospace;
  font-size: 16px;
  font-weight: 760;
  white-space: nowrap;
}
.advisor-detail {
  margin: var(--s3) 0 0;
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.45;
}
.advisor-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: var(--s3);
}
.advisor-meta span,
.reason-chip,
.limit-samples {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 var(--s2);
  color: var(--ink-2);
  font-size: 11px;
  background: var(--panel-2);
  border: 1px solid var(--hairline);
  border-radius: 999px;
}
.advisor-command {
  display: block;
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  color: var(--accent-soft);
  font-size: 11px;
  line-height: 1.5;
  white-space: normal;
  overflow-wrap: anywhere;
  background: color-mix(in srgb, var(--accent) 8%, var(--panel-2));
  border: 1px solid var(--hairline);
  border-radius: 6px;
}

.table-scroll {
  overflow-x: auto;
}
.data-sortable th[data-sort] {
  cursor: pointer;
  user-select: none;
}
.data-sortable th[data-sort]:hover {
  color: var(--ink);
  background: var(--panel-hover);
}
.data-sortable th[data-sort]:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.session-label {
  display: inline-block;
  max-width: 260px;
  color: var(--ink);
  font-weight: 650;
  overflow-wrap: anywhere;
}
.session-table td:nth-child(6) {
  max-width: 180px;
  overflow-wrap: anywhere;
}

.limit-panel {
  position: relative;
  overflow: hidden;
}
.limit-panel::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--mute);
}
.limit-panel-good::before { background: var(--ok); }
.limit-panel-warn::before { background: var(--warn); }
.limit-panel-critical::before { background: var(--danger); }
.limit-panel-head {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  align-items: flex-start;
  padding: var(--s4);
  border-bottom: 1px solid var(--hairline);
}
.limit-sub {
  margin-top: 4px;
  color: var(--mute);
  font-size: 12px;
}
.limit-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.limit-stat {
  padding: var(--s4);
  border-right: 1px solid var(--hairline);
}
.limit-stat:last-child { border-right: 0; }
.limit-label {
  color: var(--mute);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.limit-value {
  margin-top: var(--s2);
  color: var(--ink);
  font-size: 22px;
  font-weight: 760;
}

.quality-panel {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: var(--s5);
  align-items: start;
  margin-bottom: var(--s4);
  padding: var(--s4);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.quality-score {
  display: flex;
  align-items: baseline;
  color: var(--ink);
}
.quality-number {
  font-size: 52px;
  font-weight: 780;
  line-height: 0.95;
}
.quality-denom {
  color: var(--mute);
  font-size: 15px;
}
.quality-list {
  display: grid;
  gap: var(--s2);
  margin: var(--s3) 0 0;
  padding: 0;
  list-style: none;
}
.quality-signal {
  display: grid;
  grid-template-columns: 160px 88px minmax(0, 1fr);
  gap: var(--s3);
  align-items: center;
  color: var(--ink-2);
  font-size: 12px;
}
.quality-signal-label { color: var(--ink); font-weight: 650; }
.quality-signal-status {
  justify-self: start;
  padding: 2px 7px;
  color: var(--ink-2);
  font-size: 10px;
  font-weight: 750;
  text-transform: uppercase;
  background: var(--panel-2);
  border: 1px solid var(--hairline);
  border-radius: 999px;
}
.quality-signal-note {
  color: var(--mute);
  overflow-wrap: anywhere;
}

/* — Responsive --------------------------------------------------------- */

@media (max-width: 920px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
  .command-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mix-grid,
  .advisor-grid { grid-template-columns: 1fr; }
  .limit-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .limit-stat:nth-child(2n) { border-right: 0; }
  .quality-panel { grid-template-columns: 1fr; gap: var(--s4); }
  .usage-window-grid { grid-template-columns: 1fr; }
  .impact-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .shape-grid { grid-template-columns: 1fr; }
  .th-tools, .col-tools { display: none; }
  .page { padding: var(--s6) var(--s4) var(--s6); }
  .recap-stat-grid { grid-template-columns: repeat(2, 1fr); gap: var(--s4); }
  .heat-stats { grid-template-columns: repeat(2, 1fr); }
  .heat-panel {
    --heat-cell-size: clamp(7px, 1.15vw, 11px);
    --heat-gap: 2px;
  }
  .data:not(.evidence) { min-width: 620px; }
}
@media (max-width: 640px) {
  .cards { grid-template-columns: 1fr; }
  .dash-nav {
    position: static;
    margin-top: 0;
  }
  .command-grid { grid-template-columns: 1fr; }
  .impact-grid { grid-template-columns: 1fr; }
  .forecast-cards { grid-template-columns: 1fr; }
  .page { padding: var(--s5) var(--s4) var(--s5); }
  [data-theme="print"] .page-wrap {
    padding: var(--s5) 0 var(--s6);
  }
  [data-theme="print"] .page {
    max-width: none;
    padding: var(--s5) var(--s4) var(--s5);
  }
  .page-head { grid-template-columns: 1fr; }
  .page-head-right { text-align: left; align-items: flex-start; }
  .window-badge,
  .page-meta {
    max-width: 100%;
    white-space: normal;
    flex-wrap: wrap;
  }
  .sec-head {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: var(--s2) var(--s3);
  }
  .sec-head-left {
    flex-wrap: wrap;
    white-space: normal;
  }
  .sec-hint {
    width: 100%;
    white-space: normal;
  }
  .shape-strip,
  .shape-strip-row {
    padding-left: 0;
    padding-right: 0;
  }
  .shape-strip-row {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: var(--s2) var(--s3);
  }
  .shape-strip-legend {
    margin-left: 0;
    flex-wrap: wrap;
    gap: var(--s2) var(--s3);
  }
  .heat-panel {
    --heat-cell-size: clamp(4px, 1.35vw, 7px);
    --heat-gap: 2px;
  }
  .heat-grid-wrap {
    grid-template-columns: 16px 1fr;
    column-gap: 4px;
  }
  .heat-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mix-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .mix-spark {
    display: none;
  }
  .advisor-card-top {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--s2);
  }
  .limit-panel-head {
    flex-direction: column;
    gap: var(--s3);
  }
  .limit-stats { grid-template-columns: 1fr; }
  .limit-stat,
  .limit-stat:nth-child(2n) {
    border-right: 0;
    border-bottom: 1px solid var(--hairline);
  }
  .limit-stat:last-child { border-bottom: 0; }
  .quality-signal {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .quality-signal-note {
    grid-column: 1 / -1;
  }
  .data:not(.evidence) { min-width: 0; }
  #models .data th:nth-child(n+4),
  #models .data td:nth-child(n+4),
  #projects .data th:nth-child(n+3),
  #projects .data td:nth-child(n+3) {
    display: none;
  }
  #models .th-vendor { width: 72px; }
  #models .th-cost,
  #projects .th-cost { width: 86px; }
  #models .data thead th,
  #projects .data thead th,
  #models .data tbody td,
  #projects .data tbody td {
    padding-left: var(--s3);
    padding-right: var(--s3);
  }
  #models .data thead th:first-child,
  #projects .data thead th:first-child,
  #models .data tbody td:first-child,
  #projects .data tbody td:first-child { padding-left: var(--s4); }
  #models .data thead th:last-child,
  #projects .data thead th:last-child,
  #models .data tbody td:last-child,
  #projects .data tbody td:last-child { padding-right: var(--s4); }
  #models .vendor-badge {
    padding: 2px 6px;
    font-size: 9.5px;
  }
  #models .th-model { width: auto; }
  #models .data td:nth-child(2) {
    max-width: 118px;
    overflow-wrap: anywhere;
  }
  #projects .proj-name {
    display: inline-block;
    max-width: 150px;
    overflow-wrap: anywhere;
  }
  .data.evidence tbody tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--s2) var(--s3);
    padding: var(--s4);
    border-bottom: 1px solid var(--hairline);
  }
  .data.evidence tbody tr:last-child { border-bottom: 0; }
  .data.evidence tbody td,
  .data.evidence tbody td:first-child,
  .data.evidence tbody td:last-child {
    padding: 0;
    border-bottom: 0;
  }
  .data.evidence tbody td:nth-child(2) {
    justify-self: end;
  }
  .data.evidence .evidence-dim {
    width: auto;
    min-width: 0;
  }
  .data.evidence .evidence-note {
    grid-column: 1 / -1;
    line-height: 1.5;
    max-width: 32ch;
  }
  .mean-label-bg,
  .mean-label-text {
    display: none;
  }
  .recap-header { gap: var(--s2); }
  .page-foot-left { flex-wrap: wrap; }
  .page-foot-right { align-items: flex-start; }
}

/* — Print -------------------------------------------------------------- */

@media print {
  body { background: #fff; }
  .page { padding: 32px; max-width: none; }
  .sec { break-inside: avoid; }
  .insight { break-inside: avoid; }
  .chart-panel { break-inside: avoid; }
  [class*="twk-"] { display: none !important; }
}
"""


def render_dashboard(d: Dashboard, *, theme: str = "dark", density: str = "comfortable") -> str:
    """
    Produce the entire dashboard as one self-contained HTML string.

    theme:    "dark" | "light" | "print"
    density:  "comfortable" | "compact"
    """
    css = INLINE_STYLES
    is_empty = d.totals.events == 0
    title = f"Caliper Dashboard — {d.window.start} → {d.window.end}"

    body = "".join(
        [
            render_header(d),
            render_banner(d.banner) if not is_empty else "",
            render_dashboard_nav(d),
            render_cards(d.totals, is_empty),
            render_command_center(d.command_center),
            render_usage_windows(d.usage_windows),
            render_impact_cards(d.impact_cards),
            render_cost_over_time(d.daily, is_empty),
            render_yearly_heatmap(d.heatmap) if not is_empty else "",
            render_recap(d.recap) if not is_empty else "",
            render_session_shape(d.shape, is_empty),
            render_usage_mix(d.usage_mix) if not is_empty else "",
            render_advisor(d.advisor_recommendations) if not is_empty else "",
            render_top_sessions(d.top_sessions) if not is_empty else "",
            render_models(d.by_model, d.totals.cost_usd) if not is_empty else "",
            render_projects(d.by_project, d.show_paths) if not is_empty else "",
            render_rate_limits(d.rate_limit_pressure) if not is_empty else "",
            render_insights(d.insights),
            render_forecast(d.forecast) if not is_empty else "",
            render_evidence(d.evidence, d.quality_score) if not is_empty else "",
            render_footer(d),
        ]
    )

    return (
        f"<!doctype html>\n"
        f'<html lang="en" data-theme="{esc(theme)}" '
        f'data-density="{esc(density)}">\n'
        f"<head>\n"
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>\n{css}\n</style>\n"
        f"</head>\n"
        f"<body>\n"
        f'<div class="page-wrap">'
        f'<main class="page">{body}</main>'
        f"</div>\n"
        f"<script>\n{INLINE_SCRIPT}\n</script>\n"
        f"</body>\n"
        f"</html>\n"
    )
