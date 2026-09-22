# Boatrace Project Instructions

## Objective

Build a new boat-race prediction system from first principles.

The system will:

- estimate racer strength from historical race results;
- measure venue × course effects;
- measure venue × course × wind effects;
- measure venue × course × wave effects;
- measure the effect of pre-race timing information;
- combine racer strength and external conditions into calibrated
  first-place and second-place probabilities;
- compare pre-race probabilities with market odds separately;
- update ratings only after race results become available.

Prediction accuracy, reproducibility, and prevention of time leakage
take priority over architectural complexity.

---

## Core principles

### 1. Time leakage is a blocking error

Every historical prediction must reproduce what was actually knowable
at the prediction timestamp.

For race R at time T:

- training data must precede T;
- ratings must use only races completed before T;
- weather and water conditions must be values available before T;
- exhibition and pre-race timing information must use only information
  published before the prediction;
- odds must use the actual snapshot available at the decision timestamp;
- race results must never influence features for the same race.

If temporal availability is uncertain, treat the feature as unavailable
until verified.

Do not use random train/test splits for final model evaluation.

Prefer chronological / walk-forward validation.

---

## Primary analytical unit

Venue × course is the primary unit for course-specific analysis.

Do not rely on nationwide aggregate effects when the relationship may
differ materially by venue or course.

National data may be used for priors, shrinkage, fallback estimates,
or exploratory analysis.

---

## Racer ratings

Ratings must represent information available before each race.

A race result may update ratings only after that race has finished.

Store enough information to reproduce the exact rating state used for
every historical prediction.

Do not choose a rating formula by intuition alone.

Compare candidate rating methods using out-of-sample predictive
performance.

---

## External-condition analysis

Treat these as empirical questions rather than fixed assumptions:

- wind speed;
- wind direction;
- wave height;
- weather;
- venue;
- course;
- interactions among them.

Do not assume that stronger wind or higher waves have the same effect
at every venue or every course.

Prefer statistically supported interactions and regularization over
large collections of manually invented rules.

---

## Pre-race timing information

Evaluate independently and jointly:

- exhibition time;
- lap time;
- turning-foot time;
- straight-line time.

Measure incremental predictive value against a baseline model.

Do not assume that a timing variable is useful merely because its raw
correlation is strong.

Test whether it improves true out-of-sample prediction.

---

## Prediction probabilities

The model must produce calibrated probabilities, not only rankings.

At race level:

- first-place probabilities must form a coherent probability
  distribution;
- second-place probabilities must form a coherent probability
  distribution.

Evaluate at minimum:

- log loss;
- Brier score;
- calibration;
- discrimination / ranking quality.

Model selection must use out-of-sample results.

Do not select models from training-set performance.

---

## Odds separation

Keep racing-performance prediction and market-price evaluation separate.

The primary probability model should not use betting odds as an input.

First estimate race probabilities from racing information.

Then compare those probabilities with the odds snapshot available at
the decision timestamp.

If a future market-aware model is investigated, treat it as a separate
model and benchmark it independently.

---

## Betting evaluation

Do not judge a prediction model only by short-term profit.

Separate:

1. probability quality;
2. calibration;
3. odds/value detection;
4. bet-selection rules;
5. realized betting results.

Backtests must use only odds that would actually have been available
at the simulated decision time.

Keep prediction records even when no bet is placed.

---

## Data architecture

Preserve source observations before transformation.

Prefer clear separation between:

raw source data
→ normalized data
→ derived features
→ ratings
→ model inputs
→ predictions
→ odds snapshots
→ bet decisions
→ race results
→ evaluation

Do not silently overwrite historical source observations.

Missing values are missing values unless a documented rule explicitly
defines an imputation.

Record provenance for derived data where practical.

---

## Legacy assets

This is a new implementation.

Do not restore the old Boatrace architecture merely because old
artifacts exist.

Legacy dumps, CSV files, and definition documents may be reused as
data or reference material after their contents are verified.

Do not depend on unidentified legacy schemas, materialized views,
security artifacts, orchestration infrastructure, or historical code
without explicit justification.

Prefer the simplest new design that satisfies the current objective.

---

## Computation

Use SQL, Python, statistical libraries, and existing scripts for:

- aggregation;
- feature generation;
- rating calculation;
- model fitting;
- hyperparameter search;
- walk-forward evaluation;
- calibration;
- backtesting;
- large comparisons.

Do not manually calculate large statistical results in the agent
context.

Codex should primarily:

- design;
- inspect;
- implement;
- invoke computation;
- validate;
- diagnose;
- interpret results.

All substantial analytical results should be reproducible by code.

---

## Model-development discipline

Start with simple baselines before complex models.

A more complex model is accepted only when it provides reproducible
out-of-sample improvement.

Preserve frozen evaluation periods when practical.

Avoid repeatedly tuning against the same test period.

Record:

- dataset version;
- feature definition;
- training window;
- evaluation window;
- model configuration;
- calibration method;
- metrics.

Prefer reproducibility over one-off improvements.

---

## Implementation style

Prefer small, testable modules.

Avoid architecture for hypothetical future requirements.

Do not add frameworks, services, abstractions, databases, agents,
or dependencies unless they solve a current requirement.

Reuse stable Python, PostgreSQL, and standard statistical tooling
before introducing custom infrastructure.

When showing Python execution commands on Windows, use the full path
to the project Python executable when it is known.

---

## Verification

Verification effort should match the change.

For simple changes:
run the narrow relevant test.

For analytical or model changes:
validate calculations using code and representative real data.

For changes affecting historical simulation:
explicitly test time ordering and leakage.

For changes affecting probability output:
test probability bounds, normalization, calibration inputs, and
determinism where applicable.

Do not create large audit/evidence systems solely to prove that routine
work was performed.

---

## Credit efficiency

Default to Astra Low.

Do not increase reasoning effort merely because the dataset is large.

Delegate computation to Python, SQL, or statistical libraries.

Keep simple tasks single-agent.

Use subagents only when independent parallel work materially reduces
time or improves correctness.

Do not spawn agents merely to repeat work already performed by the
primary agent.

Escalate reasoning effort only when the task genuinely requires deeper
reasoning, such as:

- statistical model design with unresolved tradeoffs;
- difficult leakage analysis;
- major architecture decisions;
- ambiguous model-performance diagnosis;
- complex correctness failures.

Return to Low after the difficult task is resolved.

---

## Decision rule

When multiple technically valid approaches exist:

1. prefer the simplest reproducible approach;
2. prefer the approach with stronger out-of-sample evidence;
3. prefer deterministic computation over agent reasoning;
4. prefer lower operational and credit cost when accuracy is comparable.

If evidence is insufficient, state that it is insufficient rather than
inventing certainty.