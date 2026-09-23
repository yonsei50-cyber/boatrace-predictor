# K3-only source policy: pre-migration impact audit

> Historical read-only audit. The subsequent
> [formal K3-only migration](k3_only_formal_migration_report.md) directly
> checked all 60 old-Canonical-only 2025 races in K3, found all 60 absent
> without a probe bug, and rebuilt the populated Canonical result set from
> K3. Counts and runtime descriptions below are pre-migration observations.

Date: 2026-09-23. Verdict: `K3_ONLY_MIGRATION_READY` for a subsequent controlled
migration and revalidation. This audit and its probes did not change either
database, frozen checkpoint, or prediction path.

## Binding source policy

`pckyotei.public.brd_r3` is prohibited throughout this project: acquisition,
reconciliation, validation, migration, Canonical, features, models, evaluation,
and audit. Result observations must come from `pckyotei.public.brd_k3` only.
The former primary/fallback proposal is retired. The user has confirmed that K3
contains the required result information; this audit does not reopen that
assumption. R2 and other sources remain available under their own rules.
Historical reports and frozen artifacts describe past work, not current source
authority. Their old metrics remain recorded and are not deleted here.

## Repository and safety boundary

- Root: `C:/Users/knkzh/Documents/boatrace-predictor`
- Branch: `main`
- HEAD = `origin/main`: `953c6c8a4e9b35141ec8a409c85742096d427cd2`
- Initial working tree: modified `AGENTS.md` and `.codex/config.toml` only.
  Neither was edited, staged, or committed by this audit.
- Source and target PostgreSQL connections were explicitly read-only. Probe
  outputs are local JSON; no schema/data migration, Prediction wiring,
  checkpoint deletion, commit, or push occurred.

## Direct and indirect reference inventory

Active import paths: `scripts/import_sample.py`, `scripts/import_history.py`,
`scripts/history_source.py` (imports `KEYS` from `import_sample.py`),
`scripts/normalize.py` (table-neutral `chakujun/shinnyu_course/st/kigo` mapper),
and `scripts/migrate.py` (applies every migration including
`sql/migrations/0004_result_states.sql`). The migration creates
`core.result_source_evidence`, `core.race_result_state`, and
`core.boat_finish_state` with the forbidden result lineage.

Direct preflight, audit, and verification paths: `scripts/preflight_results.py`,
`scripts/preflight_odds.py` (result race denominator),
`scripts/investigate_result_evidence.py`, `scripts/audit_history.py`,
`scripts/audit_result_states.py`, `scripts/audit_rating_prep.py`,
`scripts/verify_history.py`, and `scripts/verify_import.py`.

Direct tests: `tests/test_history.py`, `tests/test_result_states.py`, and
`tests/test_database.py`. These fixtures/assertions encode the previous source.

Indirect active lineage, even without a source-table literal:

- `scripts/freeze_history.py` freezes `core.race_result` and its source references.
- `scripts/compare_rating_methods.py` and
  `scripts/evaluate_rating_v1_holdout_2025.py` consume result/state views.
- `scripts/entry_course_index_v1.py` consumes actual course data supplied by
  the caller; `scripts/evaluate_entry_course_index_v1_holdout_2025.py`
  fetches it from the existing result/state views.
- `scripts/motor_a_v1.py` consumes supplied result/finish-state inputs;
  `.local/motor_a_development.py` and `.local/motor_a_confounds.py` fetch the
  existing result/state values.
- `.local/entry_course_development_readonly.py` fetches existing result/state.
- Existing `.local/f_suspension_*` exploration also reads old result/state or
  directly queries the prohibited table. It must not be rerun as current proof.

Historical tracked documents with a direct literal or old source conclusion:
`README.md`, `docs/source_mapping.md`, `docs/phase2_report.md`,
`docs/phase25_report.md`, `docs/phase3b_report.md`,
`docs/rating_prep_report.md`, `docs/result_anomalies_preflight.md`,
and `docs/environment_preinfo_source_inventory.md`. Additional downstream
checkpoint reports/artifacts do not necessarily spell out the source name but
inherit the old Canonical lineage. Those are listed in the checkpoint section.

All matched filenames, including ignored `.local` exploration and generated
artifacts, are in the appendix. The inventory used
`rg -l -i 'brd_r3|\bR3\b|r3_' scripts sql tests docs artifacts README.md .local`;
the table-neutral and downstream aliases above were checked separately.

## K3 field mapping for a future Canonical migration

The K3 schema was read from `information_schema` and the 2017+ value domains
were counted from K3 only. The mapping below is the probe rule, not a write to
Canonical. Every source string remains available as a raw observation after
future K3 Raw preservation.

| Canonical/result concept | K3 source | Probe rule |
|---|---|---|
| Race identity | `kaisai_nen`, `kaisai_tsukihi`, `kyoteijo_code`, `race_no` | Preserve raw tuple; parse date/venue/race for natural-key join. |
| Boat identity | `teiban` | Parse 1–6; do not use K3 `boat_no` (hull number). |
| Player identity | `toroku_bango` | Match L3 registration for the same race/boat; mismatches are reported. |
| `finish_raw` | `chakujun` | Preserve exact token, including padding. |
| `finish_position` | `chakujun` | Only numeric 1–6. Special tokens and `00` remain NULL. |
| `result_status` / F event | `chakujun` | Trimmed `F` is F; numeric 1–6 is NORMAL. No term F count substitution. |
| `result_status` / L | `chakujun` | `L0`/`L1` are the probe's L class; retain the exact token for future codebook validation. |
| Other finish codes | `chakujun` | `K0/K1/S0/S1/S2/00` remain nonnumeric/unresolved as finish values. No inferred rank or points. |
| `actual_course_raw` / `actual_course` | `shinnyu_course` | Preserve raw; parse only 1–6. Keep distinct from `teiban`. |
| `start_timing_raw` / numeric | `st` | Preserve raw; three ASCII digits divide by 100 seconds. F/L remain NULL numeric timing. |
| `start_timing_status` | `chakujun`, `st` | F/L classes take F/L status; otherwise numeric, blank, or unresolved status from `st`. |
| `result_symbol_raw` | No separate K3 column | NULL; retain K3 finish token in `finish_raw`, never manufacture a `kigo` value. |
| `normalization_status` | Parsed fields above | UNRESOLVED for unresolved finish/ST or invalid nonblank course, otherwise NORMALIZED. |
| `normalization_version` | New K3 mapper version | Assign only in the controlled migration; the probe identifies itself as `k3-only-result-v1`. |
| `source_record_id`, provenance | Future preserved K3 Raw row | Not fabricated in this read-only probe; migrate K3 Raw first, then link its source record and versioned field mapping. |

K3 `motor_no`, `boat_no` (hull), `tenji_time`, and `race_time` are not
substituted for existing L3 entry fields, pre-race exhibition evidence, or
verified publication timestamps. In this snapshot K3 has no separate `kigo`
column. K3's 2017+ finish token counts were: numeric `01`–`06`, 3,164,488;
`F ` 12,635; `L0/L1` 371; `S0/S1/S2` 28,160;
`K0/K1` 5,943; `00` 53. (The numeric subtotal is obtained by subtracting
all special counts from the 3,211,650 K3 rows.)
K3 finish and registration are nonblank in all 3,211,650 rows; course has
6,093 blank values and ST has 6,206 blank values. These field-level blanks
are retained and do not turn into model-ready values.

## Canonical and checkpoint impact

The target DB has 3,210,456 `core.race_result` rows, dated 2017-01-01 through
2026-09-18; every adopted `source_record_id` currently has the old result-source
lineage. `core.race.race_status` also used result-record presence in the old
importer. `core.result_source_evidence`, `core.race_result_state`, and
`core.boat_finish_state` are old-source views. Existing frozen dataset rows and
hashes inherit those values and stay untouched. `core.race_entry` identity and
L3 fields, including national win rate and current-term F/L display counts,
remain separately sourced; the result-source policy alone does not retire them.

| Checkpoint | Method definition | Development/holdout evidence impact |
|---|---|---|
| Rating Method v1 | Keep 14-series, STRICT, D-1 and chosen method definition frozen for now. | Its `finish_state`, result completeness, actual course, and rating-history inputs inherit old result lineage. Recompute 2023/2024 development; K3's 2022 added results can affect D-1 ratings. |
| Rating v1 2025 holdout | Keep the frozen method and holdout window. | 2025 has 1,500 new K3 rows and 360 old-only Canonical rows; re-evaluate population and metrics. Old scores are historical, not K3-only proof. |
| Entry Course Index Method v1 | Keep 1Y boat×actual-course, no smoothing, D-1, Edogawa rule frozen for now. | 2023's two actual-course changes, plus 2022 new result rows, can affect development and 1Y rolling inputs. Recompute 2023/2024. |
| Entry Course Index v1 2025 holdout | Keep frozen method/window. | 2025 result coverage changes and rolling-history effects require holdout re-evaluation. |
| Motor A Method v1 | Keep residual and meeting/recency rules frozen for now; L3 win rate and L1/B1/K1 meeting identity are not retired. | K3 adds 54 2022 result rows, 52 with numeric finish; 2017–2024 eligibility/residuals and downstream D-1 score diagnostics require recalculation. No Motor A 2025 holdout existed in the checked checkpoint. |

No method is automatically rejected or refrozen. Because affected input rows
exist, no old development/holdout metric is claimed identical; rerunning the
frozen definitions on a versioned K3-only Canonical is the next validation.

## Read-only K3-only Canonical rebuild probe

`scripts/k3_only_rebuild_probe.py` streams K3 rows and target entry/result rows
in natural-key order, reconstructs the above result fields, and records
differences in `.local/k3_only_rebuild_probe.json`. Both DB sessions verified
`transaction_read_only=on`. Source end was 2026-09-18; the target has another
156 races/936 entries on 2026-09-19 without a K3 result snapshot, kept outside
the comparable interval.

| Measure, 2017-01-01 to 2026-09-18 | Count |
|---|---:|
| K3 races / boats | 535,275 / 3,211,650 |
| Existing Canonical race / entry universe | 542,004 / 3,252,024 |
| Existing Canonical result rows | 3,210,456 |
| Matched K3/entry keys | 3,211,650 |
| K3 result without existing Canonical result | 259 races / 1,554 boats (2022: 54, 2025: 1,500) |
| Existing Canonical result without K3 | 60 races / 360 boats (all 2025) |
| Entries without K3 | 40,374 boats, including cancelled/other absent-result races |
| K3/player identity mismatches | 0 |

On the 3,210,096 result rows present on both sides: numeric finish differences
0; raw finish differences 47,134; raw actual-course / parsed actual-course
differences 2 / 2 (one 2023 race); raw ST / numeric ST differences 110 / 2;
result-status / ST-status / normalization-status differences 1 / 1 / 1
(one 2026 row). New K3-only rows have 1,526 numeric finishes and 1,551 valid
actual courses. Old-only Canonical rows have 353 numeric finishes. The two
different 2023 course/ST rows are 2023-01-15, venue 19, race 03, boats 5/6.
These counts describe migration impact; old Canonical is not used as an
authority for K3 correctness.

## F Suspension K3-only replay

`scripts/f_suspension_k3_only_probe.py` is a separate read-only replay over
2017+ L3 entries and K3 results; R2 only labels K3-absent cancelled entries.
It uses K3 `F` alone for an F event. K3 numeric/L results or a measured
three-digit start are evidence of a race appearance; K3 `K` with blank ST is
not treated as an appearance. Unclassified evidence stays possible/UNRESOLVED.
It maintains a daily pre-result snapshot and applies all D results only after
that snapshot; 29/30-day, F2, same-day, and 2017 seed assertions pass.

The 2017-01-01 entry cohort has 617 players: 48 have a K3 F seed from
2016-12-03 through 2016-12-31, and 569 start UNRESOLVED. No earlier career
state is fabricated. The 2017-01-01 through 2026-09-18 replay covers 2,090
players, 3,252,024 entries, and 7,415,320 player-calendar-days.

| K3-only F replay measure | Count |
|---|---:|
| K3 F events / players | 12,635 / 1,958 |
| New ACTIVE transitions / F2-or-more additional events | 11,827 / 808 |
| CLEAR transitions after a 30-day gap | 12,636 |
| Prediction entry states: CLEAR / ACTIVE_UNSERVED / UNRESOLVED | 2,565,857 / 329,543 / 356,624 |
| Final player states: CLEAR / ACTIVE_UNSERVED / UNRESOLVED | 1,791 / 231 / 68 |
| K3-absent entries: R2 cancelled / other unresolved | 40,014 / 360 |

K3 F events are 1,200 in 2025; the other yearly event counts and replay
diagnostics are in `.local/f_suspension_k3_only_probe.json`. The 360 K3-absent
entries correspond to the 60 old-only Canonical result races above. They are
possible F inputs, not assumed non-F. K3 `S0/S1/S2/00` have three-digit ST in
all 28,213 observed rows and thus supply appearance evidence without assigning
a numeric finish. K3 `K0/K1` have blank ST in all 5,943 rows and do not advance
the last confirmed race date. A confirmed ACTIVE-period appearance updates that
date; F2 remains a single 30-day-clearance episode. The daily reducer does not
reset at term boundaries. This is development/probe evidence only, not a frozen
F feature or an acceptance of any earlier old-source development result.

## Controlled next step

The measured differences are material but do not prevent a K3-only migration.
Preserve K3 observations in immutable Raw, introduce new versioned K3-only
result Canonical and result-state/finish-state views, replace every active
direct reference and its tests/audits, then rerun frozen method definitions
against a separate versioned dataset. Resolve the 60 2025 K3-absent races as
missing under the authoritative source rather than silently retaining their
old Canonical results. Recompute Rating, Entry Course Index, Motor A, and F
Suspension evidence before deciding whether checkpoints remain valid. Do not
overwrite prior formal data or delete the existing freezes during that work.

## Appendix: every direct literal match filename

The paths below are the pre-audit repository-wide text search matches,
including ignored local historical material. This report itself was created
after that inventory. No listed historical artifact was changed except the
policy notices added to `README.md` and `docs/source_mapping.md`.

```text
README.md
docs/environment_preinfo_source_inventory.md
docs/phase2_report.md
docs/phase25_report.md
docs/phase3b_report.md
docs/rating_prep_report.md
docs/result_anomalies_preflight.md
docs/source_mapping.md
scripts/audit_history.py
scripts/audit_rating_prep.py
scripts/audit_result_states.py
scripts/import_history.py
scripts/import_sample.py
scripts/investigate_result_evidence.py
scripts/preflight_odds.py
scripts/preflight_results.py
scripts/verify_history.py
scripts/verify_import.py
sql/migrations/0004_result_states.sql
tests/test_database.py
tests/test_history.py
tests/test_result_states.py
.local/entry_course_development_2017_2024.json
.local/environment_preinfo/build_report.py
.local/environment_preinfo/checkpoint_inventory.json
.local/environment_preinfo/inventory.json
.local/f_coverage_certification_report.md
.local/f_coverage_initial_transition_probe.py
.local/f_coverage_probe.py
.local/f_suspension_boundary.py
.local/f_suspension_development_report.md
.local/f_suspension_development.json
.local/f_suspension_development.py
.local/f_suspension_k3_check.py
.local/f_suspension_k3_f_compare.json
.local/f_suspension_k3_f_compare.py
.local/f_suspension_k3_reconciliation.json
.local/f_suspension_k3_sensitivity.json
.local/f_suspension_k3_sensitivity.py
.local/f_suspension_method_probe.py
.local/f_suspension_method_redevelopment_report.md
.local/f_suspension_method_v1.py
.local/f_suspension_method_verify.py
.local/f_suspension_probe.py
.local/motor_a_development_report.md
.local/motor_a_development.json
.local/motor_a_development.py
.local/motor_a_meeting_development_report.md
.local/phase25/audit.json
.local/phase25/canonical_2017.json
.local/phase25/hashes.json
.local/phase25/raw_2017.json
.local/phase25/raw_2017.log
.local/phase25/raw_import_initial.log
.local/phase25/raw_import.log
.local/phase25/raw_registration_diagnostic.json
.local/phase25/replay_checkpoint.log
.local/phase25/replay_progress.json
.local/phase25/replay.json
.local/phase25/replay.log
.local/phase3b/audit.json
.local/phase3b/build_report.py
.local/phase3b/checkpoint_audit.json
.local/phase3b/investigation.json
.local/phase3c/legacy_raw_unchanged.json
.local/phase3c/tests.log
.local/preflight/national_score_readonly.json
.local/preflight/odds_o6_csv.json
.local/preflight/results.json
.local/rating_prep_audit.json
```
