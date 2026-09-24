# Prediction Baseline v1: pre-holdout freeze

**Verdict:** `P1_P2_BASELINE_V1_PREHOLDOUT_FROZEN`.

The only source is `core.prediction_dataset_v1`, filtered to `label_eligible = TRUE`
and `race_date < DATE '2025-01-01'`. The development input has 407,707
eligible six-boat races from 2017 through 2024. The input hash below covers
the extracted model values after their float32 representation, category codes,
race IDs, years, and P1/P2 labels. The extract uses a read-only repeatable-read
database snapshot. The existing K3-only dataset labels are used directly;
there is no new result-source join.

## Method fixed before the independent holdout

For each race and boat, `score = beta dot x`. P1 and exact P2 have separate
coefficient vectors and separate `softmax(score / T)` distributions over the
six boats. Each distribution sums to one. P2 is trained on the exactly-second
label, not on a P1-conditional label. Neither model includes odds or raw
player ID.

The only bundles compared were CORE, CORE+SHORT, CORE+MOTOR, and FULL. CORE
contains boat number; L3 national win rate; the six first-course and six
exact-second-course Rating v1 values and overall Rating v1; six Entry Course
Index v1 probabilities; F Suspension State v1 and the unserved-F flag;
current-term F count; and the associated statuses. SHORT adds Rating SHORT_50
only. MOTOR adds Motor A Base3 and Current, their statuses, and the supporting
meeting/use/residual counts. FULL contains all three groups. No C2/C3/C4,
Motor B, exhibition, tilt, part-change, newcomer, or stabilizer feature was
added. Entry Course history count and SHORT_50 history count are also excluded.

Each fit calculates numeric medians, means, and standard deviations from its
training years only. Numeric NULL is median-imputed and gets a separate
missing indicator. Zero standard deviation uses scale 1. Categorical values,
including `MISSING` and `UNRESOLVED`, remain separate levels derived only from
training years; an unseen validation level gets all-zero indicators. The
transformed features are centered within each race, which leaves softmax
probabilities unchanged. The source dataset is unchanged. The model artifact
contains the final preprocessor statistics, category vocabulary, feature
order, and coefficients.

The objective is mean race negative log likelihood plus
`0.5 * L2 * sum(beta**2)`. L2 candidates were `0.01, 0.1, 1, 10, 100`.
Selection uses the equally weighted mean of annual 2022 and 2023 Log Loss.
Within an absolute `1e-5` Log Loss tie band, the lower mean Brier wins;
within an absolute `1e-5` Brier tie band, the simpler bundle wins. Brier is
the six-boat squared-error sum per race. ECE uses ten equal-width probability
bins across all boat predictions, consistent with the existing Rating
evaluation. Top1 is the race-level highest-probability label hit rate.

| Stage | Train | Validation / calibration |
| --- | --- | --- |
| Selection fold 1 | 2017–2021 | 2022 |
| Selection fold 2 | 2017–2022 | 2023 |
| Temperature | 2017–2023 | 2024 |
| Final coefficients | 2017–2024 | none |

After selection, each model is fitted on 2017–2023 and one positive scalar
temperature minimizes 2024 Log Loss. The fixed bundle, L2, preprocessing
procedure, and 2024 temperature are then used with new coefficients and
training-only statistics fitted on all eligible 2017–2024 races. Temperature
is carried forward without retuning.

## Selected method

| Target | Bundle | L2 | 2022/2023 mean Log Loss | 2022/2023 mean Brier | Temperature |
| --- | --- | ---: | ---: | ---: | ---: |
| P1 | CORE+MOTOR | 0.01 | 1.184994725 | 0.580693087 | 1.014333406 |
| exact P2 | FULL | 0.01 | 1.671992794 | 0.798514052 | 1.006654879 |

## Development metrics

All rows below are development data. The 2022 and 2023 rows are the chosen
candidate's forward validation scores. The 2024 rows are the selected model
before and after its temperature scaling; they do not choose the bundle or L2.

| Target | Year | Races | Log Loss | Brier | ECE 10-bin | Top1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P1 | 2022 | 51,264 | 1.180534319 | 0.578416324 | 0.002646430 | 0.573735955 |
| P1 | 2023 | 51,246 | 1.189455131 | 0.582969849 | 0.002110294 | 0.571693400 |
| P1 before T | 2024 | 51,392 | 1.199242962 | 0.586994614 | 0.002393415 | 0.569096357 |
| P1 after T | 2024 | 51,392 | 1.199160738 | 0.586975750 | 0.002170778 | 0.569096357 |
| exact P2 | 2022 | 51,264 | 1.668192249 | 0.797318815 | 0.010071951 | 0.280586767 |
| exact P2 | 2023 | 51,246 | 1.675793339 | 0.799709288 | 0.009942532 | 0.275553214 |
| exact P2 before T | 2024 | 51,392 | 1.676512479 | 0.800006713 | 0.009401632 | 0.273252646 |
| exact P2 after T | 2024 | 51,392 | 1.676508150 | 0.799955670 | 0.009527299 | 0.273252646 |

## Freeze and reproducibility

The final models have 78 ordered coefficients for P1 and 80 for P2. The 2024
prediction artifact stores pre-temperature, post-temperature, and final-fit
probabilities for a deterministic rerun check. No final-fit performance metric
is computed.

| Item | SHA-256 |
| --- | --- |
| Development model input | `25056b8213e43b17b8cc8b6a94d50acff21741d609cdae6062add5f40da06095` |
| Development SQL | `707bc38ff182627198feee0f63b42ce6828e72604cd292dd29a3007685b3eafa` |
| Implementation | `057c048e6b8032cc5a0165839896e89120ef2f08f61197d3117eb2e88cb8ceea` |
| Freeze JSON | `f7dcb2f64fbc345de64767dcf9723a52b4db972121f30320c85ee48ea606a9f4` |
| Model JSON | `3954fbecb97dae5816b45e00735ab4ec31f13dbdb13d21c2c4022fca9d37f54e` |
| Development predictions NPZ | `13d8c22b45055426a777bb9a98c78157e4913a1ea60557b0bddea5e1096ecdea` |

Artifacts:

- `artifacts/p1_p2_baseline_v1_freeze.json`
- `artifacts/p1_p2_baseline_v1_model.json`
- `artifacts/p1_p2_baseline_v1_development_predictions.npz`

Reproduction on the configured local database, using the known project Python:

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -m scripts.p1_p2_baseline_v1 extract
$env:OPENBLAS_NUM_THREADS = '4'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -m scripts.p1_p2_baseline_v1 develop
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -m unittest tests.test_p1_p2_baseline_v1
```

The known limitation of historical L3 publication-time verification is
carried forward from the existing dataset documentation. It was not
reinvestigated here. The independent 2025 holdout remains for a separate
task; 2026 was outside this development run.
