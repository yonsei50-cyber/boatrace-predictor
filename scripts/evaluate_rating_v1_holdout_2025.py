"""One-shot, read-only 2025 holdout of the committed Rating Method Freeze v1.

Run ``preflight`` before ``evaluate``. The gate records identities before any
2025 outcome scoring and prevents a second run after evaluation has started.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from scripts.compare_rating_methods import (
    ESTABLISHED, NEWCOMER_UNCERTAIN, EXTRACT_SQL as FROZEN_EXTRACT_SQL, QUERY_VERSION,
    RATING_SCALE, CourseSoftmax, MetricSet, PairwiseElo, Short50Model,
    _make_race, _row_for_hash,
)
from scripts.db import target_connection


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts/rating_method_freeze_v1.json"
COMPARISON = ROOT / "artifacts/rating_method_comparison_2023_2024_v2.json"
FROZEN_CODE = ROOT / "scripts/compare_rating_methods.py"
GATE = ROOT / "artifacts/rating_v1_holdout_2025_gate.json"
REPORT = ROOT / "artifacts/rating_v1_holdout_2025.json"
EXPECTED_FREEZE_SHA256 = "c7fbd2af725f2c9d62491923a5a411350a33076b8b1b305798c5ed07d23136fb"
EXPECTED_CHECKPOINT = "240044f92975fa6f6c426d899660ec134f2666dc"
HOLDOUT_START = date(2025, 1, 1)
HOLDOUT_END = date(2025, 12, 31)
DATASET_SQL = """SELECT dataset_name,canonical_content_hash,manifest_hash
FROM core.dataset_version
WHERE status='FROZEN_HISTORY_SHARD'
  AND dataset_name >= 'phase2.5-stored-history-v1-2017-01'
  AND dataset_name <= 'phase2.5-stored-history-v1-2025-12'
ORDER BY dataset_name"""
EXTRACT_SQL = r"""
WITH boats AS (
  SELECT r.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
         b.finish_state,b.finish_position,b.actual_course,s.result_state,
         (z.race_id IS NOT NULL) AS canonical_result
  FROM core.race r
  JOIN core.race_entry e USING(race_id)
  JOIN core.boat_finish_state b USING(race_id,boat_no)
  JOIN core.race_result_state s USING(race_id)
  LEFT JOIN core.race_result z USING(race_id,boat_no)
  WHERE r.race_date >= DATE '2017-01-01'
    AND r.race_date < DATE '2026-01-01'
), flags AS (
  SELECT race_id,
         count(*)=6
         AND bool_and(result_state='RESULT_RECORDS_PRESENT')
         AND bool_and(canonical_result)
         AND count(*) FILTER (WHERE finish_state='NUMERIC_VALID')=6
         AND count(DISTINCT finish_position)=6
         AND min(finish_position)=1 AND max(finish_position)=6 AS common_strict
  FROM boats GROUP BY race_id
)
SELECT b.race_id,b.race_date,b.venue_code,b.race_no,b.boat_no,b.player_id,
       b.finish_state,b.finish_position,b.actual_course,b.result_state,
       b.canonical_result,f.common_strict
FROM boats b JOIN flags f USING(race_id)
ORDER BY b.race_date,b.venue_code,b.race_no,b.race_id,b.boat_no
"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def checked_freeze():
    if EXTRACT_SQL != FROZEN_EXTRACT_SQL.replace("DATE '2025-01-01'", "DATE '2026-01-01'"):
        raise RuntimeError("BLOCKING: extraction changed beyond the 2025 date bound")
    if sha(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("BLOCKING: freeze file SHA-256 changed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if (freeze["status"] != "RATING_METHOD_FROZEN"
            or freeze["development_data_cutoff"] != "2024-12-31"
            or freeze["independent_holdout_2025"] != "SEALED_NOT_EVALUATED"):
        raise RuntimeError("BLOCKING: freeze status or cutoff changed")
    hashes = freeze["versions_and_hashes"]
    if (sha(FROZEN_CODE) != hashes["current_comparison_code_sha256"]
            or sha(COMPARISON) != hashes["comparison_artifact_sha256"]):
        raise RuntimeError("BLOCKING: frozen comparison code or artifact changed")
    if git_head() != EXPECTED_CHECKPOINT or hashes["rating_prep_checkpoint_commit"] != "2192d97cb7aab2f51f0d27f6bee6d412cd9e1983":
        raise RuntimeError("BLOCKING: unexpected Git checkpoint")
    if RATING_SCALE != freeze["parameters"]["rating_scale"]:
        raise RuntimeError("BLOCKING: rating scale differs")
    return freeze


def selected_models(freeze):
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    candidates = {c["candidate_id"]: c for c in comparison["candidates"]
                  if c["status"] == "SUPPORTED"}
    short = {c["candidate_id"]: c for c in comparison["short50"]["performance_candidates"]}
    a_id = freeze["rating_series"]["FIRST_COURSE_1_TO_6"]["candidate_id"]
    b_id = freeze["rating_series"]["OVERALL"]["candidate_id"]
    s_id = freeze["rating_series"]["SHORT_50"]["candidate_id"]
    if a_id != freeze["rating_series"]["EXACT_SECOND_COURSE_1_TO_6"]["candidate_id"]:
        raise RuntimeError("BLOCKING: A first/second candidates differ")
    a, b, s = candidates[a_id], candidates[b_id], short[s_id]
    if (a["config"] != {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT", "learning_rate": 16.0}
            or b["config"] != {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT", "k_factor": 120.0,
                               "pair_weight": "RACE_NORMALIZED", "link": "EXP_SOFTMAX_SCALE_400"}
            or s["config"] != {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT",
                               "basis": "VALID_RESULT", "fallback": "AVAILABLE_HISTORY"}
            or freeze["parameters"]["short_window_size"] != 50
            or freeze["parameters"]["A_course_prior_pseudocount_each"] != 1
            or freeze["parameters"]["decay"] != "none beyond the SHORT_50 window"):
        raise RuntimeError("BLOCKING: selected method, parameters or eligibility differ")
    return (CourseSoftmax(a_id, a["config"]),
            PairwiseElo(b_id, b["config"]),
            Short50Model(s_id, s["config"]))


def dataset_identity(conn, freeze):
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(),current_setting('transaction_read_only'),pg_current_snapshot()::text")
        database, readonly, snapshot = cur.fetchone()
        if database != "boatrace_predictor" or readonly != "on":
            raise RuntimeError("BLOCKING: expected read-only target snapshot")
        cur.execute(DATASET_SQL)
        rows = cur.fetchall()
    if len(rows) != 108 or rows[0][0] != "phase2.5-stored-history-v1-2017-01" or rows[-1][0] != "phase2.5-stored-history-v1-2025-12":
        raise RuntimeError("BLOCKING: expected 108 frozen monthly shards")
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    development_hash = digest(rows[:96])
    if development_hash != freeze["versions_and_hashes"]["historical_dataset_shard_chain_sha256"]:
        raise RuntimeError("BLOCKING: development dataset hash changed")
    return {"database": database, "read_only": readonly, "isolation": "REPEATABLE READ",
            "snapshot": snapshot, "shards": len(rows),
            "development_shard_chain_sha256": development_hash,
            "full_shard_chain_sha256": digest(rows)}


def open_snapshot():
    conn = target_connection()
    conn.commit()
    conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='0'")
    return conn


def identities(freeze):
    return {"freeze_sha256": sha(FREEZE), "frozen_code_sha256": sha(FROZEN_CODE),
            "holdout_code_sha256": sha(Path(__file__)), "comparison_artifact_sha256": sha(COMPARISON),
            "git_head": git_head(), "development_cutoff": freeze["development_data_cutoff"],
            "holdout_period": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "methods": {key: value["candidate_id"] for key, value in freeze["rating_series"].items()},
            "parameters": freeze["parameters"], "eligibility": freeze["eligibility"]["selected"]}


def preflight():
    if GATE.exists() or REPORT.exists():
        raise RuntimeError("BLOCKING: holdout gate or result already exists")
    freeze = checked_freeze()
    selected_models(freeze)
    conn = open_snapshot()
    try:
        dataset = dataset_identity(conn, freeze)
    finally:
        conn.rollback()
        conn.close()
    gate = {"status": "READY", "preflight_utc": utc_now(),
            "identity": identities(freeze), "dataset": dataset}
    save_json(GATE, gate)
    print(json.dumps({"gate": str(GATE), "status": "READY", "dataset_hash": dataset["full_shard_chain_sha256"]}))


def with_calibration_error(metric):
    value = metric.json()
    if not value["races"]:
        return value
    for target in ("first", "exact_second"):
        bins = value[target]["calibration"]
        n = sum(row["observations"] for row in bins)
        value[target]["calibration_ece_10bin"] = sum(
            row["observations"] * abs(row["mean_probability"] - row["event_rate"])
            for row in bins if row["observations"]) / n
    return value


class BinaryMetric:
    """Post-result course stratum; actual_course never enters prediction."""
    def __init__(self):
        self.n = self.positives = 0
        self.loss = self.brier = 0.0
        self.bins = [[0, 0.0, 0] for _ in range(10)]

    def add(self, probability, event):
        import math
        self.n += 1
        self.positives += event
        self.loss -= math.log(max(probability if event else 1 - probability, 1e-15))
        self.brier += (probability - event) ** 2
        bucket = self.bins[min(9, int(probability * 10))]
        bucket[0] += 1
        bucket[1] += probability
        bucket[2] += event

    def json(self):
        if not self.n:
            return {"boats": 0}
        bins = [{"lower": i / 10, "upper": (i + 1) / 10,
                 "observations": row[0], "mean_probability": row[1] / row[0] if row[0] else None,
                 "event_rate": row[2] / row[0] if row[0] else None}
                for i, row in enumerate(self.bins)]
        return {"boats": self.n, "events": self.positives, "binary_log_loss": self.loss / self.n,
                "binary_brier": self.brier / self.n, "calibration": bins,
                "calibration_ece_10bin": sum(row[0] * abs(row[1] / row[0] - row[2] / row[0])
                                                 for row in self.bins if row[0]) / self.n}


def model_state(models):
    a, b, s = models
    return (tuple(dict(series) for series in a.first), tuple(dict(series) for series in a.second),
            dict(b.ratings), {player: tuple(s.history.get(player, ())) for player in s.known_players})


def evaluate():
    if not GATE.exists() or REPORT.exists():
        raise RuntimeError("BLOCKING: READY gate required and result must not exist")
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    if gate["status"] != "READY":
        raise RuntimeError("BLOCKING: holdout execution already started")
    freeze = checked_freeze()
    models = selected_models(freeze)
    if identities(freeze) != gate["identity"]:
        raise RuntimeError("BLOCKING: preflight identity changed")
    conn = open_snapshot()
    try:
        dataset = dataset_identity(conn, freeze)
        if dataset["full_shard_chain_sha256"] != gate["dataset"]["full_shard_chain_sha256"]:
            raise RuntimeError("BLOCKING: dataset changed after preflight")
        gate["status"] = "STARTED"
        gate["evaluation_started_utc"] = utc_now()
        gate["evaluation_snapshot"] = dataset["snapshot"]
        save_json(GATE, gate)

        metrics = {name: {"annual": MetricSet(), "quarters": {f"Q{q}": MetricSet() for q in range(1, 5)}}
                   for name in ("course", "overall", "short50")}
        course = {target: {str(c): BinaryMetric() for c in range(1, 7)}
                  for target in ("first", "exact_second")}
        counts, depth, newcomer = Counter(), Counter(), Counter()
        players_2025, depth_players = set(), defaultdict(set)
        seen_players = set()
        prior_update_day = None
        checked_historical_extract = False
        historical_digest = hashlib.sha256()
        historical_digest.update((QUERY_VERSION + "\n").encode())
        holdout_digest = hashlib.sha256()
        holdout_digest.update(b"rating-v1-holdout-2025-v1\n")
        historical_rows = holdout_rows = 0
        current_race_rows, day_races, current_day = [], [], None

        def process_day(day, races):
            nonlocal prior_update_day
            if day is None:
                return
            if prior_update_day is not None and not prior_update_day < day:
                raise RuntimeError("BLOCKING: D-1 ordering violated")
            roster = {entry.player_id for race in races for entry in race.entries}
            statuses = {player: ESTABLISHED if player in seen_players else NEWCOMER_UNCERTAIN
                        for player in roster}
            if day < HOLDOUT_START:
                for model in models:
                    model.process_day(day, races, statuses, collect_validation=False)
            else:
                if day > HOLDOUT_END:
                    raise RuntimeError("BLOCKING: holdout boundary crossed")
                for model in models:
                    model.prepare_day(roster, statuses)
                before = model_state(models)
                newcomer.update(statuses.values())
                counts["newcomer_confirmed"] += 0  # No as-of evidence establishes a confirmed newcomer.
                for race in races:
                    counts["total_races"] += 1
                    counts["total_boats"] += len(race.entries)
                    if not race.common_strict:
                        counts["excluded_races"] += 1
                        counts["excluded_boats"] += len(race.entries)
                        reason = ("RESULT_RECORDS_NOT_PRESENT" if race.result_state != "RESULT_RECORDS_PRESENT"
                                  else "NONSTRICT_RESULT_OR_INCOMPLETE")
                        counts[f"exclusion_{reason}"] += 1
                        continue
                    if len(race.entries) != 6 or sorted(e.finish for e in race.entries) != [1, 2, 3, 4, 5, 6]:
                        raise RuntimeError("BLOCKING: STRICT scoring race has invalid finish order")
                    if (not all(e.actual_course in range(1, 7) for e in race.entries)
                            or sorted(e.actual_course for e in race.entries) != [1, 2, 3, 4, 5, 6]):
                        raise RuntimeError("BLOCKING: 2025 STRICT course permutation invalid")
                    counts["eligible_races"] += 1
                    counts["eligible_boats"] += 6
                    quarter = f"Q{(day.month - 1) // 3 + 1}"
                    predictions = [model.predict(race) for model in models]
                    for name, (first, second) in zip(metrics, predictions):
                        if (abs(sum(first) - 1) > 1e-10 or abs(sum(second) - 1) > 1e-10
                                or any(not 0 <= p <= 1 for p in first + second)):
                            raise RuntimeError("BLOCKING: invalid probability distribution")
                        metrics[name]["annual"].add(first, second, race.entries)
                        metrics[name]["quarters"][quarter].add(first, second, race.entries)
                    for i, entry in enumerate(race.entries):
                        players_2025.add(entry.player_id)
                        n = len(models[2].history[entry.player_id])
                        category = "50" if n == 50 else "1_to_49" if n else "0"
                        depth[category] += 1
                        depth_players[category].add(entry.player_id)
                        counts["rating_covered_boats"] += all(
                            entry.player_id in series for series in models[0].first + models[0].second)
                        counts["overall_covered_boats"] += entry.player_id in models[1].ratings
                        counts["short_covered_boats"] += entry.player_id in models[2].known_players
                        c = str(entry.actual_course)
                        course["first"][c].add(predictions[0][0][i], entry.finish == 1)
                        course["exact_second"][c].add(predictions[0][1][i], entry.finish == 2)
                pending_a = [models[0].deltas(race) for race in races if models[0].update_eligible(race)]
                pending_b = [models[1].deltas(race) for race in races if models[1].update_eligible(race)]
                if model_state(models) != before:
                    raise RuntimeError("BLOCKING: rating state changed during same-day scoring")
                if pending_a:
                    models[0].apply(models[0].combine_day(pending_a))
                if pending_b:
                    models[1].apply(models[1].combine_day(pending_b))
                for model in models:
                    model.after_day(races)
                counts["course_update_races"] += len(pending_a)
                counts["overall_update_races"] += len(pending_b)
            seen_players.update(roster)
            prior_update_day = day

        with conn.cursor(name="rating_v1_holdout_extract") as cur:
            cur.itersize = 20000
            cur.execute(EXTRACT_SQL)
            for row in cur:
                row_bytes = json.dumps(_row_for_hash(row), ensure_ascii=False,
                                       separators=(",", ":"), default=str).encode("utf-8") + b"\n"
                if row[1] < HOLDOUT_START:
                    historical_digest.update(row_bytes)
                    historical_rows += 1
                else:
                    if not checked_historical_extract:
                        if (historical_rows != freeze["versions_and_hashes"]["comparison_extract_ordered_rows"]
                                or historical_digest.hexdigest() != freeze["versions_and_hashes"]["comparison_extract_sha256"]):
                            raise RuntimeError("BLOCKING: 2017-2024 result extract changed")
                        checked_historical_extract = True
                    holdout_digest.update(row_bytes)
                    holdout_rows += 1
                if current_race_rows and row[0] != current_race_rows[0][0]:
                    race = _make_race(current_race_rows)
                    if current_day is not None and race.day != current_day:
                        process_day(current_day, day_races)
                        day_races = []
                    current_day = race.day
                    day_races.append(race)
                    current_race_rows = []
                current_race_rows.append(row)
            if current_race_rows:
                race = _make_race(current_race_rows)
                if current_day is not None and race.day != current_day:
                    process_day(current_day, day_races)
                    day_races = []
                current_day = race.day
                day_races.append(race)
            process_day(current_day, day_races)
        if not checked_historical_extract or not counts["eligible_races"]:
            raise RuntimeError("BLOCKING: missing historical identity or holdout scoring rows")
        if counts["total_races"] != counts["eligible_races"] + counts["excluded_races"]:
            raise RuntimeError("BLOCKING: eligibility races do not reconcile")
        if counts["total_boats"] != counts["eligible_boats"] + counts["excluded_boats"]:
            raise RuntimeError("BLOCKING: eligibility boats do not reconcile")
        if any(counts[key] != counts["eligible_boats"] for key in
               ("rating_covered_boats", "overall_covered_boats", "short_covered_boats")):
            raise RuntimeError("BLOCKING: a selected rating does not cover a scored boat")
        if (sha(FREEZE) != gate["identity"]["freeze_sha256"]
                or sha(FROZEN_CODE) != gate["identity"]["frozen_code_sha256"]
                or sha(COMPARISON) != gate["identity"]["comparison_artifact_sha256"]
                or sha(Path(__file__)) != gate["identity"]["holdout_code_sha256"]):
            raise RuntimeError("BLOCKING: frozen file or evaluation code changed during run")
        comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
        reference_candidates = {c["candidate_id"]: c for c in comparison["candidates"]
                                if c["status"] == "SUPPORTED"}
        reference_short = {c["candidate_id"]: c for c in comparison["short50"]["performance_candidates"]}
        references = {}
        for name, model in zip(metrics, models):
            candidate = (reference_short if name == "short50" else reference_candidates)[model.candidate_id]
            references[name] = {"2023_internal_q2_q4": candidate["selection_2023_q2_q4_prequential"],
                                "2024_out_of_time_development": candidate["validation_2024"]}
        annual = {name: with_calibration_error(group["annual"]) for name, group in metrics.items()}
        quarters = {name: {q: with_calibration_error(value) for q, value in group["quarters"].items()}
                    for name, group in metrics.items()}
        result = {
            "status": "RATING_V1_HOLDOUT_EVALUATED_NO_PREDECLARED_PASS_THRESHOLD",
            "integrity": {**gate["identity"], "dataset": dataset,
                          "preflight_utc": gate["preflight_utc"],
                          "evaluation_started_utc": gate["evaluation_started_utc"],
                          "evaluation_finished_utc": utc_now(),
                          "historical_extract_rows": historical_rows,
                          "historical_extract_sha256": historical_digest.hexdigest(),
                          "holdout_extract_rows": holdout_rows,
                          "holdout_extract_sha256": holdout_digest.hexdigest()},
            "eligibility": {**dict(sorted(counts.items())), "unique_scored_players": len(players_2025),
                            "newcomer_day_roster_status_counts": dict(newcomer)},
            "metrics": annual, "quarterly_metrics": quarters,
            "course_metrics": {target: {c: metric.json() for c, metric in value.items()}
                               for target, value in course.items()},
            "short50_history_depth": {"scored_boats": dict(depth),
                                      "unique_players_by_depth": {key: len(value) for key, value in depth_players.items()},
                                      "players_reaching_50": len(depth_players["50"])},
            "short50_minus_overall_combined_log_loss": (annual["short50"]["combined_log_loss"]
                                                         - annual["overall"]["combined_log_loss"]),
            "development_comparison": references,
            "leakage_audit": {"ordered_days": True, "max_result_update_date_before_scoring_day": True,
                              "same_day_rating_state_unchanged_until_all_predictions_and_deltas": True,
                              "current_actual_course_only_used_for_post_result_update_and_posthoc_diagnostic": True,
                              "historical_extract_matches_freeze": True,
                              "frozen_files_unchanged_through_run": True},
            "limitations": freeze["limitations"],
        }
        save_json(REPORT, result)
        gate["status"] = "COMPLETED"
        gate["evaluation_finished_utc"] = result["integrity"]["evaluation_finished_utc"]
        save_json(GATE, gate)
        print(json.dumps({"report": str(REPORT), "status": result["status"],
                          "eligible_races": counts["eligible_races"],
                          "course_combined_log_loss": annual["course"]["combined_log_loss"]}))
    finally:
        conn.rollback()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "evaluate"))
    action = parser.parse_args().action
    if action == "preflight":
        preflight()
    else:
        evaluate()


if __name__ == "__main__":
    main()
