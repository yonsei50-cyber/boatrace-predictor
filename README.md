# Boatrace foundation — Phase 2 / Phase 2.5

Nine PostgreSQL tables, immutable source observations, explicit sample import,
and frozen result datasets. No ratings, models, odds, or betting implementation.

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
