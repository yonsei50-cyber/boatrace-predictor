# Phase 2.5 report — 2017+ Raw / Canonical foundation

実測日: 2026-09-22。対象はユーザー修正により **2017-01-01以降**。
全件移行・監査・空DB再現を実行して確定した報告。

## A. Verdict

**PASS_WITH_KNOWN_LIMITATIONS**。

対象Raw / Canonical移行、全件監査、空DBからの全期間replay、冪等性・dataset一致確認が完了。
既存DBと再構築DBの監査はいずれもPASS、BLOCKING各項目は0。
source欠測・未解釈特殊値・公開時刻不明は残り、意味を推測した補完は行っていない。
この判定は2017+の保存済みsourceに対する基盤品質の判定であり、
全開催の外部完全性や予測用の時点情報を保証するものではない。

## B. Git identity / initial gate

- Repository: `C:\Users\knkzh\Documents\boatrace-predictor`
- Branch: `main`
- HEAD / local `origin/main`: `894914a06f7a57113d2ca3ee304710d3c1dd748f`
- 開始時working tree: clean。`docs/phase2_report.md` と `docs/source_mapping.md` を確認。
- DB: `boatrace_predictor`, role `itgakko`, PostgreSQL 16.4。
- 既存0001/0002 migrations・9 tablesを再利用。空DBへmigrationを二度適用し同一schemaを確認。
- Schema signature: `0b0abc6e1f5abc9f5997a9c28a0f8067864594dd9bce5a1a52311b82062fd828`。
- 開始時Phase 2 counts: Raw batch 5 / record 174、venue 24 / race 9 / player 49 / motor 52 / entry 54 / result 54 / dataset 2。
- checkpointとの矛盾なし。旧DB `pckyotei` はread-only接続のみ、旧保全資産へwriteなし。

## C. 移行対象期間

「最新」は実測した保存済みsourceの最新。外部配信サービス全体の最新取得可能日までは保証しない。

| Source | 主要対象の最古 | 最新 | 日数 | Venue | Scoped Raw rows |
|---|---|---|---:|---:|---:|
| L1 | 2017-01-01 | 2026-09-19 | 3,549 | 24 | 45,180 |
| L2 | 2017-01-01 | 2026-09-19 | 3,549 | 24 | 542,160 |
| L3 | 2017-01-01 | 2026-09-19 | 3,549 | 24 | 3,252,960 |
| R3 | 2017-01-01 | 2026-09-18 | 3,548 | 24 | 3,252,024 |
| KI | source year 2017 | source year 2026 | 年・期単位 | 対象外 | 32,183 |

KIは公開日・レース日を表さないため正確な日付範囲を推測しない。
2017+の選手identityに直接必要な2016年KIを1,548件だけ追加保持（選手ごと最大1件）。
各sourceの観測範囲内で全国日付の空白・不正日付groupは0。
非開催日と取得漏れの区別に必要な公式開催予定・過去取得ログはなく、未観測開催の完全性はUNKNOWN。
場別日付・件数・月別範囲は `.local/phase25/raw_2017.json` を参照。

場別coverage（L1/L2/L3は同じ観測日集合）:

| Venue | L系日数 | L系最新日 | R3日数 | R3最新日 |
|---|---:|---|---:|---|
| 01 桐生 | 1,883 | 2026-09-10 | 1,883 | 2026-09-10 |
| 02 戸田 | 1,882 | 2026-09-19 | 1,881 | 2026-09-18 |
| 03 江戸川 | 1,838 | 2026-09-19 | 1,837 | 2026-09-18 |
| 04 平和島 | 1,780 | 2026-09-19 | 1,779 | 2026-09-18 |
| 05 多摩川 | 1,843 | 2026-09-19 | 1,842 | 2026-09-18 |
| 06 浜名湖 | 1,975 | 2026-09-19 | 1,974 | 2026-09-15 |
| 07 蒲郡 | 1,905 | 2026-09-18 | 1,905 | 2026-09-18 |
| 08 常滑 | 1,968 | 2026-09-17 | 1,968 | 2026-09-17 |
| 09 津 | 1,880 | 2026-09-17 | 1,880 | 2026-09-17 |
| 10 三国 | 1,875 | 2026-09-15 | 1,875 | 2026-09-15 |
| 11 びわこ | 1,811 | 2026-09-18 | 1,811 | 2026-09-18 |
| 12 住之江 | 1,857 | 2026-09-19 | 1,856 | 2026-09-18 |
| 13 尼崎 | 1,833 | 2026-09-19 | 1,832 | 2026-09-18 |
| 14 鳴門 | 1,806 | 2026-09-19 | 1,805 | 2026-09-18 |
| 15 丸亀 | 1,926 | 2026-09-19 | 1,925 | 2026-09-18 |
| 16 児島 | 1,906 | 2026-09-19 | 1,905 | 2026-09-18 |
| 17 宮島 | 1,935 | 2026-09-19 | 1,934 | 2026-09-18 |
| 18 徳山 | 1,924 | 2026-09-17 | 1,924 | 2026-09-17 |
| 19 下関 | 1,821 | 2026-09-17 | 1,821 | 2026-09-17 |
| 20 若松 | 1,933 | 2026-09-15 | 1,933 | 2026-09-15 |
| 21 芦屋 | 1,907 | 2026-09-14 | 1,907 | 2026-09-14 |
| 22 福岡 | 1,864 | 2026-09-18 | 1,864 | 2026-09-18 |
| 23 唐津 | 1,882 | 2026-09-19 | 1,881 | 2026-09-18 |
| 24 大村 | 1,946 | 2026-09-19 | 1,945 | 2026-09-18 |

## D. Raw

同一の `raw.source_batch` / `raw.source_record` にsource別値を保存。
対象479 batches / **7,126,055 records**（選択KI supportを含む）。
原値、空白、NULL、全source列、自然キー、source位置、取得時刻、行hash、batch hashを保持。
同一内容の再実行はbatchを再利用。変更版は保存して自動Canonical採用を停止する。
正常な0件抽出はSOURCE_EMPTY、SELECT失敗はSOURCE_FETCH_FAILEDとして区別し成功batchを作らない。
ただし旧sourceに過去の取得履歴がないため、旧source内部の欠測原因までは確定できない。

物理格納総数は **656 batches / 8,567,684 records**。
内訳は今回対象479 / 7,126,055、既存Phase 2 sample 5 / 174、
期間修正前に保存済みの対象外pre-2017 Raw 172 / 1,441,455。
後者はimmutable原則で保持し、Canonical・品質保証・全件replayの対象外。
2016年以前の完全化や不整合調査は行わず、Phase 2.5のBLOCKINGに含めない。

## E. Canonical

| Table | Rows |
|---|---:|
| core.venue | 24 |
| core.race | 542,160 |
| core.player | 2,090 |
| core.motor | 16,297 |
| core.race_entry | 3,252,960 |
| core.race_result | 3,210,456 |
| core.dataset_version | 119 |

race_entryは全L3を採用。race_resultは登録番号を確認できるR3のみ採用。
playerは最初の2017+出走以前に使えるKIだけで性別を決定し、未来情報による補完なし。


## F. Coverage

| 指標 | 有効数 / 分母 | 比率 |
|---|---:|---:|
| 24場 | 24 / 24 | 100.0000% |
| 6艇entryが揃うrace | 542,160 / 542,160 | 100.0000% |
| 6艇resultが揃うrace | 535,076 / 542,160 | 98.6934% |
| resultがあるentry | 3,210,456 / 3,252,960 | 98.6934% |
| sex判明player | 1,560 / 2,090 | 74.6411% |
| sex判明entry | 2,790,905 / 3,252,960 | 85.7959% |
| motorありentry | 3,252,960 / 3,252,960 | 100.0000% |
| actual_courseありresult | 3,204,365 / 3,210,456 | 99.8103% |
| 数値finishありresult | 3,163,315 / 3,210,456 | 98.5316% |
| 数値STありresult | 3,191,507 / 3,210,456 | 99.4098% |

全45,180 venue-daysで12 race、全542,160 raceで6 entries。
結果0件の7,084 raceはSOURCE_INCOMPLETE。6件の535,076 raceはRESULT_RECORDS_PRESENT。
このstatusは正常完走や公式成立の判定ではない。
選手2,090人全員にentryがある。性別は男性1,358、女性202、不明530。
motor 16,297 identities、generation rule/interval/venue整合性違反0。
actual_course NULL 6,091件はboat_no補完なし。race内actual_course重複0。
ST数値範囲0.00–0.99、原値が明示する0は2,094件。欠測の0補完なし。
数値finishが6艇揃うraceは497,033。数値着順の重複を解消した件数ではない。

Raw R3を分母にすると3,252,024件中、actual_course 1–6は3,204,365件、
finish 1–6は3,163,315件、ST 3桁原表記は3,204,144件。
Raw空欄はregistration/finish各41,568、course 47,659、ST 47,880。
RawのST 3桁にはF原表記も含むため、Canonical数値ST coverageと区別する。
年別・場別coverageは `audit.json` の `annual_field_coverage` / `canonical` を参照。


## G. Anomalies

| 分類 | 発見事項 | 件数 | 処理 |
|---|---|---:|---|
| BLOCKING | 監査の整合性・D-1・lineage・世代違反 | 0 | 全項目0をSQL確認 |
| KNOWN_SOURCE_LIMITATION | 最新日L3に対応するR3なし | 936艇 / 156 race | Raw source期間差。resultを生成しない |
| UNRESOLVED_BUT_PRESERVED | R3登録番号・finish・course・STがすべて空欄 | 41,568艇 / 6,928 race | Raw-only。L3番号を流用せず中止等の意味も推測しない |
| UNRESOLVED_BUT_PRESERVED | 未解釈特殊着順 | 34,134 | 原値を保持、result_status=UNRESOLVED |
| UNRESOLVED_BUT_PRESERVED | 同一raceの数値着順重複 | 515組 | 元の値を維持。同着とは未確定 |
| KNOWN_SOURCE_LIMITATION | 安全に採用できる性別がないplayer | 530 | NULL、未来KIで補完しない |
| KNOWN_SOURCE_LIMITATION | 採用結果のactual_course欠測 | 6,091 | NULL、boat_noで補完しない |
| KNOWN_SOURCE_LIMITATION | ST MISSING | 5,942 | 原空白＋NULL |
| CLEAN | F / L原値保持 | F 12,637 / L 370 | 数値STには変換しない（違反0） |
| CLEAN | source自然キー重複 / 内容矛盾 | 0 / 0 | scoped Raw内で全件比較 |
| CLEAN | 空欄以外のL3/R3登録番号矛盾 | 0 | 値が存在する番号同士の不一致なし |
| CLEAN | Canonical重複 / 必須キー欠測 / lineage不一致 | 0 / 0 / 0 | 全件検証 |

未解釈finish内訳: 転16,083、欠5,942、落4,423、エ2,911、妨2,805、不1,253、沈414、失250、＿53。
いずれもPhase 2で確認していない意味を追加実装しない。
代表例:

- 空欄R3: 2017-01-14 / venue14 / race1 / boat1、Raw ID 5,321,193。
- `＿`: 2017-04-29 / venue23 / race11 / boat5、Raw ID 5,414,353。
- F: 2017-01-01 / venue08 / race7 / boat4、ST原値 `002`、数値STはNULL。
- Lかつcourse欠測: 2017-04-16 / venue02 / race1 / boat2。course原値空白を維持。
- 数値着順重複: 2017-01-13 / venue15 / race1、boat3とboat5がともに原値 `05`。
  Raw IDs 5,320,187 / 5,320,189。勝手に順序を付けない。

Canonical移行ログのREGISTRATION_CONFLICT 41,568件は、最終全件比較では全件が空欄登録番号。
既知番号同士の矛盾41,568件という意味ではない。

Raw→Canonical自然キー未採用はR3 41,568とKI 32,171。
KI全期間統計をCanonicalや特徴量に取り込む仕様ではないため、必要identity以外はRawで保持。
L1/L2/L3の自然キーは全件表現される。
今回batchのL2 9件、L3/R3各54件は、既存Phase 2の同一内容Rawを参照するため
直接参照数に差があるが、自然キー・payload一致を確認済み。
全Canonical参照のsource table/原値/型付き値/manifest照合に不一致なし。

source record_idはL1/L2/L3/R3/KIのみ、各sourceの列集合は1種類。
2017–2026各年のgrade code集合は1/2/3/4/5/9、L2対象flagは0/1。
年度別finish/symbol分布も保存した。列・codeの観測上の差から新しい意味を推測せず、
sourceの歴史的な仕様変更がなかったとまでは断定しない。


## H. Reproducibility

- Scoped Raw +既存sampleの484 batches / 7,126,229 rowsについて行hash、batch hash、位置、件数が一致。
- 117個の月別history shardsと既存2個、合計119 datasetsの保存内容hash・manifest hash・D-1境界を検証済み。
- 空DBへmigration → 対象Raw全件を保存・同内容再保存 → 全117か月のCanonicalを各二回計算。
  件数・除外理由・完全snapshot hashがすべて一致。
- 全117か月のdatasetを各二回生成し、全月のportable hashが既存DBと一致。
- 長時間処理の途中、Raw/Canonical完了後のcheckpointからdataset検証を再開した。
  保存済みRawの479 batchの件数・hashとCanonical全table件数を照合して引き継ぎ、
  全月datasetを改めて二回検証した。checkpointログhashは
  `9a161fa604bb2824b2d08641f4c2e73e2f94fafdb5629e652be260f9976c4ec2`。
  `.local/phase25/replay_checkpoint.log` と `replay_completion.log` に証跡を保持。
- 再構築先の全件監査 **PASS**。coverage、sex、motor、結果分布、重複、必須値、lineage、年別coverageは既存DBと一致。
- 再構築先は117 history datasets、既存DBはこれに元の2つを加えた119 datasets。
- 検証DB削除完了を `pg_database` で確認（該当DB 0）。`replay.json` のstatusはPASS。
- 監査SQLのsort/hash workspaceは64MB（transaction-local）。server/database設定やschema変更なし。
- 既存Phase 2 frozen snapshotsは変更しない。月別shardはretrospective result foundation。
  当時の公開・取得時刻を証明する予測datasetではない。
- 月別Dは当該月の最終観測日の翌日。将来consumerも営業日Dに対して必ずD-1を適用する。
- 自然現象・Rating・直前タイムの開発/検証期間と2026年の7日更新方針は
  [analysis_periods.md](analysis_periods.md) に記録。今回の実装対象外。

## I. Tests

**62 tests / 0 failures / 0 skips**。既存29件を維持し33件追加。
元のDBテストは限定sampleを前提とするため、変更せず専用の使い捨てsample DBで実施。
別の空DBで実データを使う小範囲pipeline、Raw/COPY、Canonical・datasetの再実行を確認。
境界日、motor generation、actual_course欠測、特殊着順、conflict、empty/failure、lineage、portable hashを含む。
テストDBは削除済み。

## J. Blocking / unresolved

全件監査で検出したBLOCKINGは0。全件空DB再現・再現先監査もPASS。
以下は後続で意味を使う前にsource仕様・人間の判断が必要:

1. 転/欠/落/エ/妨/不/沈/失/＿の正式な解釈・学習対象への採否。
2. 登録番号と結果項目が空欄の41,568件の公式状態。中止等を推測しない。
3. 数値着順重複515組の同着/訂正等の扱い。順序を推測しない。
4. 当時の公開時刻・取得時刻の証拠、未観測開催の完全性。
5. motor固定更新日ルールと実際の交換日差の扱い。今回は既存確認済みルールだけを再現。
6. 後日source内容が変わったpartitionの採用方針。変更版をRaw保存した後、自動置換は停止する。

これらの原値保存を維持する基盤は利用可能だが、意味が確定していない行を
将来のモデルへ無条件投入してよいという判定ではない。
2016年以前の欠測・不整合をBLOCKINGにしていない。

## K. Changed files / Git

Branch `main`、HEAD / local `origin/main` は
`894914a06f7a57113d2ca3ee304710d3c1dd748f`。commit / pushなし。
working treeは以下の今回変更のみ（開始時clean）:

- Modified: `.gitignore`, `README.md`, `docs/source_mapping.md`
- Added: `docs/analysis_periods.md`, `docs/phase25_report.md`
- Added: `scripts/history_source.py`, `scripts/import_history.py`, `scripts/freeze_history.py`,
  `scripts/audit_history.py`, `scripts/verify_history.py`
- Added: `tests/test_history.py`, `tests/test_history_dataset.py`

既存migrations、Phase 2 normalization、requirementsは変更なし。
機械可読の実測証跡はgit対象外の `.local/phase25/`:
`raw_2017.json`, `canonical_2017.json`, `audit.json`, `anomaly_followup.json`,
`datasets.json`, `hashes.json`, `dataset_hashes.json`, `tests.json`。
全件再現の確定証跡は `replay.json`。再開前の完了ログは `replay_checkpoint.log`、
その後のログは `replay_completion.log`。再開に使った限定スクリプトは `finish_replay.py`。
将来の空DBからの再現には、現在の `scripts.verify_history --mode replay` を使用する。
実行手順は [README.md](../README.md#reproducible-verification) を参照。
Rating、Prediction、3連単確率、Betting、F休み派生、艇番別進入指数、C2/C3/C4特徴量は実装していない。
