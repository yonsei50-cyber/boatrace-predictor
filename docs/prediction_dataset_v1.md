# Prediction Dataset v1

**Verdict:** `PREDICTION_DATASET_V1_READY` for the canonical snapshot through
2026-09-19. The table is `core.prediction_dataset_v1`; its primary key is
`(race_id, boat_no)`. `race_id` is the existing canonical key, with date,
venue, race number, boat number, and player ID retained as readable identity.
The build script refuses to overwrite an existing table.

The builder is
`C:\Users\knkzh\Documents\boatrace-predictor\scripts\build_prediction_dataset_v1.py`.
It creates the table and loads every row in one transaction. To reproduce in a
fresh canonical database, run:

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -m scripts.build_prediction_dataset_v1
```

The included columns are canonical L3 national win rate and status, Rating v1
six P1 course ratings plus six exact P2 course ratings plus overall and SHORT_50
ratings, Entry Course Index v1 six course probabilities, F Suspension State v1,
Current Term F Count v1, and both Motor A v1 scores with supporting status and
counts. Rating actual course is never a pre-race column. For Edogawa, the frozen
entry rule yields a one-hot vector at `boat_no` and status
`EDOGAWA_MODEL_RULE`. Null Motor A scores, unresolved F state, and unresolved
national rate are preserved.

All stateful features for date D are calculated before any D result update.
Every race on D receives the same preceding-day state. K3 is the only
individual-result source. `label_eligible` requires six canonical entries and
the exact 1–6 numeric-finish permutation with no special, unresolved, or
missing K3 result. `label_p1` and `label_p2` are 1 for finish 1 and 2 and 0
for other normal finishes only when the race is eligible; otherwise both are
NULL. Actual course is not a label eligibility condition.

## Coverage

These counts are independent DB aggregations after the build. Missing columns
are row counts; `F ?` counts `UNRESOLVED` states. 2026 ends on 09-19, with
09-19's 936 entries retaining NULL labels because K3 results are absent.

| Year | Races | Rows | Eligible races | Eligible rows | Rate NULL | Entry NULL | F ? | Term F NULL | Motor base NULL | Motor current NULL |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2017 | 55,032 | 330,192 | 50,668 | 304,008 | 541 | 1,008 | 192,030 | 0 | 29,178 | 66,386 |
| 2018 | 55,332 | 331,992 | 50,584 | 303,504 | 623 | 0 | 71,284 | 0 | 14,450 | 63,036 |
| 2019 | 55,176 | 331,056 | 50,766 | 304,596 | 658 | 0 | 31,485 | 0 | 12,051 | 61,920 |
| 2020 | 55,464 | 332,784 | 50,923 | 305,538 | 667 | 0 | 15,759 | 0 | 11,277 | 63,451 |
| 2021 | 55,728 | 334,368 | 50,864 | 305,184 | 762 | 0 | 8,287 | 0 | 14,186 | 63,540 |
| 2022 | 56,436 | 338,616 | 51,264 | 307,584 | 631 | 0 | 3,782 | 0 | 13,772 | 65,026 |
| 2023 | 55,992 | 335,952 | 51,246 | 307,476 | 635 | 0 | 2,590 | 0 | 12,447 | 63,981 |
| 2024 | 56,064 | 336,384 | 51,392 | 308,352 | 693 | 0 | 1,906 | 0 | 13,168 | 64,588 |
| 2025 | 55,908 | 335,448 | 51,311 | 307,866 | 658 | 0 | 14,330 | 0 | 16,339 | 63,149 |
| 2026 | 41,028 | 246,168 | 37,689 | 226,134 | 357 | 0 | 15,220 | 0 | 12,472 | 47,961 |

No 2025 target association, model fit, feature selection, or performance metric
was calculated. The next step is to freeze the P1/exact P2 model and evaluation
protocol before viewing 2025 model performance. Historical publication-time
availability for L3 observations is recorded as unverified by the canonical
source views; D-1 result ordering does not establish live publication readiness.
