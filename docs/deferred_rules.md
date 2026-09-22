# Frozen user rules, not implemented in Phase 2

These are user-defined rules, not claims about observed official sanctions or
empirically optimal rating design. No derived-state or rating tables/functions
are added in this phase.

## F-suspension state

- A verified F race result sets internal unserved state TRUE.
- May1 / November1 term changes do not reset this internal state.
- Source displayed term F/L counts may reset at those boundaries and remain
  separate from internal suspension state.
- A verified interval between consecutive appearances of **at least30 days**
  clears the internal state. Both endpoint appearances and adequate history
  coverage are required; elapsed wall-clock time alone is not evidence.
- F2 or more is cleared together by one qualifying interval.
- Apparent gaps caused by missing history do not clear the state.
- No computed state exists in Phase2; no default FALSE is emitted.

Future acceptance scenarios (specification, not Phase2 test results):

| Input | Required outcome |
|---|---|
| Confirmed F, then May1 / November1 without qualifying gap | TRUE remains |
| Confirmed consecutive appearances29 days apart | No clearing |
| Confirmed consecutive appearances30 days apart with complete coverage | Cleared |
| F2 followed by verified30-day interval | Both cleared together |
| Visible30-day gap but incomplete source history | Not a clearing basis |
| No observed F but unknown earlier career/history | UNKNOWN, not inferred FALSE |
| Cleared at a return appearance, new F in that race | TRUE after new result |

Future daily processing must use only D-1 results, not D's return appearance or
F result, for D's state.

## Rookie debut and initialization

- Training class139 has debut month2026-11.
- Each class earlier moves back6 months; term boundaries are May1/November1.
- A rookie debut race means the player's **confirmed career-first appearance
  within one year after/on the cohort's debut month**.
- Adequate career coverage is necessary. The first record visible because a
  dataset begins is not proof of career debut.
- All14 rating series initialize to that series' mean over all existing valid
  rated players, multiplied by0.8.
- Same-day debuting rookies are excluded from the mean population; all use the
  same pre-initialization mean. Processing order must not affect initialization.
- Save cohort raw/normalized identity, coverage evidence, debut date rule,
  population membership/count, mean, multiplier, cutoff, and version when this
  calculation is later implemented. No rating values are created here.

Future specification cases: class138→2026-05; class137→2025-11; a first visible
race with inadequate earlier coverage→not a confirmed debut; same-day rookies
receive identical per-series initial values when the base mean is identical.
The exact day-level end boundary for the phrase “within one year” must be
made explicit before implementing it; this document preserves the user's
month-based rule without inventing a tested day-level convention.

## Other deferred features

race_environment, race_preinfo, parts, full player_term, F derived state,
entry-course index, all ratings, predictions, trifecta probabilities,
odds/value/betting, and full-period migration are absent. The current keys
support adding these later without using legacy race IDs as canonical PKs.
