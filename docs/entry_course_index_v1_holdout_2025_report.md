# Entry Course Index v1: independent 2025 holdout

## A. Verdict

`ENTRY_COURSE_INDEX_V1_HOLDOUT_EVALUATED_NO_PREDECLARED_PASS_THRESHOLD`.
The frozen one-calendar-year national `boat_no × actual_course` method was
evaluated once on 2025-01-01 through 2025-12-31. No PASS/FAIL threshold was
fixed before the outcomes were read, so none is invented after the run.
Entry Course Index v1, Rating v1, and the Edogawa rule are unchanged.

## B. Repository and freeze identity

- Repository: `C:\Users\knkzh\Documents\boatrace-predictor`, branch `main`.
- Preflight `HEAD` and `origin/main`:
  `f8a4d4d0d2bff962489d7c492f391951a1eccc6d`.
- Freeze artifact: `artifacts/entry_course_index_method_freeze_v1.json`,
  SHA-256 `00233686ff49bca92e09645eb9177aecddd83d141f1a9478a5e6365a89374453`.
- Frozen reference implementation LF-normalized SHA-256:
  `4a6486e527b788c328ec6cbf8db8856668ac83af48d8413c86f1d4401ceb856e`.
- The freeze specifies `RECENT_1Y`, no smoothing or fallback, course-specific
  eligibility, and the separate `EDOGAWA_MODEL_RULE`. The holdout evaluator
  checks those fields and the exact development SQL hash before DB access.
- Pre-existing dirty files `AGENTS.md` and `.codex/config.toml` were not edited.

## C. One-shot gate and data identity

The gate is `artifacts/entry_course_index_v1_holdout_2025_gate.json`. It was
written `READY` before any 2025 outcome row was returned, with preflight start
`2026-09-23T04:28:00.817920+00:00`. In a read-only `REPEATABLE READ` snapshot,
preflight verified all **2,671,344** ordered 2017–2024 extraction rows against
the frozen development SHA-256
`9f671b9fcd70feeae45d6a315e2171201ba810f02c582e7f35c9e86b150989db`.
It also recorded the 108 monthly dataset metadata shard chain hash
`a0bfb0bf2f9e6b4c055372ded6d805326f8162c6ff69d0d733c395ea3bc8d610`,
the freeze/reference/evaluator hashes, the holdout SQL hash, and the Git HEAD.
The gate records **0** 2025 outcome rows read before it was saved.

Evaluation rechecked the identities and shard chain, marked the gate
`STARTED` at `2026-09-23T04:30:41.014960+00:00`, then read the 2024–2025
extract once. It saved the result and marked the gate **`COMPLETED`** at
`2026-09-23T04:32:45.394965+00:00`. The gate's result SHA-256 matches the
saved result bytes. A second run is rejected before DB access. The 2025
extract contained 671,832 rows, with SHA-256
`bf5d17a01ce64fd0c93694c67cb254bb7a2d595395cf2e52981e42ec041f048d`.
No 2026 race was included.

## D. 2025 eligibility and evaluated population

| Category | Races | Entries |
|---|---:|---:|
| All Canonical races | 55,908 | — |
| Non-Edogawa races | 53,520 | — |
| Non-Edogawa eligible | **52,080** | **312,480** |
| Non-Edogawa excluded | 1,440 | — |
| Evaluated | **52,080** | **312,480** |
| `NOT_EVALUABLE` | — | **0** |

The frozen course-specific requirements were applied, including six entries,
`RESULT_RECORDS_PRESENT`, six Canonical results, a 1–6 actual-course
permutation, and at least one numeric finish. Rating STRICT was not substituted.
All 52,677 eligible non-Edogawa 2024 races were present in the warm-up extract,
matching the frozen development scoring population.

## E. 2025 overall metrics

| Metric | Independent holdout |
|---|---:|
| Multiclass Log Loss | **0.398673** |
| Multiclass Brier sum | **0.174186** |
| Top-1 accuracy | **90.441%** |
| 10-bin top-1 ECE | **0.001106** |

The Log Loss is finite without changing any production probability or adding
epsilon: there were no actual outcomes assigned probability zero.

## F. Boat-number metrics

Each boat number has 52,080 evaluated entries.

| `boat_no` | Log Loss | Brier sum | Top-1 accuracy |
|---:|---:|---:|---:|
| 1 | 0.068704 | 0.022104 | 98.884% |
| 2 | 0.286730 | 0.114668 | 93.994% |
| 3 | 0.373030 | 0.152519 | 91.912% |
| 4 | 0.505615 | 0.216611 | 88.232% |
| 5 | 0.617581 | 0.291673 | 83.416% |
| 6 | 0.540377 | 0.247543 | 86.208% |

## G. Monthly 2025 Log Loss

| Month | Evaluated entries | Log Loss |
|---|---:|---:|
| Jan | 28,164 | 0.368968 |
| Feb | 24,468 | 0.406598 |
| Mar | 25,536 | 0.396265 |
| Apr | 23,958 | 0.415950 |
| May | 28,458 | 0.410948 |
| Jun | 27,018 | 0.385879 |
| Jul | 29,310 | 0.405727 |
| Aug | 29,154 | 0.398514 |
| Sep | 23,928 | 0.385864 |
| Oct | 23,112 | 0.411057 |
| Nov | 22,170 | 0.404566 |
| Dec | 27,204 | 0.397719 |

## H. Frozen development and independent holdout

| Period | Role | Evaluated entries | Log Loss | Brier sum | Top-1 accuracy | Top-1 ECE |
|---|---|---:|---:|---:|---:|---:|
| 2023 | Development | 314,838 | 0.422372 | — | — | — |
| 2024 | Validation | 316,062 | 0.400248 | 0.176494 | 90.278% | 0.004687 |
| 2025 | Independent holdout | 312,480 | **0.398673** | **0.174186** | **90.441%** | **0.001106** |

The 2023/2024 values come from the committed freeze artifact; 2025 was
calculated once from frozen v1. These observations do not authorize tuning v1
or establish a post hoc PASS criterion.

## I. Zero history and zero actual probability

There were **0** `boat_no × D` instances with zero total history on a 2025
non-Edogawa race date, **0** `NOT_EVALUABLE` entries, and **0** actual outcomes
assigned probability zero. The evaluator has explicit fixture tests for both
unobserved branches. It neither falls back nor clips probabilities for Log
Loss; if a zero-probability actual outcome occurs, it records the date, boat
number, and course and reports the affected Log Loss as infinite.

## J. Edogawa 2025 diagnostic

Edogawa contributed no national training or evaluation entry. Of 2,388
Edogawa races, 2,185 met the course-specific result requirements. The model
rule `predicted_course=boat_no` matched 13,104 of their 13,110 entries;
**6 entries** in **3 races** differed from observed `actual_course`. The rule
was not changed, and observed results were not overwritten.

## K. Date-causal leakage audit

The holdout extract is bounded before `2026-01-01`; the reference window uses
the previous calendar date inclusive and D exclusive. The evaluator first
freezes one probability vector per boat number for D, scores every D race,
then appends D's eligible non-Edogawa courses to history for D+1. Runtime
checks reject future dates in the history deque, changing counts during
same-day scoring, unexpected warm-up population, and count reconciliation
failures. Fixture tests exercised same-day isolation and window expiry.

## L. Historical as-of limit

This is a **date-causal D-1** evaluation on results currently saved in
Canonical. It does not prove the exact publication and correction vintage
available on each historical D. Full vintage as-of simulation remains
unverified and is a separate requirement for later Prediction evaluation.

## M. Tests

Before the real holdout, the frozen v1 and new holdout fixture suites passed
**13 tests**. They cover freeze identity, leap-date window, D-1 ordering,
same-day isolation, Edogawa separation, course eligibility, probability
normalization, zero history, zero actual probability, the single-run gate,
and rejection of 2026 rows. No test calls the real holdout twice.

## N–P. Files, Git state, and checkpoint decision

The holdout evaluation left five files for checkpoint review: the gate JSON,
result JSON, this report, evaluator script, and fixture test. The freeze
artifact and reference implementation were unchanged. The one-shot gate is
`COMPLETED`, and the result hash and internal counts reconcile. Any future
method change must be Entry Course Index v2; 2025 would then be development
evidence rather than a second independent holdout.
