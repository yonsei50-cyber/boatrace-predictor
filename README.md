# Boatrace foundation — Phase 2

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
repository artifacts. No full-period importer is enabled.
