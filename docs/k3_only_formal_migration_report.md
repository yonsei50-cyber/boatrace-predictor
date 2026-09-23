# K3-only formal result-source migration (2026-09-24)

## Authority and scope

K3 is the authoritative individual race-result source.
R3 is prohibited and must not be used by active project workflows.
R2 remains the independent source for race state, cancellation, and payouts. It
does not fill an absent K3 boat result. Rating v1, Entry Course Index v1, and
Motor A v1 method definitions remain frozen; this migration does not re-evaluate
their metrics or the 2025 holdout.

The populated database migration uses `scripts.migrate_k3_results`. It first
preserves monthly K3 observations in Raw, checks every month and the 60-race
direct-lookup gate before writing Canonical, then changes Canonical, dependent
result-state views, and the result dataset version in one target transaction.
The empty-database path is `scripts.import_history`, followed by the independent
R2 evidence import. The result metadata manifest identifies monthly source
batches and their content hashes.
Legacy Raw observations and frozen historical `core.dataset_version` shards
remain preserved as evidence. Active result acquisition, Canonical rebuild,
views, audits, and model input extraction use K3 for individual results.

## 2025 old-Canonical-only gate

The gate queried `pckyotei.public.brd_k3` directly for every race key. All 60
races had six existing Canonical boats with recorded player registrations; the
direct K3 count and alternative normalized K3 key count were zero for every
race. The source used the sole observed 2025 year encoding, `2025`, and had
zero malformed K3 race keys in that year. There was no probe extraction bug.
The 60 races are all on **2025-08-12**:

| Venue | Race numbers (each an individual verified race key) | Canonical boats | Direct K3 boats | Normalized K3 boats |
|---|---|---:|---:|---:|
| 01 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | 72 | 0 | 0 |
| 07 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | 72 | 0 | 0 |
| 15 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | 72 | 0 | 0 |
| 19 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | 72 | 0 | 0 |
| 20 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12 | 72 | 0 | 0 |

The machine-readable [60-race gate record](../artifacts/k3_2025_60_race_gate.json)
lists each date/venue/race, all six Canonical boat and registration values, the
K3 direct and normalized query counts, and the returned K3 rows. Its SHA-256 is
`3649510DE83796D5BFAB10523F80FB7904BB638C580ABADED12FDBDD2258530C`.
K3 has 120 other races on that date. The finding establishes absence in the
queried K3 base table, without asserting why those races were absent upstream.
Under the authoritative-source policy, their 360 old-only individual results
are excluded from Canonical; race identity and R2 evidence remain separate.

## Result mapping

K3 `chakujun` supplies the exact finish token. Numeric positions 1–6 alone
become numeric finishes; `F ` becomes F, `L0`/`L1` become L, and other special
tokens remain unresolved with numeric finish NULL. K3 has no independent
`kigo`; no such field is invented. `shinnyu_course`, `st`, `toroku_bango`, and
`teiban` supply course, timing, registration, and boat identity respectively.
Original strings remain in Raw; F/L have numeric start timing NULL. Every
Canonical result retains its Raw source-record ID and normalization version.

## Validation evidence

The negative prewrite test deliberately changed one boat in the gate and ran
the full migration validation pass. It rejected the altered set with
`old-only Canonical keys differ ... (360, 360, 1, 1)` and left Canonical at
3,210,456 boats / 535,076 result races. The normal migration uses the verified
gate and an intact Raw acquisition report.

The populated database migration committed with `status=APPLIED`. It staged
and adopted 3,211,650 K3 rows representing 535,275 races through 2026-09-18,
and deleted exactly the 360 verified old-only Canonical boats. The result
dataset ID is `K3_ONLY_RESULT_V1_b68a27cf8f653602`; its monthly source manifest
hash is `b68a27cf8f6536024f8d68149bd026f1ab271f62b1190b3bc1d860bf3bb1db4a`.
The prewrite negative test and live migration are separate runs; the former
proved a changed gate would block before any Canonical write.

The post-commit check of those exact 60 race keys found 60 race IDs and all
360 entries still present, zero `core.race_result` rows, and
`SOURCE_INCOMPLETE` in `core.race.race_status` for all 60. This preserves the
race and entry foundation while excluding only unsupported individual results.

The post-migration Canonical audit passed with zero wrong-source, invented
symbol, numeric F/L ST, key, registration, raw-field, non-six, duplicate, or
mandatory-null defects. Raw and Canonical both contain 535,275 result races
and 3,211,650 boats. Of those boats, 3,164,488 have numeric finishes,
12,635 are F, 371 are L, and 34,156 have special or unresolved finish codes.
Valid actual course is present for 3,205,557 boats and valid numeric start
timing for 3,192,701. These are coverage counts, not historical availability
certification.
The unresolved finish tokens remain `00` (53), `K0` (4,363), `K1` (1,580),
`S0` (11,435), `S1` (13,867), and `S2` (2,858). No token in this group was
given a numeric finish.

The starting `953c6c8` tree had 44 literal retired-table references across
active `scripts/`, `sql/`, and `tests/` files. The current tree has zero, as
checked by `tests.test_no_r3_runtime`; its opt-in database check also found
zero references through current `raw`/`core` views and functions. Historical
documents may still record the superseded source and are explicitly labeled
as such.

The result-state audit also passed. Across 542,160 race identities and
3,252,960 entries, it found 535,275 `RESULT_RECORDS_PRESENT` races, 6,669
`R2_EVENT_STATE_PRESENT`, 59 `R2_PAYOUT_PRESENT_K3_MISSING`, and 157
`SOURCE_INCOMPLETE`. It kept R2 payouts separate from individual K3 finishes;
the 59 payout-only races did not acquire boat results. The view-to-Canonical
finish, numeric, timing, and adopted-source lineage mismatch counts were all
zero. Independent numeric classification mismatches and source revision
conflicts were also zero. Its R2 Raw hash audit covered 542,004 rows in 117
batches without mismatch. The audit found 515 races with duplicate numeric
finishes and kept their finish-state classification unresolved.

The read-only frozen-input smoke test extracted six pre-2025 rows each through
the Rating v1, Entry Course Index v1, and Motor A v1 input paths. All 2,638,614
pre-2025 Canonical result boats inspected for lineage used K3, with zero
foreign-source boats. This confirms extraction shape and K3 lineage; it does
not rerun metrics, method selection, or the sealed 2025 holdout.

The F-suspension replay over the migrated K3-only Canonical produced 12,635 F
events and 808 additional F2 events. Prediction-before-entry states were
2,565,857 CLEAR, 329,543 ACTIVE_UNSERVED, and 356,624 UNRESOLVED. Period-end
states were 1,791 CLEAR, 231 ACTIVE_UNSERVED, and 68 UNRESOLVED. Scope, all
counts, yearly F totals, initial 2017 seeds, prediction states, and final
states matched the independent direct-K3 probe exactly. Boundary tests cover
29/30/31-day gaps, same-day F isolation, F2, period boundaries, and the 2017
initial state. The F-suspension method remains unfrozen.

An independent read-only source-to-Canonical merge compared all 3,211,650
K3 boats with the migrated result set through 2026-09-18. It matched all
3,211,650 keys/results and reported an empty difference map. Among the
3,252,024 entries through that source endpoint, 40,374 had no K3 boat result;
they were not filled from another result source. Later entries are outside
this K3 source endpoint and are excluded from that comparison.

Focused verification passed: 54 pure tests (two DB-only skips), the separate
two-case no-R3 runtime guard with its database scan enabled, two migration DB
tests, and all 14 result-state DB fixture tests. The result-state fixtures
cover normal/partial/missing K3, independent R2 event/payout evidence,
conflicting revisions, duplicate numeric finishes, F/L and special finishes,
R2 Raw idempotency/hash, view reapplication, and D-1. The migration gate test
proved an invalid direct-lookup report is rejected before connecting to the
target database.

The 16 legacy `tests.test_database` cases require an isolated 54-result sample
database; on the populated history database they explicitly skip. They are not
counted as migration gate passes. Full-history coverage is provided by the
Canonical, result-state, and fresh-build checks above.
The wider legacy `scripts.audit_history` scan was started but stopped during
its expensive all-Raw-key reconciliation. It has no PASS claim in this report;
the K3-specific Canonical and result-state audits and full K3 source comparison
are the completed migration gates.

## Empty database reproduction

`scripts.reproduce_k3_empty_db` created a dedicated empty database, migrated
the schema, imported L1/L2/L3/K3/KI Raw without a retired result source,
rebuilt Canonical, and imported 542,004 R2 rows. It compared the populated
database before and after the run with the empty database and returned
`status=PASS`, `match=true`. All three matched on 542,160 races, 535,275 result
races, 3,211,650 result boats, F 12,635, L 371, numeric finish 3,164,488,
special/unresolved finish 34,156, valid actual course 3,205,557, and valid
numeric ST 3,192,701. The four-way result-state distribution also matched:
535,275 `RESULT_RECORDS_PRESENT`, 6,669 `R2_EVENT_STATE_PRESENT`, 59
`R2_PAYOUT_PRESENT_K3_MISSING`, and 157 `SOURCE_INCOMPLETE`.

Both databases recorded `K3_ONLY_RESULT_V1_b68a27cf8f653602`, authority
`brd_k3`, range 2017-01-01 through 2026-09-18, normalization
`k3-only-result-v1`, and the same monthly manifest hash shown above. The
temporary database was removed after the successful comparison. The local
machine-readable run result is `.local/k3_empty_db_reproduction.json`.
