# Entry Course Index v1 K3-only source-corrected reevaluation

Frozen method: NATIONAL_BOAT_NO_ACTUAL_COURSE_FREQUENCY / RECENT_1Y. The method and freeze artifact were not changed; no method reselection used 2025.

Source-policy checkpoint: `fd49bffe83b2f23443ec5f525786c0dd309abe95`. K3 Canonical version: `K3_ONLY_RESULT_V1_b68a27cf8f653602`. Freeze SHA-256: `00233686ff49bca92e09645eb9177aecddd83d141f1a9478a5e6365a89374453`.

The read-only replay starts on 2017-01-01. Each day D uses the preceding calendar-year same date (Feb 29 maps to Feb 28), inclusive, through D exclusive. All D races use one D-1 state; eligible results are appended after scoring D.

Six-boat eligibility follows the freeze artifact. Edogawa is excluded from the national 6x6 counts and from all three scored cohorts. Its planned prediction rule remains predicted_course=boat_no, entry_fixed_effective=true, entry_fixed_basis=EDOGAWA_MODEL_RULE; Prediction integration is still absent.

No smoothing or epsilon was applied. Zero cells have probability zero; zero boat history is NOT_EVALUABLE. A zero actual-outcome probability would make the unclipped log loss infinite.

| Year | Eligible races old→new | Entries old→new | NOT_EVALUABLE old→new | Zero actual p old→new | Log loss old→new | Brier old→new | Top1 old→new | ECE old→new |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 52473→52473 | 314838→314838 | 0→0 | 0→0 | 0.422371501→0.422384442 | 0.187281130→0.187290265 | 0.896241877→0.896235524 | 0.003212404→0.003211605 |
| 2024 | 52677→52677 | 316062→316062 | 0→0 | 0→0 | 0.400247604→0.400247635 | 0.176494271→0.176494285 | 0.902778569→0.902778569 | 0.004686514→0.004686803 |
| 2025 | 52080→52265 | 312480→313590 | 0→0 | 0→0 | 0.398672849→0.399521177 | 0.174186340→0.174587503 | 0.904409882→0.904174240 | 0.001105662→0.001215036 |

Full absolute and relative differences are in the comparison JSON. The old development aggregate and old 2025 holdout are historical comparison values only, never formal K3 input or validation.

## Source and zero-probability audit

K3-lineage result boats: 2,969,286; non-K3: 0. The known 2025-08-12 K3-absent set has 60 races, 360 entries, and zero Canonical results; old actual_course values were not carried forward.

- 2023: boat-number minimum history totals {'1': 51994, '2': 51994, '3': 51994, '4': 51994, '5': 51994, '6': 51994}; minimum course-cell count 7; zero-cell boat-days 0; zero-history boat-days 0; actual-outcome probability-zero 0.
- 2024: boat-number minimum history totals {'1': 52019, '2': 52019, '3': 52019, '4': 52019, '5': 52019, '6': 52019}; minimum course-cell count 5; zero-cell boat-days 0; zero-history boat-days 0; actual-outcome probability-zero 0.
- 2025: boat-number minimum history totals {'1': 52057, '2': 52057, '3': 52057, '4': 52057, '5': 52057, '6': 52057}; minimum course-cell count 1; zero-cell boat-days 0; zero-history boat-days 0; actual-outcome probability-zero 0.

## Replay identity

Ordered input SHA-256: `be780e7598a70d0dfd7e941b1ec59a6a05f94a7ff6693bfad9810b837305c62a`.
History state SHA-256: `3627876023137fcf5b4361e51b54cf7716b3be0003151875b1d5277e5505e9fe`.
Eligible result SHA-256: `a5e2336562b98c50e79299bb184912b4060d4b717257e9d00e940b4fe4e4f71a`.
Metrics SHA-256: `4e5814717cafed09f6fed53532a9d4151021b61b85dc88c0d3d5ca8a846a555b`.

A separate database replay matched all four hashes and the complete replay data. The
verification JSON records this equality. An independent SQL aggregation of the frozen
six-boat eligibility returned 52,265 non-Edogawa 2025 races, equal to the replay.

The 2023 and 2024 eligible cohorts stayed at 52,473 and 52,677 races. The 2025
cohort grew by 185 races (1,110 entries) after source correction, even though the
60 known K3-absent races are excluded. The exact per-race contribution of all
historical source changes was not reconstructed from the old source; the old
artifacts serve only as aggregate comparison baselines.

The source-correction effects are the changed K3 Canonical training windows and scored outcome cohort. Prior migration recorded two 2023 actual-course corrections, added K3 results, and 60 unsupported 2025-08-12 race results removed. This replay does not consult R3 to attribute individual score differences. Full historical publication vintage availability remains unverified, as in the v1 freeze.
