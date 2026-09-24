# Natural Environment Feature v1 — preholdout freeze

## A. Verdict

`NATURAL_ENVIRONMENT_V1_PREHOLDOUT_FROZEN`。開発・選択・calibration・最終fitに使用した年は2017～2024であり、2025 Independent Holdoutは別タスクに留保する。2024は開発・calibration年であり、独立holdoutではない。

## B. Source

- C2: `pckyotei.public.brd_c2` の `hogaku_code`, `fuko_code`, `fusoku`, `tenki_code`, `kion`。`tenki_code`は原本code `1～6`をcategoricalに使い、`kion`は原値÷10の℃に変換する。raw値とC2 record IDをrace単位のinterfaceに保持する。波・`hako`・水温は使わない。
- 締切予定時刻: `pckyotei.public.brd_l2` の `kaisai_nen`, `kaisai_tsukihi`, `kyoteijo_code`, `shimekiri_yotei_jikoku`。L2 record IDも保持する。
- 潮汐極値: `pckyotei.public.apd_choihyo` の `data_kubun`, `chiten_code`, `kaisai_nen`, `kaisai_tsukihi`, `jikoku`, `choi`。`data_kubun=1` は干潮、`2` は満潮。補間に用いた両極値の原本値をlineageに保持する。
- `core.natural_environment_feature_v1` はrace grainで、2017～2024の対象raceを一意に参照できる。学習対象raceは凍結済みbaselineと同じ集合を用いる。原本行ハッシュとcacheハッシュはfreeze JSONに記録した。

原本のhistorical exact publication timestampは未検証である。C2はpre-race情報種別、L2は予定時刻であることを根拠にした開発評価であり、厳密な時点再現が立証されたという主張はしない。

## C. Wind method

`d = (fuko_code - hogaku_code) mod 16`。`fusoku=0`を最優先して`CALM`とする。風速が正なら、`d=15,0,1`は`LEFT_CROSSWIND`、`2～6`は`HEADWIND`、`7～9`は`RIGHT_CROSSWIND`、`10～14`は`TAILWIND`。`fusoku`の単位はユーザー指定の`m`として扱う。無効値と欠損値はrawのまま保存し、解釈できない値を数値へ強制変換しない。

## D. Tide method

対象場と地点の対応は`03/04→TK`, `06→MI`, `14→KM`, `15→AX`, `16→UN`, `17→Q8`, `18→QA`, `19→WH`, `20→N1`, `22→QF`, `24→NS`。17および20の修正は原本masterと極値表の実データに基づく。

race締切予定timestampを挟む隣接する干潮・満潮の高さを直線補間する。前日・翌日の極値も使用できる。干潮→満潮は`RISING`、満潮→干潮は`FALLING`。完全一致時は原本`choi`を高さとして使用し、`HIGH_TIDE`または`LOW_TIDE`、変動速度0とする。通常の変動速度は`abs(h1-h0)/elapsed_hours`で、単位は`choi`原本単位/時。水そのものの流速ではない。対象外の場は`NOT_APPLICABLE`、安全に解決できない対象場は`UNRESOLVED`とし、潮位数値はNULLとする。

## E. Coverage

2017～2024のfeature interfaceは445,224 raceで、C2あり445,223、風分類が得られたraceは439,792、外気温あり439,793。天気欠損428。潮位`AVAILABLE`は223,716、対象外`NOT_APPLICABLE`は221,508、`UNRESOLVED`は0。DBの独立集計でrace ID重複、17/20の地点mapping不一致、潮位statusとNULLの不整合はいずれも0。学習集合は凍結済みbaselineの407,707 raceである。

## F. Development comparison

2022は2017～2021でfit、2023は2017～2022でfit。各候補のL2は`0.01, 0.1, 1, 10, 100`。表は各bundleで2022/2023の平均Log Lossが最良のL2を示す。E0は凍結済みbaselineのP1 `CORE + MOTOR`、P2 `FULL`を比較対象にした。選択は年別Log Lossの等重み平均を優先し、`1e-5`以内ならBrier、その次に単純なbundleを優先した。

| 対象 | bundle | L2 | 2022 Log Loss | 2023 Log Loss | 平均 Log Loss | 平均 Brier |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| P1 | E0 | 0.01 | 1.180534319 | 1.189455131 | 1.184994725 | 0.580693087 |
| P1 | E1 | 0.01 | 1.179172238 | 1.188381158 | 1.183776698 | 0.580032095 |
| P1 | E2 | 0.01 | 1.179014448 | 1.188060068 | 1.183537258 | 0.579914061 |
| P2 | E0 | 0.01 | 1.668192249 | 1.675793339 | 1.671992794 | 0.798514052 |
| P2 | E1 | 0.01 | 1.667587995 | 1.675198335 | 1.671393165 | 0.798281550 |
| P2 | E2 | 0.01 | 1.667542836 | 1.675221649 | 1.671382242 | 0.798281068 |

E1は6コース進入確率×風分類・風速・天気・外気温。E2はさらに6コース進入確率×潮位・潮の向き・潮位変動速度。艇番・実actual course・venue・Rating・Motorとの環境interactionは追加しない。潮位の対象外・未解決statusは管理用だけに保持し、方向のinteractionは物理的な4方向だけを学習する。P2のE2とE1の平均Log Loss差は約0.0000109で、選択閾値に近い小さな差である。

## G. Selected method

| 対象 | bundle | L2 | 2024 temperature |
| --- | --- | ---: | ---: |
| P1 | E2 | 0.01 | 1.0149487987174035 |
| P2 | E2 | 0.01 | 1.0068924602159712 |

各対象を2017～2023でfitし、2024で正のscalar temperatureをfitした。選択済みmethodを2017～2024で最終fitした。温度は2024で確定した値を保持する。

## H. 2024 diagnostics

| 対象 | race | Log Loss | Brier | ECE 10 bin | Top1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| P1 | 51,392 | 1.198323539 | 0.586566834 | 0.002251436 | 0.569174191 |
| P2 | 51,392 | 1.676195244 | 0.799879053 | 0.009849216 | 0.273427771 |

`sequential_p1_p2_p2_v1`による2024の3連単Probability diagnosticは51,392 race。Log Loss `3.921103351`、120-class Brier `0.965046406`、実際の組合せへの確率の平均 `0.033141791`・中央値 `0.024442437`。Top1 `0.087834682`、Top3 `0.222622198`、Top5 `0.318940691`、Top10 `0.478012142`。3着の結果sourceは`brd_k3`。

## I. Tests / leakage

風向の全16差・無風優先、潮位の両方向・日付跨ぎ・極値完全一致・対象外・未解決、preprocessorのtrain年限定・status管理専用、120通りの確率整合性を関連unit tests 21件で検証した。開発集合は2017～2024に限定し、選択foldは2022/2023、calibrationは2024。追加したコードに`brd_r3`参照はない。全候補と最終fitを同一入力で再実行し、model、2024開発予測、3連単診断、freezeの4ファイルがSHA-256で完全一致した。別計算でselection rule、source/code lineage hash、feature順、確率の有限性・範囲・6艇合計1、race ID一意性も検証した。

## J. Freeze artifact

`artifacts/natural_environment_v1_freeze.json`（SHA-256 `78c24d7c97d07678684045ee3b4ef2a1b8f25871a8549cbfe959efd6a29eebf7`）にsource、mapping、feature順、前処理、選択、temperature、modelとdiagnosticのハッシュを記録した。model実体は`artifacts/natural_environment_v1_model.json`、2024開発予測は`artifacts/natural_environment_v1_development_predictions.npz`。

## K. Git

commitと通常pushの完了情報は作業終了時の最終報告に記録する。
