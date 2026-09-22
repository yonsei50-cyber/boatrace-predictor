# Phase 2 verification report — 2026-09-22

## A. Verdict

**PASS — Phase 2 bounded foundation implementation.** Nine tables and limited
real-data migration are established. Historical publication-time availability,
continuous history coverage, prediction suitability, and unresolved source
symbols are not certified by this verdict.

## B. Git identity

- Project: `C:\Users\knkzh\Documents\boatrace-predictor`
- Start branch: `main`
- Start HEAD: `fa78dd69e244903ef3a422dab16c9979af7e09c4`
- Start working tree: clean
- Implementation branch: `codex/phase2-core-foundation`
- Commit subject: `feat: establish boatrace core data foundation`
- Final commit ID / post-commit working-tree status are reported in the task
  completion message (a commit cannot include its own hash in this document).
- `AGENTS.md` and `.codex/config.toml` remain unchanged. No push.

Only code, plain SQL, tests, requirements, and small documentation are tracked.
No source rows, dumps, credentials, or generated databases are Git artifacts.

## C. PostgreSQL

- Local endpoint: `127.0.0.1:5432`; PostgreSQL16.4, Windows x64.
- Initial catalog: `postgres`, `pckyotei`, `juggler_setting_predictor`; target
  `boatrace_predictor` did not exist.
- Created `boatrace_predictor`, schemas `raw` and `core`.
- Existing non-superuser `itgakko` owns/creates target objects via SET ROLE;
  configured existing login supplies authentication. No new roles.
- Source: `pckyotei.public` base tables L1/L2/L3/R3/KI, read-only transactions.
- No source write statements are issued. Exact selected source values and
  hashes are equal before/after import and at final DB testing. This is not a
  claim that unrelated sessions or the entire server were frozen.
- New tables have no foreign data wrappers, cross-database JOINs, legacy views,
  or legacy-schema FK dependencies. Juggler/V3/shared security were not changed.

## D. Tables, keys, limited sample counts

| Table | Rows | Principal keys/references |
|---|---:|---|
| raw.source_batch | 5 | PK source_batch_id; immutable |
| raw.source_record | 174 | PK source_record_id; FK batch; UNIQUE batch+position; immutable |
| core.venue | 24 | PK venue_code, UNIQUE venue_name |
| core.race | 9 | surrogate PK race_id; UNIQUE date+venue+race_no; venue/raw FKs |
| core.player | 49 | PK registration number; adopted raw and sex-source FKs |
| core.motor | 52 | surrogate PK; UNIQUE venue+generation_start_year+motor_no; raw/venue FKs |
| core.race_entry | 54 | PK race_id+boat_no; player/raw FKs; composite race/motor venue FKs |
| core.race_result | 54 | PK/FK race_id+boat_no to entry; raw FK |
| core.dataset_version | 2 | PK dataset_version_id; full snapshot/manifest/hash; immutable |

Entry boat bounds1–6, actual course bounds1–6 or NULL, generation intervals,
parent corrections, immutable raw/datasets, complete batch row counts, and
source-position bounds are enforced. Revision records belong to a new batch.

## E. Source mapping

[Complete field mapping and evidence](source_mapping.md).

Extracted batches: L1=8, L2=9, L3=54, R3=54, KI=49. Each record retains all
columns, source natural key, deterministic position, and raw hash. L3 and R3
entrant keys/registrations agree. No source race identifier was invented.

Sample selection:

- 江戸川2024-05-06 / 05-07, each1R.
- 蒲郡2024-07-18 / 07-19, each1R.
- 戸田2026-08-07 6R.
- 多摩川2026-09-01 4R / 11R.
- 浜名湖2026-09-01 7R.
- 下関2026-09-01 6R.

Grades: G3=3 races, GENERAL=6. Unconfirmed definitions remain explicitly NULL
or UNRESOLVED; no zero/male/course/normal-result imputation.

## F. Motor boundary verification

| Venue | Day before | Generation | Boundary day | Generation |
|---|---|---:|---|---:|
| 江戸川 | 2024-05-06, 6 entries | 2023 | 2024-05-07, 6 entries | 2024 |
| 蒲郡 | 2024-07-18, 6 entries | 2023 | 2024-07-19, 6 entries | 2024 |

All24 venue rules additionally pass day-before/day-of unit checks. The Kiryu
2026-01-10 case uses generation2025. Generation dates are user rules, never
represented as observed motor replacement facts. All54 sample entries have a
valid motor identity and race date inside `[start,end)`.

## G. Boat number / actual course

- 54 unique race×boat entries; all canonical boat numbers1–6.
- 11 rows have boat_no != actual_course.
- One missing actual course stays NULL and its raw value remains preserved.
- Edogawa effective fixed-entry flag is TRUE with explicit user-rule basis.
  Its actual result courses remain source values.
- The official Tamagawa4R comparison independently matches all6 rows.

## H. Result, ST, F/L

- Normal results48, F2, L1.
- Other exact raw finishes: `欠`, `エ`, `転`, one each, remain UNRESOLVED.
- Numeric ST50 rows; missing ST1 row; F/L-specific numeric NULL3 rows.
- Three-digit ST scale is confirmed by PDF and independent official results.
- F raw ST `001` / `002` and `kigo=F` are preserved independently; L raw ST
  contains three spaces. No negative/positive numerical F/L timing is guessed.
- Finish raw and normalized fields are separate; no accidental conversion of
  nonnumeric finish into rank0 or ordinary rank.

## I. Player sex

49 players:38 MALE,10 FEMALE,1 UNKNOWN. Code1/2 interpretation is confirmed from
the primary code table. All normalized sex values refer to stored KI records.
Player5357 has no eligible earlier-year KI, so sex is deliberately NULL/MISSING.
No later source-year identity fills an older sample race. Female-only derived
flag is TRUE for1 race, FALSE for8 races (confirmed male present).

## J. Lineage

All race/player/motor/entry/result records reference a new-DB raw record. Grade
and sex have separate typed raw references. Venue names are a fixed primary
code-table mapping. Rule-derived values identify the user rule/version.

All174 record hashes and all5 batch content hashes/row counts were recomputed.
Source sample content hash:

`253efaf21957c05478880a4a0dc62b5025c279f5b1370251461b5dc4d5742386`

Raw correction never updates an existing raw observation or completed batch.

## K. Fixed datasets and D-1

| Dataset ID | Effective D | Cutoff | Races | Results |
|---:|---|---|---:|---:|
| 1 | 2026-09-01 | 2026-08-31 | 5 | 30 |
| 2 | 2026-09-02 | 2026-09-01 | 9 | 54 |

Canonical content SHA-256:

- ID1: `fa0be23c7eae42506ef394157bce4e1d092ff8ae59e6ca192216d8a46119a042`
- ID2: `0a2c5d8113e48777e5748826a62b0db92a7c0f5d4cb8fdfadd030f7ae3bc9a12`

The manifest selects exact raw record IDs/hashes; its result observations all
precede D. It may refer to a source batch containing additional unselected rows;
those are not dataset members. Full canonical snapshot and manifest reside
inside the new DB. A current-canonical correction in a rolled-back test leaves
the frozen content unchanged. A complete replay into a disposable empty DB
using the final importer reproduces both snapshots and manifests exactly.

D-1 is a race-date bound, not proof of historical source publication or full
history coverage. These datasets are marked RETROSPECTIVE_RESULT_FOUNDATION.

## L. Verification

-29 tests PASS:13 pure rules/normalization tests and16 real DB tests.
- Migration0001 and0002 reproduced twice in a disposable empty database;
  resulting schema equals installed target.
- Final schema SHA-256:
  `0b0abc6e1f5abc9f5997a9c28a0f8067864594dd9bce5a1a52311b82062fd828`
- Final importer replay from real read-only source: PASS, exact two dataset
  snapshots/manifests/hashes match installed target.
- Injected changed source recheck: full import rollback PASS, all9 tables empty
  in the disposable test DB. This is injected failure evidence, not a real
  observed source-change event.
- Temporary verification databases removed.
- Independent targeted code review findings (parent motor updates, commit
  ordering, later-KI fallback, completed-batch extension) were fixed and rereviewed.
  No remaining finding in that bounded review. Runtime tests are separately
  performed by the primary agent.

Commands and runtime are documented in [README](../README.md).

## M. Intentionally absent

Environment/preinfo, parts, full player_term, F derived state, entry-course
index, ratings, models, predictions, trifecta, odds/value/betting, and full
history migration. [Deferred F/rookie rules](deferred_rules.md) preserve the user
specification without producing uncomputed FALSE states or ratings.

## N. Blocking findings and unresolved items

No blocker for the bounded Phase2 foundation. Remaining source limits:

- One unavailable sex observation, three uninterpreted non-F/L finish symbols.
- L2 initial zero semantics and pre-race stabilizer availability unconfirmed.
- The primary PDF's R3 trailing byte offsets are inconsistent; binary imports
  are blocked until clarified. Named DB column extraction is independently
  supported by the workbook and real-result checks.
- Historical retrieval/publication times and continuous career coverage are
  unknown. These inputs cannot establish a leakage-free historical prediction
  backtest merely because the result date filter passes.

## O. Next phase

**Can proceed to full-period migration design and additional source-definition
work.** Do not begin model adoption/backtesting from this sample.

Minimal full-period migration design: enumerate date/venue/race natural keys
in read-only source batches; persist each batch atomically; verify raw hashes,
entry/result key agreement, unknown codes, and per-period coverage; normalize
with an explicitly frozen code/rule version; retain exclusions and missingness;
freeze exact selected snapshots before evaluation. Do not overwrite prior raw
batches or datasets. Canonical revision selection and identity-attribute
availability need an explicit policy before enabling incremental history
updates. Resolve the three missing finish definitions before analyzing accident
subtypes; verify coverage before F-suspension or rookie inference. No automatic
full-period command or broad source extraction is implemented in this phase.
