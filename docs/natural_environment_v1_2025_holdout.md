# Natural Environment v1 — 2025 Independent Holdout

## A. Verdict

`NATURAL_ENVIRONMENT_V1_2025_INDEPENDENT_HOLDOUT_COMPLETE`。正常な一回評価の完了を示し、性能のPASS/FAILではない。

## B. Holdout identity

2025-01-01～2025-12-31、`core.prediction_dataset_v1` の `label_eligible = TRUE`。51,311 race / 307,866 rows、各race 6艇。Baseline正式artifactとrace ID・日付・P1/P2 labelが完全一致。

## C. Natural Environment frozen method

freeze SHA-256 `78c24d7c97d07678684045ee3b4ef2a1b8f25871a8549cbfe959efd6a29eebf7`。P1/P2ともE2、L2=0.01。P1 temperature=1.0149487987174035、P2 temperature=1.0068924602159712。Baseline + Entry Course probability × C2 Environment + Tide。波は使用しない。

## D/E. 2025 P1/P2 metrics and Baseline difference

差はNatural Environment − Baseline。Log Loss、Brier、ECEは負が改善。

| Target | Metric | Natural | Baseline | 差 |
| --- | --- | ---: | ---: | ---: |
| P1 | Log Loss | 1.198443418 | 1.199922972 | -0.001479555 |
| P1 | Brier | 0.586500631 | 0.587272358 | -0.000771728 |
| P1 | ECE 10-bin | 0.002577289 | 0.002652481 | -0.000075192 |
| P1 | Top1 | 0.570618386 | 0.569215178 | +0.001403208 |
| P2 | Log Loss | 1.672652729 | 1.672845340 | -0.000192611 |
| P2 | Brier | 0.798797872 | 0.798877450 | -0.000079578 |
| P2 | ECE 10-bin | 0.008927967 | 0.008953478 | -0.000025510 |
| P2 | Top1 | 0.276392976 | 0.278127497 | -0.001734521 |

## F/G. 2025 trifecta metrics and Baseline difference

差はNatural Environment − Baseline。

| Metric | Natural | Baseline | 差 |
| --- | ---: | ---: | ---: |
| Trifecta Log Loss | 3.906661854 | 3.908322294 | -0.001660440 |
| 120-class Brier | 0.964200286 | 0.964284042 | -0.000083755 |
| Actual probability mean | 0.033720776 | 0.033668253 | +0.000052523 |
| Actual probability median | 0.024893128 | 0.024841355 | +0.000051773 |
| Top1 | 0.090740777 | 0.090760266 | -0.000019489 |
| Top3 | 0.225585157 | 0.225819025 | -0.000233868 |
| Top5 | 0.323809709 | 0.323108105 | +0.000701604 |
| Top10 | 0.484827815 | 0.484087233 | +0.000740582 |

## H. Coverage

対象は51,311 eligible race。

| Item | Race |
| --- | ---: |
| C2 available | 51,311 |
| Wind category available | 51,272 |
| Air temperature available | 51,272 |
| Tide source target | 25,159 |
| Tide valid | 25,152 |
| Tide NOT_APPLICABLE | 26,152 |
| Tide UNRESOLVED | 7 |

## I. Validation / leakage

各race 6艇、P1/P2 finite・範囲内・sum=1、3連単120通り/race・sum=1、全51,311 race evaluable。凍結済みpreprocessorと係数をtransformのみで適用し、この評価でfitなし。3着結果はK3 lineageを検証した評価用labelで、予測featureには使用していない。新規コードにR3参照はない。C2/L2のhistorical exact publication timestampは未検証であり、厳密な時点再現は主張しない。

## J. Artifact hashes

- 2025 feature report: `7f0b2e7406ad25afb6bfd187ff4c8120140a47217c348a7be6d5a32be1d87e1c`
- P1/P2 predictions: `0fe7ee41c176e6df788c681bede487d487ccfbed84e63a4d0f9155bf1716ea32`
- Trifecta probabilities: `6b7999f6983a596bbe1d4071409f49f26017c862b919c46c2865d206ed310bd6`
- Metrics JSON: `3f8539de0125c11cf63c3c8e3355367e12cf9c84fadaa92925a53f3f8012e9d6`

## K. Git

通常commitとpushの実績は最終報告で示す。
