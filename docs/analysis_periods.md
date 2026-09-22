# Period policy — user revision, 2026-09-22

Phase 2.5 "full history" means **2017-01-01 through each source's observed latest
date**, not all history stored by the source. Source inventories, Raw/Canonical
migration, completeness, conflicts, and reproducibility certification use that
scope. Missing pre-2017 history is not a Phase 2.5 blocker.

Pre-2017 records may only support necessary boundaries/identity for 2017+
observations. The importer selects at most one latest eligible pre-2017 KI per
player when that observation is required by the player's earliest 2017+ race
year. It does not import complete pre-2017 KI history. Motor generation in early
2017 can be named 2016 under the existing fixed month/day rule; this does not
require importing races from 2016.

Before this revision, a source-wide Raw import had already started. Those
immutable observations remain preserved, are excluded from the current
Canonical import and quality certification, and are not a reason to complete
pre-2017 history. No pre-2017 canonical dataset is created.

## Future analysis windows (not implemented in Phase 2.5)

| Analysis | Development / optimization | Independent test |
|---|---|---|
| Wind, waves, weather and environment | 2017-01-01–2024-12-31 | 2025-01-01–2025-12-31 |
| Rating | 2023-01-01–2024-12-31 | 2025-01-01–2025-12-31 |
| Pre-race timing | Available records through 2024-12-31; start window deferred | 2025-01-01–2025-12-31 |

Methods and parameters must be developed before the independent 2025 test.
After inspecting 2025 outcomes, retuning earlier development and calling the
same 2025 observations an independent test again is prohibited.

In 2026, use the method selected through 2025 as the initial method and
reevaluate/re-tune every seven days from 2026-01-01. The 2026-01-01 update may
use data available through 2025-12-31; 2026-01-08 through 2026-01-07;
2026-01-15 through 2026-01-14, and so on. This is an update cadence, **not a
seven-day training window**. Candidate methods, windows, and parameters may
use eligible earlier history, with decisions and temporal availability recorded.

For every business day D, result-based prediction inputs are limited to D-1.
The update cadence never relaxes this boundary. Retrospective source year/race
date and today's extraction timestamp do not prove historical publication or
availability. Phase 2.5 creates no ratings, features, predictions, trifecta
probabilities, odds/value logic, or betting implementation.
