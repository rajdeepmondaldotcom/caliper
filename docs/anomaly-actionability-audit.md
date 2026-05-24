# Actionable Anomaly Detection Audit

## Pre-Implementation Audit

The approved direction is compatible with the existing codebase.

Confirmed integration points:

- `src/caliper/anomaly.py` owns detector math and has no external runtime dependencies.
- `src/caliper/models.py` owns the `Anomaly` value object used by predict and dashboard.
- `src/caliper/dashboards/data_models.py` owns `AnomalyRow`.
- `src/caliper/dashboards/adapter.py` is the dashboard conversion seam.
- `src/caliper/dashboards/html.py` owns the rendered anomaly copy.
- `src/caliper/cli.py` owns `caliper predict` output assembly.

Gaps to close:

- Existing anomaly tests do not assert that broad all-session medians are rejected.
- Existing dashboard tests do not assert comparison context in anomaly copy.
- Current sort order prioritizes capped sigma before dollar impact, which makes many
  `>=20 sigma` rows look equally urgent.
- Existing anomaly output has no sample count or comparison scope, which prevents the UI
  from explaining why a row should be trusted.
- Several source files are already dirty. Implementation must stage carefully and avoid
  overwriting unrelated changes.

## Research Audit

The research did not change the architecture. It tightened three implementation choices:

- Require both absolute impact and relative deviation/fold-change, matching cloud cost
  anomaly products.
- Preserve actual, expected, impact, and percent-style reasoning instead of using only a
  z-score.
- Add root-cause/comparison context because FinOps anomaly workflows depend on routing
  and investigation metadata.

## Final Pre-Code Audit

No blocker remains.

The safest sequence is:

1. Add failing regression tests at the pure detector seam and dashboard/CLI seams.
2. Extend value objects with defaulted fields.
3. Implement prior-cohort scoring.
4. Update presentation and serialization.
5. Run targeted tests, then full verification.
6. Produce a post-implementation audit and fix any findings.
