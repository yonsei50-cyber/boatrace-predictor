# Phase 3D: C3 part changes at race × boat × source field grain

## A. Verdict

**PASS_WITH_LIMITATIONS.** The full-period structural audit passed, including
Raw replay and lineage, with no blocking mismatches. Every observed quantity
remains unknown because the saved specification defines exchange codes rather
than counts. The part-change implementation is scoped to the nine files listed
below.

## B. Phase 3C checkpoint

The ten designated Phase 3C files were committed as
`fc8b4444ff1fcf5c49d680c38f5ffae1ce9d1251`
(`feat(preinfo): canonicalize C2 C3 race preinfo`) and normally pushed from
`main` to `origin/main`. Local HEAD, tracking `origin/main`, and actual remote
`refs/heads/main` were read back at the same SHA. The 107-test disposable-DB
suite passed. Saved full Raw/Canonical audit had zero nonzero blockers, C2/C3
repeat imports inserted zero, the 157 races/942 boats without C3 were not
imputed, F/L stayed symbolic, unknown wind/wave units stayed unresolved,
C4 remained metadata only, and 119 frozen datasets and the D-1 boundary were
unchanged. `.codex/config.toml` and `AGENTS.md` were already dirty and were not
included in the checkpoint.

## C. Schema

Migration `0006_race_boat_part_change.sql` creates one Canonical table and a
lineage view. Each row stores race and boat identity, source field, an ordinal,
the documented stable part-type code and source field name, original JSON value,
original exchange code as `quantity_raw`, unknown `quantity`, status, Raw record
ID, normalization version, and provenance. The source record and source field
form an idempotency key. The race/boat foreign key and source identity trigger
reject orphans and forged lineage. A repeated migration is designed to leave
existing data unchanged.

## D. Source: nine fields

The saved *PC-KYOTEIデータ仕様書.pdf* p.4 C3 items 13–21 and
*PC-KYOTEIテーブル定義書.xlsx* sheet「直前情報(艇番)」rows 26–34 explicitly identify
all nine fields. Their source type is `varchar(1)`.

| Source field | Documented part | Observed nonzero code(s) | Observed rows |
|---|---|---|---:|
| `propeller` | プロペラ | none | 0 |
| `piston` | ピストン | 1, 2 | 17,741 |
| `piston_ring` | ピストンリング | 1, 2, 3, 4 | 55,135 |
| `denki_isshiki` | 電気一式 | 1 | 13,535 |
| `carburetor` | キャブレター | 1 | 16,132 |
| `cylinder` | シリンダ | 1 | 9,662 |
| `crankshaft` | クランクシャフト | 1 | 3,996 |
| `gearcase` | ギヤケース | 1 | 11,923 |
| `careerbody` | キャリアボデー | 1 | 15,571 |

The PDF defines `0` as an initial code, `1` as a part-exchange code for seven
fields, `1–2` for piston, and `1–4` for piston ring. It does not define these
codes as physical quantities. Zero remains in Raw and is not evidence that no
physical exchange occurred. A single C3 row can have several positive fields;
the one-byte fields do not contain an internal list. All nine source fields had
zero NULL/blank/space/invalid observations in the 2017+ source check. Year and
venue frequencies vary; no causal explanation is inferred.

## E. Coverage

Canonical has **143,695 rows / 98,578 affected races / 111,005 affected boats**
across 24 venues, 2017-01-01 through 2026-09-18. Source C3 has 3,252,018
boats in 542,003 races. There are no pre-2017 Canonical rows.

| Year | Part rows | Affected races | Affected boats |
|---:|---:|---:|---:|
| 2017 | 12,647 | 8,898 | 9,848 |
| 2018 | 11,926 | 8,475 | 9,282 |
| 2019 | 12,670 | 8,537 | 9,376 |
| 2020 | 13,543 | 8,790 | 9,696 |
| 2021 | 13,490 | 9,088 | 10,121 |
| 2022 | 13,699 | 9,243 | 10,233 |
| 2023 | 15,290 | 10,000 | 11,225 |
| 2024 | 17,653 | 11,458 | 13,029 |
| 2025 | 19,234 | 14,150 | 16,614 |
| 2026 (through Sep 18) | 13,543 | 9,939 | 11,581 |

| Venue | Rows | Venue | Rows | Venue | Rows | Venue | Rows |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 | 6,238 | 07 | 6,299 | 13 | 5,335 | 19 | 6,590 |
| 02 | 6,759 | 08 | 6,152 | 14 | 6,210 | 20 | 5,332 |
| 03 | 4,128 | 09 | 6,375 | 15 | 6,785 | 21 | 5,640 |
| 04 | 6,150 | 10 | 5,648 | 16 | 4,233 | 22 | 5,213 |
| 05 | 4,045 | 11 | 6,080 | 17 | 6,544 | 23 | 7,150 |
| 06 | 8,118 | 12 | 6,486 | 18 | 6,476 | 24 | 5,709 |

The complete year × venue rows/races/boats and part-type breakdowns are in the
ignored local `.local/phase3d/audit.json`.

## F. Part types

All nine source-field-to-part mappings are documented, so stable uppercase
codes are stored. Eight types have observed exchange rows; `PROPELLER` has
zero. Unresolved types: **0**. Future undocumented fields are not mapped to an
existing part.

## G. Quantity

All observed positive values are *exchange codes*. Quantity known: **0**;
quantity unknown: **143,695**. All 143,695 rows have status
`UNRESOLVED_QUANTITY`; observed blank/invalid/out-of-spec rows: **0**. Quantity
stays NULL even where the raw code is `1`. The original code is retained in
`quantity_raw` and `raw_value`. Future blank, malformed, and out-of-spec codes
remain unresolved, not normalized to a quantity.

## H. Multiple changes

Source and Canonical agree: 111,005 boats have at least one exchange-code
field; **20,812** have at least two, and the maximum is **eight** on one boat.
The distribution for one through eight types is 90,193 / 11,600 / 7,077 /
1,710 / 344 / 58 / 21 / 2 boats. Duplicate observations for the same
race/boat/part type are retained separately by Raw record and are never summed.
Observed duplicate candidate groups: **0**.

## I. Lineage

The full Raw-to-Canonical replay expected 143,695 rows: missing Canonical **0**,
raw-value mismatch **0**. Wrong source/version, raw natural-key mismatch,
race/boat identity mismatch, part-type mismatch, status mismatch, inferred
quantity, provenance result dependency, and missing Raw reference are all
**0**. Orphan race/boat **0/0**. The existing C3 Raw supplies source record ID,
record hash, batch hash, source locator, natural key, and audit timestamps.
The Phase 3C full Raw hash audit had zero mismatches. C2/C3 Canonical counts
remain 542,003/3,252,018, with 119 frozen datasets and zero D-1 violations.
The six protected Core tables plus frozen-dataset manifest fingerprint matched
before and after Phase 3D exactly (SHA-256
`f22f3e47f37eb5fc67a85902cf8c036f1a42a2df632512a23d2b2b188197ee09`).

## J. Tests

The disposable-DB suite passed **116 / 0 failed / 0 skipped**, including the
existing 107 tests and nine new tests. The strengthened 2017 boundary fixture
has a 2016 race/boat that could otherwise join its Raw C3 record, and still
produces zero Canonical rows. Empty-DB schema reproduction passed. Initial
117-batch backfill inserted 143,695 rows; migration and full backfill repeated
with **0** additional rows. Both disposable DBs were removed.
Empty-DB schema reproduction matched the populated target at SHA-256
`aa2f6509ac2e2fac7e68e884db9e9bb31ef67e3702db44a64ad20560f6231342`.

## K. Known limitations

1. The saved source defines exchange codes but no physical quantity; all
   Canonical quantities remain unknown.
2. A source `0` is an initial code, not proof of no physical exchange.
3. Individual historical publication/retrieval times and revisions are absent.
   Source-class pre-race policy is separate from extraction/ingestion timestamps
   and does not prove an exact historical as-of state.
4. No part-change prediction feature, motor evaluation, rating, or C4 numeric
   Canonical data is created here.

## L. Changed files

The Phase 3D working files are `README.md`, `docs/phase3d_report.md`,
`scripts/apply_part_changes.py`, `scripts/audit_part_changes.py`,
`scripts/migrate.py`, `scripts/verify_history.py`,
`sql/migrations/0006_race_boat_part_change.sql`, `tests/test_database.py`, and
`tests/test_part_changes.py`.
`.codex/config.toml` and `AGENTS.md` were already dirty before this work and
were not edited or staged for Phase 3D.

## M. Recommended next step

| Candidate | Present prerequisite / main question | Recommendation |
|---|---|---|
| C4 quality investigation | Scale, boat alignment, carryover, and venue/year coverage remain unresolved. | **Next:** read-only source-quality gate before timing features. |
| F-suspension derivation | Requires separate result-code and time-order rules. | After a focused specification. |
| Boat-number entry index | Requires pre-race identity/course availability rules. | After its own source/timing audit. |
| Rating preparation | Result-state eligibility and frozen evaluation choices remain unresolved. | Defer until input rules are stable. |

No C4 Canonical, F-suspension, entry index, rating, motor evaluation, or
prediction was implemented in this phase.
