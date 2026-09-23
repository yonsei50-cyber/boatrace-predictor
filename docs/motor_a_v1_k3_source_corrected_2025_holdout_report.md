# Motor A Method v1: K3-only development 再評価と初回2025 independent holdout

## 判定と実行順

**MOTOR_A_V1_K3_REEVALUATED_AND_2025_HOLDOUT_COMPLETE**。開始 HEAD は
`272d5bf00c9a84a287b83c950228bcb817975425`。Motor A freeze commit は
`953c6c8a4e9b35141ec8a409c85742096d427cd2`、source-policy checkpoint は
`fd49bffe83b2f23443ec5f525786c0dd309abe95`。

凍結済み method artifact の SHA-256 は開始時・評価後とも
`cc5b1b690919871897a625b910bbd7fef9f2247ac65e8e779073c9fb39d43779`。
2017–2024 の K3-only 再生で 2023・2024 を再評価した後、2025 結果の読み取り前に
[`holdout protocol`](../artifacts/motor_a_v1_2025_holdout_protocol.json) を保存した。
protocol SHA-256 は
`84a2256e0cccf5ddba49b2729bcf97a20abf7d16dc79c160c056cc9260714996`。
protocol の最終更新は 2026-09-23 18:31:16 UTC、初回 holdout artifact は
18:36:51 UTC。protocol はその後変更していない。

正式 result は K3-only Canonical version `K3_ONLY_RESULT_V1_b68a27cf8f653602`。
source manifest SHA-256 は
`b68a27cf8f6536024f8d68149bd026f1ab271f62b1190b3bc1d860bf3bb1db4a`。
2017–2025 の Canonical result 2,969,286 boat 中、K3 以外の lineage は 0。
2017-01-01 から state を組み直し、旧 result lineage の Motor state/cache は利用していない。

## 固定した評価契約

residual は `{1:10, 2:8, 3:6, 4:4, 5:2, 6:1}[着順] - L3全国勝率`。
eligibility、motor generation、source-confirmed meeting、最大3つの完了開催を等重みで
平均する Base3、同開催 D-1 までの Current は freeze artifact と
[`reference implementation`](../scripts/motor_a_v1.py) のまま。
Base3 と Current は別々の連続 feature。全国勝率帯 bias、Rating、補完は加えていない。

Group 1 は同一選手の同開催後続 entry、Group 2 は前の certified 開催から新利用者に
変わった初走、Group 3 はその新利用者の後続 entry、Group 4 は全 eligible residual。
各 score の評価では観測可能な行だけを使用した。両観測 cohort は Group 4 で Base3 と
Current の両方が観測された行。保存済み 2017–2022 線形診断係数を固定し、
K3 再評価や2025で係数・組み合わせ weight を学習し直していない。
race recent5 は同一両観測 cohort の historical comparator に限る。

## 2023–2024 source-corrected development

凍結済み開発用 `.local` JSON の SHA-256 を freeze artifact の記録と照合し、
旧値として使用した。K3 再生値は以下の通り。表の旧→新は保存された全精度で一致した。

| Cohort と指標 | 2023 旧→K3 | 2024 旧→K3 |
|---|---:|---:|
| Group 2 Base3、評価件数 | 36,465→36,465 | 36,296→36,296 |
| Group 2 Base3、Pearson | 0.060896780→0.060896780 | 0.050298795→0.050298795 |
| Group 2 Base3、MSE | 8.852761203→8.852761203 | 8.896758560→8.896758560 |
| Group 1 Current、評価件数 | 264,824→264,824 | 264,782→264,782 |
| Group 1 Current、Pearson | 0.089502360→0.089502360 | 0.087643111→0.087643111 |
| Group 1 Current、MSE | 8.937487514→8.937487514 | 8.954732019→8.954732019 |
| Group 3 Current、評価件数 | 254,848→254,848 | 254,330→254,330 |
| Group 3 Current、Pearson | 0.090230221→0.090230221 | 0.088033242→0.088033242 |
| Group 3 Current、MSE | 8.943255208→8.943255208 | 8.952532477→8.952532477 |
| 両観測 cohort、評価件数 | 255,181→255,181 | 254,720→254,720 |
| 両観測、Current 単独 MSE | 8.946654670→8.946654670 | 8.951864380→8.951864380 |
| 両観測、Base3 + Current MSE | 8.933428325→8.933428325 | 8.937880786→8.937880786 |
| 両観測、race recent5 MSE | 8.938484895→8.938484895 | 8.937672383→8.937672383 |

| Count（旧→K3、差分） | 2023 | 2024 |
|---|---:|---:|
| Candidate uses | 335,952→335,952（0） | 336,384→336,384（0） |
| Eligible residuals | 326,374→326,374（0） | 326,431→326,431（0） |
| Source meeting count | 857→857（0） | 857→857（0） |
| Base3 evaluable | 314,277→314,277（0） | 313,587→313,587（0） |
| Current evaluable | 264,824→264,824（0） | 264,782→264,782（0） |
| Both observed | 255,181→255,181（0） | 254,720→254,720（0） |
| Eligible motor generations | 旧値未保存→2,997 | 旧値未保存→3,001 |

旧 artifact に年別 motor-generation count は保存されていないので差分は不明。
集計一致は、全行の値が不変だったという証明ではない。今回の source correction は、
これら凍結済み Motor A aggregate に変化を生じなかった。

## 2025 初回 independent holdout

| 固定 cohort | n | Pearson | MSE |
|---|---:|---:|---:|
| Group 2 Base3 | 35,970 | 0.064249718 | 8.789739211 |
| Group 1 Current | 264,011 | 0.085910452 | 8.890506519 |
| Group 3 Current | 251,592 | 0.087229105 | 8.896519846 |

| Group 4 両観測（同じ251,574行） | MSE |
|---|---:|
| Current 単独 | 8.897265602 |
| Base3 + Current | 8.882576761 |
| race recent5 comparator | 8.886173889 |

Base3 を加えた診断 MSE は Current 単独より `0.014688841` 低い。
2023 の `0.013226345`、2024 の `0.013983594` と方向が一致する。
2025 Group 2 Base3 の Pearson は両開発年より高く、Group 1 / 3 Current の Pearson は
両開発年よりやや低い。2025 の各 MSE の絶対値を別年の別 cohort と直接比較して
method の優劣を決めない。race5 との差はこの cohort で `0.003597128` の MSE だが、
2025 で comparator を使った方式選択はしていない。

事前 PASS 閾値は設定されていない。したがって後付けの統計的 PASS/FAIL は付けない。
これらは次回 residual の診断であり、最終 Prediction の1着・2着確率の増分価値、
calibration、賭け判断の有効性は別工程である。

## 2025 coverage と K3 欠測

| 区分 | 件数 | 対 eligible residual |
|---|---:|---:|
| Candidate uses | 335,448 | — |
| Eligible residuals | 325,087 | 100% |
| Excluded | 10,361 | — |
| Base3 evaluable / NOT_EVALUABLE | 309,164 / 15,923 | 95.10% / 4.90% |
| Current evaluable / NOT_EVALUABLE | 264,011 / 61,076 | 81.21% / 18.79% |
| Both observed | 251,574 | 77.39% |
| Neither observed | 3,486 | 1.07% |

2025-08-12 の既知の K3 result 不在は 60 race / 360 entries / 0 result。
360 entries は candidate uses の 0.1073% で、eligible residual や Motor update には入らない。
その後の state/coverage に対する反事実的な影響量は K3-only data からは特定できない。
旧 result で補完していない。

## 時系列・再現性 gate

[`tests/test_motor_a_v1.py`](../tests/test_motor_a_v1.py) の7件と
[`tests/test_motor_a_v1_k3_reevaluation.py`](../tests/test_motor_a_v1_k3_reevaluation.py)
の2件が PASS。着順点、residual、eligibility、generation、source meeting、
完了した直近3開催、開催等重み、D-1、同日遮断、current meeting の Base からの除外、
未評価、未知開催 continuity を確認した。実データ再生は全 D の score 後に D の result を
commit し、Base には final-day 9 が完了した certified meeting だけを追加する。
motor key は venue + generation_start_year + motor_no。source lineage gate は
K3以外を 0 件と確認した。2017–2022 の保存済み係数以外を使用せず、protocol は
2025 結果に先立って固定した。

2回目の独立した read-only DB replay は初回 artifact と完全一致した。

| Identity | SHA-256 |
|---|---|
| Ordered input | `9207c4bcf56b0217b4a9ed45e57aa8d5a96d4de9204a1fa84cd96d75d9dd653f` |
| Eligible residual dataset | `809a8265249f9e07ec013a61c34a1160c005e35d8cec962726e4f3f5e49f8993` |
| State/features | `03496bae6478509de71c4e4f0f5c11c6d8614f5575511b12715712d9f8db4e85` |
| 2025 metrics | `63405fa8fe0ce39c7512e86d748d7d6d50011edb99cb9946a2b9113ae933f581` |

再評価用の保存済み `.local` 開発 artifact は Git 管理対象外であり、この環境では
freeze JSON に記録されたハッシュで同一性を確認した。別 checkout で旧→新比較を
再実行するには、同一ハッシュの開発 artifact が必要である。
2017–2024 の保存済み feature 行列 `.local/motor_a_meeting_features.npz` の
SHA-256 は `5f3386c60c6540e3c8ca2e87571b9e4d9bac9e2ec9ae42ac8bc47888814744da`。
旧 race5 係数はこの行列から復元し、凍結済み両観測 cohort の2023・2024 MSE と
両年とも一致することを確認してから protocol に固定した。
L3 の過去の個別公開 timestamp は freeze 時点から未検証で、日単位 D-1 の契約を
超える公開時刻の証明はしていない。

Motor A Method v1 の freeze artifact、method、Base3/Current 契約、診断係数は不変。
2025 の結果による retuning はない。改善候補は将来の別 method として扱う。

## 保存物

- [`development 再評価`](../artifacts/motor_a_v1_k3_2023_2024.json)
- [`旧→K3 比較`](../artifacts/motor_a_v1_k3_development_comparison.json)
- [`2025 holdout protocol`](../artifacts/motor_a_v1_2025_holdout_protocol.json)
- [`2025 初回 holdout`](../artifacts/motor_a_v1_k3_2025_holdout.json)
- [`deterministic replay verification`](../artifacts/motor_a_v1_k3_replay_verification.json)
- [`read-only 再生コード`](../scripts/reevaluate_motor_a_v1_k3.py)
