# Odds Dataset v1 — 2025 trifecta

**Verdict:** `TRIFECTA_ODDS_DATASET_V1_READY`.

The cohort is exactly the 51,311 eligible 2025 races in
`artifacts/trifecta_probability_v1_2025.npz` (SHA-256
`1be7f4338693c0f1a4984f06b89c0ae5a3c08c03f7b6a7e94778800d848f068d`).
No probability values were recalculated. Odds outside this cohort were not added.

## Sources and classification

| Series | Observed source | Race and combination identity | Value and missing representation |
| --- | --- | --- | --- |
| Confirmed | `pckyotei.public.brd_o6` | `kaisai_nen`, `kaisai_tsukihi`, `kyoteijo_code`, `race_no`; each nine-character segment of `odds_sanrentan` has a three-digit ordered combination | Six-character odds token in each segment. `000000` is no votes, `******` is scratched, `099999` is a capped value (at least 9999.9), and ordinary six-digit tokens are tenths. Every raw odds token is retained exactly. |
| Five minutes before cutoff | Preserved dump, `br_model.kyoteibiyori_odds_5min` | `race_id`, `race_date`, `kyoteijo_code`, `race_no`, `bet_type='3t'`, `kumiawase`, `combination` | `odds_5min numeric(10,1)` and `odds_missing_reason`; `source_shimekiri=5`. The original decimal spelling of present values is retained. |

The project classification is `source_shimekiri=5` for five-minute odds and
other odds for confirmed odds. O6 has **no `source_shimekiri` column**; its
observed `record_id='O6'`, `data_kubun='3'`, and blank `odds_koshinjikan`
identify the confirmed O6 series. The five-minute source has the explicit
`source_shimekiri=5` column. No source was used to fill the other series.

For the cohort, O6 had 51,237 source rows, one per matched race, and no
duplicate race key. The five-minute dump had 120 rows for one matched race,
one per combination, and no duplicate combination key. The builder raises
`UNRESOLVED_DUPLICATE` if either source later presents an ambiguous key;
there is no average or latest-row rule.

The preserved dump's SHA-256 is
`c709a9ca54f1a793f0d4cdeb7d1a63a889ceeacc979deacb3793e31e102d3d56`.
The sole matched five-minute race was `2025-12-15` venue `01` race `01`
(core `race_id=503110`, source `race_id=202512150101`). Its
`retrieved_at` is `2026-08-01 22:08:36.042136+09`. That is a retrospective
retrieval time; the actual historical snapshot timestamp is unknown.
The dataset's classification does not establish availability at a historical
betting decision time.

## Dataset interface

`artifacts/trifecta_odds_dataset_v1_2025.npz` contains 6,157,320 flat rows at
`race_id × first_boat × second_boat × third_boat` grain. Every race has 120
distinct ordered combinations. Its columns are:

- `race_id`, `race_date_yyyymmdd`, `venue_code`, `race_no`, `first_boat`,
  `second_boat`, `third_boat`;
- `confirmed_odds`, `confirmed_odds_status`, `confirmed_odds_raw`;
- `odds_5min`, `odds_5min_status`, `odds_5min_raw`.

Status codes are in `artifacts/trifecta_odds_dataset_v1_2025_report.json`.
Numeric arrays use `NaN` as the NPZ representation of **NULL**; only
`status=VALID` is a price. `scripts.build_trifecta_odds_dataset_v1.odds_or_none`
returns Python `None` for every non-valid status. Raw tokens remain available
for source observations. `MISSING_SOURCE` has no raw token. The O6 cap token
does not become an invented exact price.

The identity arrays match the Probability artifact row for row. A consumer
can also join on all four identity fields and gets exactly one odds row per
Probability row. The two odds columns remain independent even when both are
valid for the same combination.

## Coverage on the 51,311-race Probability cohort

| Series | Complete races | Partial races | All-missing races | Valid rows | Missing rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| Confirmed | 51,237 | 0 | 74 | 6,148,440 | 8,880 |
| Five minutes before cutoff | 1 | 0 | 51,310 | 120 | 6,157,200 |

All 51,311 races and all 6,157,320 Probability combinations join to one
dataset row. There were no source duplicates, grain or boat-repeat violations,
non-positive numeric odds, non-NULL missing odds, or cross-series fills.
The 120 combinations for the one five-minute race have both independent odds
series present; this is co-presence, not source mixing. The low five-minute
coverage is retained explicitly and is not promoted to a larger sample.

## Reproduce and scope

Run `C:\Users\knkzh\AppData\Local\Python\bin\python.exe -m scripts.build_trifecta_odds_dataset_v1`
from this repository on a machine with the same read-only PostgreSQL source
and preserved dump. The builder refuses to overwrite an existing output;
verify or move the two named output artifacts before intentional regeneration.
The report includes source states, source hashes, row counts, coverage,
status codes, and validation counts. Narrow normalization tests are in
`tests/test_trifecta_odds_dataset_v1.py`.

This dataset does not calculate expected value, implied probability,
bet selection, return, or bankroll results.
