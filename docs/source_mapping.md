# Phase 2 source mapping

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
