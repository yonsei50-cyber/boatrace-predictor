# Motor A Method v1 freeze（2026-09-23）

## 判定と範囲

**MOTOR_A_METHOD_V1_FROZEN**。2017–2024 の development で選んだ Motor A の二層方式を、[freeze JSON](../artifacts/motor_a_method_freeze_v1.json)、[純粋な参照実装](../scripts/motor_a_v1.py)、[契約テスト](../tests/test_motor_a_v1.py)に固定した。この文書は方式選択の根拠を残す。Prediction への接続、DB/schema 変更、Motor B、Rating v2、2025 independent holdout の実行結果は含まない。

## 入力と eligibility

1利用の residual は `finish_point - core.race_entry.national_win_rate`。着順点は1～6着に `10, 8, 6, 4, 2, 1`。全国勝率は `brd_l3.zenkoku_ritsu_1` に由来する既存 Canonical 値と `VALID` status を使用する。全国勝率帯補正、Rating 補正は加えない。

Canonical の `(venue_code, generation_start_year, motor_no)` を motor identity とし、既存の venue 別 generation 日付規則 `user-fixed-month-day-v1` は変えない。別 venue や旧 generation の利用を混ぜない。

eligible は Canonical race/entry、motor identity、player identity、個別 canonical result、`NUMERIC_VALID` の1～6着、`VALID` で非 NULL の全国勝率を持つ entry。特殊着、結果欠測、重複着順関連の未解決状態、全国勝率 `UNRESOLVED` は除外する。Rating STRICT の race 単位 eligibility は流用しない。除外 entry も motor がどの開催を通過したかの連続性判定には使う。

2017–2024 の開発抽出では全 entry **2,671,344**、eligible **2,591,688**、除外 **79,656**。最初に該当した除外理由は特殊着39,229、結果欠測32,784、重複着順関連2,609、全国勝率 `UNRESOLVED` 5,034。後二者を恣意的に数値へ変換していない。

## 開催 identity と未確認境界

`brd_l1` の venue×日付を基礎とし、L1 開始日目 `1`、L1 最終日 `9`、L1 日目空欄時の同日 `brd_b1` / `brd_k1` 日目一致、開催名継続、日目整合で開催を構築する。L1 空欄かつ B1/K1 とも `1` は開始信号。直前も同名・L1 空欄・B1 `1` の場合は重複開始とせず同一開催を継続する。日付 gap から開催を作らない。識別子は `(venue_code, source-confirmed meeting_start_date)`。

L1 **37,102** venue-day は Canonical **37,102** venue-day / **445,224** race と一致し、各日に12 race。B1 は37,196、K1 は37,102 venue-day。**6,654開催 / 36,889 venue-day** の開始・終了を確認。**55開催 / 213 venue-day** は片側境界が未確認で、開発時の扱いは次の通り。

| 開催状態 | 開催数 | venue-day | 開発抽出と同じ扱い |
|---|---:|---:|---|
| L1 最終日9なし、開始日あり | 41 | 156 | 開始 identity を使い、D-1 までの Current を計算。完了済み Base 履歴には追加しない。次開催へ移ると古い Base 履歴をクリアする。 |
| L1 開始日1なし | 14 | 57 | 開催 identity 不明。Base/Current とも未観測。通過した motor の古い Base 履歴をクリアする。 |

他の矛盾理由が付く開催は、最終日 `9` があっても certified Base へ追加しない。開始日があっても、理由が `NO_FINAL_9` だけでなければ Current を計算しない。開発期間では未確認理由は上表の2種類のみ。2023 の全4,666 venue-day は certified。2024 の4,672 venue-day 中4,618は certified、残る54日は最終日未確認だが開始日既知だった。

## 二層 score と D-1

`motor_a_base3` は、現在開催より前に最終日 `9` が確認され、eligible 利用を1件以上持つ**同一 motor generation の直近最大3つの完了開催**について、各開催の residual 平均を一度作り、その開催平均を**等重みで平均**する。race をまとめて平均しない。`base_n_meetings` は採用開催数、`base_n_uses` は採用開催内の eligible 利用数の合計。直近3開催平均が `+0.8, +0.2, -0.1` なら Base3 は `0.3`。完了開催0なら score `NULL` / `NOT_EVALUABLE`、両 count 0。1～2開催ならその数だけ使う。

`motor_a_current` は、source から識別した**現在開催内**の、営業日 D より前の日付の同 motor generation eligible residual 平均。`current_n_uses` を併記する。現開催の履歴0なら score `NULL` / `NOT_EVALUABLE`、count 0。同じ選手自身の過去利用は除外しないため、Current は選手と motor の組み合わせや今節の仕上がりを含み得る。純粋な motor 固有効果とは定義しない。

営業日 D の全 race は共通の D-1 state で score し、D の eligible result は全 D entry の score 後に一括反映する。D の1R結果を同日の後続 race に入れない。最終日 D の開催はその日の score 中は Current のまま、D 終了後に completed Base 履歴へ確定し、次開催の D+1 以降に初めて Base へ入る。Base と Current は**別々の連続 score**であり、確率でも固定 weight 付き合算値でもない。欠測時に旧世代・同 motor 番号・venue 平均で補完しない。

履歴量を失わないため、Current は `mean × current_n_uses` から同じ対象の residual 合計を再構成できる。Base は開催等重み score なので、`base3 × base_n_uses` は採用 race の合計 residual には**ならない**。そこで参照実装は採用開催の `base_residual_sum` も付随量として返す。これは第3の正式 score ではない。`base_n_uses` と `base_n_meetings` も履歴量・採用量として保持する。

## Development の検証結果

2017–2022 で当てはめた単純な次回 residual 線形診断を2023と2024へ別々に固定適用した。以下の MSE は **次回 residual** の誤差で、1着・2着確率の品質や calibration を示さない。異なる母集団の MSE を直接順位付けしない。

| 同一条件内の指標 | 2023 | 2024 |
|---|---:|---:|
| 新利用者初走 Group 2、Base3 Pearson | 0.06090 | 0.05030 |
| 新利用者初走 Group 2、Base3 MSE | 8.85276 | 8.89676 |
| 同開催の同一選手後続走 Group 1、Current Pearson | 0.08950 | 0.08764 |
| 新利用者後続走 Group 3、Current Pearson | 0.09023 | 0.08803 |
| Base3・Current 両観測 cohort の件数 | 255,181 | 254,720 |
| 同 cohort、Current 単独 MSE | 8.94665 | 8.95186 |
| 同 cohort、Base3 + Current 診断 MSE | 8.93343 | 8.93788 |

両観測 cohort で Base3 を加えた診断 MSE は両年で低下した。これは二層を別 feature として残す根拠であり、最終的な組み合わせ係数や cold start 行の性能を決めるものではない。同一 motor generation×開催の eligible 利用308,144組は、各組で distinct player が1人だった。

Group 4 の Base 未観測は2023 **12,097 / 326,374**、2024 **12,844 / 326,431**。Current 未観測はそれぞれ **61,550**、**61,649**。両観測は **255,181**、**254,720**。NULL/0を値0へ補完せず、Base と Current の観測状態を独立に残す。

race直近5利用平均は v1 の正式 feature に入れず、比較対象として維持する。Base3 と Current 両観測の同一 cohort で、race5 MSE は2023 **8.93848**、2024 **8.93767**、二層診断は **8.93343**、**8.93788**。2024 は race5 が僅かに低く、二層方式の全面優位を主張しない。今後の Prediction feature 比較で再評価できる。

## 再現性と限界

参照実装は DB を開かず、source venue-day 辞書と Canonical entry 列から meeting map と D-1 score を作る。テストは着順点・residual・generation分離・開催 identity・未確認55開催の境界処理・開催等重み・最大3開催・同日遮断・same-player・cold start・eligibility・freeze JSON 整合を確認する。開発用 `.local` スクリプト・結果 JSON の SHA-256 は freeze JSON に記録したが、これらは Git 管理対象外。今回、2025 を読まず、実 DB の再抽出も行っていない。

L3 の過去の個別公開 timestamp は記録されていない。ここでは採用済みの日単位 D-1 運用規則に従うが、個別 timestamp の実測証明とは呼ばない。2025 independent holdout、Prediction への採用、確率品質・校正の検証は後工程。Motor A v1 の方式選択はここで一段落とし、次は **F休み判定**へ戻る。
