# Trifecta Probability v1: 2025 evaluation

**Verdict:** `TRIFECTA_PROBABILITY_V1_2025_EVALUATION_COMPLETE`.
This evaluates the fixed `sequential_p1_p2_p2_v1` method. The frozen P1/P2
models were not fitted, rerun, or adjusted. No odds or betting decision enters
this evaluation.

## Input and labels

- Frozen prediction input: `artifacts/p1_p2_baseline_v1_2025_holdout_predictions.npz`.
- Input SHA-256: `b05869f2df22477c17851014f8a9b4aca7dfb006acdf433b5a6cc1df7bf7915a` (same before and after evaluation).
- Period: 2025-01-01 through 2025-12-31; 51,311 eligible six-boat races.
- First and second labels come from the frozen input. Third place comes from
  `core.race_result.finish_position` with `raw.source_batch.source_table = 'brd_k3'`.
  All six K3 finish ranks were 1–6 exactly once and matched the frozen first
  and second labels for every race. R3 was not queried.

## Fixed method

For distinct boats A, B, C:

`P(A-B-C) = P1(A) * [P2(B) / sum(P2(x), x != A)] * [P2(C) / sum(P2(x), x != A,B)]`.

Denominators are computed by summing the remaining boats. If any denominator
is zero or cannot be calculated safely, the whole race is `NOT_EVALUABLE`;
there is no epsilon or uniform fallback. The combination order is lexicographic
by first, second, then third boat. Ties in top-k are resolved by that order.

## Coverage and metrics

| Measure | 2025 result |
| --- | ---: |
| Evaluable races | 51,311 |
| `NOT_EVALUABLE` races | 0 |
| Saved trifecta rows | 6,157,320 |
| Trifecta Log Loss, primary | 3.908322293832667 |
| 120-class Brier, sum of squared class errors per race | 0.9642840419379898 |
| Actual trifecta probability, mean | 0.03366825257967162 |
| Actual trifecta probability, median | 0.02484135477814658 |
| Top-1 hit rate | 0.090760265829939 |
| Top-3 hit rate | 0.225819025160297 |
| Top-5 hit rate | 0.3231081054744597 |
| Top-10 hit rate | 0.48408723275710863 |

The uniform 120-outcome Log Loss is `log(120) = 4.787491742782046`; the fixed
v1 result is lower by `0.8791694489493787`. This reference is descriptive,
not a comparison used to select another method.

## Validation and artifacts

Each evaluable race has 120 distinct ordered combinations, no repeated boat
within a combination, finite nonnegative probabilities, a probability sum of
one (absolute tolerance `2e-10`), and exactly one actual trifecta. All
violation counts were zero. An independent read of the saved artifact
reproduced every reported metric; its maximum race probability-sum error was
`6.661338147750939e-16`.

- Probability artifact: `artifacts/trifecta_probability_v1_2025.npz`,
  6,157,320 flat rows, SHA-256
  `1be7f4338693c0f1a4984f06b89c0ae5a3c08c03f7b6a7e94778800d848f068d`.
  Columns are `race_id`, `race_date_yyyymmdd`, `first_boat`, `second_boat`,
  `third_boat`, `trifecta_probability`, and `is_actual`.
- Metrics and validation: `artifacts/trifecta_probability_v1_2025_metrics.json`.
- Reproduction code: `scripts/evaluate_trifecta_probability_v1_2025.py`.
- Narrow tests: `tests/test_trifecta_probability_v1_2025.py`.

Any future improvement belongs to a separately versioned method. The next
task is an Odds Dataset v1 with confirmed trifecta odds and five-minute odds
kept separate; betting decisions follow later.
