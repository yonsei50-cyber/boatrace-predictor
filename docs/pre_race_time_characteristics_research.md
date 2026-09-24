# Pre-race time characteristics: C3 feasibility and C4 raw quality

Observed on 2026-09-25. Source DB: `pckyotei`, target DB:
`boatrace_predictor`. Both research transactions were read-only. Their latest
stored source date was 2026-09-18; that is not a claim about external source
availability. The machine-readable [metrics](pre_race_time_research_metrics.json)
contain all 144 C3 venue × boat cells, all 23 × 6 C4 raw profiles, and C3/C4
year × venue coverage. No race result, 2025 outcome, odds, or Prediction metric
was read. No DB or model change was made.

## A. Verdict

**C3_RESEARCH_COMPLETE; C4_RAW_QUALITY_RESEARCH_COMPLETE_WITH_BLOCKERS.**
The original five-type `PRE_RACE_TIME_CHARACTERISTICS_V1_RESEARCH_COMPLETE`
verdict is not earned: C4 scale, value-to-boat mapping, and suspected carried
values remain unresolved. C4 was not interpreted as seconds, repaired, used for
venue × boat numeric baselines, or z-scored. C3 calculations below are research
candidates, not a feature-method freeze.

## B. Source inventory

| Type | Source field | Stored range | Source rows | Nonzero four-digit raw | Blank | `0000` |
|---|---|---|---:|---:|---:|---:|
| Exhibition | `brd_c3.tenji_time` | 2017-01-01–2026-09-18 | 3,252,018 | 3,207,528 | 0 | 44,490 |
| Lap | `brd_c4.isshu` | 2023-10-12–2026-09-18 | 874,555 | 797,401 | 40,404 | 36,750 |
| Half lap | `brd_c4.hanshu` | same C4 row range | 874,555 | 40,316 | 834,151 | 88 |
| Turning foot | `brd_c4.mawariashi` | same C4 row range | 874,555 | 841,760 | 16,992 | 15,803 |
| Straight line | `brd_c4.chokusen` | same C4 row range | 874,555 | 746,462 | 112,800 | 15,293 |

C3's documented conversion is `0671 → 6.71 seconds`; its `0000` remains a
source sentinel. C4's four nonzero numeric shapes are **syntactic** convertibility
only. The provider's formal scale is not established, and `0000` is not a zero
time. Against all C4 rows, the nonzero four-digit rates are 91.178%
(`isshu`), 4.610% (`hanshu`), 96.250% (`mawariashi`), and 85.353%
(`chokusen`). There were no other raw shapes or NULLs in the current C4 rows.

C3 has 542,003 races at 24 venues, each with six boats. C4 has 145,761 races
at 23 venues; Edogawa (03) has no C4 rows. Annual C4 race counts against C3
are 10,680/55,992 (2023), 50,612/56,064 (2024), 50,196/55,908 (2025), and
34,273/40,872 (2026 through the stored end date). These are source-coverage
fractions, not valid-feature rates. C4's first/last observed day varies by
venue: Tsu (09) starts 2025-10-23; Tokoname (08) ends 2026-03-23, Suminoe
(12) 2026-04-08, Marugame (15) 2026-07-25, and Kojima (16) 2026-02-03.
These bounds alone do not establish official provision or discontinuation.

## C. Data quality and identity

C3 Canonical has zero duplicate `(race_id, boat_no)` keys; all 3,252,018 rows
join to a `core.race_entry` boat and player. C4 has zero duplicate natural keys
`(kaisai_nen, kaisai_tsukihi, kyoteijo_code, race_no, teiban)`; all 874,555
rows find the same source boat slot in L3 and C3, with an L3 registration
number. Source `teiban` is the boat-number identity used here; `actual_course`
was not used. The join proves key presence, **not** that each C4 value belongs
to that boat. C4 has 145,750 six-boat and 11 five-boat races. All 11 are Kojima
(2025-12-23–2026-01-29); the missing slots are listed in the metrics file.

The number of C4 races with 0 / 5 / 6 nonzero four-digit boat observations:

| Field | 0 boats | 5 boats | 6 boats | Other counts |
|---|---:|---:|---:|---|
| `isshu` | 12,559 | 1,639 | 131,487 | 1: 4; 2: 2; 3: 4; 4: 66 |
| `hanshu` | 139,030 | 66 | 6,663 | 4: 2 |
| `mawariashi` | 5,156 | 1,723 | 138,812 | 1: 1; 2: 1; 3: 2; 4: 66 |
| `chokusen` | 21,067 | 1,553 | 123,069 | 1: 1; 3: 2; 4: 69 |

Blank structure is venue-specific: Kiryu (01) has no `isshu` and is the only
venue with `hanshu`; Suminoe (12), Amagasaki (13), and Tokuyama (18) have no
`chokusen`; Wakamatsu (20) has 16,992 blank `mawariashi` rows. The historical
reason for every missing period is not inferred. Race absence, blank field,
`0000`, and numeric-looking raw code are kept distinct.

The repeated-value diagnostic re-ran on this source snapshot. Among 133,412
same-day adjacent six-boat race pairs, **373** repeated the full informative
C4 packet by boat slot. Field-level six-boat repeats were `isshu` 279,
`hanshu` 26, `mawariashi` 374, and `chokusen` 349; one full packet also
recurred on the previous calendar day. These are suspicious repetitions, not
proven source corruption. For Kiryu 2024-03-20 11R→12R, all six raw `hanshu`,
`mawariashi`, and `chokusen` values repeat by boat slot. The L3 player IDs
change from `4654,3156,4319,3909,4608,4578` to
`4137,4580,4360,4491,4089,4105`, and the six motor numbers also change.

The conservative zero-slot mapping diagnostic again found **79 candidate
races** (Hamanako 50, Wakamatsu 29). Hamanako 2024-12-31 6R is an example:
C3 exhibition `0000` is on boat 1, while C4 `isshu/mawariashi/chokusen`
`0000` is on boat 6. Independent source missingness is possible; this does
not authorize shifting values. No value was reassigned or filled.

## D. Distributions and venue × boat baseline evidence

For the 3,207,528 valid C3 exhibition values in seconds: mean 6.8096,
sample SD 0.1143, min 6.25, p01 6.58, p05 6.64, median 6.80, p95 7.01,
p99 7.12, max 10.45. Pooled venue means range from 6.7215 (Miyajima 17)
to 6.9803 (Tokuyama 18). Within each venue, the range of six boat-number
means is 0.0152–0.0417 seconds. As examples, Toda (02) boat 1/6 means are
6.7559/6.7976; Hamanako (06) 6.7121/6.7293. Every one of the 144
venue × boat cells has 20,561–23,486 observations. Their full count, mean,
median, sample SD, min, and max are in the metrics file. These are descriptive
differences; they do not identify a causal boat effect or freeze a baseline.

C4 numeric-looking **raw code** distributions, with no time unit assigned:

| Field | n | median raw code | p05–p95 | raw min–max |
|---|---:|---:|---:|---:|
| `isshu` | 797,401 | `3750` | `3663–3849` | `0004–6877` |
| `hanshu` | 40,316 | `1871` | `1825–1932` | `1779–2195` |
| `mawariashi` | 841,760 | `0576` | `0483–1171` | `0005–1732` |
| `chokusen` | 746,462 | `0730` | `0610–0803` | `0006–3833` |

The metrics file records raw-shape counts and raw-code quantiles for **every
C4 venue × boat_no × field**. Examples of boat 1–6 median ranges: Kiryu
`hanshu` `1856–1878`; Toda `isshu` `3713–3760`; Hamanako `isshu`
`3731–3778`; Wakamatsu `mawariashi` `0595–0608`. Suminoe `mawariashi`
`1145–1165` differs markedly from Toda `0553–0560`; no shared scale is
inferred. Venue × boat numeric baselines for C4 were intentionally not made.

## E. Availability

C3 valid exhibition time is present for 98.632% of C3 boats. On the
representative day 2024-12-31, the 793 participating players have 15–50
prior races in the 2017+ history. For the 779 players with 50 prior races,
599 have 50 observed times, 114 have 49, 55 have 48, 7 have 47, 3 have 46,
and 1 has 45. The other 14 have 15–24 prior races and 15–24 observed times.
The exploratory rate `observed_n / history_n_races` ranges 0.90–1.00,
with median 1.00 and p05 0.96. Using available races as the denominator for
the 14 shorter histories is a research display choice, not a formal feature
rule. A specific cause of C3 `0000` is not assigned.

C4 raw observation coverage varies strongly by venue and field. It is not
converted into a player availability trait while the value-to-boat mapping
remains under question. The C4 raw row and race distributions above remain
available for such a later decision.

## F. Recent-50 feasibility and D-1 boundary

The 2024-12-31 C3 representative-day cohort has 1,296 boats and 793
distinct players. Their history query returned 39,224 **prior race entries**,
ranked by player and limited to 50 entries per player before testing whether
a time was observed. All 1,296 target-day boats use the same history cutoff
`race_date < 2024-12-31`; no 2024-12-31 race enters another same-day race's
history. The illustrative venue × boat mean baseline also uses only rows
before 2024-12-31. The current target-day observation is kept separate.
This is a race-date boundary check; individual historical source publication
times and revisions are not present, so exact historical as-of state is not
proven by this analysis.

All 793 players had at least two observed historical C3 times; 14 had fewer
than 50 prior races. Residual sample SD was zero for 0 players and below
0.01 seconds for 0; median SD was 0.0824 seconds (min 0.0437, p95 0.1191,
max 0.2096). A production fallback for short history or zero SD is not
defined by this check.

## G. Candidate z-score feasibility

For C3 only, a **demonstration** used each venue × boat's pooled pre-day
mean, historical player residual mean/sample SD over observed entries among
the last 50 races, and the target day's current C3 time. The 144 pre-day
baseline cells have 16,948–19,255 observations each. Player residual means
still vary after venue × boat adjustment: p05 −0.0521, median 0.0064,
p95 0.0672 seconds. This is descriptive variation, not proof of player-specific
predictive value.

Of 1,296 current boats, 1,292 had current valid times and a calculable
candidate z. Distribution: mean −0.751, median −0.455, p01 −5.701,
p99 1.767, min −7.974, max 3.296; 24 have `|z| > 5`, none `|z| > 10`.
The negative shift and tail warrant more investigation before a formal
feature method. One representative day cannot establish stability or
calibration. No clipping, winsorization, threshold, or prediction evaluation
was selected. C4 z-scores were not calculated.

## H. Blocking questions before a later feature-method task

1. Obtain authoritative C4 field-by-field scale and definitions, including
   why raw code ranges differ sharply by venue. Otherwise exclude C4 from
   numeric features.
2. Establish the C4 boat assignment rule and historical revision/repair
   evidence. Options for later design are verified correction from source
   evidence or exclusion of suspect observations; this task adopts neither.
3. Establish whether/which repeated C4 packets are carried values and the
   affected period. A repeated packet alone is not proof.
4. For C3, choose a time-ordered venue × boat baseline window and confirm
   robustness across representative days; then decide short-history and
   zero/near-zero-SD behavior, and whether any tail treatment is needed.
5. Decide the formal denominator for fewer than 50 prior races. The displayed
   `observed_n / available_prior_races` is only a candidate.

No 2025 label, Log Loss, hit rate, P1/P2, odds, EV, or Prediction data was
used to settle these questions.

## I. Reproduction and Git scope

`scripts/research_pre_race_times.py` produces the metrics file using read-only
transactions. `scripts/research_c4_carry_forward.py` and
`scripts/research_c4_boat_mapping.py` reproduce the raw repeat and zero-slot
diagnostics. The output of the latter two is under ignored `.local/` paths.
Checks reconciled C3 status totals and all 144 cell counts, C4 raw status
totals and race counts, 2017+ history depth, and the D-1 boundary. No schema,
Canonical data, frozen method, or Prediction model was changed.

From the project root in PowerShell, the primary report data can be reproduced
with the project Python executable and these absolute paths:

```powershell
$env:PYTHONPATH = 'C:\Users\knkzh\Documents\boatrace-predictor'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -B 'C:\Users\knkzh\Documents\boatrace-predictor\scripts\research_pre_race_times.py' --day 2024-12-31 --output 'C:\Users\knkzh\Documents\boatrace-predictor\.local\pre_race_time_research\metrics.json'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -B 'C:\Users\knkzh\Documents\boatrace-predictor\scripts\research_c4_carry_forward.py'
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -B 'C:\Users\knkzh\Documents\boatrace-predictor\scripts\research_c4_boat_mapping.py'
```
