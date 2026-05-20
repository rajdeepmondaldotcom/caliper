"""Sample dashboard fixture — mirrors the design project's reference data.

Usage:
    from caliper.dashboards.sample_data import sample_dashboard
    from caliper.dashboards import render_dashboard

    html = render_dashboard(sample_dashboard())
    Path("out.html").write_text(html)

Convenience:
    python -m caliper.dashboards.sample_data
    # writes rich / empty / two banner variants / light / print HTML to out/
"""

from __future__ import annotations

from caliper import __version__
from caliper.dashboards.data_models import (
    AdvisorRecommendation,
    AnomalyRow,
    Banner,
    BriefFinding,
    CaliperMeta,
    CategoryCount,
    CommandCenterCard,
    ComparisonSignal,
    DailyPoint,
    Dashboard,
    DecisionQueueItem,
    EvidenceRow,
    ExecutiveBrief,
    Forecast,
    HeatCell,
    HourCell,
    ImpactCard,
    Insight,
    MixRow,
    ModelRow,
    ProjectRow,
    QualityScore,
    QualitySignal,
    RateLimitPressure,
    Recap,
    RecapStat,
    SessionRow,
    SessionShape,
    ToolCount,
    Totals,
    UsageWindow,
    WindowMeta,
    YearlyHeatmap,
)


def _sample_heatmap() -> YearlyHeatmap:
    """Synthesize a 365-day grid with a few peaks and weekend lulls."""
    import datetime as _dt
    import math
    import random

    rng = random.Random(42)
    end_day = _dt.date(2026, 5, 17)
    start_day = end_day - _dt.timedelta(days=364)
    cells: list[HeatCell] = []
    values: list[int] = []
    day = start_day
    while day <= end_day:
        weekday_bias = 1.4 if day.weekday() < 5 else 0.4
        seasonal = 1.0 + 0.6 * math.sin((day.timetuple().tm_yday / 365.0) * 2 * math.pi)
        base = int(rng.gauss(150 * weekday_bias * seasonal, 80))
        v = max(0, base)
        if rng.random() < 0.05:
            v *= 4  # occasional spike
        values.append(v)
        day = day + _dt.timedelta(days=1)
    # Quartile thresholds for level binning.
    nz = sorted(v for v in values if v > 0)
    n = max(1, len(nz))
    t = (
        nz[min(n - 1, int(0.20 * (n - 1)))],
        nz[min(n - 1, int(0.45 * (n - 1)))],
        nz[min(n - 1, int(0.70 * (n - 1)))],
        nz[min(n - 1, int(0.90 * (n - 1)))],
    )

    def level(v: int) -> int:
        if v <= 0:
            return 0
        if v >= t[3]:
            return 4
        if v >= t[2]:
            return 3
        if v >= t[1]:
            return 2
        return 1

    day = start_day
    for v in values:
        cells.append(HeatCell(date=day.isoformat(), value=v, level=level(v)))
        day = day + _dt.timedelta(days=1)
    return YearlyHeatmap(
        metric_label="AI tool calls",
        metric_total=sum(values),
        cells=cells,
        most_active_month="July",
        most_active_day="Feb 4, 2026",
        longest_streak=9,
        current_streak=3,
        legend_values=t,
    )


def _sample_recap() -> Recap:
    import random

    rng = random.Random(7)
    hours: list[HourCell] = []
    values: list[int] = []
    for dow in range(7):
        for hour in range(24):
            weekday_bias = 1.0 if dow < 5 else 0.3
            hour_bias = 1.5 if 9 <= hour <= 17 else 1.0 if 18 <= hour <= 22 else 0.2
            base = max(0, int(rng.gauss(18 * weekday_bias * hour_bias, 7)))
            values.append(base)
    nz = sorted(v for v in values if v > 0)
    n = max(1, len(nz))
    t = (
        nz[min(n - 1, int(0.20 * (n - 1)))],
        nz[min(n - 1, int(0.45 * (n - 1)))],
        nz[min(n - 1, int(0.70 * (n - 1)))],
        nz[min(n - 1, int(0.90 * (n - 1)))],
    )

    def level(v: int) -> int:
        if v <= 0:
            return 0
        if v >= t[3]:
            return 4
        if v >= t[2]:
            return 3
        if v >= t[1]:
            return 2
        return 1

    idx = 0
    for dow in range(7):
        for hour in range(24):
            v = values[idx]
            hours.append(HourCell(day_of_week=dow, hour=hour, value=v, level=level(v)))
            idx += 1
    return Recap(
        title="Caliper recap",
        stats=[
            RecapStat(label="Sessions", value="32"),
            RecapStat(label="Events", value="5,852"),
            RecapStat(label="Total tokens", value="6.1M"),
            RecapStat(label="Active days", value="142"),
            RecapStat(label="Current streak", value="3d"),
            RecapStat(label="Longest streak", value="9d"),
            RecapStat(label="Peak hour", value="5 PM"),
            RecapStat(label="Favorite model", value="Sonnet 4.6"),
        ],
        hours=hours,
        comparison="You've used ~39× more tokens than Pride and Prejudice.",
        legend_values=t,
    )


def sample_dashboard(banner: Banner | None = None, show_paths: bool = False) -> Dashboard:
    return Dashboard(
        caliper=CaliperMeta(version=__version__, schema_version=2),
        window=WindowMeta(
            start="2026-05-03",
            end="2026-05-17",
            label="Last 14 days",
            range="2026-05-03 → 2026-05-17",
            timezone="America/Los_Angeles",
            vendors_active=["claude-code"],
            vendor_count_total=4,
        ),
        generated_at="2026-05-17T12:34:56-07:00",
        totals=Totals(
            cost_usd=1243.18,
            events=480,
            cache_savings_usd=612.40,
            cache_hit_rate=0.724,
            total_tokens=4_120_000,
            cached_input_tokens=2_800_000,
            uncached_input_tokens=1_062_000,
            output_tokens=258_000,
            sessions=32,
            turns=480,
            tools_per_turn=1.123,
            delta_cost_pct=0.082,
            delta_cache_pct=-0.031,
            delta_tokens_pct=0.142,
            delta_sessions_pct=0.083,
            daily_cost_sparkline=[88, 62, 144, 51, 18, 0, 84, 168, 92, 108, 110, 33, 134, 154],
            daily_cache_sparkline=[
                0.78,
                0.81,
                0.74,
                0.79,
                0.81,
                0.0,
                0.72,
                0.66,
                0.70,
                0.71,
                0.73,
                0.69,
                0.71,
                0.70,
            ],
            daily_token_sparkline=[
                240,
                180,
                420,
                160,
                80,
                0,
                300,
                560,
                330,
                400,
                420,
                140,
                490,
                420,
            ],
            daily_session_sparkline=[3, 2, 4, 2, 1, 0, 3, 5, 2, 3, 4, 1, 4, 3],
        ),
        daily=[
            DailyPoint("2026-05-03", 88, 28, "exploration"),
            DailyPoint("2026-05-04", 62, 18, "exploration"),
            DailyPoint("2026-05-05", 144, 51, "execution"),
            DailyPoint("2026-05-06", 51, 19, "diagnostic"),
            DailyPoint("2026-05-07", 18, 8, "mixed"),
            DailyPoint("2026-05-08", 0, 0, "no-tools"),
            DailyPoint("2026-05-09", 84, 32, "exploration"),
            DailyPoint("2026-05-10", 168, 58, "execution"),
            DailyPoint("2026-05-11", 92, 36, "exploration"),
            DailyPoint("2026-05-12", 108, 44, "execution"),
            DailyPoint("2026-05-13", 110, 46, "diagnostic"),
            DailyPoint("2026-05-14", 33, 14, "mixed"),
            DailyPoint("2026-05-15", 134, 55, "execution"),
            DailyPoint("2026-05-16", 154, 51, "exploration"),
        ],
        shape=SessionShape(
            total_sessions=32,
            total_turns=480,
            tool_use_total=539,
            tools_per_turn=1.123,
            coverage_events=480,
            coverage_total_events=480,
            top_tools=[
                ToolCount("Read", 172, "explore"),
                ToolCount("Bash", 154, "diagnose"),
                ToolCount("Edit", 101, "execute"),
                ToolCount("Grep", 54, "explore"),
                ToolCount("Write", 40, "execute"),
                ToolCount("MultiEdit", 11, "execute"),
                ToolCount("Glob", 7, "explore"),
            ],
            categories=[
                CategoryCount("exploration", "exploration · read-heavy", 10, 0.31),
                CategoryCount("execution", "execution · edit-heavy", 10, 0.31),
                CategoryCount("diagnostic", "diagnostic · bash/grep-heavy", 8, 0.25),
                CategoryCount("mixed", "mixed", 4, 0.13),
            ],
        ),
        by_model=[
            ModelRow("anthropic", "claude-sonnet-4-6", "standard", 812.40, 320, 2_400_000, 0.78),
            ModelRow("anthropic", "claude-opus-4-7", "standard", 312.18, 80, 1_100_000, 0.62),
            ModelRow("anthropic", "claude-haiku-4-5", "fast", 118.60, 80, 620_000, 0.81),
        ],
        by_project=[
            ProjectRow(
                "api-server",
                "~/work/api-server",
                412.18,
                180,
                12,
                [
                    ToolCount("Read", 64, "explore"),
                    ToolCount("Bash", 51, "diagnose"),
                    ToolCount("Edit", 31, "execute"),
                ],
                11,
                "2026-05-17 10:40",
                29.44,
                883.24,
                "+18.4% vs prior 7d",
                "warn",
                [22.0, 18.0, 41.0, 16.0, 12.0, 8.0, 31.0, 52.0, 28.0, 24.0, 18.0, 39.0, 44.0, 59.0],
            ),
            ProjectRow(
                "frontend-app",
                "~/work/frontend-app",
                318.40,
                110,
                9,
                [
                    ToolCount("Edit", 41, "execute"),
                    ToolCount("Read", 33, "explore"),
                    ToolCount("Write", 18, "execute"),
                ],
                9,
                "2026-05-16 18:10",
                22.74,
                682.29,
                "flat vs prior 7d",
                "neutral",
                [12.0, 24.0, 18.0, 8.0, 14.0, 19.0, 26.0, 20.0, 21.0, 25.0, 18.0, 22.0, 17.0, 23.0],
            ),
            ProjectRow(
                "mobile-app",
                "~/work/mobile-app",
                186.20,
                86,
                6,
                [
                    ToolCount("Grep", 28, "explore"),
                    ToolCount("Read", 24, "explore"),
                    ToolCount("Bash", 18, "diagnose"),
                ],
                6,
                "2026-05-15 14:05",
                13.30,
                399.00,
                "-12.0% vs prior 7d",
                "good",
                [10.0, 12.0, 22.0, 18.0, 16.0, 0.0, 18.0, 12.0, 8.0, 14.0, 11.0, 0.0, 9.0, 16.0],
            ),
            ProjectRow(
                "data-pipeline",
                "~/work/data-pipeline",
                164.00,
                56,
                3,
                [
                    ToolCount("Bash", 32, "diagnose"),
                    ToolCount("Read", 14, "explore"),
                    ToolCount("Edit", 8, "execute"),
                ],
                5,
                "2026-05-15 09:20",
                11.71,
                351.43,
                "new activity in last 7d",
                "warn",
                [0.0, 0.0, 0.0, 12.0, 18.0, 0.0, 0.0, 22.0, 31.0, 40.0, 28.0, 25.0, 0.0, 10.0],
            ),
            ProjectRow(
                "infra-cdk",
                "~/work/infra-cdk",
                162.40,
                48,
                2,
                [
                    ToolCount("Bash", 22, "diagnose"),
                    ToolCount("Edit", 14, "execute"),
                    ToolCount("Read", 9, "explore"),
                ],
                4,
                "2026-05-14 17:35",
                11.60,
                348.00,
                "needs 14d history",
                "neutral",
                [0.0, 0.0, 13.0, 0.0, 18.0, 0.0, 0.0, 24.0, 0.0, 16.0, 0.0, 37.0, 0.0, 0.0],
            ),
        ],
        anomalies=[
            AnomalyRow(
                "Project-day spike",
                "api-server / 2026-05-17",
                "2026-05-17 10:40",
                59.00,
                22.00,
                7.20,
                5.1,
                37.00,
                "estimated",
                "critical",
            ),
            AnomalyRow(
                "Session spike",
                "session-018",
                "2026-05-10 15:42",
                84.10,
                20.00,
                15.20,
                4.2,
                64.10,
                "estimated",
                "warn",
            ),
        ],
        insights=[
            Insight(
                "info",
                "High cache reuse",
                "72.4% of input tokens were recorded as cached input. Keep prompts "
                "and file context stable to preserve cache reads.",
                impact="est. $612",
            ),
            Insight(
                "warn",
                "Project concentration",
                "One repo (api-server) accounts for about a third of selected-window "
                "cost. Consider "
                "per-PR caps or splitting sessions.",
                impact="$412 · 33%",
            ),
            Insight(
                "warn",
                "Tier mix is fast-heavy",
                "18% of events ran on the fast tier. Run "
                "`caliper advise --strict` to review high-confidence swaps.",
                impact="+$74 vs standard",
            ),
            Insight(
                "critical",
                "Outlier session",
                "Session session-018 cost $84 against a median of $20. "
                "Review with `caliper session 018`.",
                impact="$84 · 4.2× median",
            ),
            Insight(
                "info",
                "Sonnet dominates spend",
                "claude-sonnet-4-6 accounts for 65% of selected-window cost. Try "
                "`caliper whatif --model claude-haiku-4.5` for the same window.",
                impact="$812 · 65%",
            ),
        ],
        forecast=Forecast(
            days_analyzed=14,
            days_remaining=17,
            daily_mean=89.00,
            daily_stdev=48.00,
            linear_total=2759.00,
            linear_low=2432.00,
            linear_high=3086.00,
            ewma_total=2952.00,
        ),
        evidence=[
            EvidenceRow("Usage completeness", "exact", "480 of 480 events parsed"),
            EvidenceRow("Pricing freshness", "exact", "rate card checked 2026-05-12"),
            EvidenceRow("Deduplication", "exact", "0 duplicate event IDs"),
            EvidenceRow("Service tier", "estimated", "inferred from response headers"),
            EvidenceRow("Project attribution", "partial", "12 of 480 events missing cwd"),
            EvidenceRow("Git attribution", "unsupported", "no recorded git SHA in source logs"),
        ],
        usage_windows=[
            UsageWindow(
                label="Last 7 days",
                days=7,
                start="2026-05-10",
                end="2026-05-17",
                range="2026-05-10 → 2026-05-17",
                cost_usd=799.0,
                total_tokens=2_330_000,
                events=284,
                sessions=18,
                cache_hit_rate=0.71,
                active_days=7,
                daily_cost_sparkline=[168, 92, 108, 110, 33, 134, 154],
                daily_token_sparkline=[560, 330, 400, 420, 140, 490, 420],
            ),
            UsageWindow(
                label="Last 30 days",
                days=30,
                start="2026-04-17",
                end="2026-05-17",
                range="2026-04-17 → 2026-05-17",
                cost_usd=1754.0,
                total_tokens=8_870_000,
                events=1042,
                sessions=61,
                cache_hit_rate=0.69,
                active_days=24,
                daily_cost_sparkline=[31, 42, 55, 48, 77, 22, 0, 88, 62, 144, 51, 18, 0, 84],
                daily_token_sparkline=[
                    90,
                    120,
                    160,
                    140,
                    210,
                    80,
                    0,
                    240,
                    180,
                    420,
                    160,
                    80,
                    0,
                    300,
                ],
            ),
            UsageWindow(
                label="Last 90 days",
                days=90,
                start="2026-02-16",
                end="2026-05-17",
                range="2026-02-16 → 2026-05-17",
                cost_usd=4238.0,
                total_tokens=21_400_000,
                events=3120,
                sessions=183,
                cache_hit_rate=0.66,
                active_days=68,
                daily_cost_sparkline=[18, 24, 64, 80, 41, 95, 57, 38, 112, 76, 120, 92, 144, 154],
                daily_token_sparkline=[
                    60,
                    70,
                    180,
                    210,
                    130,
                    280,
                    160,
                    120,
                    320,
                    240,
                    350,
                    290,
                    420,
                    440,
                ],
            ),
        ],
        impact_cards=[
            ImpactCard(
                "Cost driver",
                "api-server",
                "$412 · 33% of selected-window cost",
                "neutral",
            ),
            ImpactCard("Budget risk", "78%", "monthly cost: $1,754 of $2,250", "warn"),
            ImpactCard(
                "Estimated cache savings",
                "$612.40",
                "72.4% cached-input share.",
                "good",
            ),
            ImpactCard(
                "Usage rhythm",
                "13 active days",
                "Peak hour 5 PM; 32 sessions; 4.1M tokens.",
            ),
            ImpactCard(
                "Dedupe",
                "18 skipped",
                "Rolling windows use parser-deduped usage events.",
                "good",
            ),
        ],
        command_center=[
            CommandCenterCard(
                "Budget posture",
                "78%",
                "monthly cost: $1,754 of $2,250",
                "warn",
                "control",
            ),
            CommandCenterCard(
                "Spend velocity",
                "$114.14/day",
                "+95.3% vs 30d/day",
                "warn",
                "trend",
            ),
            CommandCenterCard(
                "Largest savings candidate",
                "$184.20",
                "Largest advisor recommendation",
                "good",
                "savings",
            ),
            CommandCenterCard(
                "Anomaly findings",
                "2",
                "Project-day spike · observed $59.00",
                "critical",
                "audit",
            ),
            CommandCenterCard(
                "Highest-cost session",
                "$84.10",
                "long context · 820.0K tokens",
                "warn",
                "drilldown",
            ),
            CommandCenterCard(
                "Peak rate-limit usage",
                "82%",
                "18 limit samples",
                "warn",
                "reliability",
            ),
            CommandCenterCard("Evidence quality", "82/100", "Good", "neutral", "evidence"),
        ],
        executive_brief=ExecutiveBrief(
            title="AI usage needs review",
            verdict="4 priority items before sharing or acting on this report.",
            subtitle=(
                "$1,243 selected-window cost · 480 deduped events · 32 sessions · Last 7 days $799"
            ),
            tone="warn",
            findings=[
                BriefFinding(
                    "Spend velocity changed",
                    "The last 7 days are running higher than the 30-day daily baseline.",
                    "$114/day",
                    "warn",
                    "usage-windows",
                    "executive",
                ),
                BriefFinding(
                    "Review estimated savings",
                    "Estimated routing savings need review before the next heavy session.",
                    "est. $184",
                    "good",
                    "advisor",
                    "executive",
                ),
                BriefFinding(
                    "Check rate-limit pressure",
                    "Recorded limit samples show elevated pressure.",
                    "82% peak",
                    "warn",
                    "rate-limits",
                    "audit",
                ),
                BriefFinding(
                    "Review anomaly finding",
                    "Project-day spike crossed the dashboard detector threshold.",
                    "5.1σ",
                    "critical",
                    "anomalies",
                    "audit",
                ),
            ],
        ),
        decision_queue=[
            DecisionQueueItem(
                1,
                "Spend velocity changed",
                "The last 7 days are running higher than the 30-day daily baseline.",
                "Review rolling windows and daily cost to find the date that moved the trend.",
                "$114/day",
                "warn",
                "usage-windows",
                "executive",
            ),
            DecisionQueueItem(
                2,
                "Review budget posture",
                "monthly cost: $1,754 of $2,250",
                "Open the Impact section and decide whether the configured budget needs action.",
                "78%",
                "warn",
                "impact",
                "finance",
            ),
            DecisionQueueItem(
                3,
                "Review estimated savings",
                "Largest advisor recommendation is $184.20.",
                "Validate quality and latency before changing model or tier routing.",
                "3 recommendations",
                "good",
                "advisor",
                "executive",
            ),
            DecisionQueueItem(
                4,
                "Review anomaly finding",
                "Project-day spike on api-server / 2026-05-17: observed $59.00.",
                "Inspect the Anomalies section before treating the spike as a repeatable trend.",
                "5.1σ · $37.00 impact",
                "critical",
                "anomalies",
                "audit",
            ),
            DecisionQueueItem(
                5,
                "Inspect the highest-cost session",
                "The top session is $84.10 and long context.",
                "Inspect tokens, tools, models, and project attribution.",
                "7% of selected-window cost",
                "neutral",
                "top-sessions",
                "engineer",
            ),
        ],
        comparisons=[
            ComparisonSignal(
                "7d spend velocity",
                "$114.14/day",
                "30d baseline $58.44/day",
                "warn",
                0.953,
                "usage-windows",
                "finance",
            ),
            ComparisonSignal(
                "Top project concentration",
                "33%",
                "api-server is $412 of selected-window cost",
                "neutral",
                None,
                "projects",
                "finance",
            ),
            ComparisonSignal(
                "Evidence quality",
                "82/100",
                "Good",
                "neutral",
                None,
                "evidence",
                "audit",
            ),
        ],
        advisor_recommendations=[
            AdvisorRecommendation(
                "Move low-output fast tier calls to standard",
                "$96.40",
                "124 matching events across 9 sessions. Target standard tier.",
                "caliper advise --rule fast-tier-low-output",
                0.74,
                124,
                9,
                "good",
                96.40,
            ),
            AdvisorRecommendation(
                "Use Sonnet for Opus non-reasoning turns",
                "$68.80",
                "21 matching events across 4 sessions. Target claude-sonnet-4.6.",
                "caliper whatif --model claude-sonnet-4.6",
                0.80,
                21,
                4,
                "good",
                68.80,
            ),
            AdvisorRecommendation(
                "Route short premium contexts to a smaller model",
                "$19.00",
                "37 matching events across 6 sessions. Target cheaper model.",
                "caliper advise --rule premium-short-context",
                0.70,
                37,
                6,
                "good",
                19.00,
            ),
        ],
        top_sessions=[
            SessionRow(
                "session-018",
                "2026-05-10 15:42",
                "api-server",
                84.10,
                820_000,
                58,
                83,
                ["claude-opus-4-7", "claude-sonnet-4-6"],
                "long context",
            ),
            SessionRow(
                "session-024",
                "2026-05-15 11:04",
                "frontend-app",
                62.20,
                410_000,
                42,
                91,
                ["claude-sonnet-4-6"],
                "tool-heavy",
            ),
            SessionRow(
                "session-011",
                "2026-05-08 09:18",
                "data-pipeline",
                44.75,
                280_000,
                31,
                47,
                ["claude-sonnet-4-6"],
                "cost outlier",
            ),
        ],
        usage_mix=[
            MixRow(
                "vendor",
                "claude-code",
                1243.18,
                4_120_000,
                480,
                1.0,
                [88, 62, 144, 51, 18, 0, 84, 168, 92, 108, 110, 33, 134, 154],
            ),
            MixRow(
                "model/tier",
                "claude-sonnet-4-6 · standard",
                812.40,
                2_400_000,
                320,
                0.65,
                [41, 55, 91, 28, 12, 0, 63, 104, 71, 82, 78, 22, 108, 117],
            ),
            MixRow(
                "model/tier",
                "claude-opus-4-7 · standard",
                312.18,
                1_100_000,
                80,
                0.25,
                [30, 4, 39, 16, 4, 0, 14, 48, 12, 18, 22, 8, 16, 81],
            ),
            MixRow(
                "model/tier",
                "claude-haiku-4-5 · fast",
                118.60,
                620_000,
                80,
                0.10,
                [17, 3, 14, 7, 2, 0, 7, 16, 9, 8, 10, 3, 10, 12],
            ),
            MixRow(
                "tier",
                "standard",
                1124.58,
                3_500_000,
                400,
                0.90,
                [71, 59, 130, 44, 16, 0, 77, 152, 83, 100, 100, 30, 124, 142],
            ),
            MixRow(
                "tier",
                "fast",
                118.60,
                620_000,
                80,
                0.10,
                [17, 3, 14, 7, 2, 0, 7, 16, 9, 8, 10, 3, 10, 12],
            ),
            MixRow(
                "source",
                "claude-code",
                1243.18,
                4_120_000,
                480,
                1.0,
                [88, 62, 144, 51, 18, 0, 84, 168, 92, 108, 110, 33, 134, 154],
            ),
        ],
        rate_limit_pressure=RateLimitPressure(
            sample_count=18,
            peak_primary_pct=0.82,
            peak_secondary_pct=0.61,
            latest_primary_pct=0.54,
            latest_secondary_pct=0.18,
            latest_limit_name="5-hour usage",
            latest_plan_type="max",
            latest_resets_at="2026-05-17T18:00Z",
            reached_count=0,
            tone="warn",
        ),
        quality_score=QualityScore(
            score=82,
            grade="Good",
            tone="neutral",
            signals=[
                QualitySignal("Usage completeness", "exact", "480 of 480 events parsed", "good"),
                QualitySignal("Pricing freshness", "exact", "rate card checked 2026-05-12", "good"),
                QualitySignal("Service tier", "estimated", "inferred from response headers"),
                QualitySignal(
                    "Project attribution",
                    "partial",
                    "12 of 480 events missing cwd",
                    "warn",
                ),
                QualitySignal("Git attribution", "unsupported", "no recorded git SHA", "critical"),
            ],
        ),
        heatmap=_sample_heatmap(),
        recap=_sample_recap(),
        banner=banner,
        show_paths=show_paths,
    )


def empty_dashboard() -> Dashboard:
    """The all-zero dashboard. Renderer falls back to empty placeholders."""
    return Dashboard(
        caliper=CaliperMeta(version=__version__, schema_version=2),
        window=WindowMeta(
            start="2026-05-10",
            end="2026-05-17",
            label="Last 7 days",
            range="2026-05-10 → 2026-05-17",
            timezone="America/Los_Angeles",
            vendors_active=[],
            vendor_count_total=4,
        ),
        generated_at="2026-05-17T12:34:56-07:00",
        totals=Totals(
            cost_usd=0,
            events=0,
            cache_savings_usd=0,
            cache_hit_rate=0,
            total_tokens=0,
            cached_input_tokens=0,
            uncached_input_tokens=0,
            output_tokens=0,
            sessions=0,
            turns=0,
            tools_per_turn=0,
        ),
        daily=[],
        shape=SessionShape(
            total_sessions=0,
            total_turns=0,
            tool_use_total=0,
            tools_per_turn=0,
            coverage_events=0,
            coverage_total_events=0,
            top_tools=[],
            categories=[],
        ),
        by_model=[],
        by_project=[],
        anomalies=[],
        insights=[],
        forecast=None,
        evidence=[],
    )


if __name__ == "__main__":
    # Convenience: write the rich + empty + banner variants to disk.
    from pathlib import Path

    from caliper.dashboards import render_dashboard

    out = Path("out")
    out.mkdir(exist_ok=True)

    (out / "rich.html").write_text(render_dashboard(sample_dashboard()))
    (out / "empty.html").write_text(render_dashboard(empty_dashboard()))
    (out / "vendor-banner.html").write_text(
        render_dashboard(
            sample_dashboard(
                banner=Banner(
                    kind="warn",
                    label="PARTIAL",
                    text=(
                        "Showing 1 of 4 vendors. Codex, Cursor, and Aider did not "
                        "write parseable logs in this window. Run "
                        "<code>caliper doctor</code> to verify your local setup."
                    ),
                )
            )
        )
    )
    (out / "stale-banner.html").write_text(
        render_dashboard(
            sample_dashboard(
                banner=Banner(
                    kind="crit",
                    label="STALE",
                    text=(
                        "Pricing data is 47 days old. Costs are extrapolated from "
                        "the last known rate card. Run "
                        "<code>caliper rates refresh --allow-network</code> "
                        "for the latest."
                    ),
                )
            )
        )
    )
    (out / "light.html").write_text(render_dashboard(sample_dashboard(), theme="light"))
    (out / "print.html").write_text(render_dashboard(sample_dashboard(), theme="print"))
    (out / "share-safe.html").write_text(
        render_dashboard(sample_dashboard(show_paths=True), share_safe=True)
    )
    print(f"Wrote 7 variants to {out}/")
