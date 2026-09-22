# Phase 3A: L3全国勝率のCanonical化とlineage整備

実測: 2026-09-22T23:20:23.011280+09:00

## A. Verdict

**PASS_WITH_LIMITATIONS**。実装・全件更新・監査・再適用完了。0000の意味と歴史的receipt timestampは未確定のまま保持。

## B. Git identity

- branch: `main`
- HEAD: `ccbfc544e9a0ef0b1c61414f576c458dfc4f71d2`
- working tree: このPhase 3Aの変更あり。commit/pushなし。

## C. Schema

migration: `sql/migrations/0003_l3_national_win_rate.sql`。既存9 base tablesを維持。

|table|追加column|型・役割|
|---|---|---|
|core.race_entry|national_win_rate_raw|text、L3原値の完全保持|
|core.race_entry|national_win_rate|numeric(4,2)、generated stored|
|core.race_entry|national_win_rate_status|text、generated stored|

既存race×boat_no PKとsource_record_id FKを再利用する最小変更。選手の恒久属性やKI期別値に置き換えず、対象raceのentry値として保存する。新しい能力tableやmotor集計tableは不要。

`core.race_entry_national_win_rate` viewはrace自然キー、boat_no、registration_no、原値・数値・status、source record/batch ID、raw key、record/batch hash、各timestamp、source_field、normalization versionを公開する。

INSERT/COPY/UPDATEはL3 Rawから原値を導出し、race・艇番・登録番号・Raw keyの不一致を拒否する。採用entryを持つraceの自然キー変更も拒否する。型付き値・statusは直接書換不可。

既存Phase 2/2.5の結果snapshotは列選択を明示して従来の形式を維持。今回の全国勝率を旧凍結snapshotへ追加しない。

## D. 全国勝率定義

正式sourceは `brd_l3.zenkoku_ritsu_1`。競走点平均であり1着率ではない。保存済みPDF p.1の全国勝率4桁・0580→5.80、およびxlsx 出走表(艇番) rows18–20の対応を根拠とする。既存preflightの定義証跡を利用。

|原値|数値|status|
|---|---|---|
|0654|6.54|VALID|
|0000|NULL|UNRESOLVED|
|NULL・空文字・space-only|NULL|MISSING|
|桁不正・非ASCII数字等|NULL|INVALID|

非0000のASCII数字4桁を正確なDecimal相当で100除算。未確認の上限・下限による除外は追加しない。VALIDは形式・scale変換の妥当性であり、source値の業務的正しさや予測timestampの保証ではない。確認済みSPECIAL/SOURCE_SENTINELの分類はまだない。

KI ritsu_1は補助参照。5–10月=1期、11–4月=2期を維持し、今回はKI join・一致必須条件・自動補完を実装しない。

## E. Coverage

2017-01-01〜2026-09-19、24場、2,090選手。全3,252,960 entriesと一致。

|total|VALID|raw 0000|UNRESOLVED|INVALID|MISSING|
|---:|---:|---:|---:|---:|---:|
|3,252,960|3,246,735|6,225|6,225|0|0|

年別・venue別ともINVALID/MISSINGは全区分0。以下の0000はすべてUNRESOLVEDであり、VALIDとの重複はない。

### 年別

|年|total|VALID|0000 / UNRESOLVED|数値min–max|
|---|---:|---:|---:|---|
|2017|330,192|329,651|541|0.92–8.75|
|2018|331,992|331,369|623|0.83–9.43|
|2019|331,056|330,398|658|0.67–9.10|
|2020|332,784|332,117|667|0.75–9.15|
|2021|334,368|333,606|762|0.80–9.38|
|2022|338,616|337,985|631|0.80–8.72|
|2023|335,952|335,317|635|0.83–8.99|
|2024|336,384|335,691|693|0.80–8.80|
|2025|335,448|334,790|658|0.80–9.16|
|2026|246,168|245,811|357|0.94–8.77|

2026年は9月19日まで。

### venue別

|場|total|VALID|0000 / UNRESOLVED|
|---|---:|---:|---:|
|01 桐生|135,576|135,303|273|
|02 戸田|135,504|135,167|337|
|03 江戸川|132,336|132,326|10|
|04 平和島|128,160|127,908|252|
|05 多摩川|132,696|132,340|356|
|06 浜名湖|142,200|141,912|288|
|07 蒲郡|137,160|136,850|310|
|08 常滑|141,696|141,386|310|
|09 津|135,360|135,069|291|
|10 三国|135,000|134,771|229|
|11 びわこ|130,392|130,184|208|
|12 住之江|133,704|133,354|350|
|13 尼崎|131,976|131,764|212|
|14 鳴門|130,032|129,805|227|
|15 丸亀|138,672|138,390|282|
|16 児島|137,232|136,981|251|
|17 宮島|139,320|139,083|237|
|18 徳山|138,528|138,292|236|
|19 下関|131,112|130,907|205|
|20 若松|139,176|138,856|320|
|21 芦屋|137,304|137,032|272|
|22 福岡|134,208|133,845|363|
|23 唐津|135,504|135,262|242|
|24 大村|140,112|139,948|164|

### player別確認

全2,090選手の件数・status・数値min/maxをJSONに保存。INVALIDのある選手0、UNRESOLVEDのある選手698、全件UNRESOLVEDの選手0。

- 数値最小0.67: 登録5082。最大9.43: 登録4350。原値との一致を全件照合済み。低値を理由に1.00へ補正・除外していない。
- 0000最多: 登録4510の35/581件。比率最大: 登録5149の9/31件（約29.0%）。
- 選手対応・形式・scale変換の異常は検出0。ただし0000の偏りの原因や0.67等の業務的妥当性を、統計的に解明したという判定ではない。

## F. Lineage

全件でRaw→Canonicalの原値・数値・status、race自然キー、艇番、登録番号、source_record_keyを照合。不一致・lineage欠落・Canonical duplicateはいずれも0。

保存済みL3全体から逆方向にも照合し、未対応Raw・未対応Canonical・入力競合は0。

```json
{
  "raw_observations": 3253014,
  "distinct_entry_keys": 3252960,
  "distinct_input_observations": 3252960,
  "raw_without_matching_canonical": 0,
  "canonical_without_matching_raw": 0,
  "repeated_identical_observations": 54,
  "conflicting_input_observations": 0
}
```

同一観測の複数batch保存はRawの履歴であり、Canonical重複とは区別。全件のretrieved_atはNULLで、historical_availability_statusはNOT_VERIFIED。extracted_at/ingested_atを過去公開時刻へ読み替えていない。

## G. Tests

79 tests PASS / 0 fail / 0 skip（既存62 + 追加17）。使い捨てDBで実source sample・COPY pipeline・冪等性も成功。

追加範囲: normal parse、raw保持、0000、invalid/missing、直接改変防止、lineage、race×boat/registration対応、duplicate防止、parent自然キー保護、migration再適用、Raw replay、既存populated schema upgrade、実fixtureの2017境界、D-1、旧snapshot形式維持。

実DB初回更新3,252,960件、最終コードによる再適用更新0件。初回と再監査の全体・年別・場別・全player・lineage集計は完全一致。監査の数値/status期待値は正規化関数を呼ばず別式で算出。

途中の再適用試行は大規模UPDATE JOINの一時ディスク書出しにより中断し、当該transactionをrollbackした。未設定行がなければUPDATEを省略する処理を追加し、全件監査を維持した最終コードで上記の再適用を完了した。

空DBからの全migration再構築と実DBのschema signatureが一致: `cea0e0c93b17911352455813e8d313c9a2dc12d8ff3060f4efd4e1373690c66f`。

凍結datasetの保存hash/manifest hash/D-1 metadataとRaw batch metadataは更新前後不変。2017-01・2026-09の既存frozen shard再生成が同一hashでnew=False。今回、全履歴を別空DBへ再importするPhase 2.5全件replayは実施していない。

凍結datasetは119件、Raw batchは656件。2017年より前のCanonical raceは0、datasetのD-1境界違反も0。

## H. Known limitations

- 0000のsource意味は未確定。6,225件は数値NULL・UNRESOLVEDのまま。0補完なし。
- 過去の実retrieved_atは全件不明。VALIDをas-known-at-Tの証明として扱わない。
- L3は対象raceの出走表情報。営業日DのRating更新はD-1までの結果という既存原則を維持。同日結果へのjoinは追加していない。
- 旧snapshotには新fieldを追加していない。将来の予測datasetでは新しい入力snapshot versionとavailability方針が必要。
- motor評価A/B、finish join、motor contribution/ranking/累積、Rating、F休み、進入指数、environment/preinfo model、Prediction、3連単、Odds/value/Betting、2026 walk-forwardはいずれも未実装。

## I. Changed files

- README.md
- docs/source_mapping.md
- docs/phase3a_report.md
- scripts/import_sample.py
- scripts/freeze_history.py
- scripts/verify_history.py
- scripts/national_win_rate.py
- sql/migrations/0003_l3_national_win_rate.sql
- tests/test_national_win_rate.py

実測JSONはgitignore対象 `.local/phase3a/` に保持（coverage.json、reapply.json、tests.json、final_checks.json）。Raw・secret・大容量生成物をGit変更へ追加していない。

## J. Recommended next step

R2/R3結果状態分類へ進める入力基盤は整った。次は別scopeで結果状態・特殊着順・採否規則を確定する。今回の判定はmotor計算やRating/Predictionの開始・モデル投入可否を一括承認するものではない。0000とtimestampの制約は次段階へ引き継ぐ。
