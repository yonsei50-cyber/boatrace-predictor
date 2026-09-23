"""One-shot read-only 2025 independent holdout for Entry Course Index v1.

Run ``preflight`` first. It verifies the frozen 2017-2024 extract and records
dataset/code identities without returning 2025 outcome rows. ``evaluate``
marks the gate STARTED before its first 2025 extraction and never retries.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess

from scripts.db import target_connection
from scripts.entry_course_index_v1 import (
    COURSES, EDOGAWA_VENUE_CODE, NOT_EVALUABLE, CourseEntry, CourseRace,
    eligible, probabilities_from_counts, window_start,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts/entry_course_index_method_freeze_v1.json"
REFERENCE = ROOT / "scripts/entry_course_index_v1.py"
GATE = ROOT / "artifacts/entry_course_index_v1_holdout_2025_gate.json"
RESULT = ROOT / "artifacts/entry_course_index_v1_holdout_2025.json"
EXPECTED_HEAD = "f8a4d4d0d2bff962489d7c492f391951a1eccc6d"
EXPECTED_FREEZE_SHA256 = "00233686ff49bca92e09645eb9177aecddd83d141f1a9478a5e6365a89374453"
HOLDOUT_START = date(2025, 1, 1)
HOLDOUT_STOP = date(2026, 1, 1)

# Exactly the development SQL bytes. The frozen artifact contains its SHA-256.
DEVELOPMENT_SQL = """
SELECT r.race_date,r.venue_code,r.race_id,e.boat_no,z.actual_course,
       z.finish_position,z.result_status,z.normalization_status,s.result_state
FROM core.race r
LEFT JOIN core.race_entry e USING (race_id)
LEFT JOIN core.race_result z ON z.race_id=e.race_id AND z.boat_no=e.boat_no
LEFT JOIN core.race_result_state s ON s.race_id=r.race_id
WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2025-01-01'
ORDER BY r.race_date,r.race_id,e.boat_no
"""
HOLDOUT_SQL = DEVELOPMENT_SQL.replace(
    "WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2025-01-01'",
    "WHERE r.race_date >= DATE '2024-01-01' AND r.race_date < DATE '2026-01-01'",
)
DATASET_SQL = """SELECT dataset_name,canonical_content_hash,manifest_hash
FROM core.dataset_version
WHERE status='FROZEN_HISTORY_SHARD'
  AND dataset_name >= 'phase2.5-stored-history-v1-2017-01'
  AND dataset_name <= 'phase2.5-stored-history-v1-2025-12'
ORDER BY dataset_name"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_sha_lf() -> str:
    source = REFERENCE.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def checked_freeze() -> dict:
    if git_head() != EXPECTED_HEAD or sha(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("BLOCKING: freeze checkpoint or artifact bytes changed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if reference_sha_lf() != freeze["hashes"]["reference_code_sha256_lf"]:
        raise RuntimeError("BLOCKING: frozen reference implementation changed")
    if hashlib.sha256(DEVELOPMENT_SQL.encode()).hexdigest() != freeze["hashes"]["development_extract_sql_sha256"]:
        raise RuntimeError("BLOCKING: development extraction SQL differs")
    if HOLDOUT_SQL == DEVELOPMENT_SQL or "DATE '2026-01-01'" not in HOLDOUT_SQL:
        raise RuntimeError("BLOCKING: holdout extraction bounds invalid")
    if (freeze["freeze_id"] != "ENTRY_COURSE_INDEX_METHOD_FREEZE_V1"
            or freeze["status"] != "METHOD_FROZEN"
            or freeze["method"]["selected_candidate_id"] != "RECENT_1Y"
            or freeze["method"]["smoothing"] != "NONE"
            or freeze["dataset"]["development_end_inclusive"] != "2024-12-31"
            or freeze["window"]["start_inclusive"] != "previous calendar year's same month and day; Feb 29 maps to Feb 28"
            or freeze["window"]["end_exclusive"] != "prediction date D"
            or freeze["zero_history"]["status"] != NOT_EVALUABLE
            or freeze["zero_history"]["fallback"] != "NONE"
            or freeze["edogawa"]["venue_code"] != EDOGAWA_VENUE_CODE
            or freeze["edogawa"]["national_training"] != "EXCLUDED"
            or freeze["holdout_2025"]["status"] != "SEALED_NOT_EVALUATED"):
        raise RuntimeError("BLOCKING: frozen method specification differs")
    return freeze


def identity(freeze: dict) -> dict:
    return {
        "git_head": git_head(), "freeze_sha256": sha(FREEZE),
        "reference_sha256_lf": reference_sha_lf(), "evaluator_sha256": sha(Path(__file__)),
        "development_sql_sha256": hashlib.sha256(DEVELOPMENT_SQL.encode()).hexdigest(),
        "holdout_sql_sha256": hashlib.sha256(HOLDOUT_SQL.encode()).hexdigest(),
        "selected_method": freeze["method"]["selected_candidate_id"],
        "holdout_period": [HOLDOUT_START.isoformat(), "2025-12-31"],
    }


def open_snapshot():
    conn = target_connection()
    conn.rollback()
    conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='0'")
    return conn


def dataset_identity(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(),current_setting('transaction_read_only'),pg_current_snapshot()::text")
        database, readonly, snapshot = cur.fetchone()
        if database != "boatrace_predictor" or readonly != "on":
            raise RuntimeError("BLOCKING: target database is not the read-only snapshot")
        cur.execute(DATASET_SQL)
        rows = cur.fetchall()
    if (len(rows) != 108 or rows[0][0] != "phase2.5-stored-history-v1-2017-01"
            or rows[-1][0] != "phase2.5-stored-history-v1-2025-12"):
        raise RuntimeError("BLOCKING: expected 108 frozen 2017-2025 monthly dataset shards")
    def digest(values):
        payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "database": database, "read_only": readonly, "isolation": "REPEATABLE READ",
        "snapshot": snapshot, "shards": len(rows),
        "development_shard_chain_sha256": digest(rows[:96]),
        "full_shard_chain_sha256": digest(rows),
        "dataset_sql_sha256": hashlib.sha256(DATASET_SQL.encode()).hexdigest(),
    }


def row_bytes(row) -> bytes:
    return (json.dumps([row[0].isoformat(), *row[1:]], ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def verify_development_extract(conn, freeze: dict) -> dict:
    """Read only rows dated before 2025 and match the frozen development hash."""
    digest = hashlib.sha256()
    count = 0
    with conn.cursor(name="entry_course_preflight_development") as cur:
        cur.itersize = 10000
        cur.execute(DEVELOPMENT_SQL)
        for row in cur:
            if not date(2017, 1, 1) <= row[0] < HOLDOUT_START:
                raise RuntimeError("BLOCKING: development extract crossed the holdout boundary")
            digest.update(row_bytes(row))
            count += 1
    if count != 2671344 or digest.hexdigest() != freeze["hashes"]["development_extracted_rows_sha256"]:
        raise RuntimeError("BLOCKING: current 2017-2024 extraction differs from frozen development")
    return {"rows": count, "sha256": digest.hexdigest()}


def preflight() -> dict:
    if GATE.exists() or RESULT.exists():
        raise RuntimeError("BLOCKING: existing holdout gate or result; one-shot preflight denied")
    freeze = checked_freeze()
    started = utc_now()
    conn = open_snapshot()
    try:
        dataset = dataset_identity(conn)
        historical = verify_development_extract(conn, freeze)
    finally:
        conn.rollback()
        conn.close()
    gate = {
        "status": "READY", "preflight_started_utc": started,
        "preflight_completed_utc": utc_now(), "identity": identity(freeze),
        "dataset": dataset, "development_extract": historical,
        "2025_outcome_rows_read_before_gate": 0,
    }
    if GATE.exists() or RESULT.exists():
        raise RuntimeError("BLOCKING: holdout artifact appeared during preflight")
    save_json(GATE, gate)
    return gate


def mark_started(gate_path: Path, result_path: Path, expected_identity: dict,
                 expected_dataset_hash: str, snapshot: str) -> dict:
    """Reserve the one real execution before reading any 2025 outcome row."""
    if not gate_path.exists() or result_path.exists():
        raise RuntimeError("BLOCKING: unique READY gate and absent result required")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if (gate["status"] != "READY" or gate["identity"] != expected_identity
            or gate["dataset"]["full_shard_chain_sha256"] != expected_dataset_hash):
        raise RuntimeError("BLOCKING: gate already consumed or identity changed")
    gate["status"] = "STARTED"
    gate["evaluation_started_utc"] = utc_now()
    gate["evaluation_snapshot"] = snapshot
    save_json(gate_path, gate)
    return gate


class Metrics:
    def __init__(self):
        self.entries = self.log_sum = self.brier_sum = self.hits = self.zero_events = 0
        self.top_bins = [[0, 0.0, 0] for _ in range(10)]

    def add(self, probabilities: tuple[float, ...], actual_course: int) -> bool:
        if (len(probabilities) != 6 or any(not math.isfinite(p) or not 0 <= p <= 1
                                            for p in probabilities)
                or abs(sum(probabilities) - 1) >= 1e-12):
            raise RuntimeError("BLOCKING: invalid frozen probability distribution")
        actual = actual_course - 1
        p_actual = probabilities[actual]
        self.entries += 1
        if p_actual == 0:
            self.zero_events += 1
        else:
            self.log_sum -= math.log(p_actual)
        self.brier_sum += 1 - 2 * p_actual + sum(p * p for p in probabilities)
        top = max(range(6), key=probabilities.__getitem__)
        self.hits += top == actual
        bucket = self.top_bins[min(9, int(probabilities[top] * 10))]
        bucket[0] += 1
        bucket[1] += probabilities[top]
        bucket[2] += top == actual
        return p_actual == 0

    def result(self) -> dict:
        n = self.entries
        return {
            "evaluated_entries": n,
            "log_loss": self.log_sum / n if n and not self.zero_events else None,
            "log_loss_status": ("FINITE" if n and not self.zero_events else
                                "INFINITE_ZERO_PROBABILITY" if self.zero_events else "NOT_EVALUABLE"),
            "zero_probability_actuals": self.zero_events,
            "multiclass_brier_sum": self.brier_sum / n if n else None,
            "top1_accuracy": self.hits / n if n else None,
            "top1_ece_10bin": (sum(abs(row[1] - row[2]) for row in self.top_bins) / n
                               if n else None),
        }


def make_race(rows) -> tuple[int, CourseRace]:
    first = rows[0]
    if any(row[2] != first[2] or row[0] != first[0] or row[1] != first[1] for row in rows):
        raise RuntimeError("BLOCKING: race extract grouping is inconsistent")
    entries = tuple(CourseEntry(row[3], row[4], row[5], row[6] is not None)
                    for row in rows if row[3] is not None)
    return first[2], CourseRace(first[0], first[1], first[8], entries)


def evaluate_stream(rows, freeze: dict) -> dict:
    """One chronological pass. The source iterator is used exactly once."""
    history = deque()
    totals = {boat: [0] * 6 for boat in COURSES}
    overall = Metrics()
    by_boat = {boat: Metrics() for boat in COURSES}
    by_month = {f"2025-{month:02d}": Metrics() for month in range(1, 13)}
    counts = Counter()
    zero_history_days = []
    zero_history_entries = Counter()
    zero_probability = Counter()
    latest_prior_day = None
    previous_day = None
    current_day = None
    day_races = []
    race_rows = []
    extraction_digest = hashlib.sha256()

    def process_day(day: date, races: list[tuple[int, CourseRace]]) -> None:
        nonlocal latest_prior_day
        if day is None:
            return
        start = window_start(day)
        while history and history[0][0] < start:
            _, expired = history.popleft()
            for boat in COURSES:
                for course in COURSES:
                    totals[boat][course - 1] -= expired[boat][course - 1]
                    if totals[boat][course - 1] < 0:
                        raise RuntimeError("BLOCKING: window count underflow")
        if history and history[-1][0] >= day:
            raise RuntimeError("BLOCKING: current or future result in D-1 state")
        latest_prior_day = history[-1][0] if history else None
        frozen = {boat: probabilities_from_counts(tuple(totals[boat])) for boat in COURSES}
        before = tuple(tuple(totals[boat]) for boat in COURSES)
        if day.year == 2025:
            if not HOLDOUT_START <= day < HOLDOUT_STOP:
                raise RuntimeError("BLOCKING: holdout day outside 2025")
            if any(race.venue_code != EDOGAWA_VENUE_CODE for _, race in races):
                for boat in COURSES:
                    if frozen[boat].status == NOT_EVALUABLE:
                        zero_history_days.append({"date": day.isoformat(), "boat_no": boat})
            for _, race in races:
                counts["all_races"] += 1
                if race.venue_code == EDOGAWA_VENUE_CODE:
                    counts["edogawa_races"] += 1
                    if eligible(race):
                        counts["edogawa_eligible_races"] += 1
                        mismatches = sum(entry.actual_course != entry.boat_no for entry in race.entries)
                        counts["edogawa_eligible_entries"] += 6
                        counts["edogawa_mismatched_entries"] += mismatches
                        counts["edogawa_races_with_mismatch"] += bool(mismatches)
                    else:
                        counts["edogawa_excluded_races"] += 1
                    continue
                counts["national_races"] += 1
                if not eligible(race):
                    counts["national_excluded_races"] += 1
                    continue
                counts["national_eligible_races"] += 1
                counts["national_eligible_entries"] += 6
                for entry in race.entries:
                    prediction = frozen[entry.boat_no]
                    if prediction.status == NOT_EVALUABLE:
                        counts["not_evaluable_entries"] += 1
                        zero_history_entries[(day.isoformat(), entry.boat_no)] += 1
                        continue
                    if prediction.probabilities is None:
                        raise RuntimeError("BLOCKING: READY prediction without probabilities")
                    key = f"2025-{day.month:02d}"
                    zero = overall.add(prediction.probabilities, entry.actual_course)
                    by_boat[entry.boat_no].add(prediction.probabilities, entry.actual_course)
                    by_month[key].add(prediction.probabilities, entry.actual_course)
                    if zero:
                        zero_probability[(day.isoformat(), entry.boat_no, entry.actual_course)] += 1
            if before != tuple(tuple(totals[boat]) for boat in COURSES):
                raise RuntimeError("BLOCKING: state changed during same-day scoring")
        update = {boat: [0] * 6 for boat in COURSES}
        for _, race in races:
            if race.venue_code != EDOGAWA_VENUE_CODE and eligible(race):
                if day.year == 2024:
                    counts["warmup_2024_eligible_national_races"] += 1
                for entry in race.entries:
                    update[entry.boat_no][entry.actual_course - 1] += 1
        for boat in COURSES:
            for course in COURSES:
                totals[boat][course - 1] += update[boat][course - 1]
        history.append((day, update))

    for row in rows:
        day, race_id = row[0], row[2]
        if not date(2024, 1, 1) <= day < HOLDOUT_STOP:
            raise RuntimeError("BLOCKING: extraction crossed 2024-2025 bounds")
        if previous_day is not None and day < previous_day:
            raise RuntimeError("BLOCKING: extracted days are not ordered")
        previous_day = day
        extraction_digest.update(row_bytes(row))
        counts["extract_rows"] += 1
        if race_rows and race_id != race_rows[0][2]:
            parsed = make_race(race_rows)
            if current_day is not None and parsed[1].race_date != current_day:
                process_day(current_day, day_races)
                day_races = []
            current_day = parsed[1].race_date
            day_races.append(parsed)
            race_rows = []
        race_rows.append(row)
    if race_rows:
        parsed = make_race(race_rows)
        if current_day is not None and parsed[1].race_date != current_day:
            process_day(current_day, day_races)
            day_races = []
        current_day = parsed[1].race_date
        day_races.append(parsed)
    process_day(current_day, day_races)
    if (counts["national_eligible_races"] == 0
            or counts["warmup_2024_eligible_national_races"]
               != freeze["development_evidence"]["scoring_period_2024"]["RECENT_1Y"]["entries"] // 6
            or counts["national_eligible_entries"] != overall.entries + counts["not_evaluable_entries"]
            or counts["national_races"] != counts["national_eligible_races"] + counts["national_excluded_races"]
            or counts["edogawa_races"] != counts["edogawa_eligible_races"] + counts["edogawa_excluded_races"]
            or counts["all_races"] != counts["national_races"] + counts["edogawa_races"]
            or sum(metric.entries for metric in by_boat.values()) != overall.entries
            or sum(metric.entries for metric in by_month.values()) != overall.entries):
        raise RuntimeError("BLOCKING: holdout count reconciliation failed")
    return {
        "status": "ENTRY_COURSE_INDEX_V1_HOLDOUT_EVALUATED_NO_PREDECLARED_PASS_THRESHOLD",
        "method": freeze["method"]["selected_candidate_id"],
        "period": [HOLDOUT_START.isoformat(), "2025-12-31"],
        "counts": dict(sorted(counts.items())),
        "overall": overall.result(),
        "by_boat": {str(boat): by_boat[boat].result() for boat in COURSES},
        "by_month": {key: metric.result() for key, metric in by_month.items()},
        "zero_history_boat_days": zero_history_days,
        "not_evaluable_by_date_boat": [
            {"date": day, "boat_no": boat, "entries": value}
            for (day, boat), value in sorted(zero_history_entries.items())],
        "zero_probability_actuals": [
            {"date": day, "boat_no": boat, "actual_course": course, "entries": value}
            for (day, boat, course), value in sorted(zero_probability.items())],
        "extract_rows_sha256": extraction_digest.hexdigest(),
        "development_comparison": {
            "2023_development": freeze["development_evidence"]["scoring_period_2023"]["RECENT_1Y"],
            "2024_validation": freeze["development_evidence"]["scoring_period_2024"]["RECENT_1Y"],
            "2025_independent_holdout": overall.result(),
        },
        "leakage_audit": {
            "score_before_appending_same_day_results": True,
            "history_dates_strictly_before_scoring_day": True,
            "all_races_on_day_share_one_probability_state": True,
            "edogawa_excluded_from_national_history_and_metrics": True,
            "latest_prior_result_date_in_final_state": latest_prior_day.isoformat() if latest_prior_day else None,
            "full_vintage_as_of_certified": False,
        },
        "as_of_limitation": freeze["as_of_limitation"],
    }


def evaluate() -> dict:
    if not GATE.exists() or RESULT.exists():
        raise RuntimeError("BLOCKING: unique READY gate and absent result required")
    freeze = checked_freeze()
    expected = identity(freeze)
    preliminary = json.loads(GATE.read_text(encoding="utf-8"))
    if preliminary["status"] != "READY" or preliminary["identity"] != expected:
        raise RuntimeError("BLOCKING: gate already consumed or freeze identity changed")
    conn = open_snapshot()
    started = False
    try:
        dataset = dataset_identity(conn)
        gate = mark_started(GATE, RESULT, expected, dataset["full_shard_chain_sha256"],
                            dataset["snapshot"])
        started = True
        with conn.cursor(name="entry_course_holdout_2025_once") as cur:
            cur.itersize = 10000
            cur.execute(HOLDOUT_SQL)
            result = evaluate_stream(cur, freeze)
        if identity(freeze) != gate["identity"]:
            raise RuntimeError("BLOCKING: frozen identity changed during execution")
        if dataset["full_shard_chain_sha256"] != gate["dataset"]["full_shard_chain_sha256"]:
            raise RuntimeError("BLOCKING: dataset identity changed")
        result["integrity"] = {
            **gate["identity"], "gate_preflight_started_utc": gate["preflight_started_utc"],
            "evaluation_started_utc": gate["evaluation_started_utc"],
            "evaluation_finished_utc": utc_now(), "dataset": dataset,
            "development_extract": gate["development_extract"],
            "holdout_extraction_sql_sha256": gate["identity"]["holdout_sql_sha256"],
        }
        save_json(RESULT, result)
        gate["status"] = "COMPLETED"
        gate["evaluation_finished_utc"] = result["integrity"]["evaluation_finished_utc"]
        gate["result_sha256"] = sha(RESULT)
        save_json(GATE, gate)
        return result
    except Exception as exc:
        if started:
            failed = json.loads(GATE.read_text(encoding="utf-8"))
            if failed["status"] == "STARTED":
                failed["status"] = "FAILED_NO_RETRY"
                failed["failure_utc"] = utc_now()
                failed["failure_type"] = type(exc).__name__
                save_json(GATE, failed)
        raise
    finally:
        conn.rollback()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "evaluate"))
    action = parser.parse_args().action
    if action == "preflight":
        gate = preflight()
        print(json.dumps({"status": gate["status"], "gate": str(GATE),
                          "development_extract_sha256": gate["development_extract"]["sha256"],
                          "dataset_sha256": gate["dataset"]["full_shard_chain_sha256"]}))
    else:
        result = evaluate()
        print(json.dumps({"status": result["status"], "result": str(RESULT),
                          "eligible_races": result["counts"]["national_eligible_races"],
                          "evaluated_entries": result["overall"]["evaluated_entries"],
                          "log_loss": result["overall"]["log_loss"]}))


if __name__ == "__main__":
    main()
