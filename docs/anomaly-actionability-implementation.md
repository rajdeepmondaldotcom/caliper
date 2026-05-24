# Actionable Anomaly Detection Implementation Plan

## Phase 1 - Initial Implementation Plan

The current anomaly pipeline is intentionally isolated in `src/caliper/anomaly.py`.
It feeds two public surfaces:

- `caliper predict`, which serializes `Anomaly` dataclasses to JSON/table/markdown.
- `caliper dashboard`, where `src/caliper/dashboards/adapter.py` adapts anomalies into
  `AnomalyRow` records and `src/caliper/dashboards/html.py` renders the section.

The screenshot symptom comes from a detector that treats broad spend distributions as
comparable. A large session can be compared against the median of all sessions, so a
normal expensive workflow can read as a `Spend spike` against a tiny baseline. The fix is
not a renderer-only copy change. Detection must be stricter about what counts as
comparable history.

Implementation direction:

- Keep anomaly detection pure stdlib and offline.
- Preserve existing detector entrypoints, but add a unified actionable anomaly assembler
  for dashboard and predict surfaces.
- Add metadata to `Anomaly` rather than replacing fields: comparison scope, cohort key,
  cohort label, baseline sample count, reason, and dedupe key.
- Score candidates only against prior comparable observations:
  - sessions: prior sessions in the same project/model/tier/vendor cohort;
  - model-days: prior active days for the same model/tier/vendor cohort;
  - project-days: prior active days in the same project;
  - total daily: prior selected-window days.
- Keep the existing robust baseline machinery: active-cost preference, MAD/IQR/median
  scale, absolute scale floor, fold-change gate, dollar-impact gate, and sigma cap.
- Deduplicate correlated findings before rendering so one underlying cause does not
  fill the section with near-identical rows.
- Keep all public schema changes additive.

## Phase 2 - Self-Audit Against Code

Findings before implementation:

- `Anomaly` has only numeric baseline fields, so renderer copy cannot explain the
  comparison set.
- `AnomalyRow` also lacks comparison context, so dashboard HTML can only say
  `Observed X vs typical Y`.
- `caliper predict` and dashboard duplicate anomaly assembly logic. Updating only one
  surface would leave inconsistent behavior.
- Existing `tests/test_anomaly.py` covers sparse baseline protection but not comparable
  cohort behavior.
- Existing `tests/test_handoff_adapter.py` expects both project-day and session anomalies
  for a single large final day. That fixture is a useful end-to-end regression because it
  has enough prior history.
- The worktree already contains unrelated/uncommitted changes in dashboard progress and
  efficiency reuse paths. The anomaly implementation must not revert or absorb them.
- `docs/*.md` is ignored. Planning files under `docs/` must be force-added.

## Phase 3 - Plan Revision Round 1

The first revision keeps the architecture narrower:

- Put all new detector behavior in `caliper.anomaly`; do not add a new dependency layer.
- Use helper observations internally instead of adding new public dataclasses.
- Make `detect_actionable_anomalies(...)` the shared high-level API for dashboard and
  predict.
- Leave legacy detector function names in place and have them use the same prior-cohort
  scoring rules for consistency.
- Sort actionable output by impact first, then capped sigma, so capped `>=20 sigma`
  findings do not all tie ahead of dollar relevance.

## Phase 4 - Industry Standards Research

Research was used only to refine the approved approach:

- FinOps Foundation anomaly management emphasizes detection, investigation, ownership,
  and granular allocation metadata. This supports comparison scopes and root-cause
  context rather than broad all-up medians.
  https://www.finops.org/framework/capabilities/anomaly-management/
- AWS Cost Anomaly Detection supports dollar and percentage-change thresholds and root
  cause details. This maps to Caliper's dollar-impact and fold-change gates plus concise
  reason/context fields.
  https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/features/
- AWS anomaly impact APIs separate actual spend, expected spend, total impact, and
  impact percentage. This supports preserving observed, baseline, impact, and deviation
  fields rather than replacing them with a single score.
  https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Impact.html
- Google Cloud cost anomalies expose cost-impact and deviation-percentage thresholds,
  root-cause context, and feedback options. Caliper should similarly suppress
  insignificant/no-context rows and tell the user what to inspect.
  https://docs.cloud.google.com/billing/docs/how-to/manage-anomalies
- Microsoft FinOps guidance recommends reviewing related engineers, usage trends,
  lower-level utilization, and configuration changes. This supports actionable copy and
  cohort labels.
  https://learn.microsoft.com/en-us/cloud-computing/finops/framework/understand/anomalies
- Robust-statistics references support median/MAD/IQR scale over mean/stdev for
  outlier-heavy spend distributions. This confirms the existing robust scale should stay.
  https://en.wikipedia.org/wiki/Robust_statistics
  https://en.wikipedia.org/wiki/Robust_measures_of_scale

## Phase 5 - Plan Revision Round 2

Research refinements:

- Keep both absolute dollar impact and fold-change/deviation requirements.
- Add comparison-scope metadata because allocation granularity is part of anomaly
  usefulness.
- Keep robust statistics and the display sigma cap; do not redesign around a hosted or
  machine-learning detector because Caliper is offline-first.
- Prefer concise actionable reasons in the dashboard over exposing raw scale math.

## Phase 6 - Final Critical Audit

Decision-complete implementation checklist:

- Extend `caliper.models.Anomaly` with defaulted additive metadata fields.
- Extend dashboard `AnomalyRow` with defaulted additive metadata fields.
- Implement internal observation builders and prior-cohort evaluation in
  `caliper.anomaly`.
- Add `detect_actionable_anomalies(events, rate_card, timezone, daily=None)` and export
  it.
- Update dashboard and predict to use the shared high-level API.
- Update dashboard copy to include sample count and comparison scope without leaking raw
  paths when safe-share is active.
- Add tests for broad-baseline suppression, prior-cohort detection, metadata population,
  dashboard copy, and JSON additive fields.
- Run targeted tests, ruff, then the full test suite.
- Do not run Terraform commands.
- Commit locally only; do not push.
