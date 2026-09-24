# Current-term F count v1

Status: `CURRENT_TERM_F_COUNT_V1_FROZEN`.

`current_term_f_count` is the L3 race-entry `f_kaisu` value, already preserved as
`core.race_entry.f_count_current_term_raw` and parsed as
`core.race_entry.f_count_current_term`. It means the displayed current-term F
count (F0, F1, F2, ...), not an unserved F suspension. The source is an entry
list, so the feature does not read an individual result. A prediction-day F
cannot be added to that day's feature by this implementation. All races on D
use the same displayed count for a player; if source observations disagree or
any is missing or malformed, the entire player-day is NULL / `UNRESOLVED`.

Terms start on May 1 and November 1. `term_start_date` is metadata for this
definition. No preceding-term count is carried across a boundary. The view
is `core.race_entry_current_term_f_count_v1`, keyed by `(race_id, boat_no)`;
Prediction Dataset v1 can join on that key and select the count and status.
The view retains source IDs, hashes, and batch timestamps. Its
`historical_availability_status = NOT_VERIFIED` reflects that retrospective
extraction timestamps do not prove when each historical L3 row was first
available. Prediction Dataset v1 must preserve that distinction when claiming
an as-known-at-time backtest; it must not use results or a later source
correction to change an earlier observation.

The source-normalization contract is integer digits with optional outer
whitespace; all other raw forms remain NULL / `UNRESOLVED`. There is no
imputation to F0. This feature has no K3 dependency, so K3 result absence on
2025-08-12 does not change its count.

Local coverage, 2017-01-01 through 2026-09-19 (inclusive), from the view:

| Status / value | Entries |
|---|---:|
| VALID | 3,252,960 |
| UNRESOLVED | 0 |
| F0 | 2,748,383 |
| F1 | 485,719 |
| F2 | 18,772 |
| F3 or higher | 86 |

There were zero differing valid counts within a player-day. All 19 observed
May 1 / November 1 boundary dates had only F0 entries. As a targeted timing
check, 2025 F result events had 449 same-day later-race entries with unchanged
count and 1,048 next-day same-term entries with count increased by one. These
checks validate the source behavior for those observations; the view itself
does not derive its value from results.
