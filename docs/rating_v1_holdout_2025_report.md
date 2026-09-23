# Rating Method v1: independent 2025 holdout

## A. Verdict

`RATING_V1_HOLDOUT_EVALUATED_NO_PREDECLARED_PASS_THRESHOLD`. The frozen v1 was evaluated once on 2025-01-01 through 2025-12-31, with no parameter, method, eligibility, initialization, short-window, or calibration change. A PASS/FAIL threshold was not fixed before the holdout, so this report records the observed performance without inventing one. All three selected definitions have lower combined log loss than in 2024, while the course model's first-place Brier and top-1 hit rate are slightly worse. The v1 freeze remains permanent.

## B. Rating v1 checkpoint

- Freeze checkpoint: `240044f92975fa6f6c426d899660ec134f2666dc`, `feat(rating): freeze rating method v1`.
- Normal push succeeded. Local `HEAD`, `origin/main`, and remote `refs/heads/main` all matched that full commit ID after the push.
- Freeze file SHA-256: `c7fbd2af725f2c9d62491923a5a411350a33076b8b1b305798c5ed07d23136fb`.
- The checkpoint contains exactly the freeze JSON, 2023–2024 comparison JSON, comparison script, its test, and the method report. The pre-existing changes to `AGENTS.md` and `.codex/config.toml` were excluded.
- Before commit, the frozen file cutoff was `2024-12-31`, its 2025 status was `SEALED_NOT_EVALUATED`, the comparison artifact had no 2025-labelled metric keys, the selected configurations matched the report, and all 17 rating-method tests passed.

## C. Holdout integrity

The pre-outcome gate was recorded at `2026-09-23T02:45:15.416599+00:00`; evaluation began at `2026-09-23T02:45:24.275596+00:00` and ended at `2026-09-23T02:51:32.779371+00:00`. The gate is `COMPLETED` and blocks another evaluation call.

|Identity|SHA-256 or value|
|---|---|
|Git HEAD|`240044f92975fa6f6c426d899660ec134f2666dc`|
|Freeze file|`c7fbd2af725f2c9d62491923a5a411350a33076b8b1b305798c5ed07d23136fb`|
|Frozen comparison code|`10fb2db5c6b97ce0e6e2d968e783ca5fcbd35b77314bc5817561f146f9703271`|
|Holdout evaluator code|`54996c3e3d7bc936446165ca071cd9f165cf719118dc1c49517d917614adc141`|
|2017–2024 monthly shard chain|`ae4075eeff72db3b66ce68d6f06ee5c62c00cc74b8df7a886c1d21c1209a6ed8`|
|2017–2025 monthly shard chain, 108 shards|`a0bfb0bf2f9e6b4c055372ded6d805326f8162c6ff69d0d733c395ea3bc8d610`|
|2017–2024 ordered result extract, 2,671,344 boats|`2177eb4df8b64dcc0c28b46d940f3770be7742538ff86c4932a83861fe4d0c8c`|
|2025 ordered result extract, 335,448 boats|`b47b52fcf17fffb4f491063ff737ab5d6a4665d40776a448fb0f3768cc04f7ec`|

The target DB was `boatrace_predictor`, read-only, under a `REPEATABLE READ` snapshot. The 2017–2024 extract matched the frozen v1 hash before the first 2025 day was scored. The evaluator SQL differs from the frozen comparison query only by its exclusive upper bound changing from `2025-01-01` to `2026-01-01`. It reads race identity, entries, and result state only; C3/C4, motor, odds, and environment data are absent. Selected methods are A course softmax at learning rate 16 and scale 400, B pairwise Elo at K 120 with race normalization and scale 400, and STRICT valid-result SHORT_50 with available-history fallback. All retain 2017–2022 warm-up, D-1 daily updates, no decay, and the frozen newcomer rule.

## D. 2025 eligibility

|Measure|Count|
|---|---:|
|Total races / boats|55,908 / 335,448|
|STRICT eligible races / boats|51,137 / 306,822|
|Excluded races / boats|4,771 / 28,626|
|Excluded: result records not present|986 races|
|Excluded: other non-STRICT or incomplete result|3,785 races|
|Unique scored players|1,636|
|A, B, SHORT_50 rating coverage|306,822 / 306,822 scored boats for each|
|2025 day-roster `CONFIRMED_NEWCOMER`|0|
|2025 day-roster `NEWCOMER_UNCERTAIN`|53 appearances|

Both A and B applied 51,137 STRICT race updates. No excluded race supplied a numeric rating update. The exclusion population was not changed after inspecting the result.

## E–G. Course first, exact second, and combined metric

These are race-level six-boat probabilities from the frozen A method. ECE is the ten-bin, boat-weighted absolute calibration gap.

|Target|2025 log loss|Brier|ECE|Top-1 hit rate|
|---|---:|---:|---:|---:|
|First|1.280773|0.609904|0.018623|0.559360|
|Exactly second|1.696535|0.801714|0.007407|See JSON|
|Equal-weight first/exact-second combined|1.488654|—|—|—|

Post-result `actual_course` strata use one boat per course in each eligible race. These **binary** one-versus-rest losses are diagnostic and are not directly comparable with the six-boat race-level losses above. Actual course was never supplied to the prediction function.

|Actual course|First wins|First binary LL|First Brier|First ECE|Exact-second finishes|Second binary LL|Second Brier|Second ECE|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|1|28,370|0.647628|0.227472|0.046555|8,901|0.462503|0.143776|0.016563|
|2|6,736|0.362568|0.107959|0.013598|12,863|0.555750|0.185150|0.022074|
|3|6,544|0.358522|0.105876|0.011804|11,141|0.515235|0.167418|0.016366|
|4|5,360|0.316578|0.089929|0.007602|8,699|0.446589|0.138478|0.006054|
|5|3,134|0.223135|0.056534|0.016291|6,411|0.369564|0.107825|0.005280|
|6|993|0.120399|0.022134|0.048648|3,122|0.239229|0.059066|0.045882|

Each actual-course stratum contains 51,137 scored boats. Its ten-bin calibration table is in the machine-readable JSON.

## H. Overall Rating

The frozen B method produced first/exact-second combined log loss **1.662897**. First log loss was 1.602097, exact-second log loss 1.723696, pairwise log loss **0.614679** across 767,055 ordered pair comparisons, full-ranking log loss 6.092759 per race, and mean Spearman correlation 0.394788. First/exact-second Brier scores were 0.769193/0.814332; ten-bin ECE values were 0.012342/0.009873. The same ranking calculations were used for 2023 and 2024.

## I. Short-term Rating

The frozen SHORT_50 standalone diagnostic yielded first/exact-second combined log loss **1.770291**, first/exact-second log loss 1.762545/1.778037, Brier 0.823627/0.828839, full-ranking log loss 6.473039, and pairwise log loss 0.677676. Its combined log loss exceeds the B overall diagnostic by **0.107394** per race. This does not measure incremental value when SHORT_50 is combined with other ratings.

|D-1 STRICT valid-result history|Scored boat appearances|Distinct players observed in category|
|---|---:|---:|
|50 (window full)|303,991|1,612|
|1–49 (available history only)|2,775|82|
|0 (initializer)|56|53|

The distinct-player categories can overlap as a player accumulates results. No 2025 result was used in that day's history. The very small standalone ten-bin ECE reflects near-base-rate predictions and does not establish useful discrimination.

## J. Quarterly stability

|2025 period|STRICT races|A combined LL|B combined LL|B pairwise LL|SHORT_50 combined LL|
|---|---:|---:|---:|---:|---:|
|Q1|12,749|1.478686|1.666859|0.617220|1.771561|
|Q2|13,012|1.488797|1.658933|0.611587|1.769752|
|Q3|13,473|1.503828|1.657025|0.611952|1.769036|
|Q4|11,903|1.482000|1.669632|0.618424|1.770939|
|Annual|51,137|1.488654|1.662897|0.614679|1.770291|

A's combined loss was highest in Q3; B's was highest in Q4. The JSON retains quarterly first/second scores, Brier, calibration bins, and ranking diagnostics for every method.

## K. 2023 / 2024 / 2025 comparison

The 2023 internal statistic is **Q2–Q4 prequential**, whereas 2024 and 2025 are full-year out-of-time periods. All use the frozen method definition and common STRICT scoring target; 2025 was neither fit nor calibrated.

|Method|2023 internal combined LL|2024 development combined LL|2025 holdout combined LL|2025 minus 2024|
|---|---:|---:|---:|---:|
|A course|1.494430|1.489451|1.488654|-0.000797|
|B overall|1.666262|1.668118|1.662897|-0.005221|
|SHORT_50 standalone|1.771079|1.771368|1.770291|-0.001078|

A's first-place Brier changed from 0.609120 to 0.609904 and top-1 hit rate from 0.561391 to 0.559360, despite a slightly lower log loss. Its first/exact-second ECE moved by -0.002522/-0.001168 relative to 2024. B's changed by -0.000249/-0.000196. These are descriptive ten-bin gaps, with no preregistered drift threshold or uncertainty interval.

## L. Leakage audit

The evaluator asserted chronological dates, checked that every update date preceded the next scored day, and compared A/B/SHORT_50 rating state before and after all same-day predictions and deltas. It applied D results only after every D race was scored. Each race's actual course was used for post-result updates and post-hoc diagnostics only. Probability bounds and first/second normalization were checked for every scored race. The frozen 2017–2024 extract and file hashes matched, and saved annual/quarter, eligibility/boat, depth, course-event, and file-hash reconciliations passed after the run.

## M. Known limitations

- Original historical result publication timestamps and as-of availability remain unverified. This is a D-1 retrospective holdout, not a live-readiness certification.
- Metrics are conditional on complete six-boat numeric-finish races; calibration on F/L and other special-result races is not established.
- The A method mixes player course ratings with an estimated pre-race course distribution and is not a pure racer-strength ablation or exact marginalization over courses.
- No confirmed newcomer exercised the conditional 0.8 initializer in the observed holdout. First observation alone was never promoted to confirmed debut.
- There are no preregistered PASS/FAIL thresholds or paired uncertainty intervals. SHORT_50 incremental value in a future combined model remains unknown.

## N. Changed files and artifacts

The holdout evaluator, four pre-outcome tests, gate JSON, result JSON, and this report remain uncommitted as requested. No production Rating state migration or canonical/frozen dataset change was made. `AGENTS.md` and `.codex/config.toml` retain their prior dirty state and were not touched by this task.

## O. Next step

Review the 2025 result and retain Rating Method Freeze v1 unchanged. If improvement is needed, define a separate **Rating Method v2 / 2026 candidate**; 2025 may become its development evidence, and an independently evaluated v2 would require later data. The 2026 seven-day re-evaluation is outside this task.
