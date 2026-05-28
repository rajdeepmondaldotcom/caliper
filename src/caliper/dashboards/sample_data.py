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
    DASHBOARD_SCHEMA_VERSION,
    AdvisorAlternative,
    AdvisorRecommendation,
    AgentRow,
    AnomalyRow,
    Banner,
    BriefFinding,
    BudgetRow,
    CacheLeverageRow,
    CaliperMeta,
    CohortDeltaRow,
    DailyPoint,
    Dashboard,
    EvidenceRow,
    ExecutiveBrief,
    InefficiencyRow,
    Insight,
    LongContextHistogram,
    ModelRow,
    OutputSummary,
    ProjectRow,
    QualityScore,
    QualitySignal,
    RateLimitPressure,
    SessionRow,
    SkillRow,
    TierProvenance,
    ToolCount,
    Totals,
    WindowMeta,
)


def sample_dashboard(banner: Banner | None = None, show_paths: bool = False) -> Dashboard:
    return Dashboard(
        caliper=CaliperMeta(
            version=__version__, schema_version=DASHBOARD_SCHEMA_VERSION, build_sha="330c1ab"
        ),
        window=WindowMeta(
            start="2026-05-03",
            end="2026-05-17",
            label="Last 14 days",
            range="2026-05-03 → 2026-05-17",
            timezone="America/Los_Angeles",
            # Use the canonical vendor IDs the real parsers emit. See
            # ``caliper.models.VENDOR_*`` constants — the masthead now shows
            # every known source with detected/missing status, so consistency
            # with real-world IDs is what makes the demo trustworthy.
            vendors_active=["claude-code", "openai-codex", "cursor", "aider"],
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
        by_model=[
            ModelRow("anthropic", "claude-sonnet-4-6", "standard", 812.40, 320, 2_400_000, 0.78),
            ModelRow("anthropic", "claude-opus-4-7", "standard", 312.18, 80, 1_100_000, 0.62),
            ModelRow("openai", "gpt-5.5", "standard", 184.20, 42, 540_000, 0.48),
            ModelRow("anthropic", "claude-haiku-4-5", "fast", 118.60, 80, 620_000, 0.81),
            ModelRow("openai", "gpt-5.4-mini", "fast", 36.40, 28, 220_000, 0.55),
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
                "3:42 pm, Sunday 10 May 2026",
                "3:42 pm, Sunday 10 May 2026",
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
                evidence_metrics={"events": 480, "sessions": 32, "tokens": 4_120_000},
            ),
            Insight(
                "warn",
                "Project concentration",
                "One repo (api-server) accounts for about a third of selected-window "
                "cost. Consider "
                "per-PR caps or splitting sessions.",
                impact="$412 · 33%",
                evidence_metrics={"events": 180, "sessions": 12},
            ),
            Insight(
                "warn",
                "Tier mix is fast-heavy",
                "18% of events ran on the fast tier. Run "
                "`caliper advise --strict` to review high-confidence swaps.",
                impact="+$74 vs standard",
                evidence_metrics={"events": 86, "sessions": 14, "tokens": 620_000},
            ),
            Insight(
                "critical",
                "Outlier session",
                "The session at 3:42 pm, Sunday 10 May 2026 cost $84 against a median of $20. "
                "Review the matching row in Top sessions.",
                impact="$84 · 4.2× median",
                evidence_metrics={"events": 58, "sessions": 1, "tokens": 820_000},
            ),
            Insight(
                "info",
                "Sonnet dominates spend",
                "claude-sonnet-4-6 accounts for 65% of selected-window cost. Try "
                "`caliper whatif --hypothetical-model gpt-5.4-mini` for the same window.",
                impact="$812 · 65%",
                evidence_metrics={"events": 320, "sessions": 28, "tokens": 2_400_000},
            ),
        ],
        evidence=[
            EvidenceRow("Usage completeness", "exact", "480 of 480 events parsed"),
            EvidenceRow("Pricing freshness", "exact", "rate card checked 2026-05-12"),
            EvidenceRow("Deduplication", "exact", "0 duplicate event IDs"),
            EvidenceRow("Service tier", "estimated", "inferred from response headers"),
            EvidenceRow("Project attribution", "partial", "12 of 480 events missing cwd"),
            EvidenceRow("Git attribution", "unsupported", "no recorded git SHA in source logs"),
        ],
        output_summary=OutputSummary(
            commits_touched=37,
            cost_per_commit_usd=33.59,
            linked_cost_usd=1243.0,
            linked_cost_pct=0.82,
            edit_share=0.41,
            diagnostic_share=0.34,
            exploration_share=0.25,
            classified_tool_calls=2480,
            has_git=True,
            caveat=(
                "Cost per commit divides git-linked spend by commits touched. It is "
                "a rough unit cost, not a per-commit invoice. Unlinked spend is "
                "exploration, planning, or work that never reached a commit, not "
                "automatically waste."
            ),
        ),
        executive_brief=ExecutiveBrief(
            title="AI usage needs review",
            verdict="4 items to review before sharing or acting on this report.",
            subtitle=("$1,243 selected-window cost · 480 deduped events · 32 sessions"),
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
                    "Review avoidable spend",
                    "A routing change worth reviewing before the next heavy session.",
                    "$184 at API rates",
                    "good",
                    "inefficiencies",
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
                "Use Sonnet 4.6 for Opus non-reasoning turns",
                "$61.24",
                "21 matching events across 4 sessions. Test current alternatives: "
                "claude-sonnet-4.6 (anthropic, $61.24 cheaper), "
                "gpt-5.4 (openai, $55.10 cheaper), "
                "gpt-5.4-mini (openai, $68.80 cheaper).",
                "caliper whatif --hypothetical-model claude-sonnet-4.6",
                0.80,
                21,
                4,
                "good",
                61.24,
                (
                    AdvisorAlternative("claude-sonnet-4.6", "anthropic", 15.76, 61.24, 21),
                    AdvisorAlternative("gpt-5.4", "openai", 21.90, 55.10, 21),
                    AdvisorAlternative("gpt-5.4-mini", "openai", 8.20, 68.80, 21),
                ),
            ),
            AdvisorRecommendation(
                "Route short premium contexts to current cheaper models",
                "$19.00",
                "37 matching events across 6 sessions. Keep GPT-5.5 and Sonnet 4.6 "
                "for complex work. Test current alternatives: "
                "gpt-5.4 (openai, $12.40 cheaper), "
                "gpt-5.4-mini (openai, $19.00 cheaper).",
                "caliper whatif --hypothetical-model gpt-5.4",
                0.70,
                37,
                6,
                "good",
                19.00,
            ),
        ],
        top_sessions=[
            SessionRow(
                "3:42 pm, Sunday 10 May 2026",
                "2026-05-10 15:42 UTC",
                "api-server",
                84.10,
                820_000,
                58,
                83,
                ["claude-opus-4-7", "claude-sonnet-4-6"],
                "long context",
            ),
            SessionRow(
                "11:04 am, Friday 15 May 2026",
                "2026-05-15 11:04 UTC",
                "frontend-app",
                62.20,
                410_000,
                42,
                91,
                ["claude-sonnet-4-6"],
                "tool-heavy",
            ),
            SessionRow(
                "9:18 am, Friday 8 May 2026",
                "2026-05-08 09:18 UTC",
                "data-pipeline",
                44.75,
                280_000,
                31,
                47,
                ["claude-sonnet-4-6"],
                "cost outlier",
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
        # Per-source rate-limit panels reflect what real parsing actually
        # produces. As of 0.0.76 ONLY the Codex parser populates
        # `rate_limit_samples` (the Claude Code, Cursor, and Aider parsers
        # currently return an empty list). Do NOT add a synthetic Claude Code
        # entry here just to make the demo look prettier — the Claude Code
        # parser doesn't extract rate-limit headers yet, and a fake demo
        # entry would mislead users into expecting a panel they won't see on
        # their own logs. When `vendors/claude_code.py` learns to surface
        # rate-limit data, the Claude Code panel will appear automatically.
        rate_limit_pressures=[
            RateLimitPressure(
                sample_count=24,
                peak_primary_pct=0.68,
                peak_secondary_pct=0.42,
                latest_primary_pct=0.08,
                latest_secondary_pct=0.04,
                latest_limit_name="5-hour usage",
                latest_plan_type="pro",
                # The demo's generated_at is 12:34 Pacific (19:34 UTC). 23:17 UTC
                # is 16:17 Pacific — exactly 3 hr 43 min from "now", matching
                # the friendly target Codex shows on its own usage page.
                latest_resets_at="2026-05-17T23:17Z",
                reached_count=0,
                tone="neutral",
                source="openai-codex",
                source_label="Codex",
            ),
        ],
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
        agents=[
            AgentRow(
                "claude-code · planner",
                "direct",
                "estimated",
                "logged via claude-code session header",
                "claude-code",
                812.40,
                2_400_000,
                320,
                240,
                18,
                [88, 62, 144, 51, 18, 0, 84, 168, 92, 108, 110, 33, 134, 154],
            ),
            AgentRow(
                "codex · multi-file edit",
                "direct",
                "exact",
                "logged via openai codex CLI",
                "codex",
                184.20,
                540_000,
                42,
                36,
                4,
                [0, 0, 8, 12, 0, 0, 14, 22, 18, 16, 20, 12, 28, 34],
            ),
            AgentRow(
                "cursor · agent mode",
                "direct",
                "partial",
                "inferred from cursor agent flag",
                "cursor",
                146.20,
                480_000,
                78,
                52,
                7,
                [0, 12, 18, 8, 0, 0, 10, 22, 14, 16, 12, 6, 18, 10],
            ),
            AgentRow(
                "aider · refactor",
                "direct",
                "estimated",
                "inferred from aider commit prefix",
                "aider",
                64.80,
                240_000,
                31,
                20,
                3,
                [0, 0, 12, 0, 8, 0, 0, 14, 0, 18, 0, 0, 0, 12],
            ),
            AgentRow(
                "background · review",
                "overhead",
                "partial",
                "inferred from session metadata",
                "assistant",
                35.58,
                180_000,
                9,
                12,
                2,
                [0, 4, 0, 6, 0, 0, 8, 0, 10, 0, 0, 0, 4, 3],
            ),
        ],
        skills=[
            SkillRow("diagnose", "estimated", "session marker", 48.20, 8.03, 180_000, 6, 4),
            SkillRow("tdd", "partial", "prompt pattern", 24.10, 6.02, 92_000, 4, 3),
            SkillRow("refactor", "partial", "prompt pattern", 18.60, 5.20, 74_000, 3, 2),
        ],
        inefficiencies=[
            InefficiencyRow(
                "FAST_TIER_LOW_OUTPUT",
                "warn",
                "estimated",
                "Fast tier on low-output turns",
                "124 low-output events used a premium tier without a matching token benefit.",
                "Route low-output turns to standard tier unless latency matters.",
                96.40,
                206.57,
                "medium",
                124,
                "low-output median",
            ),
            InefficiencyRow(
                "LONG_CONTEXT_MISFIRE",
                "warn",
                "estimated",
                "Long-context multiplier near threshold",
                "12 events crossed a long-context price boundary by less than 8%.",
                "Split large context dumps or trim unchanged files before retrying.",
                42.80,
                91.71,
                "medium",
                12,
                "272K token threshold",
            ),
        ],
        tier_provenance=TierProvenance(
            sources=(("Logged in event", 320), ("Codex config", 120), ("Assumed default", 40)),
            total_events=480,
        ),
        cache_leverage=[
            CacheLeverageRow(
                "3:42 pm, Sunday 10 May 2026", "api-server", 144.20, 0.82, 720_000, 158_000
            ),
            CacheLeverageRow(
                "11:04 am, Friday 15 May 2026",
                "frontend-app",
                88.10,
                0.74,
                410_000,
                144_000,
            ),
        ],
        long_context_histogram=LongContextHistogram(
            bins=(0, 1_000, 4_000, 16_000, 64_000, 200_000, 1_000_000),
            counts=(62, 128, 144, 96, 37, 11, 2),
            threshold_tokens=200_000,
            share_above_threshold=0.027,
            cost_share_above_threshold=0.18,
            total_events=480,
        ),
        cohort_deltas=[
            CohortDeltaRow("Total cost", "$1,243.18", "$1,148.90", 0.082, 94.28, "warn"),
            CohortDeltaRow("Cache hit rate", "72.4%", "75.5%", -0.031, -0.031, "warn"),
        ],
        banner=banner,
        show_paths=show_paths,
        budgets=[
            BudgetRow(period="daily", spent=37.0, cap=100.0, warn=80.0, tone="good"),
            BudgetRow(period="weekly", spent=412.0, cap=500.0, warn=400.0, tone="warn"),
            BudgetRow(period="monthly", spent=1640.0, cap=2000.0, warn=1600.0, tone="warn"),
        ],
    )


def empty_dashboard() -> Dashboard:
    """The all-zero dashboard. Renderer falls back to empty placeholders."""
    return Dashboard(
        caliper=CaliperMeta(
            version=__version__, schema_version=DASHBOARD_SCHEMA_VERSION, build_sha="330c1ab"
        ),
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
        by_model=[],
        by_project=[],
        anomalies=[],
        insights=[],
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
