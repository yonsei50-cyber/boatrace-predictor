# Phase 3B: R2/R3結果状態分類
実測report生成: 2026-09-22T14:48:31.861672+00:00

## A. Verdict

**PASS_WITH_LIMITATIONS（Phase 3B）**。実装・実DB適用・93 tests・全件監査完了。特殊記号と重複順位、5件の状態は未解決として保持。Phase 3Aの通常pushは後続の明示承認により完了し、local / origin/main / 実remoteの一致を確認済み。

## B. Phase 3A checkpoint

- branch: `main`
- local HEAD: `6bda83e1d5df6aef8921706357244e85f6ba8c91`
- commit: `feat(entries): canonicalize L3 national win rate`、指定9ファイルのみ。
- origin/main / 実remote main: `6bda83e1d5df6aef8921706357244e85f6ba8c91`（通常push後のread-only ls-remote確認）。
- Phase 3A通常push完了。force push/history rewriteなし。
- commit前再検証: 79 tests PASS、L3 lineage不一致0、0000=6225件はnumeric NULL/UNRESOLVED、KI補完なし。119 frozen datasetの実content/manifest hashとD-1検証PASS。
- Phase 3B checkpoint前の基準HEADは上記Phase 3A commit。対象は本報告の9ファイルのみ。

## C. Schema

|view|役割|
|---|---|
|core.result_source_evidence|R2/R3原観測、自然キー、全payload、record/batch ID・hash・source location・各timestamp|
|core.race_result_state|2017+ raceごとのR3充足・R2根拠・revision conflictとrace状態|
|core.boat_finish_state|既存entryごとのfinish分類、原値、既存ST状態、全R3 lineage|

`0004_result_states.sql`はviewのみ追加。既存9 base tablesの構造・Canonical値・旧result_status・frozen snapshot列契約を変更しない。全原観測のhash差異は競合として公開し、勝手にrevisionを選ばない。競合boatのscalar原値はNULL、原値配列とlineageで各観測を保持。現在のRawを参照するviewであり、過去予測時点のsnapshotではない。

## D. R2

source: `pckyotei.public.brd_r2`、2017-01-01〜2026-09-18。542,004レコード、117月partition。完全な原行を既存Raw batch/record frameworkへ追加し、Raw自然キー・行hash・batch hash・provenanceを保持。source接続はREAD ONLY。2016以前の移行なし。
全件hash/lineage監査: {'rows': 542004, 'batches': 117, 'lineage_mismatch': 0}。再実行の新規batch数: 0。
historical retrieved_atはNULL。extracted_at/ingested_atを過去の公開時刻として扱わない。変更partitionは自動採用を拒否する。

|R2 raw data_kubun|有効な第1枠3連単組番|race数|
|---|---|---|
|0|あり|535026|
|0|なし|309|
|9|なし|6669|
|R2観測なし|なし|156|

調査対象515+5=520 raceは、調査時のR2全行hashと保存Rawのhashを再照合し、不一致0。

保存仕様書 `C:\Users\knkzh\Documents\kyotei\PC-KYOTEIデータ仕様書.pdf` p.5を今回再確認。SHA256 `08b3bb2c3897a808de74bc8f75283103625456cfa72ff23d746bf9befca85897`。R2 data_kubun=9はレース中止、0は初期値。3連単払戻は6回繰返し、000は当該勝式の不成立、***は特払い。R3 kigo F/L/K/Sの定義は確認できたが、参照されている着順(R3)コード表は当該PDFに見つからない。

## E. Race states

|状態|race数|定義|
|---|---|---|
|R2_EVENT_STATE_PRESENT|6669|有効な個別R3がなく、R2の確認済みdata_kubun=9が存在。|
|R2_PAYOUT_PRESENT_R3_MISSING|254|有効な個別R3がなく、R2第1枠3連単払戻組番が1〜6の異なる3艇。|
|RESULT_RECORDS_PRESENT|535076|6艇の非空欄R3 finishが存在。正常完走・eligibilityの保証ではない。|
|SOURCE_INCOMPLETE|156|R3が部分的、boat key不完全、またはR3観測自体がない。|
|UNRESOLVED|5|空欄R3の理由が根拠から確定できない、またはsource revision競合。|

R2/R3競合があればUNRESOLVEDを優先。6艇非空欄は特殊finishや数値重複と両立する。払戻検出は現在の第1枠3連単に限定し、他勝式・後続枠・特払いだけの未知ケースを正常に推定しない。全払戻原値はRawに残る。

|total races|entries / finish view|Canonical results|blank R3 races|duplicate numeric races|
|---|---|---|---|---|
|542160|3252960|3210456|6928|515|

Canonical resultsはPhase 2.5と同じ3,210,456件。Raw R3空欄41,568艇をCanonical結果へ追加していない。2026-09-19の156 race / 936 entriesには結果観測がなくSOURCE_INCOMPLETE。これと6,928 blank R3 raceを混同しない。

## F. Finish states

|状態|艇数|
|---|---|
|NO_INDIVIDUAL_RESULT|42504|
|NUMERIC_DUPLICATE_UNRESOLVED|1030|
|NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED|2052|
|NUMERIC_VALID|3160233|
|UNRESOLVED_SPECIAL|47141|

NUMERIC_VALIDは同一race内に数値着順重複がない1〜6。重複した値をNUMERIC_DUPLICATE_UNRESOLVED、同raceの残り数値をNUMERIC_IN_DUPLICATE_RACE_UNRESOLVEDと分ける。値の付替えなし。NO_INDIVIDUAL_RESULTは原観測の空欄または不存在。UNRESOLVED_SPECIALは原記号を保持する。

## G. Special symbols

|raw symbol|艇数|race数|意味|
|---|---|---|---|
|＿|53|53|未確定、UNRESOLVED_SPECIAL|
|Ｆ|12637|9194|未確定、UNRESOLVED_SPECIAL|
|Ｌ|370|353|未確定、UNRESOLVED_SPECIAL|
|エ|2911|2836|未確定、UNRESOLVED_SPECIAL|
|欠|5942|5875|未確定、UNRESOLVED_SPECIAL|
|失|250|218|未確定、UNRESOLVED_SPECIAL|
|沈|414|413|未確定、UNRESOLVED_SPECIAL|
|転|16083|15549|未確定、UNRESOLVED_SPECIAL|
|不|1253|1225|未確定、UNRESOLVED_SPECIAL|
|妨|2805|2805|未確定、UNRESOLVED_SPECIAL|
|落|4423|4374|未確定、UNRESOLVED_SPECIAL|

9記号（転/欠/落/エ/妨/不/沈/失/＿）は合計34,134件。finish側のＦ/Ｌもこのviewでは特殊finishとして保持し、ST側の確認済みF/L定義と区別する。一般用語からの意味確定や点数付与なし。

## H. Blank R3

|race state|race数|
|---|---|
|R2_EVENT_STATE_PRESENT|6669|
|R2_PAYOUT_PRESENT_R3_MISSING|254|
|UNRESOLVED|5|

計6,928 race / 41,568艇。6,669=R2 code9、254=払戻組番あり、5=未解決という既存preflightと一致。254件の個別着順を払戻から生成していない。

重点5件は以下。全件L1×1、L2×1、L3×6、R2×1、R3×6が保存sourceに存在。R2は0、払戻全欄空白、R3は登録番号/finish/course/ST空欄。metadataや出走表だけで終了/中止を確定できずUNRESOLVED。全原行・hashを調査JSONに保存。

|開催年|月日|venue|race|
|---|---|---|---|
|2025|0810|04|10|
|2025|0810|05|10|
|2025|0810|07|04|
|2025|0810|19|03|
|2025|0810|19|04|

## I. Duplicate numeric finish

515組 / 515 raceを全艇Raw R3・R2全払戻・race状態と照合。重複順位: 1着5、2着28、3着168、4着187、5着127。201 raceは3連単払戻2組、314 raceは1組。数値の同順位を許す順序仮説から列挙した組番とR2払戻組番は515/515一致。これは整合性の証拠であり、515件すべての正式同着認定ではない。全件未解決分類を維持。確定オッズを根拠として使用していない。

## J. F/L

|ST状態|finish原値|finish状態|race状態|actual_courseあり|艇数|
|---|---|---|---|---|---|
|F|Ｆ|UNRESOLVED_SPECIAL|RESULT_RECORDS_PRESENT|True|12637|
|L|Ｌ|UNRESOLVED_SPECIAL|RESULT_RECORDS_PRESENT|False|149|
|L|Ｌ|UNRESOLVED_SPECIAL|RESULT_RECORDS_PRESENT|True|221|

F=12,637、L=370。数値ST変換0件。ST状態は既存Canonicalを再利用し、finishとは独立監査。

### 年別・venue別 coverage

#### year

|year|R2_EVENT_STATE_PRESENT|R2_PAYOUT_PRESENT_R3_MISSING|RESULT_RECORDS_PRESENT|SOURCE_INCOMPLETE|UNRESOLVED|
|---|---|---|---|---|---|
|2017|496|0|54536|0|0|
|2018|821|0|54511|0|0|
|2019|635|0|54541|0|0|
|2020|581|0|54883|0|0|
|2021|772|0|54956|0|0|
|2022|852|9|55575|0|0|
|2023|602|0|55390|0|0|
|2024|696|0|55368|0|0|
|2025|736|245|54922|0|5|
|2026|478|0|40394|156|0|

|year|NO_INDIVIDUAL_RESULT|NUMERIC_DUPLICATE_UNRESOLVED|NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED|NUMERIC_VALID|UNRESOLVED_SPECIAL|F|L|
|---|---|---|---|---|---|---|---|
|2017|2976|118|235|322079|4784|1298|32|
|2018|4926|130|259|321842|4835|1286|37|
|2019|3810|130|259|322237|4620|1232|48|
|2020|3486|108|215|324089|4886|1269|48|
|2021|4632|104|207|324451|4974|1346|48|
|2022|5166|104|206|327921|5219|1300|42|
|2023|3612|100|200|326995|5045|1366|34|
|2024|4176|78|156|327108|4866|1389|28|
|2025|5916|106|211|324610|4605|1202|31|
|2026|3804|52|104|238901|3307|949|22|

#### venue

|venue|R2_EVENT_STATE_PRESENT|R2_PAYOUT_PRESENT_R3_MISSING|RESULT_RECORDS_PRESENT|SOURCE_INCOMPLETE|UNRESOLVED|
|---|---|---|---|---|---|
|1|238|47|22311|0|0|
|2|125|23|22424|12|0|
|3|1448|5|20591|12|0|
|4|100|11|21236|12|1|
|5|42|8|22053|12|1|
|6|178|35|23475|12|0|
|7|131|40|22688|0|1|
|8|180|1|23435|0|0|
|9|698|5|21857|0|0|
|10|410|5|22085|0|0|
|11|151|3|21578|0|0|
|12|78|12|22182|12|0|
|13|144|3|21837|12|0|
|14|320|0|21340|12|0|
|15|418|13|22669|12|0|
|16|114|1|22745|12|0|
|17|138|3|23067|12|0|
|18|95|1|22992|0|0|
|19|299|18|21533|0|2|
|20|643|9|22544|0|0|
|21|159|0|22725|0|0|
|22|228|7|22133|0|0|
|23|148|0|22424|12|0|
|24|184|4|23152|12|0|

|venue|NO_INDIVIDUAL_RESULT|NUMERIC_DUPLICATE_UNRESOLVED|NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED|NUMERIC_VALID|UNRESOLVED_SPECIAL|F|L|
|---|---|---|---|---|---|---|---|
|1|1710|32|63|131933|1838|467|10|
|2|960|16|31|132399|2098|527|12|
|3|8790|22|43|120808|2673|705|35|
|4|744|14|28|125291|2083|585|14|
|5|378|30|60|130488|1740|506|14|
|6|1350|38|76|138709|2027|617|13|
|7|1032|38|76|133992|2022|569|18|
|8|1086|48|96|138650|1816|565|25|
|9|4218|38|74|129090|1940|605|19|
|10|2490|80|160|130375|1895|559|14|
|11|924|36|72|127594|1766|384|14|
|12|612|34|68|131028|1962|519|14|
|13|954|74|148|128985|1815|396|18|
|14|1992|72|144|125982|1842|456|4|
|15|2658|28|56|133925|2005|551|13|
|16|762|28|56|134388|1998|558|8|
|17|918|96|191|136006|2109|483|26|
|18|576|78|156|135996|1722|397|14|
|19|1914|44|87|127348|1719|475|11|
|20|3912|28|56|133134|2046|577|18|
|21|954|48|96|134099|2107|542|10|
|22|1410|28|55|130752|1963|427|20|
|23|960|40|80|132379|2045|596|12|
|24|1200|40|80|136882|1910|571|14|

symbol別の年/venue明細も `.local/phase3b/audit.json` に保存。各集計の粒度は上記列名どおりで、race数と艇数を混算しない。

## K. Tests / lineage

93 tests PASS / 0 fail / 0 skip（既存79維持、追加14）。使い捨てDBでRaw replay・既存pipeline・D-1・migration再適用・保全・F/L独立性・数値重複・R2競合/冪等性/拒否を検証。
全件lineage: `{"finish_mismatch": 0, "numeric_mismatch": 0, "st_raw_mismatch": 0, "st_mismatch": 0, "st_status_mismatch": 0, "missing_adopted_source": 0, "numeric_fl": 0}`。独立数値監査: `{"invalid_valid": 0, "missing_valid": 0}`。Canonical/view重複0、source conflict race0。
既存race/entry/result/datasetの行数と全行fingerprint、既存非R2 batchのID/hash/count fingerprintは前後一致。frozen dataset119件はPhase3A commit前に実content/manifest hashとD-1を全検証し、Phase3B後は全行fingerprintの不変を照合。全履歴の別DBへの再importは今回未実施。
初期SQLの曖昧JOINを修正後、最終93 testsは全PASS。途中のfocused testが実DBへ接続したがtransactionはrollback済み、データ/DDL変更の残存なし。非transactional identity sequenceには欠番が生じた。最終検証は使い捨てDBのみ。

## L. Known limitations

- 5 race・9種特殊finish・515 numeric duplicate raceは意味/扱い未解決。
- F/LはST定義のみ確認。finish側の全角記号の意味・Rating/motor採否を追加確定しない。
- historical publication/receipt時刻は未検証。viewは現在のRaw観測を分類する。
- 同順位順序仮説と払戻一致を全件同着認定へ昇格しない。
- Raw修正版の自動選択、Rating/motor A/B・点数・Prediction・モデル・odds/value/bettingは未実装。
- 全件viewはRaw集約を実行するため、監査では一時tableに一度展開して集計する。永続cache/新基盤は追加していない。

## M. Changed files

- `README.md`
- `docs/source_mapping.md`
- `docs/phase3b_report.md`
- `scripts/verify_history.py`
- `scripts/import_result_evidence.py`
- `scripts/investigate_result_evidence.py`
- `scripts/audit_result_states.py`
- `sql/migrations/0004_result_states.sql`
- `tests/test_result_states.py`

Phase 3B checkpoint対象は上記9ファイル。実測JSONはgitignore対象 `.local/phase3b/` に保持。secret・Raw大量データ・一時生成物をGitへ追加していない。

## N. Recommended next step

environment/preinfoのsource定義・時間的可用性の独立した調査へは進める。今回まだ実装しない。Rating/motor/学習への結果投入前には、未解決・source incomplete・duplicate・specialの採否規則と評価プロトコルを別途固定する。未解決を正常値へ補完して進めない。Phase3Bを独立checkpointとし、その後にsource inventoryを行う。
