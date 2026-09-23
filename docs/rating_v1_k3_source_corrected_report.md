# Rating v1 K3-only source-corrected reevaluation

Frozen Rating Method v1 was replayed from 2017-01-01 on K3-only Canonical.
2017–2022 is warm-up. No model selection, parameter tuning, or v2 development was performed.

Method freeze SHA-256: `c7fbd2af725f2c9d62491923a5a411350a33076b8b1b305798c5ed07d23136fb`.
K3 result version: `K3_ONLY_RESULT_V1_b68a27cf8f653602`.
Ordered input SHA-256: `f71d5f77b83b7671331bb16629765cbec04e40ba57d4a7c28f471fc0a8faea8d`.
Deterministic replay SHA-256: `7663c3e050f3e4214c0c73e2bdb927b9289bf9f79472c5531656fe8cd7771025`.

## Annual old → K3-corrected

| Year | STRICT races | Course mean LL | P1 LL | P1 Brier | P1 ECE | P1 top1 | exact P2 LL | exact P2 Brier | exact P2 ECE | Overall LL | SHORT_50 LL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 51,246 → 51,246 | 1.488830 → 1.488827 | 1.280933 → 1.280927 | 0.607989 → 0.607987 | 0.024439 → 0.024437 | 0.563439 → 0.563439 | 1.696726 → 1.696727 | 0.801705 → 0.801705 | 0.010776 → 0.010756 | 1.664683 → 1.664683 | 1.771068 → 1.771068 |
| 2024 | 51,392 → 51,392 | 1.489451 → 1.489452 | 1.281331 → 1.281332 | 0.609120 → 0.609121 | 0.021145 → 0.021149 | 0.561391 → 0.561391 | 1.697570 → 1.697572 | 0.802135 → 0.802136 | 0.008576 → 0.008580 | 1.668118 → 1.668118 | 1.771368 → 1.771368 |
| 2025 | 51,137 → 51,311 | 1.488654 → 1.488789 | 1.280773 → 1.280803 | 0.609904 → 0.609926 | 0.018623 → 0.018581 | 0.559360 → 0.559315 | 1.696535 → 1.696775 | 0.801714 → 0.801809 | 0.007407 → 0.007296 | 1.662897 → 1.663106 | 1.770291 → 1.770335 |

Absolute and relative differences for every metric are in the comparison JSON.

## Source correction and limits

2022 STRICT warm-up races increased by 7; 2023 and 2024 STRICT scoring populations did not change.
The K3 migration audit records 54 added 2022 result boats and two corrected 2023 actual-course values.
For 2025, STRICT races increased by 174. Result-record-absent races decreased by 190,
while result-present but non-STRICT races increased by 16.
The migration audit records 1,500 added K3 result boats and 360 old-only boats removed;
the known 2025-08-12 60 races / 360 entries have no K3 individual result and receive no STRICT update.
These aggregate movements do not uniquely isolate the effect of each correction on the metrics.
Full historical per-player rating-state snapshots were not saved, so old-versus-new state hashes cannot be compared.
The frozen method and its artifact remain unchanged; future method changes require v2.
