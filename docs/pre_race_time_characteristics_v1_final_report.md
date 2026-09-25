# Pre-race Time Characteristics v1 — research report

**Verdict: `PRE_RACE_TIME_CHARACTERISTICS_V1_RESEARCH_COMPLETE`.** This is a
descriptive research checkpoint, **not** a feature-method freeze or Prediction
deployment. Read-only source and target queries were run on 2026-09-25. The
latest stored C3/C4 source day was 2026-09-18. The complete distributions,
venue × boat cells, eight representative dates, and observed-n bands are in
[`pre_race_time_characteristics_v1_metrics.json`](pre_race_time_characteristics_v1_metrics.json).

## A. Verdict, source, scale, and time boundary

The effective time types are C3 exhibition, C4 lap-family, C4 turning-foot,
and C4 straight-line. C4 uses `raw / 100` seconds. Kiryu (`01`) uses `hanshu`
for the lap-family series; other provided venues use `isshu`. The original
field and raw value remain in source provenance. Smaller is better for every
type; the candidate z has the opposite sign so positive means faster than the
player's usual residual. No C4 value is assigned to a different boat.

The research windows use only race dates before prediction date D. A player's
history is the most recent **50 races**, then only valid observations within
those races enter the mean and sample standard deviation. For fewer than 50
prior races, the denominator is the number of prior races that exist.
Availability is `observed_n / history_n_races`. The venue × `boat_no` baseline
is calculated from values before D; `actual_course` is not used. Individual
historical publication timestamps are not proved by these day-level checks.
No result label, K3 value, odds, or Prediction outcome enters a C4 gate,
baseline, history statistic, or candidate z.

## B. C4 boat mapping safety

The C4 source has 145,761 races / 874,555 rows from 2023-10-12 through
2026-09-18. The gate requires stored slots `1`–`6`, at least one nonzero
four-digit C4 time in each slot, no C3 exhibition `0000` anywhere in the
race, no detected carried packet, and no explicit quarantine. A gate failure
excludes **all three C4 numeric series for the entire race**. C3 exhibition
remains separate. A numeric four-digit raw code is a candidate observation;
this research does not invent an additional plausibility cutoff.

| Race status | Races | Meaning |
|---|---:|---|
| `SAFE` | 141,230 | Passes the defined pre-race C4 numeric gates |
| `UNAVAILABLE_MAPPING` | 4,157 | C4 structure or C3 `0000` prevents certification; not proof of a bad mapping |
| `CARRY_FORWARD_INVALID` | 373 | Later race in a confirmed carried packet pair |
| `QUARANTINED_C4_PACKET` | 1 | Explicit user decision for Kojima 2024-01-02 12R only |

The C4-only structural gate fails 4,135 races. C3 `tenji_time='0000'` occurs
on at least one boat in 1,842 C4 source races; after the structural and carry
gates, it removes **24 additional races**, as requested. This use of `0000`
does **not** classify a scratch and does **not** remap C4. All **79** previously
listed boat-mapping suspects fail the safety gate. All **11** Kojima five-row
races are excluded from C4 numeric features as `UNRESOLVED_MAPPING` cases in
the research interpretation; the report's aggregate status is
`UNAVAILABLE_MAPPING`. Their C3 exhibition observations are not excluded by
this rule. K3 remains audit-only.

The exact Kojima (`16`) **2024-01-02 12R** C4 packet is quarantined in all
three C4 series; C3 is retained. Its source packet is checked byte-for-byte
before the exception is applied. The one-race exception is **not** a general
numeric threshold, field correction, or rule for other races. The earlier
packet evidence is recorded in
[`pre_race_time_characteristics_v1_packet_blocker.md`](pre_race_time_characteristics_v1_packet_blocker.md).

## C. Carry-forward and chains

The existing informative adjacent-race raw-packet predicate reproduced all
**373** known pairs exactly. They identify 373 distinct later races / 2,238
C4 rows for exclusion. Chain lengths in pair counts are: 300×1, 23×2,
4×3, 1×4, and 1×11. Thus 29 chains have multiple pairs. The first race
of each of the 329 chains is never excluded *because it is first*. Of those
first races, 316 pass the other gates and 13 fail the independent mapping
gate. No previous-race value is reused, imputed, or repaired.

## D. Corrected availability and seconds distributions

C3 has 542,003 races / 3,252,018 boats from 2017 onward; 535,579 races
have at least one valid exhibition time, 529,699 have all six, and
3,207,528 boats have valid exhibition seconds. During the C4 observed source
period, C3 has 164,508 races / 987,048 boats. C4 has no source rows for
Edogawa (`03`); source absence at other venue/dates is not reclassified as
formal non-provision without source evidence.

| Time type | Races with ≥1 usable boat among C4 source races | Usable boats | Median seconds | p05–p95 seconds | Min–max seconds |
|---|---:|---:|---:|---:|---:|
| C3 exhibition (2017+) | 535,579 | 3,207,528 | 6.80 | 6.64–7.01 | 6.25–10.45 |
| C4 lap-family | 137,899 | 827,315 | 37.47 | 36.03–38.47 | 17.79–45.44 |
| C4 turning-foot | 138,441 | 830,625 | 5.76 | 4.83–11.71 | 3.30–17.32 |
| C4 straight-line | 122,700 | 736,200 | 7.30 | 6.10–8.03 | 5.06–10.47 |

The pooled lap-family range mixes Kiryu half-lap (~18-second display) with
other venues' full-lap (~37-second display). They are one venue-dependent
feature series, not directly pooled as a single unadjusted ability measure.
For each C4 type, 24,931 source rows are in `UNAVAILABLE_MAPPING` races and
2,238 in carried later races; the six rows of the explicit quarantine are
separate. Among otherwise safe source rows, `MISSING_OTHER` counts are 20,065
lap, 16,755 turning-foot, and 114 straight. The known non-provided straight
venues (12, 13, 18) contribute 111,066 otherwise safe source rows; Edogawa
has no C4 source rows at all. Missingness is not treated as corruption or
converted to zero seconds.

## E. Venue × boat differences

The JSON contains all 144 C3 venue × boat cells, 138 C4 lap cells, 138
turning-foot cells, and 120 straight cells, each with usable count, mean,
median, sample standard deviation, and quantiles. C3 has 20,561–23,486
observations per cell. C4 cell count ranges are 1,849–6,785 lap,
2,017–6,910 turning-foot, and 2,016–6,909 straight. Within a venue, the
range of six boat-number means is 0.015–0.042 seconds for C3,
0.229–0.785 for C4 lap, 0.011–0.380 for turning-foot, and 0.008–0.134 for
straight. Kiryu's lap-family boat means are 18.584–18.813 seconds, compared
with 37.537–38.022 at Tokuyama (`18`). These descriptive differences support
examining venue × boat adjustment; they do not prove a causal boat effect.

## F. Baseline window comparison

`all_history` uses all valid pre-D observations; `trailing_1y` uses the
calendar interval `[D - 1 year, D)`. Both use venue × boat cells. In 2024,
the C3 mean absolute difference between cell baselines increased over the
four representative dates: 0.0164, 0.0191, 0.0241, and 0.0265 seconds
(March 31, June 30, September 30, December 31). All 144 cells were present;
the one-year minimum per-cell counts were 2,139, 1,951, 1,956, and 1,860.

| 2024 date | C3 mean candidate z: all / 1y | C4 lap mean candidate z: all / 1y | C4 lap mean absolute cell gap (s) |
|---|---:|---:|---:|
| Mar 31 | −0.356 / −0.456 | −0.784 / −0.784 | 0 |
| Jun 30 | −0.477 / −0.526 | −1.144 / −1.144 | 0 |
| Sep 30 | +0.363 / +0.401 | +0.994 / +0.994 | 0 |
| Dec 31 | −0.751 / −0.845 | −0.304 / −0.314 | 0.0473 |

At 2024-12-31, switching C3 to one year makes the negative z center more
negative (−0.751 → −0.845). Thus the observed baseline time drift alone does
**not** explain the negative center. The sign and size of candidate z centers
also change across 2024 dates, so neither baseline window is formally chosen.
The JSON includes current residual centers, median/extreme z values, and all
four types for all eight sampled dates.

C4 begins on 2023-10-12. Globally, all-history and one-year windows select
the same observed records through **2024-10-12**; they can first differ on
2024-10-13. Individual venue/field start dates vary. Tsu (`09`) first has
C4 source records on 2025-10-23, so a meaningful one-year-vs-all comparison
for it is not available by the stored end date. At 2024-12-31, the mean
absolute cell gaps were 0.0473 seconds for lap, 0.0120 for turning-foot, and
0.0093 for straight. C4 baseline period remains an open method choice.

## G. Recent-50 and availability

The eight representative days (2023-10-31, 11-30, 12-31; 2024-01-31,
03-31, 06-30, 09-30, 12-31) contain 7,272 race×boat current observations.
The available current / calculable candidate-z counts are C3 **7,236 / 7,236**,
C4 lap **6,150 / 6,116**, turning-foot **6,006 / 5,970**, and straight
**5,754 / 5,724**. A z is calculated only for descriptive research when the
current value exists, at least two observed prior residuals exist, and their
sample SD is positive; this is not a production fallback decision.

Early C4 history is materially shorter: on 2023-10-31, median observed counts
among the last 50 races were 10 lap, 10 turning-foot, and 9 straight, with
median availability rates 0.20, 0.20, and 0.18. By 2024-12-31 they were
44 / 42 / 38 observed and 0.88 / 0.86 / 0.78. C3's median observed count
was 50 and median availability 1.00 on both dates. These are sampled cohorts,
not a universal minimum observation rule.

## H. Candidate z stability

In all eight dates, sample SD was exactly zero for **0** current boats across
all four types. As diagnostic counts only, positive SD below 0.01 seconds
occurred on 0 C3, 0 lap, **1 turning-foot**, and 0 straight current boats.
Below 0.05 seconds the corresponding counts were 67, 3, 8, and 95. No
clipping, epsilon floor, threshold, or imputation was applied. Across the
sampled current observations, candidate `|z|>5` counts were 60 C3, 26 lap,
49 turning-foot, and 50 straight; `|z|>10` counts were 1, 8, 2, and 5.
The retained 45.44-second C4 lap observation and other tail values remain
visible as source-derived observations pending a later method decision.

## I. Minimum-observation evidence

The table uses the all-history baseline with eight dates pooled. It gives
current boats / calculable z, median player
residual SD in seconds, and z sample SD for each observed-n band. The JSON
also gives z mean, quantiles, and extreme counts in each band and on each day.
Repeated players across days are separate as-of feature observations.

| Type | observed_n | Current / z | Median residual SD (s) | z sample SD | `|z|>5` |
|---|---|---:|---:|---:|---:|
| C3 exhibition | 5–9 | 2 / 2 | 0.067 | 0.119 | 0 |
| C3 exhibition | 10–19 | 32 / 32 | 0.066 | 1.283 | 0 |
| C3 exhibition | 20–29 | 32 / 32 | 0.063 | 1.196 | 0 |
| C3 exhibition | 30–39 | 9 / 9 | 0.078 | 1.087 | 0 |
| C3 exhibition | 40–50 | 7,197 / 7,161 | 0.082 | 1.281 | 60 |
| C4 lap | 0 | 21 / 0 | — | — | 0 |
| C4 lap | 1–4 | 81 / 63 | 0.277 | 3.629 | 3 |
| C4 lap | 5–9 | 235 / 222 | 0.301 | 1.406 | 1 |
| C4 lap | 10–19 | 692 / 603 | 0.322 | 1.190 | 0 |
| C4 lap | 20–29 | 753 / 587 | 0.331 | 1.332 | 2 |
| C4 lap | 30–39 | 1,686 / 1,327 | 0.341 | 1.274 | 4 |
| C4 lap | 40–50 | 3,804 / 3,314 | 0.347 | 1.420 | 16 |
| C4 turning-foot | 0 | 21 / 0 | — | — | 0 |
| C4 turning-foot | 1–4 | 84 / 64 | 0.169 | 3.347 | 2 |
| C4 turning-foot | 5–9 | 242 / 225 | 0.164 | 1.146 | 0 |
| C4 turning-foot | 10–19 | 712 / 612 | 0.173 | 1.310 | 4 |
| C4 turning-foot | 20–29 | 840 / 638 | 0.182 | 1.262 | 8 |
| C4 turning-foot | 30–39 | 1,881 / 1,447 | 0.182 | 1.304 | 16 |
| C4 turning-foot | 40–50 | 3,492 / 2,984 | 0.188 | 1.213 | 19 |
| C4 straight | 0 | 51 / 0 | — | — | 0 |
| C4 straight | 1–4 | 88 / 68 | 0.078 | 1.734 | 1 |
| C4 straight | 5–9 | 283 / 219 | 0.076 | 1.520 | 2 |
| C4 straight | 10–19 | 817 / 649 | 0.092 | 1.403 | 4 |
| C4 straight | 20–29 | 1,258 / 906 | 0.101 | 1.308 | 6 |
| C4 straight | 30–39 | 2,378 / 1,861 | 0.103 | 1.422 | 25 |
| C4 straight | 40–50 | 2,397 / 2,021 | 0.106 | 1.266 | 12 |

The 1–4 bands for C4 lap and turning-foot show wider z spread than the
40–50 bands, but this sampled evidence does not choose an observed-n cutoff.
C3 has no 0 or 1–4 current observations in this cohort, so its low-n
behavior is not established here.

## J. Open choices before a formal feature freeze

1. Choose all-history or trailing-one-year venue × boat baseline using a
   separately frozen evaluation protocol. No choice was made here.
2. Choose a minimum observed-n policy, including what to emit for 0/1 valid
   historical observations and for histories shorter than 50 races.
3. Choose handling for zero/very small sample SD and extreme current values.
   This report provides counts and examples without picking a cutoff.
4. Define the production status schema and exact historical as-of evidence
   separately. `NOT_PROVIDED` is used only for venue/field combinations with
   confirmed structural absence; other source gaps remain `MISSING_OTHER`.

No Prediction dataset, model, probability, holdout metric, or DB schema was
changed. This checkpoint supports the next **method-freeze decision**, not
deployment.

## K. Git scope and reproduction

From `C:\Users\knkzh\Documents\boatrace-predictor`, run:

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -m scripts.research_pre_race_times_v1_continuation
```

The script requires the existing local diagnostic inputs
`.local/c4_mapping_readonly.json` and `.local/c4_carry_readonly.json` to
cross-check the known suspects; those files are not included in this commit.
It reads `pckyotei` and `boatrace_predictor` in read-only transactions,
recomputes C4 gates and eight date samples, asserts the known 79/11/373/24
counts, and writes the JSON metrics file. It does not query K3 or write to
either DB. The Git scope for this checkpoint is research code and reports
only; pre-existing unrelated untracked files are not staged.
