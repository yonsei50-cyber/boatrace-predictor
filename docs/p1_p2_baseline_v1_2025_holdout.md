# P1 / exact P2 Baseline v1: 2025 independent holdout

**Verdict:** `P1_P2_BASELINE_V1_2025_INDEPENDENT_HOLDOUT_COMPLETE`.
This means the frozen method was evaluated once, not that a performance
threshold was passed. No threshold was set before this evaluation. The v1
method was not changed after seeing the 2025 results.

## Identity and frozen method

- Source: `core.prediction_dataset_v1`, existing K3-only labels, `label_eligible = TRUE`.
- Period: 2025-01-01 through 2025-12-31 inclusive. No 2026 rows.
- Eligible races: 51,311; six-boat rows: 307,866.
- P1: six-boat race-wise linear softmax, `CORE_MOTOR` (CORE + MOTOR), L2 0.01,
  temperature 1.0143334057206692.
- Exact P2: six-boat race-wise linear softmax, `FULL`, L2 0.01,
  temperature 1.0066548794380772.
- Freeze SHA-256: `f7dcb2f64fbc345de64767dcf9723a52b4db972121f30320c85ee48ea606a9f4`.
- Model JSON SHA-256: `3954fbecb97dae5816b45e00735ab4ec31f13dbdb13d21c2c4022fca9d37f54e`.

The evaluator uses the frozen coefficients, ordered features, categorical
vocabulary, numeric preprocessing statistics, missing-value treatment, and
temperatures. It imports the development transform and metric functions. It
does not call a fit routine. The model's recorded fitted years are 2017–2024.

## Metrics

The definitions are unchanged from development: race mean negative log
likelihood, six-boat squared-error Brier sum per race, ten equal-width bins
across all boat predictions for ECE, and race-level highest-probability hit
rate for top1. The 2022 and 2023 numbers are forward selection folds, and
2024 is after temperature calibration; they use their respective pre-2025
training states. The 2025 numbers use the final frozen 2017–2024 model.

| Target | Year | Races | Log Loss | Brier | ECE 10-bin | Top1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P1 | 2022 | 51,264 | 1.180534319 | 0.578416324 | 0.002646430 | 0.573735955 |
| P1 | 2023 | 51,246 | 1.189455131 | 0.582969849 | 0.002110294 | 0.571693400 |
| P1 after T | 2024 | 51,392 | 1.199160738 | 0.586975750 | 0.002170778 | 0.569096357 |
| P1 | 2025 | 51,311 | 1.199922972 | 0.587272358 | 0.002652481 | 0.569215178 |
| exact P2 | 2022 | 51,264 | 1.668192249 | 0.797318815 | 0.010071951 | 0.280586767 |
| exact P2 | 2023 | 51,246 | 1.675793339 | 0.799709288 | 0.009942532 | 0.275553214 |
| exact P2 after T | 2024 | 51,392 | 1.676508150 | 0.799955670 | 0.009527299 | 0.273252646 |
| exact P2 | 2025 | 51,311 | 1.672845340 | 0.798877450 | 0.008953478 | 0.278127497 |

## Validation and artifacts

The source query restricts the period and eligible rows. Every returned race
had six ordered boats, one P1 label, and one distinct P2 label. For each
target, non-finite probability count = 0, out-of-range probability count = 0,
and race probability-sum violation count = 0 (absolute tolerance `2e-7`).
The output file was read back: dates span 2025-01-01 through 2025-12-31,
its arrays have the expected shapes, and its hash matches the metrics and
one-shot gate. No R3 source reference was added to the evaluator. The frozen
feature definitions were not reaudited in this task.

- `artifacts/p1_p2_baseline_v1_2025_holdout_predictions.npz`:
  race-level `race_id` and `race_date_yyyymmdd` arrays of shape `(51311,)`;
  `boat_no`, `label_p1`, `label_p2`, `pred_p1`, and `pred_p2` arrays of shape
  `(51311, 6)`, in boat number order. SHA-256:
  `b05869f2df22477c17851014f8a9b4aca7dfb006acdf433b5a6cc1df7bf7915a`.
- `artifacts/p1_p2_baseline_v1_2025_holdout_metrics.json`: full-precision
  metrics, validation counts, method identity, and artifact hashes.
- `artifacts/p1_p2_baseline_v1_2025_holdout_gate.json`: `COMPLETED`. The
  evaluator refuses a second run when this gate or an output exists.

The next separately scoped task may form 120 trifecta probabilities from
these frozen P1/P2 predictions with `sequential_p1_p2_p2_v1`. This checkpoint
contains no odds or betting logic and provides no basis to retune v1.
