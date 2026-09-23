# Entry Course Index Method v1 freeze

## A. Verdict

`ENTRY_COURSE_INDEX_METHOD_V1_FROZEN` — the development-selected national,
unsmoothed one-calendar-year `boat_no × actual_course` frequency method is
specified in `artifacts/entry_course_index_method_freeze_v1.json`. This freeze
does not integrate it into Prediction, evaluate 2025, or modify Rating v1.

## B. Repository identity and scope

- Repository: `C:\Users\knkzh\Documents\boatrace-predictor`.
- Starting branch: `main`. Starting `HEAD` and local `origin/main`:
  `a60ad15c9ce223e281bb79272bc2023379636280`.
- Pre-existing dirty set: `AGENTS.md`, `.codex/config.toml`. Both are preserved.
- Only the new reference calculation, freeze JSON, this report, and its tests
  belong to this checkpoint. The development script and JSON remain in
  `.local` and are not Git-tracked.

## C. Freeze method

For each known `boat_no` 1–6, count observed `actual_course` 1–6 among eligible
non-Edogawa Canonical races in the specified date window. Divide each of the
six counts by that boat number's total count. There is no smoothing, prior,
epsilon, ML model, or venue-specific fit. The resulting six probabilities lie
in `[0,1]` and sum to one when the total is positive. An individual zero cell
has probability zero.

`scripts/entry_course_index_v1.py` is a pure reference calculation, not a DB
job or Prediction integration. Its source SHA-256 is recorded in the freeze
JSON as UTF-8 with LF line endings. It deliberately keeps the Rating v1 files
untouched.

## D. Exact one-year window and daily boundary

For prediction date D, the inclusive start is `D.replace(year=D.year-1)`;
when D is February 29, the inclusive start is February 28 of the preceding
year. The end is **exclusive D**. The unit is calendar date, not 365 days or
race count. Thus D=`2024-01-01` uses `2023-01-01` through `2023-12-31`, and
D=`2024-02-29` uses `2023-02-28` through `2024-02-28`.
The development dataset begins on `2017-01-01`; earlier results are not
introduced if a caller supplies them to the reference calculation.

Every race on D reads the same counts from races with `race_date < D`. D
results become eligible only on D+1. The development script implements the
same `age_start` endpoint rule and appends a day's counts only after scoring
that day. A different endpoint convention would invalidate this freeze.

## E. Course-specific eligibility

An update race must have six entries numbered 1–6, `RESULT_RECORDS_PRESENT`,
six Canonical result rows, `actual_course` exactly the permutation 1–6, and at
least one non-NULL numeric `finish_position`. This matches the development
script's actual `quality_add` conditions. It does **not** require Rating STRICT
or six numeric finishes. Special finishes may remain when the course evidence
is complete. A missing `actual_course` is never filled with `boat_no`.

The development read-only extract covered 2017-01-01 through 2024-12-31. It
contained 418,128 eligible non-Edogawa races and 2,508,768 eligible entries.

## F. Zero-history and zero-cell behavior

For a boat number with no eligible history in the window, the v1 output is
`NOT_EVALUABLE` with no probability vector. It never falls back to a longer
window, uniform values, or the boat-number one-hot vector.

The development evaluator's zero-individual-cell guard raises an error rather
than scoring such a case. This branch was **not observed** in the evaluated
2023–2024 period: the minimum individual training cell count was 5. The formal
v1 rule for a positive total and one zero cell is explicitly `P=0`; the
reference calculation and tests cover it. This is a specification for an
unobserved branch, not a claim that the development evaluator tested it.

At 2025-01-01, the one-year window consists solely of 2024 results, and the
saved 2024 national 36-cell table has a minimum count of 5. Thus zero history
does not arise at that boundary. Actual 2026 production windows cannot be
checked here without inspecting 2025 results; their status remains unknown.

## G. Edogawa rule

Edogawa (`venue_code=3`) is excluded from national count updates. The planned
Prediction rule remains `predicted_course=boat_no`, with
`entry_fixed_effective=TRUE` and `entry_fixed_basis=EDOGAWA_MODEL_RULE`.
This is a model rule, not a claim of an official fixed-entry source field.
Actual Edogawa results keep observed `actual_course` unchanged. Development
found 414 mismatched entries among 99,708 and 173 races with a mismatch among
16,618 eligible races. These observations do not change the rule.

## H. Development evidence

The formal JSON copies full-precision values from the saved local development
artifact after programmatic comparison with every user-specified rounded
value. The 2024 per-entry six-class Log Loss was:

| Method | 2024 Log Loss |
|---|---:|
| Recent 1 calendar year — selected | 0.400248 |
| Recent 2 calendar years — runner-up | 0.400444 |
| Recent 3 calendar years | 0.400811 |
| Recent 5 calendar years | 0.401827 |
| All available history | 0.403801 |

The selected one-year method had 2023 Log Loss **0.422372**. In 2024 it had
multiclass Brier **0.176494**, top-1 accuracy **90.278%**, and 10-bin top-1 ECE
**0.004687** over 316,062 non-Edogawa entries. Its 2024 Log Loss by boat number
1–6 was **0.057203, 0.281376, 0.368101, 0.509062, 0.628832, 0.556911**.
Top-1 accuracy alone does not select this method; the candidate windows mostly
share the same most likely course.

The freeze JSON records the local development script and artifact SHA-256,
the extracted-row and SQL hashes, and the reference-code hash. The saved DB
snapshot identifier is ephemeral; it is not a historical as-of dataset
version. The `.local` files are not required by the repository tests.

## I. As-of and Rating limits

The comparison is **date-causal D-1 OOS**. Current Canonical data do not prove
which correction vintage was published at every historical prediction date.
Full vintage as-of certification is therefore unverified. This is not a
blocker for this retrospective method freeze, but it remains a separate gate
for strict historical Prediction simulation.

The existing Rating v1 freeze contains its own venue-by-boat Dirichlet course
mixture diagnostic. That frozen Rating specification is unchanged. This new
national, unsmoothed Entry Course Index is a separate layer. A later
Prediction implementation must explicitly decide and test the interface; this
freeze does not silently replace the Rating v1 diagnostic.

## J. Verification and holdout discipline

`tests/test_entry_course_index_v1.py` checks the six-probability range and sum,
window endpoints including leap day, D-day exclusion, Edogawa exclusion,
course-specific eligibility, zero-cell and zero-history behavior, and JSON
consistency with the reference code and selected method. The narrow suite
passed 6 tests. The 2025 holdout was not queried or scored during this freeze.
Any later change to method, window, or eligibility requires a new version;
2025 outcomes cannot then be retuned and reused as an independent holdout.
