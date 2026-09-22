# Phase 3C environment / preinfo report

## A. Verdict

**PASS_WITH_LIMITATIONS**。C2/C3全原行をRawへ保存し、確定定義のCanonical化、全件照合、再実行追加0、既存データ不変を確認した。単位未確定の風速/波高とC4の数値は採用していない。

依頼中の一周・半周・回り足・直線は、実sourceではC3ではなくC4である。C4対象外という明示指定を優先し、今回はそれらの数値Canonicalを作らず、場×fieldの構造仕様だけを公開した。この制約を8項目すべて実装済みとは表現しない。

## B. Preflight checkpoint

- 基準: `69d4f70e7d392c55ae5c07c2c69dfd97aab49025`。
- 指定2ファイルだけのcommit: `6252720e737c4ab3fd0174aceb72762df90d45a9`。
- commit名: `docs: checkpoint environment and preinfo source inventory`。
- 通常push先: `https://github.com/yonsei50-cyber/boatrace-predictor.git` のmain。
- local HEAD / origin/main / `git ls-remote` 実remoteの3者一致を確認。force/history rewriteなし。
- preflight全件を再実測し、観測時刻と旧報告へ付加されたreconciliationラベル以外の全source集計が保存inventoryと完全一致。credential pattern検査0件、内容目視確認。生成JSON/ログはcommit対象外。
- 自動承認レビューの拒否後、ユーザーから当該commitだけの明示承認を受けてpush。Phase 3Cの変更は未commit・未push。

## C. Schema

追加migration: `sql/migrations/0005_environment_preinfo.sql`。既存の初期化migrationは本DBで再実行していない。

|種類|追加内容|
|---|---|
|table|`core.race_environment_preinfo`（race）|
|table|`core.race_boat_preinfo`（race × boat_no）|
|view|`core.race_environment_preinfo_status`|
|view|`core.race_boat_preinfo_status`|
|view|`core.c4_field_structural_status`（場×fieldの仕様metadataのみ）|
|functions/triggers|raw→typed/statusの決定的関数、source identity検証、月次batch指定backfill|

既存tableへのcolumn追加なし。新tableでは原値、generated typed value/status、source_record_id、normalization_version、provenanceを保持。status viewはbatch/key/hash/locator/retrieved_at/extracted_at/ingested_atまで追跡可能。異なるrace/boat/sourceの参照は拒否し、原値とprovenanceはRawから導出する。

空DBから全migrationを再構築したschemaとの一致: PASS。signature: `beb5484e60df2e7412d0e7eb32b9d8fedeb2c93dfce5ffd6381d78dacc741359`。0005再適用も検証済み。

## D. C2 Raw

542,003 records、117月次batch、2017-01-01〜2026-09-18、24場、542,003 race。batch/record原値hash、自然キー、順序位置、lineageを全件検証。SOURCE_EMPTYは成功した空取得だけに用い、fetch failureは例外終了して成功batchを作らない。

## E. C3 Raw

3,252,018 records、117月次batch、同期間・24場、542,003 race。各raceの6艇が揃い、boat_noは1〜6のidentityである。

C2/C3合計3,794,021 recordsを追加。全sourceを再取得した同一内容再実行は**追加batch 0 / record 0**。Rawの旧sourceテーブルを変更せず、旧DBはREAD ONLY。Canonical追加は初回/追補合計3,794,021行、全件再実行追加0行。

### 年別coverage

|year|C2 raceあり|C2 source欠落race|C3 boatあり|C3 source欠落boat|
|---|---|---|---|---|
|2017|55032|0|330192|0|
|2018|55332|0|331992|0|
|2019|55176|0|331056|0|
|2020|55464|0|332784|0|
|2021|55728|0|334368|0|
|2022|56435|1|338610|6|
|2023|55992|0|335952|0|
|2024|56064|0|336384|0|
|2025|55908|0|335448|0|
|2026|40872|156|245232|936|

### 場別coverage

|venue_code|C2 raceあり|C2 source欠落race|C3 boatあり|C3 source欠落boat|
|---|---|---|---|---|
|1|22596|0|135576|0|
|2|22572|12|135432|72|
|3|22044|12|132264|72|
|4|21348|12|128088|72|
|5|22104|12|132624|72|
|6|23688|12|142128|72|
|7|22860|0|137160|0|
|8|23616|0|141696|0|
|9|22560|0|135360|0|
|10|22500|0|135000|0|
|11|21732|0|130392|0|
|12|22272|12|133632|72|
|13|21984|12|131904|72|
|14|21660|12|129960|72|
|15|23100|12|138600|72|
|16|22859|13|137154|78|
|17|23208|12|139248|72|
|18|23088|0|138528|0|
|19|21852|0|131112|0|
|20|23196|0|139176|0|
|21|22884|0|137304|0|
|22|22368|0|134208|0|
|23|22572|12|135432|72|
|24|23340|12|140040|72|

## F. Environment Canonical

分母はC2が存在する542,003 race。source行不存在157 raceは下記field欠測へ混ぜない。

|field|実測status件数|
|---|---|
|air_temperature|MISSING=6,619, VALID=535,384|
|surface_weather_marker|MISSING=497,196, UNRESOLVED=44,807|
|venue_direction|VALID=542,003|
|water_temperature|MISSING=6,619, VALID=535,384|
|wave_height|MISSING=6,621, UNRESOLVED=535,382|
|weather|MISSING=485, VALID=541,518|
|wind_direction|MISSING=42,243, VALID=499,760|
|wind_speed|MISSING=6,619, UNRESOLVED=535,384|

|field|unit / grain / interpretation|
|---|---|
|air_temperature_c|℃、原値÷10。C2 race単位の観測|
|water_temperature_c|℃、原値÷10。C2 race単位の観測|
|weather_code|source code 1〜6。C2 race単位の観測|
|wind_direction_code|source方角code 01〜16。C2 race単位の観測|
|venue_direction_code|source方角code 01〜16。意味は場の方向、保存粒度はC2 race原行のまま|
|wind_speed_raw|原値保持。source資料のm表記と物理単位の対応が未確定なので数値列なし|
|wave_height_raw|原値保持。source資料m/公式表示cmの矛盾が未解決なので数値列なし|
|surface_weather_marker_raw|原値HHmm/blank保持。race観測・場単位更新のどちらの時刻か未解決。as-of timestampにしない|

別raceへの値コピーなし。観測の原source粒度はraceだが、正確な観測/公表時刻の証明はUNKNOWN。無風や0℃を一括sentinelにせず、風向空白を北等へ補完していない。

## G. Preinfo Canonical

分母はC3が存在する3,252,018艇。行不存在942艇とは区別。

|field|実測status件数|
|---|---|
|exhibition_course|MISSING=45,024, VALID=3,206,994|
|exhibition_start|F=706,149, L=478, MISSING=45,031, VALID=2,500,360|
|exhibition_time|SOURCE_SENTINEL=44,490, VALID=3,207,528|
|tilt|MISSING=42,158, VALID=3,209,860|

展示timeは原値÷100秒、0000はSOURCE_SENTINEL、typed=NULL。tiltはpaddingを保持した原値から÷10で度へ変換し、0.0は有効値。
度という物理単位は[BOAT RACE公式用語辞典](https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/17/y_167.html)でも確認。場別の許容角度や効果をモデル化していない。

一周/半周/回り足/直線はC4専用fieldで今回数値化していない。半周を一周へ代用する処理なし。

## H. Start exhibition

展示進入 `exhibition_course` は本番 `actual_course` と独立。1〜6だけVALID、範囲外INVALID、空白MISSING。boat_noによる補完なし。

展示STは `exhibition_start_timing_raw` と `exhibition_start_symbol_raw` を保持。通常数字は原値÷100秒、000は0.00秒としてVALID。展示F **706,149**、L **478**はtyped=NULLであり、通常STへ変換しない。FでST原値空白28艇もFのまま。未知記号はUNRESOLVED_SYMBOL。既存本番start_timingと結果データは変更していない。

## I. Structural missing

`core.c4_field_structural_status` は24場×4field=96行、うち8場×fieldセルがSTRUCTURALLY_NOT_PROVIDED。

|場|STRUCTURALLY_NOT_PROVIDED|
|---|---|
|01 桐生|一周|
|03 江戸川|一周・半周・回り足・直線|
|12 住之江|直線|
|13 尼崎|直線|
|18 徳山|直線|

その他88セルはUNRESOLVED（C4未採用）。桐生の半周や各場の展示を「観測なし」と断定する表ではない。期間別提供開始/停止やC4行不存在の理由は未確定で、歴史上すべてのraceへ構造欠測を断定したものでもない。C3展示値は独立に実測statusを保持。

## J. 157 missing races

2022-04-09児島4Rの1race、2026-09-19の156race。C2/C3で欠落race集合が完全一致。各6艇で942艇のsource行不存在。全race/entryを維持し、coverage viewでMISSING_SOURCE、typed値NULLとし、0/平均値補完なし。

|date|venue_code|欠落race数|
|---|---|---|
|2022-04-09|16|1|
|2026-09-19|2|12|
|2026-09-19|3|12|
|2026-09-19|4|12|
|2026-09-19|5|12|
|2026-09-19|6|12|
|2026-09-19|12|12|
|2026-09-19|13|12|
|2026-09-19|14|12|
|2026-09-19|15|12|
|2026-09-19|16|12|
|2026-09-19|17|12|
|2026-09-19|23|12|
|2026-09-19|24|12|

全自然キーは `.local/phase3c/audit.json` の `canonical.missing_race_keys` に記録。

## K. Lineage / replay / preservation

全3,794,021 Raw行についてrecord hash、batch hash、自然キー、source_position、月次境界、順序、重複を検査し、不一致0。Canonical全行を保存Rawから別SQL式で再計算し、原値・typed値・status・identity・provenance・lineageの不一致0。SQL正規化関数そのものを期待値として呼ばない全件再計算である。

既存6table（venue/player/motor/race/race_entry/race_result）の全行fingerprintが前後一致。凍結datasetのID/content_hash/manifest_hash/effective_date/results_cutoff_dateも前後一致。D-1違反0、凍結datasetへのC2/C3混入0。既存Raw source別batch/record件数もcheckpointから不変。

## L. Tests

**107 pass / 0 fail / 0 skip**。既存93件と追加14件。9table前提の既存テストだけは追加2tableを含む正確なtable集合検査へ更新した。

追加対象: C2/C3冪等、変更source拒否、空取得/取得失敗、自然キー重複/順序/範囲、2017境界、6艇、進入範囲、通常ST/0.00/F/L、sentinel、missing/invalid/unresolved unit、lineage偽装拒否、異なるsource参照拒否、Canonical再実行/競合revision、構造欠測、本番fieldとの分離、migration再適用、D-1維持。

破棄用DBによる既存実source sample pipelineと冪等確認もPASS。schema空DB再構築PASS。全期間のRaw再取込0・Canonical再実行0・独立全件再計算PASS。今回は新しい全期間DBを別途複製してreplayしたわけではなく、保存Rawのhash検証と現在Canonicalの全件再計算照合である。

## M. Known limitations / timing policy

1. 風速/波高の単位未確定。数値Canonical採用を保留した。
2. C4はRaw取込・数値Canonicalとも0。正式scale、艇対応ずれ、持越し、場別開始/停止、historical repairを別Phaseで検証する。
3. 個別retrieved_at/過去版履歴は存在しない。予測利用はユーザー指定のpre-race source-class方針であり、exact historical as-ofの証明ではない。extracted_at/ingested_atは今回の監査・保存時刻で、公開時刻の代用にしない。
4. C2の時刻markerをrace前公開証明として使わない。結果sourceからの代用なし。
5. Parts全原値はC3 Rawに保存済みだがCanonical未実装。数量を1と推測していない。
6. 既存frozen datasetは結果中心の旧column契約を維持する。将来の入力datasetはpreinfoを含む別version/time policyが必要。
7. 同じ月のsource内容変更は自動採用を拒否する。更新revisionの選択は将来の明示手順が必要。
8. Environment development 2017-01-01〜2024-12-31、2025 holdoutを維持。Preinfoは2024以前の現存dataをdevelopment候補とするが開始windowは未固定。モデル学習・tuning・Rating・Prediction・odds/value/betting・2026 walk-forwardは未実施。

## N. Changed files

preflight checkpointに含めた2ファイル: `docs/environment_preinfo_source_inventory.md` / `scripts/preflight_environment_preinfo.py`。

未commitのPhase 3C:

- [README.md](C:/Users/knkzh/Documents/boatrace-predictor/README.md)
- [docs/phase3c_report.md](C:/Users/knkzh/Documents/boatrace-predictor/docs/phase3c_report.md)
- [scripts/import_environment_preinfo.py](C:/Users/knkzh/Documents/boatrace-predictor/scripts/import_environment_preinfo.py)
- [scripts/apply_environment_preinfo.py](C:/Users/knkzh/Documents/boatrace-predictor/scripts/apply_environment_preinfo.py)
- [scripts/audit_environment_preinfo.py](C:/Users/knkzh/Documents/boatrace-predictor/scripts/audit_environment_preinfo.py)
- [scripts/verify_history.py](C:/Users/knkzh/Documents/boatrace-predictor/scripts/verify_history.py)
- [sql/migrations/0005_environment_preinfo.sql](C:/Users/knkzh/Documents/boatrace-predictor/sql/migrations/0005_environment_preinfo.sql)
- [tests/test_database.py](C:/Users/knkzh/Documents/boatrace-predictor/tests/test_database.py)
- [tests/test_environment_preinfo.py](C:/Users/knkzh/Documents/boatrace-predictor/tests/test_environment_preinfo.py)
- [tests/test_environment_preinfo_raw.py](C:/Users/knkzh/Documents/boatrace-predictor/tests/test_environment_preinfo_raw.py)

Raw/credential/JSON/logはGit対象外。schemaとデータはローカル専用targetに適用済み。

## O. Recommended next step

**部品交換の1対多Canonical**を次に行う。C3 Rawに全fieldが揃っており、まずpart_type/raw codeを保持し、quantityは意味確認済みの場合だけ設定する。その後C4品質調査を独立Phaseで行い、scaleと艇対応/持越しの品質ゲートを確定する。F休み・進入指数・Ratingは別の仕様/時点検証を経て着手し、同時に広げない。

### Reproduction evidence

`.local/phase3c/` の `raw_import.json`, `raw_repeat.json`, `canonical_initial.json`, `canonical_complete.json`, `canonical_repeat.json`, `audit.json`, `protected_before.json`, `protected_after.json`, `tests.json`, `schema.json`。全件year×venue×field status明細と検査値はaudit JSONを参照。

再現commandはREADMEのPhase 3C節。取込は旧DB READ ONLY、監査もtarget READ ONLY。再実行は既存batchを再利用し、内容変更がある場合は停止する。
