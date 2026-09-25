# Pre-race Time Characteristics v1: resolved C4 timing-packet checkpoint

Status: **RESOLVED_BY_EXPLICIT_ONE_RACE_QUARANTINE**. This document records
the 2026-09-25 evidence and the pre-decision counts. The user subsequently
authorized excluding Kojima 2024-01-02 12R from all three C4 numeric series,
while retaining C3 and forbidding generalization into a threshold or repair.
The updated results are in `pre_race_time_characteristics_v1_final_report.md`
and `pre_race_time_characteristics_v1_metrics.json`. This checkpoint does not
freeze a feature method or authorize C4 for Prediction.

## Gates that reconciled

- Source C4: 145,761 races / 874,555 rows, 2023-10-12 through 2026-09-18.
- C4 structure gate (six stored slots and at least one numeric C4 field in each
  slot): 4,135 races fail. This rule does not infer a scratched boat or remap a
  value.
- C3 `tenji_time='0000'` on any boat: 1,842 C4 source races. After the C4
  structure and carry gates, this removes 24 additional races, as authorized.
  It does not mean that `0000` proves a scratch. C3 exhibition values remain
  independently eligible.
- The existing informative adjacent-packet predicate reproduced all 373
  previous-race / later-race pairs. There are 373 distinct later races in 329
  chains, including 29 multi-pair chains. The 373 later races are excluded;
  no previous race is classified as carried solely by being first. Of the 329
  first races, 316 pass all other gates and 13 fail the independent mapping
  gate.
- All 79 prior mapping suspects and all 11 Kojima five-row races fail the C4
  numeric gate. No K3 result value is used in a gate, mapping, baseline, or z.
- Final gate counts before the unresolved timing-packet decision: 141,231
  `SAFE`, 4,157 `UNAVAILABLE_MAPPING`, and 373
  `CARRY_FORWARD_INVALID` races. `SAFE` here certifies only the defined mapping
  gate; it is not a certificate that every numeric field is semantically valid.

## Newly unresolved source packet

Kojima (`16`), 2024-01-02, 12R passes the authorized mapping and carry gates.
All six C3 exhibition times are nonzero (`0668,0673,0674,0677,0677,0683`),
and the race is not one of the 373 carried later races. Its C4 raw packet is:

| stored boat slot | `isshu` | `hanshu` | `mawariashi` | `chokusen` |
|---:|---:|---:|---:|---:|
| 1 | `0005` | blank | `0675` | `3727` |
| 2 | `0000` | blank | `0675` | `3740` |
| 3 | `0000` | blank | `0683` | `3737` |
| 4 | `0000` | blank | `0674` | `3767` |
| 5 | `0000` | blank | `0691` | `3833` |
| 6 | `0000` | blank | `0680` | `3783` |

The user-confirmed `raw / 100` conversion gives one `isshu` observation of
0.05 seconds and six `chokusen` values of 37.27–38.33 seconds. The observed
raw shape is consistent with a misplaced field packet, but its cause and
correct values are **unverified**. It is not repaired, and no numeric
plausibility cutoff has been adopted. The current preliminary profiles count
one lap, six turning-foot, and six straight observations from this race.

Other observed extremes include a 45.44-second lap and large negative
candidate z values. They are reported as evidence, not filtered. No general
anomaly rule, field correction, or threshold was added.

## Resolution

The user selected the exact-race quarantine. The code checks the stored packet
before excluding this one race's C4 numeric observations. The final metrics
therefore remove one lap, six turning-foot, and six straight observations
compared with the pre-decision counts above. C3 exhibition remains untouched.
This decision does not authorize any other race- or value-based quarantine.
