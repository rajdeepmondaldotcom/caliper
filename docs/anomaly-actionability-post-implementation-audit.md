# Actionable Anomaly Detection Post-Implementation Audit

## What Changed

Implemented the final plan direction:

- Added additive `Anomaly` metadata: comparison scope, baseline sample count,
  cohort key/label, reason, and dedupe key.
- Added additive dashboard `AnomalyRow` metadata for comparison context.
- Added `detect_actionable_anomalies(...)` as the shared high-level anomaly API.
- Reworked session, daily, model-day, and project-day detectors to score against
  prior comparable observations instead of broad whole-window medians.
- Kept existing robust gates: minimum sample count, robust scale, dollar-impact
  floor, fold-change requirement, and sigma display cap.
- Updated `caliper predict` and the dashboard adapter to use the shared
  actionable detector.
- Updated dashboard anomaly copy to explain the comparison set.
- Added regression coverage for broad-baseline suppression, metadata output, and
  dashboard comparison copy.

## Deviations

- Correlated anomaly dedupe remains conservative. The high-level API dedupes exact
  duplicate detector rows by dedupe key, but it does not collapse distinct
  investigation scopes such as session, project-day, and model-day for the same
  expensive day. This keeps useful drill-down paths while the stricter prior-cohort
  scoring removes the noisy broad-baseline rows.
- Existing dirty worktree changes were present in dashboard/advisor/efficiency files.
  Anomaly commits staged only anomaly-related hunks in shared files and intentionally
  left unrelated changes uncommitted.

## Verification

- `uv run pytest tests/test_anomaly.py tests/test_dashboard_html.py::test_anomaly_rows_use_constructive_copy_without_scale_noise tests/test_handoff_adapter.py::test_build_handoff_dashboard_adds_project_tracking_and_anomalies tests/test_cli_analytics.py::test_predict_json_shape tests/test_cli_analytics.py::test_predict_json_anomalies_include_actionability_metadata tests/test_json_contract.py`
  - Passed: 21 tests.
- `uv run pytest`
  - Passed: 888 tests.
- `uv run ruff check`
  - Initially failed in pre-existing dirty `src/caliper/arbitrage.py` and
    `src/caliper/efficiency.py` changes.
  - Mechanical type-annotation/line-wrap cleanup was applied in the working tree.
  - Passed after cleanup.

## Remaining Risks

- The repository still has unrelated uncommitted changes outside the anomaly work.
  They should be reviewed or committed separately by their owner.
- The anomaly detector now requires comparable prior history. This is intentional,
  but it means first-time expensive workflows move out of Anomalies unless another
  surface, such as top sessions or spend drivers, highlights them.

## Phase 9 Fixes

- Fixed all anomaly-specific audit findings.
- Fixed the verification-blocking ruff issues in the existing dirty advisor files
  without staging unrelated feature work.
- No Terraform commands were run.
- No push was performed.
