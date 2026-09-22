# Phase 2 source mapping

## Phase 3B: result evidence

R2 is preserved as complete JSON observations in `raw.source_record`, with
`pckyotei.public.brd_r2` location, monthly batches, natural race keys, record and
batch hashes, extraction time, and unknown historical receipt time. Its dedicated
version is `phase3b-r2-evidence-v1`; the Phase 2.5 inventory contract is unchanged.

`core.result_source_evidence` exposes all R2/R3 observations and lineage, including
blank R3 and unjoined source rows. `core.race_result_state` classifies the 2017+
race universe. `core.boat_finish_state` classifies existing entries without adding
rows to `core.race_result`. The old `result_status` remains compatible with frozen
datasets; new consumers must use the separated finish state and race evidence.

The saved PC-KYOTEI specification PDF p.5 confirms R2 `data_kubun=9` means race
cancellation, and `0` is an initial value. The view conservatively reports
`R2_EVENT_STATE_PRESENT` and retains raw codes. First-slot valid trifecta payout
combinations establish payout evidence only. `000` is not a valid combination;
`***` is a special payout, not an individual result. This does not certify any
boat's finish. All payout slots remain in the complete Raw payload.

Race completeness and boat finish are independent: six nonblank R3 finishes can
include special symbols or duplicates. Only numeric 1–6 in a race without numeric
duplicates is `NUMERIC_VALID`. Duplicate values are
`NUMERIC_DUPLICATE_UNRESOLVED`; the other numeric finishes in that race are
`NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED`. Original numbers are retained. Nonblank
special finish symbols, including finish-side Ｆ/Ｌ, are `UNRESOLVED_SPECIAL`.
No individual finish is generated for blank/absent R3. The existing F/L ST status
and NULL numeric ST remain separate and unchanged.

Conflicting Raw revisions are exposed through all source IDs/hashes and raw-value
arrays; conflicting boat scalar raw values are NULL rather than selecting one.
No Rating, motor points, responsibility, model eligibility, or historical
availability is inferred. Existing snapshots and D-1 filtering remain unchanged.

## Phase 3A: entry-time national win rate

The primary input is L3 `zenkoku_ritsu_1`, distinct from KI `ritsu_1`.
The saved PC-KYOTEI specification PDF p.1 defines four characters and the
example `0580 = 5.80`; the table workbook's 出走表(艇番) rows18–20 maps the
national columns. The existing preflight evidence is retained in
`.local/preflight/national_score_readonly.json` and `phase3_preflight_report.md`.
Conversion uses exact four ASCII digits divided by 100 (`0654 = 6.54`). It
does not interpret this competitive-points average as a first-place percentage.

| Raw | Status | Numeric value |
|---|---|---|
| Four ASCII digits other than `0000` | `VALID` | exact decimal / 100 |
| `0000` | `UNRESOLVED` | NULL; meaning not established, no zero imputation |
| NULL, empty, space-only | `MISSING` | NULL; exact Raw preserved |
| Other shapes | `INVALID` | NULL; exact Raw preserved |

`MISSING`/`UNRESOLVED` reuse existing vocabulary. `VALID`/`INVALID` identify
field-level parsing; they do not assert historical availability or model
eligibility. No confirmed special/sentinel code is currently classified.
No unsupported plausibility cutoff is used to discard unusual numeric values.

Three columns on `core.race_entry` preserve the race×boat observation;
generated numeric/status columns use versioned SQL functions, and the entry
trigger adopts the exact Raw field and validates race/boat/registration.
The existing source_record FK resolves source_batch, raw key, hashes, and
timestamps through `core.race_entry_national_win_rate`. There is no result join.
The view labels this `RACE_ENTRY_INFORMATION` and historical availability
`NOT_VERIFIED`; current extraction/ingestion is not historical receipt evidence.

KI remains auxiliary, with May–October term1 and November–April term2.
No KI matching requirement, fallback, or period-year inference is implemented.
All D predictions retain the common D-1 result/rating boundary. This race-entry
input is not a same-day result or a rating update. Frozen Phase 2/2.5 snapshots
retain their original shape and hashes; future prediction inputs need a new,
explicitly versioned snapshot contract.

## Phase 2.5 scope and adoption (2026-09-22)

The field meanings below remain unchanged. Full-period migration now means
**2017-01-01 onward**, following the user's revised [period policy](analysis_periods.md).
L1/L2/L3/R3 are extracted in calendar-month partitions. KI is extracted by source
year from 2017 onward, plus `identity-before-2017`: at most one latest KI strictly
before a player's earliest 2017+ race year, retained only when that selected KI
is older than 2017. This is minimum identity support, not full old-history coverage.

For Canonical identity, the existing conservative `identity_observation` rule
selects the earliest eligible observation among this preserved selection, with
source year strictly before the player's earliest 2017+ race. Missing eligible
KI stays missing for that player across the foundation. Later-year records do
not backfill earlier races. Conflicting eligible known sex codes leave identity
unresolved. No KI performance statistics become features.

Existing sampled canonical records are reused only when their complete adopted
source payload matches the corresponding preserved history record. Motor
evidence is moved to the earliest observed entry for that natural motor identity
when necessary; its generation formula is unchanged. The immutable Phase 2
datasets keep their original contents.

Successful zero-row extraction has status `SOURCE_EMPTY`. A failed SELECT stops
the import and never creates a successful empty batch. Upstream acquisition
history is not present in these base tables: absence there cannot distinguish
an upstream collection failure, a non-racing date, or a genuinely absent source
record. Reports explicitly retain that uncertainty.

Unknown finish/ST/course/grade/flag codes are retained; new special-finish
meanings are not inferred. Contradictory result codes or L3/R3 registrations
remain Raw-only with counted reasons. A race's `RESULT_RECORDS_PRESENT` status
requires six adopted entries and six adopted results; this still does not
assert an official race status or six normal finishes.

Monthly frozen shards contain exact canonical values and Raw references. Their
`effective_date` is the day after the last observed race in that month (so an
incomplete latest month does not imply a future cutoff); every included result and source
race date is earlier than that D, and selected KI years precede the relevant
race years. They are retrospective result foundations, not as-known-at-T
prediction datasets. A future consumer must still impose its own D-1 cutoff.

## Phase 2 evidence (unchanged below)

Verified 2026-09-22 against local `pckyotei.public` base tables and:

- `C:\Users\knkzh\Documents\kyotei\PC-KYOTEIデータ仕様書.pdf`
- `C:\Users\knkzh\Documents\kyotei\PC-KYOTEIテーブル定義書.xlsx`

All source fields used here are nullable/non-nullable character columns as
defined in the workbook. Raw JSON retains every source column, original string,
padding, Unicode, empty string, and NULL. Hashes use UTF-8, sorted-key compact
JSON; they hash values, not original PostgreSQL storage bytes. JSON key order is
not an observation. No past retrieval timestamp exists in these extracts.

| Canonical | Primary source | Rule/evidence |
|---|---|---|
| race date/venue/race number | L2 `kaisai_nen`, `kaisai_tsukihi`, `kyoteijo_code`, `race_no` | Source PK and PDF p.1 / workbook 出走表(レースNo); year+MMDD, 24 venue code mapping |
| venue code/name | PDF p.10 venue table | 01桐生 through 24大村; user motor schedule uses same venues |
| grade | L1 `grade_code` | PDF p.10: 1 SG, 2 PG1, 3 G1, 4 G2, 5 G3, 9 一般; other values NULL |
| women only | L3 entrant set + selected KI sex | User rule; six confirmed females TRUE, any male FALSE, otherwise NULL |
| entry fixed source | L2 `shinnyukotei` | PDF p.1: 1 fixed, 0 initial; initial is not verified FALSE |
| entry fixed effective | Source above, or 江戸川 user rule | Edogawa TRUE with `EDOGAWA_MODEL_RULE`; actual course untouched |
| stabilizer source | L2 `anteiban_shiyo` | PDF p.1: 1 used, 0 initial; prediction availability remains NULL |
| race status | Six matched L3/R3 records | `RESULT_RECORDS_PRESENT` is ingestion evidence, not a fabricated official race status |
| player ID | L3/R3 `toroku_bango` | Registration, cross-checked between entries/results |
| player name | Selected KI `shimei_kanji`, else L3 `shimei` | Original spelling/padding retained, no unsafe name cleanup |
| sex | KI `seibetsu_code` | PDF p.8/p.10; workbook レーサー期別成績 row23: 1 male, 2 female |
| training class | KI `yosei_ki` | PDF p.8 example 064=64期; workbook row69. No debut inference |
| motor number | L3 `motor_no` | PDF p.1; workbook 出走表(艇番) row37. Number may be right-padded with leading space |
| motor generation | Race date + 24 user fixed month/day rules | `user-fixed-month-day-v1`; not an observed replacement date |
| canonical boat_no | L3/R3 `teiban` | PK component, 1–6. L3 `boat_no` is the separate hull number and is not copied here |
| displayed term F/L | L3 `f_kaisu`, `l_kaisu` | PDF p.1 / workbook rows28–29; F count per user's confirmed current-term meaning; no F-suspension calculation |
| actual course | R3 `shinnyu_course` | PDF p.5 / workbook 結果(艇番)~1 row23; numeric1–6, otherwise NULL |
| finish raw/position | R3 `chakujun` | Numeric1–6 only; exact 01–06 mapping corroborated with official sample below |
| result status | R3 `kigo`, verified F/L finish symbols | PDF p.5: F flying, L late, K absent, S disqualified; unknown other finish symbols remain UNRESOLVED |
| start timing | R3 `st` + `kigo` | PDF p.5: 016=0.16 seconds; raw three-digit text retained; F/L numeric NULL |

Canonical provenance contains typed foreign keys to adopted raw observations,
normalization/rule versions, and field names. There is no standalone legacy race
ID column in these source tables: `source_race_id` is NULL and the complete
source natural key is kept in `source_record_key`. The source locator plus
parameter tuples (or bounded KI selection condition) reproduce the extraction.

## Independent official sample cross-check

Checked on 2026-09-22; these pages validate interpretation, not historical
availability. The importer never depends on these URLs.

- [2026-09-01 多摩川4R](https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20260901&jcd=05&rno=4):
  numeric finishes, registrations, displayed starts, and course order match all
  six R3 rows. The start order is 1,2,3,6,4,5; 4/5/6艇 are not courses4/5/6.
- [2026-09-01 浜名湖7R](https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20260901&jcd=06&rno=7):
  boats2/3 display F.02/F.01; R3 stores `002`/`001` plus `kigo=F` and `chakujun=Ｆ`.
- [2026-08-07 戸田6R](https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20260807&jcd=02&rno=6):
  boat3 displays L; R3 keeps `st='   '`, `kigo=L`, `chakujun=Ｌ`.

## Explicit unknowns and limits

- KI selects each entrant's latest source year/term strictly before its race
  year. Where several sample years share a player, the adopted observation must
  precede the player's earliest sampled race year. No future KI backfill.
  This is identity-only metadata, not a claim that KI statistics were available
  at a historical prediction timestamp. The selected KI is fully retained raw,
  but its performance statistics are not canonical prediction inputs.
- Registration5357 has no selected earlier-year KI. Sex, cohort, and KI
  provenance remain NULL; L3 registration/name remain preserved. Other players
  establish both female and male normalization. Missing does not become male.
- The PDF refers to a 着順(R3) table that is absent. `欠`, `エ`, `転` with blank
  kigo remain exact raw values and `UNRESOLVED`; they are not silently dropped or
  converted into normal finishes. Verified F/L mapping is implemented.
- The PDF's R3 stated byte length and trailing field offsets overlap/overflow.
  This implementation extracts named DB columns verified by the workbook. It
  does not parse those inconsistent fixed-width offsets. Binary-source import
  would require a corrected definition first.
- L2 zero values remain raw and canonical NULL. `stabilizer_available_for_prediction`
  is NULL because publication/receipt timing is unverified.
- `retrieved_at` is NULL. `extracted_at`/`ingested_at` are actual current events.
  D-1 filtering is proven; historical as-known-at-T reconstruction is NOT proven.
- The source schema contains more columns than the current canonical subset;
  those columns remain in raw without asserting their semantics.

None of these unknowns is filled with guessed values. They limit downstream
use; the bounded raw/identity/result foundation does not require those values
to be invented.
