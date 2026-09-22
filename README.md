# Boatrace foundation — Phase 2 through Phase 3D

Twelve PostgreSQL tables, immutable source observations, explicit sample import,
and frozen result datasets. No ratings, models, odds, or betting implementation.

## Phase 3D: C3 part changes

The additive `0006_race_boat_part_change.sql` migration projects the nine
documented C3 part fields into `core.race_boat_part_change`, one row per observed
source field and boat. Multiple fields on one boat remain separate rows. The
existing preserved C3 Raw record supplies identity, original exchange code,
hash, source location, and lineage. The documented `0` is an initial code and
does not create a part-change row; it is not proof that no physical exchange
occurred. Unexpected nonzero, blank, and invalid codes remain unresolved rows.

The source specification defines exchange codes, not physical quantities.
`quantity_raw` retains the code, while `quantity` stays NULL for every row.
The nine part types are normalized only through the saved C3 field definition.
This layer makes no motor assessment, rating, feature, or prediction. Historical
individual publication timestamps remain unverified; source-class pre-race
policy is distinct from extraction and ingestion audit timestamps.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.apply_part_changes --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3d\apply.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.audit_part_changes --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3d\audit.json'
```

The apply command uses only already-preserved C3 Raw batches. Repeating it
adds no rows when the source is unchanged. Each monthly batch is atomic; an
interrupted run may have completed earlier batches, so use the audit for final
coverage and replay checks. See [Phase 3D report](docs/phase3d_report.md).

## Phase 3C: environment and start exhibition

C2 and C3 are preserved in the existing immutable Raw framework. The additive
`0005_environment_preinfo.sql` migration introduces `core.race_environment_preinfo`
and `core.race_boat_preinfo`. Raw-derived generated values/statuses and guarded
source identity keep exhibition course/ST separate from result course/ST.
The corresponding `_status` views include races/boats with `MISSING_SOURCE`.

Temperatures are Celsius, exhibition timing is seconds, and tilt is degrees.
Wind speed and wave height retain original text with `UNRESOLVED` units.
Exhibition F/L retain their symbols and have no ordinary numeric ST. Missing
source rows are never filled from another race or from result information.

Lap, half-lap, turning, and straight times belong to **C4, not C3**. C4 remains
excluded. `core.c4_field_structural_status` describes venue/field metadata only;
it does not claim historical C4 values or convert missing C4 rows into data.
Source-class pre-race availability policy is separate from exact historical
publication time (unverified) and extraction/ingestion audit timestamps.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.import_environment_preinfo --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3c\raw_import.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.apply_environment_preinfo --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3c\canonical_import.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.audit_environment_preinfo --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3c\audit.json'
```

Run only the dedicated additive command on the populated target. Repeated
unchanged Raw imports add nothing; changed partitions block automatic adoption.
Each Raw or Canonical batch transaction is atomic. An interrupted run can have
completed earlier batches, so inspect the audit before claiming full coverage.
The audit uses the explicitly frozen Phase 3C checkpoint counts; it is not a
rolling production count policy. See [Phase 3C report](docs/phase3c_report.md).

## Phase 3B: evidence-based result states

Three additive views separate race state (`core.race_result_state`), boat finish
(`core.boat_finish_state`), and immutable R2/R3 lineage
(`core.result_source_evidence`). Existing start timing status is reused unchanged.
`RESULT_RECORDS_PRESENT` describes source completeness, not normal finishes or
model eligibility. Duplicate numeric races and special symbols remain unresolved.
Missing R3 never receives a finish reconstructed from payouts.

Full R2 observations from 2017 onward are preserved in the existing Raw tables.
The dedicated importer does not change the Phase 2.5 source inventory or frozen
datasets. An identical repeat adds no batch; changed partition content blocks.
Migration `0004_result_states.sql` creates only views and is reapplicable; do not
rerun initial migrations against the populated target.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.import_result_evidence --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3b\r2_import.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.audit_result_states --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3b\audit.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.investigate_result_evidence --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3b\investigation.json'
```

The audit validates the current checkpoint counts and independently checks
numeric classification, lineage, and R2 hashes. Views query the current preserved
observations; they are not historical prediction snapshots. See the
[Phase 3B report](docs/phase3b_report.md) for definitions, counts, and limitations.

## Phase 3A: L3 national win rate

`core.race_entry` stores `national_win_rate_raw`, `national_win_rate`, and
`national_win_rate_status`. `core.race_entry_national_win_rate` exposes their
race/boat/player identity and Raw record/batch lineage. Only `VALID` has a
numeric value; `0000` remains `UNRESOLVED` with numeric NULL. No KI fallback.
Historical publication/receipt time remains `NOT_VERIFIED`, including for VALID
values. This status is not a historical prediction eligibility flag.

Migration `0003_l3_national_win_rate.sql` is additive and reapplicable on the
existing target. The dedicated command upgrades, backfills preserved L3, audits
coverage, and commits atomically. Omitting `--apply` audits without persistent
writes. The initial migrations must not be run against the populated target.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.national_win_rate --apply --expected-entries 3252960 --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase3a\coverage.json'
```

The expected count is the verified 2017-01-01 through 2026-09-19 checkpoint,
not a permanent limit for later imports. Inserts and COPY automatically derive
the rate from the adopted L3 record and reject mismatched entry identity.
Existing Phase 2/2.5 result snapshots retain their original column contract;
they do not acquire this new input. A future prediction dataset needs its own
versioned input snapshot and time policy. See the [Phase 3A report](docs/phase3a_report.md).

- [Verified Phase 2 report](docs/phase2_report.md)
- [Source mapping and unresolved definitions](docs/source_mapping.md)
- [Deferred user rules](docs/deferred_rules.md)

Validated runtime: PostgreSQL 16.4, Python 3.14.0, psycopg2-binary 2.9.11.
The known Python executable is
`C:\Users\knkzh\AppData\Local\Python\bin\python.exe`.
Run commands from `C:\Users\knkzh\Documents\boatrace-predictor`.

## Database setup and sample import

`scripts.db` reads the existing local PC-KYOTEI XML connection settings in
memory. It does not log passwords or DSNs. `--config` accepts another compatible
local XML settings file. Keep credentials outside Git. Source connections are
`REPEATABLE READ, READ ONLY`, with `default_transaction_read_only=on`.
Administrative authentication uses the existing configured login; target and
database creation operations use `SET ROLE itgakko`, an existing non-superuser
with CREATEDB. No roles or shared settings are created or changed.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.migrate
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.import_sample
```

These commands initialize a NEW/EMPTY `boatrace_predictor` only. They refuse a
populated target and never drop/recreate it. The sample is already imported in
the verified local database. Do not rerun initialization there. Plain SQL files
in `sql/migrations` apply in filename order inside one transaction to reproduce
the complete schema. There is no migration framework or hidden legacy JOIN.

Corrections require new raw batches/records. A frozen dataset includes the full
canonical snapshot and exact selected raw record IDs/hashes inside the new DB.
Read `canonical_snapshot` to replay; do not reconstruct an old dataset by joining
current canonical tables. `results_before` reads a supplied frozen snapshot and
filters race dates strictly before D. Date cutoff does not prove historical
publication/receipt times.

## Verification

```powershell
$env:BOATRACE_TEST_DB = '1'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m unittest discover -s tests -v
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_schema
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_import
```

Without the opt-in environment variable only pure tests run; DB tests are
explicitly skipped. DB tests target the installed bounded sample and roll back
all attempted changes. PostgreSQL identity sequences can advance on rolled-back
inserts; sequence gaps are not data loss. Verification utilities create uniquely
named disposable databases owned by `itgakko` and remove only databases they
created. `verify_import` performs a real sample replay, then a separately marked
fault-injection rollback test. It does not modify the real target sample.

Raw observations, dumps, connection secrets, and generated databases are not
repository artifacts.

## Phase 2.5: history from 2017-01-01

See the [Phase 2.5 report](docs/phase25_report.md) for measured coverage,
preserved unresolved values, and verification results.

The [period policy](docs/analysis_periods.md) limits full-period migration and
quality certification to 2017-01-01 onward. Earlier source coverage is not a
completion requirement. Only selected earlier KI records needed for identity
are included. Already-preserved pre-2017 Raw from before the scope revision is
retained, but excluded from Canonical, certification, and full replay.

The nine Phase 2 tables and both migrations are reused. Run against the existing
dedicated target; do not rerun `scripts.migrate` against a populated database.
No source database write is performed. Successful empty partitions are distinct
from failed acquisition; failure stops without creating a successful batch.
Each completed partition is atomic and immutable. Repeated identical partitions
are reused; changed source content is preserved and blocks automatic adoption.

```powershell
New-Item -ItemType Directory -Force 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25' | Out-Null
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.import_history --raw-only --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\raw_2017.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.import_history --canonical-only --inventory 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\raw_2017.json' --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\canonical_2017.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.freeze_history --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\datasets.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.audit_history
```

Canonical-only processing requires a successful scoped Raw report and a matching
complete partition/count set. It reads preserved Raw, not the source database.
Missing/invalid natural keys and contradictory entrant/result registrations or
result codes remain Raw-only with counted reasons. Unknown non-conflicting
finish symbols retain their exact text in Canonical as UNRESOLVED. No missing
course, sex, ST, or motor is guessed.

Player identity is bounded by each player's earliest 2017+ race year. Moving
from the limited sample to earlier races can therefore reduce sex coverage;
later KI is never used to fill that gap. Existing frozen Phase 2 datasets remain
unchanged. Monthly history datasets are immutable retrospective shards with
explicit D-1 bounds; they are not historical publication-time evidence. Their
portable hashes replace sequence IDs with natural identities and raw hashes.

## Reproducible verification

The original DB tests describe the nine-race fixture. Run them unchanged against
a disposable sample DB, not the expanded target. The helper below runs all tests
with no skips. The replay helper starts another empty DB, applies migrations,
replays only scoped preserved Raw, verifies Raw and Canonical idempotency,
compares every monthly portable dataset hash, and runs the aggregate audit.
It removes only the disposable database it created.

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_history --mode sample-tests --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\tests.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_history --mode hashes --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\hashes.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_history --mode datasets --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\dataset_hashes.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.verify_history --mode replay --inventory 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\raw_2017.json' --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\phase25\replay.json'
```
