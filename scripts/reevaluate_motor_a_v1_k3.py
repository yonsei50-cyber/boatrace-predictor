"""Reevaluate frozen Motor A v1 on K3 Canonical, then open the 2025 holdout.

Run ``prepare`` before ``holdout``. The prepare path rejects any result query
whose upper date bound extends into 2025 and writes the immutable holdout
protocol only after the 2023/2024 development replay is complete.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict, deque
from datetime import date
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import psycopg2
from scipy.stats import spearmanr

from scripts.db import settings, source_connection
from scripts.motor_a_v1 import FINISH_POINTS, MotorIdentity, build_meeting_days

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts/motor_a_method_freeze_v1.json"
OLD_ANALYSIS = ROOT / ".local/motor_a_meeting_analysis.json"
OLD_EXTRACT = ROOT / ".local/motor_a_meeting_extract.json"
OLD_MEETINGS = ROOT / ".local/motor_a_meeting_identity_supported.json"
DEV = ROOT / "artifacts/motor_a_v1_k3_2023_2024.json"
COMPARISON = ROOT / "artifacts/motor_a_v1_k3_development_comparison.json"
PROTOCOL = ROOT / "artifacts/motor_a_v1_2025_holdout_protocol.json"
HOLDOUT = ROOT / "artifacts/motor_a_v1_k3_2025_holdout.json"
VERIFY = ROOT / "artifacts/motor_a_v1_k3_replay_verification.json"
FREEZE_HASH = "cc5b1b690919871897a625b910bbd7fef9f2247ac65e8e779073c9fb39d43779"
SOURCE_POLICY_CHECKPOINT = "fd49bffe83b2f23443ec5f525786c0dd309abe95"
RESULT_VERSION = "K3_ONLY_RESULT_V1_b68a27cf8f653602"
START = date(2017, 1, 1)
DEV_END = date(2025, 1, 1)
HOLDOUT_END = date(2026, 1, 1)
SOURCE_TABLES = ("brd_l1", "brd_b1", "brd_k1")
SELECT = """
SELECT r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
       m.generation_start_year,m.generation_start_date,m.generation_end_date,
       m.motor_no,m.identity_rule_version,e.national_win_rate_status,
       e.national_win_rate,b.finish_state,b.finish_position,
       z.finish_position,z.race_id IS NOT NULL
FROM core.race r JOIN core.race_entry e USING(race_id)
LEFT JOIN core.motor m ON m.motor_id=e.motor_id
LEFT JOIN core.boat_finish_state b ON b.race_id=e.race_id AND b.boat_no=e.boat_no
LEFT JOIN core.race_result z ON z.race_id=e.race_id AND z.boat_no=e.boat_no
WHERE r.race_date >= %s AND r.race_date < %s
ORDER BY r.race_date,r.venue_code,r.race_no,e.boat_no
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False, default=str).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def frozen_inputs() -> tuple[dict, dict]:
    if sha(FREEZE) != FREEZE_HASH:
        raise RuntimeError("Motor A freeze artifact changed")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = freeze["development_evidence"]["local_development_artifact_sha256"]
    for path, key in ((OLD_ANALYSIS, "motor_a_meeting_analysis.json"),
                      (OLD_EXTRACT, "motor_a_meeting_extract.json"),
                      (OLD_MEETINGS, "motor_a_meeting_identity_supported.json")):
        if sha(path) != expected[key]:
            raise RuntimeError(f"frozen development evidence changed: {path.name}")
    if (freeze["freeze_id"] != "MOTOR_A_METHOD_FREEZE_V1"
            or freeze["status"] != "METHOD_FROZEN"
            or {int(k): v for k, v in freeze["residual"]["finish_points"].items()} != FINISH_POINTS
            or freeze["features"]["motor_a_base3"]["meeting_weight"] !=
            "EQUAL; do not pool all races across meetings"
            or freeze["race_recent5_comparator"]["status"] !=
            "DEVELOPMENT_COMPARATOR_NOT_V1_FEATURE"):
        raise RuntimeError("Motor A freeze contract mismatch")
    return freeze, json.loads(OLD_ANALYSIS.read_text(encoding="utf-8"))


def frozen_coefficients(old: dict) -> dict:
    g = old["groups"]
    inc = old["incremental"]["group4"]["2023"]["base3"]
    coefficients = {
        "group1_current": g["group1"]["2023"]["current"]["fit_2017_2022"],
        "group2_base3": g["group2"]["2023"]["base3"]["fit_2017_2022"],
        "group3_current": g["group3"]["2023"]["current"]["fit_2017_2022"],
        "group4_base3": g["group4"]["2023"]["base3"]["fit_2017_2022"],
        "group4_current": g["group4"]["2023"]["current"]["fit_2017_2022"],
        "both_base": inc["coefficients_2017_2022"]["model1"],
        "both_current": inc["coefficients_2017_2022"]["model2"],
        "both_joint": inc["coefficients_2017_2022"]["model3"],
        "both_race5": old_joint_race5_coefficients(old),
    }
    for group, score, key in (("group1", "current", "group1_current"),
                              ("group2", "base3", "group2_base3"),
                              ("group3", "current", "group3_current"),
                              ("group4", "base3", "group4_base3"),
                              ("group4", "current", "group4_current")):
        if coefficients[key] != g[group]["2024"][score]["fit_2017_2022"]:
            raise RuntimeError("frozen 2023/2024 diagnostic coefficients disagree")
    for model, key in (("model1", "both_base"), ("model2", "both_current"),
                       ("model3", "both_joint")):
        if coefficients[key] != old["incremental"]["group4"]["2024"]["base3"][\
                "coefficients_2017_2022"][model]:
            raise RuntimeError("frozen incremental coefficients disagree")
    return coefficients


def target_readonly():
    conn = psycopg2.connect(**settings(), dbname="boatrace_predictor",
        connect_timeout=5, application_name="motor_a_v1_k3_readonly",
        options="-c default_transaction_read_only=on -c statement_timeout=0 -c lock_timeout=2000")
    conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
    with conn.cursor() as cur:
        cur.execute("SET ROLE itgakko")
        cur.execute("SELECT current_database(),current_user,current_setting('transaction_read_only')")
        if cur.fetchone() != ("boatrace_predictor", "itgakko", "on"):
            raise RuntimeError("read-only Canonical identity mismatch")
    return conn


def source_identity(conn) -> dict:
    # This reads immutable dataset metadata, never 2025 outcome rows.
    with conn.cursor() as cur:
        cur.execute("""SELECT version_id,authoritative_source,date_start,date_end,
                       source_manifest_hash,normalization_version,result_races,result_boats
                       FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1""")
        row = cur.fetchone()
    if (row is None or row[0] != RESULT_VERSION or row[1] != "brd_k3"
            or row[2] != START or row[3] < date(2025, 12, 31)
            or row[5] != "k3-only-result-v1"):
        raise RuntimeError("expected K3-only Canonical version absent")
    return dict(zip(("version_id", "authoritative_source", "date_start", "date_end",
                     "source_manifest_hash", "normalization_version",
                     "result_races", "result_boats"),
                    (v.isoformat() if isinstance(v, date) else v for v in row)))


def meeting_map(end: date) -> tuple[dict, dict]:
    source = source_connection()
    tables = {}
    try:
        for table in SOURCE_TABLES:
            with source.cursor() as cur:
                cur.execute(f"""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,
                               kaisai_nichime,title FROM public.{table}
                               WHERE kaisai_nen >= '2017' AND kaisai_nen < %s
                               ORDER BY kyoteijo_code,kaisai_nen,kaisai_tsukihi""",
                            (str(end.year),))
                rows = cur.fetchall()
            mapped = {}
            for year, md, venue, number, title in rows:
                day = date(int(year), int(md[:2]), int(md[2:]))
                if day >= end:
                    continue
                key = (int(venue), day)
                if key in mapped:
                    raise RuntimeError(f"duplicate {table} venue-day")
                mapped[key] = ((number or "").strip(), (title or "").strip())
            tables[table] = mapped
    finally:
        source.rollback()
        source.close()
    days = build_meeting_days(*(tables[t] for t in SOURCE_TABLES))
    records = [{"venue": venue, "race_date": day.isoformat(),
                "status": info.status,
                "meeting_start": info.start.isoformat() if info.start else None,
                "meeting_end": info.end.isoformat() if info.end else None,
                "reason": list(info.reasons)}
               for (venue, day), info in sorted(days.items())]
    # Match the original supported-builder JSON digest convention.
    legacy_digest = hashlib.sha256(json.dumps(records, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    return days, {"period_end_exclusive": end.isoformat(), "map_sha256": legacy_digest,
                  "source_rows": {t: len(tables[t]) for t in SOURCE_TABLES},
                  "venue_days": len(days),
                  "certified_venue_days": sum(x.status == "CERTIFIED" for x in days.values()),
                  "meeting_count": len({(v, x.start, x.end, x.reasons)
                                        for (v, _), x in days.items()})}


def source_guards(conn, end: date, days: dict) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), count(*) FILTER
            (WHERE b.source_table IS DISTINCT FROM 'brd_k3')
            FROM core.race_result z JOIN core.race r USING(race_id)
            LEFT JOIN raw.source_record s ON s.source_record_id=z.source_record_id
            LEFT JOIN raw.source_batch b USING(source_batch_id)
            WHERE r.race_date >= %s AND r.race_date < %s""", (START, end))
        result_boats, non_k3 = cur.fetchone()
        cur.execute("""SELECT race_date,venue_code,count(*) FROM core.race
                       WHERE race_date >= %s AND race_date < %s
                       GROUP BY 1,2""", (START, end))
        core_days = {(venue, day): n for day, venue, n in cur.fetchall()}
    if non_k3 or set(core_days) != set(days) or any(n != 12 for n in core_days.values()):
        raise RuntimeError("K3 lineage or source meeting venue-day gate failed")
    return {"result_boats": result_boats, "non_k3_result_boats": non_k3,
            "core_venue_days": len(core_days), "core_races": sum(core_days.values())}


def first_reason(row) -> str | None:
    (_, venue, _, _, player, generation, start, end, motor_no, rule,
     rate_status, rate, finish_state, finish, z_finish, has_result) = row
    if generation is None or motor_no is None:
        return "MOTOR_UNKNOWN"
    if rule != "user-fixed-month-day-v1" or not start <= row[0] < end:
        raise RuntimeError("motor generation identity or date invalid")
    if player is None:
        return "PLAYER_UNKNOWN"
    if not has_result or finish_state == "NO_INDIVIDUAL_RESULT":
        return "RESULT_MISSING"
    if finish_state != "NUMERIC_VALID" or finish not in FINISH_POINTS:
        return "FINISH_" + str(finish_state)
    if z_finish != finish:
        raise RuntimeError("K3 result and canonical finish-state disagree")
    if rate_status != "VALID" or rate is None:
        return "RATE_" + str(rate_status)
    return None


def replay(conn, end: date, days: dict, years: tuple[int, ...]) -> dict:
    if end not in (DEV_END, HOLDOUT_END):
        raise ValueError("unapproved result period")
    certified = {(venue, info.start) for (venue, _), info in days.items()
                 if info.status == "CERTIFIED" and info.start is not None}
    ends = defaultdict(set)
    for (venue, _), info in days.items():
        if info.status == "CERTIFIED" and info.end is not None:
            ends[info.end].add((venue, info.start))
    meeting_sum, meeting_n = defaultdict(float), Counter()
    meeting_motors, meeting_players = defaultdict(set), defaultdict(set)
    first_player, player_entry_n = {}, Counter()
    completed, last_meeting, prior_owner = defaultdict(list), {}, {}
    history = defaultdict(lambda: deque(maxlen=5))
    pending = []
    input_hash, residual_hash, feature_hash = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    counts = defaultdict(Counter)
    used_motors, used_meetings = defaultdict(set), defaultdict(set)
    series = {year: {k: array(code) for k, code in
                     (("y", "f"), ("base3", "f"), ("current", "f"),
                      ("race5", "f"), ("group1", "B"), ("group2", "B"),
                      ("group3", "B"))} for year in years}
    current_day = None
    known_absent = Counter()
    known_absent_races = set()

    def finish_day(day):
        for motor, meeting, player, residual in pending:
            history[motor].append(residual)
            if meeting is None:
                completed[motor].clear()
                prior_owner.pop(motor, None)
            else:
                key = (motor, meeting)
                meeting_sum[key] += residual
                meeting_n[key] += 1
        pending.clear()
        for meeting in ends.get(day, ()):
            for motor in meeting_motors.get(meeting, ()):
                key = (motor, meeting)
                if meeting_n[key]:
                    completed[motor].append((meeting, meeting_sum[key] / meeting_n[key],
                                             meeting_n[key]))
                prior_owner[motor] = meeting_players[key].copy()

    scan = conn.cursor(name="motor_a_k3_scan")
    scan.itersize = 10000
    scan.execute(SELECT, (START, end))
    try:
        for row in scan:
            (day, venue, race_no, boat_no, player, generation, _, _, motor_no, _,
             _, rate, _, finish, _, has_result) = row
            if day != current_day:
                if current_day is not None:
                    finish_day(current_day)
                current_day = day
            input_hash.update(canonical_bytes(row) + b"\n")
            year = day.year
            counts[year]["candidate_uses"] += 1
            if day == date(2025, 8, 12) and venue in (1, 7, 15, 19, 20):
                known_absent["entries"] += 1
                known_absent["results"] += bool(has_result)
                known_absent_races.add((venue, race_no))
            info = days.get((venue, day))
            if info is None:
                raise RuntimeError("canonical venue-day without source meeting")
            meeting = (venue, info.start) if info.current_known else None
            motor = MotorIdentity(venue, generation, motor_no) if generation is not None else None
            if motor is not None:
                previous = last_meeting.get(motor)
                if meeting is None:
                    completed[motor].clear()
                    prior_owner.pop(motor, None)
                    last_meeting[motor] = None
                elif previous != meeting:
                    if previous is not None and previous not in certified:
                        completed[motor].clear()
                        prior_owner.pop(motor, None)
                    last_meeting[motor] = meeting
            if motor is not None and meeting is not None:
                key = (motor, meeting)
                meeting_motors[meeting].add(motor)
                meeting_players[key].add(player)
                first_player.setdefault(key, player)
                previous_entries = player_entry_n[(motor, meeting, player)]
                group1 = previous_entries > 0
                previous_players = prior_owner.get(motor)
                new_owner = (previous_players is not None
                             and first_player[key] == player and player not in previous_players)
                group2 = new_owner and previous_entries == 0
                group3 = new_owner and previous_entries > 0
                player_entry_n[(motor, meeting, player)] += 1
            else:
                group1 = group2 = group3 = False
            reason = first_reason(row)
            if reason is not None:
                counts[year]["excluded"] += 1
                counts[year]["excluded_" + reason] += 1
                continue
            counts[year]["eligible_residuals"] += 1
            if group1:
                counts[year]["group1_eligible"] += 1
            if group2:
                counts[year]["group2_eligible"] += 1
            if group3:
                counts[year]["group3_eligible"] += 1
            if meeting is None:
                counts[year]["eligible_meeting_unknown"] += 1
            else:
                used_meetings[year].add(meeting)
            used_motors[year].add(motor)
            residual = FINISH_POINTS[finish] - float(rate)
            selected = completed[motor][-3:] if meeting is not None else []
            base = sum(x[1] for x in selected) / len(selected) if selected else math.nan
            n = meeting_n[(motor, meeting)] if meeting is not None else 0
            current = meeting_sum[(motor, meeting)] / n if n else math.nan
            past = history[motor]
            race5 = sum(past) / len(past) if past else math.nan
            counts[year]["base3_evaluable"] += bool(selected)
            counts[year]["current_evaluable"] += bool(n)
            counts[year]["both_observed"] += bool(selected and n)
            counts[year]["neither_observed"] += not selected and not n
            residual_hash.update(canonical_bytes((day, venue, race_no, boat_no, residual)) + b"\n")
            feature_hash.update(canonical_bytes((day, venue, race_no, boat_no,
                                                  base if selected else None,
                                                  len(selected), sum(x[2] for x in selected),
                                                  sum(x[1] * x[2] for x in selected),
                                                  current if n else None, n,
                                                  race5 if past else None,
                                                  group1, group2, group3)) + b"\n")
            if year in series:
                for key, val in (("y", residual), ("base3", base),
                                 ("current", current), ("race5", race5),
                                 ("group1", group1), ("group2", group2),
                                 ("group3", group3)):
                    series[year][key].append(val)
            pending.append((motor, meeting, player, residual))
    finally:
        scan.close()
    if current_day is not None:
        finish_day(current_day)
    for year in counts:
        c = counts[year]
        c["base3_not_evaluable"] = c["eligible_residuals"] - c["base3_evaluable"]
        c["current_not_evaluable"] = c["eligible_residuals"] - c["current_evaluable"]
        c["motor_generation_count"] = len(used_motors[year])
        c["eligible_meeting_count"] = len(used_meetings[year])
    return {"counts": {str(y): dict(c) for y, c in sorted(counts.items())},
            "series": series,
            "hashes": {"ordered_input_sha256": input_hash.hexdigest(),
                       "residual_dataset_sha256": residual_hash.hexdigest(),
                       "state_features_sha256": feature_hash.hexdigest()},
            "known_absent_entries": {"races": len(known_absent_races),
                                     "entries": known_absent["entries"],
                                     "results": known_absent["results"]}}


def old_joint_race5_coefficients(old: dict) -> list[float]:
    # Recover the frozen matched-cohort regression from its saved 2017-2024
    # feature matrix, and verify against both saved development MSE values.
    with np.load(ROOT / ".local/motor_a_meeting_features.npz") as a:
        year = a["year"]
        y = a["y"].astype(np.float64)
        race5 = a["race5"].astype(np.float64)
        matched = np.isfinite(a["base3"]) & np.isfinite(a["current"]) & np.isfinite(race5)
        train = (year <= 2022) & matched
        coeff = np.linalg.lstsq(np.column_stack((np.ones(np.count_nonzero(train)),
                                                 race5[train])), y[train], rcond=None)[0]
        for target_year in (2023, 2024):
            test = (year == target_year) & matched
            mse = float(np.mean((y[test] - coeff[0] - coeff[1] * race5[test]) ** 2))
            saved = old["common_cohort_joint_vs_race"]["group4"][str(target_year)]["mse"]["race5"]
            if abs(mse - saved) > 1e-10:
                raise RuntimeError("local frozen race5 matrix does not reproduce saved MSE")
        return [float(v) for v in coeff]


@lru_cache(maxsize=None)
def old_training_mean(group: str, score: str) -> float:
    # The original frozen extraction is the numeric 2017-2022 training source.
    # Its path is local and ignored; its companion extraction/analysis digests
    # are sealed in the freeze artifact. This is used only for constant baselines.
    path = ROOT / ".local/motor_a_meeting_features.npz"
    with np.load(path) as a:
        mask = a["year"] <= 2022
        if group != "group4":
            mask &= a[group].astype(bool)
        mask &= np.isfinite(a[score])
        return float(np.mean(a["y"][mask].astype(np.float64)))


def score_metrics(y, x, coefficients, train_mean):
    observed = np.isfinite(x)
    y, x = y[observed], x[observed]
    n = len(y)
    if n < 10:
        return {"n": n, "status": "NOT_EVALUABLE"}
    order = np.argsort(x, kind="mergesort")
    bins = [{"n": len(idx), "score_mean": float(np.mean(x[idx])),
             "next_residual_mean": float(np.mean(y[idx]))}
            for idx in np.array_split(order, 5)]
    prediction = coefficients[0] + coefficients[1] * x
    return {"n": n, "pearson": float(np.corrcoef(x, y)[0, 1]),
            "spearman": float(spearmanr(x, y).statistic),
            "mse_constant": float(np.mean((y - train_mean) ** 2)),
            "mse_score": float(np.mean((y - prediction) ** 2)),
            "quintiles_low_to_high": bins,
            "high_minus_low": bins[-1]["next_residual_mean"] -
                              bins[0]["next_residual_mean"]}


def calculate_metrics(series: dict, coefficients: dict) -> dict:
    result = {}
    for year, a in sorted(series.items()):
        y = np.asarray(a["y"], dtype=np.float64)
        base = np.asarray(a["base3"], dtype=np.float64)
        current = np.asarray(a["current"], dtype=np.float64)
        race5 = np.asarray(a["race5"], dtype=np.float64)
        groups = {g: np.asarray(a[g], dtype=bool) for g in ("group1", "group2", "group3")}
        groups["group4"] = np.ones(len(y), dtype=bool)
        named = {}
        for group, score, x in (("group1", "current", current),
                                ("group2", "base3", base),
                                ("group3", "current", current),
                                ("group4", "base3", base),
                                ("group4", "current", current)):
            key = f"{group}_{score}"
            named[key] = score_metrics(y[groups[group]], x[groups[group]],
                                       coefficients[key], old_training_mean(group, score))
        both = np.isfinite(base) & np.isfinite(current)
        if not np.all(np.isfinite(race5[both])):
            raise RuntimeError("frozen both-observed race5 comparator unavailable")
        yy, bb, cc, rr = y[both], base[both], current[both], race5[both]
        def mse(co, *xs):
            pred = np.full(len(yy), co[0])
            for i, x in enumerate(xs):
                pred += co[i + 1] * x
            return float(np.mean((yy - pred) ** 2))
        both_metrics = {"n": len(yy),
                        "mse_base_only": mse(coefficients["both_base"], bb),
                        "mse_current_only": mse(coefficients["both_current"], cc),
                        "mse_base3_plus_current": mse(coefficients["both_joint"], bb, cc),
                        "mse_race5_comparator": mse(coefficients["both_race5"], rr)}
        result[str(year)] = {"groups": named, "both_observed": both_metrics}
    return result


def baseline_comparison(old, new_metrics, new_counts, meeting_info):
    years = {}
    for year in ("2023", "2024"):
        old_count = json.loads(OLD_EXTRACT.read_text(encoding="utf-8"))["by_year"][year]
        oc = old["cold_start"]["group4"][year]
        om = old["groups"]
        oi = old["incremental"]["group4"][year]["base3"]
        oj = old["common_cohort_joint_vs_race"]["group4"][year]
        nm = new_metrics[year]
        nc = new_counts[year]
        years[year] = {
            "counts": {
                "eligible_residuals": {"old": old_count["eligible"], "new": nc["eligible_residuals"]},
                "candidate_uses": {"old": old_count["all_entries"], "new": nc["candidate_uses"]},
                "base3_evaluable": {"old": oc["eligible_group_rows"] - oc["base3_unobserved"],
                                    "new": nc["base3_evaluable"]},
                "current_evaluable": {"old": oc["eligible_group_rows"] - oc["current_unobserved"],
                                      "new": nc["current_evaluable"]},
                "both_observed": {"old": oc["base_and_current_observed"],
                                  "new": nc["both_observed"]},
                "meeting_count": {"old": meeting_info[year]["old_meetings"],
                                  "new": meeting_info[year]["new_meetings"]},
                "motor_generation_count": {"old": None, "new": nc["motor_generation_count"]},
            },
            "metrics": {
                "group2_base3": {"old": om["group2"][year]["base3"],
                                 "new": nm["groups"]["group2_base3"]},
                "group1_current": {"old": om["group1"][year]["current"],
                                   "new": nm["groups"]["group1_current"]},
                "group3_current": {"old": om["group3"][year]["current"],
                                   "new": nm["groups"]["group3_current"]},
                "both_observed": {"old": {"n": oi["n"],
                                          "mse_current_only": oi["mse_model2_current"],
                                          "mse_base3_plus_current": oi["mse_model3_both"],
                                          "mse_race5_comparator": oj["mse"]["race5"]},
                                  "new": nm["both_observed"]},
            },
        }
        for count in years[year]["counts"].values():
            count["delta"] = count["new"] - count["old"] if count["old"] is not None else None
    return {"comparison_basis": "frozen 2017-2024 development artifact, hash-verified",
            "years": years}


def meeting_year_counts(days: dict) -> dict:
    return {str(y): len({(v, x.start, x.end, x.reasons) for (v, d), x in days.items()
                        if d.year == y}) for y in (2023, 2024, 2025)}


def prepare() -> None:
    freeze, old = frozen_inputs()
    if PROTOCOL.exists() or HOLDOUT.exists():
        raise RuntimeError("protocol/holdout already exists; no prepare overwrite")
    coefficients = frozen_coefficients(old)
    days, meeting_identity = meeting_map(DEV_END)
    if meeting_identity["map_sha256"] != freeze["development_evidence"]["meeting_map_sha256"]:
        raise RuntimeError("frozen 2017-2024 meeting mapping changed")
    conn = target_readonly()
    try:
        source = source_identity(conn)
        guards = source_guards(conn, DEV_END, days)
        replayed = replay(conn, DEV_END, days, (2023, 2024))
        conn.rollback()
    finally:
        conn.close()
    metrics = calculate_metrics(replayed["series"], coefficients)
    old_days = json.loads(OLD_MEETINGS.read_text(encoding="utf-8"))["day_mapping"]
    old_meetings = {str(y): len({(r["venue"], r["meeting_start"], r["meeting_end"],
                                   tuple(r["reason"])) for r in old_days
                                  if r["race_date"].startswith(str(y))})
                    for y in (2023, 2024)}
    new_meetings = meeting_year_counts(days)
    meeting_info = {y: {"old_meetings": old_meetings[y],
                        "new_meetings": new_meetings[y]} for y in ("2023", "2024")}
    dev = {"status": "K3_ONLY_DEVELOPMENT_REEVALUATED", "source_policy_checkpoint": SOURCE_POLICY_CHECKPOINT,
           "freeze_sha256": FREEZE_HASH, "source_identity": source,
           "meeting_identity": meeting_identity, "source_guards": guards,
           "period": ["2017-01-01", "2024-12-31"], "evaluation_years": [2023, 2024],
           "coefficients": coefficients, "counts_by_year": replayed["counts"],
           "metrics": metrics, "replay_hashes": replayed["hashes"],
           "metrics_sha256": digest(metrics)}
    comparison = baseline_comparison(old, metrics, replayed["counts"], meeting_info)
    write_json(DEV, dev)
    write_json(COMPARISON, comparison)
    protocol = {
        "protocol_id": "MOTOR_A_V1_FIRST_2025_K3_HOLDOUT", "status": "FROZEN_BEFORE_2025_RESULTS",
        "freeze_sha256": FREEZE_HASH, "source_policy_checkpoint": SOURCE_POLICY_CHECKPOINT,
        "source_identity": source, "development_artifact_sha256": sha(DEV),
        "development_comparison_sha256": sha(COMPARISON),
        "k3_canonical_identity": {"version_id": source["version_id"],
                                  "source_manifest_hash": source["source_manifest_hash"],
                                  "direct_ordered_result_hash": "COMPUTED_AFTER_PROTOCOL_FREEZE"},
        "evaluation_period": ["2025-01-01", "2025-12-31"],
        "history_start": "2017-01-01", "history_policy": "K3-only Canonical; no prior R3 state/cache",
        "eligibility": freeze["eligibility"], "motor_identity": freeze["motor_identity"],
        "meeting_identity": freeze["meeting_identity"], "residual": freeze["residual"],
        "base3": freeze["features"]["motor_a_base3"],
        "current": freeze["features"]["motor_a_current"],
        "time_boundary": freeze["time_boundary"],
        "cohorts": {
            "group1_current": "same-player following entry in current meeting with Current observed",
            "group2_base3": "new user's first entry after prior certified motor-meeting owner, with Base3 observed",
            "group3_current": "new user's following entry in current meeting with Current observed",
            "group4": "all eligible residual rows",
            "both_observed": "group4 rows where Base3 and Current are both observed",
        },
        "metrics": {"group1_current": ["n", "pearson", "spearman", "mse_constant", "mse_score",
                                       "quintiles_low_to_high", "high_minus_low"],
                    "group2_base3": ["n", "pearson", "spearman", "mse_constant", "mse_score",
                                      "quintiles_low_to_high", "high_minus_low"],
                    "group3_current": ["n", "pearson", "spearman", "mse_constant", "mse_score",
                                       "quintiles_low_to_high", "high_minus_low"],
                    "group4_base3_current": ["n", "pearson", "spearman", "mse_score"],
                    "both_observed": ["n", "mse_base_only", "mse_current_only",
                                      "mse_base3_plus_current", "mse_race5_comparator"],
                    "coverage": ["candidate_uses", "eligible_residuals", "base3_evaluable",
                                 "base3_not_evaluable", "current_evaluable", "current_not_evaluable",
                                 "both_observed", "neither_observed"]},
        "diagnostic_coefficients_2017_2022_frozen": coefficients,
        "prediction_formula": "intercept + slope*score; joint intercept + base_slope*Base3 + current_slope*Current",
        "constant_baseline": "mean of frozen 2017-2022 cohort training residuals",
        "race5_comparator": "historical development comparator only; same both-observed cohort; no method selection",
        "no_retuning": "No changes to method, cohort, eligibility, window, coefficients, or comparator after viewing 2025",
        "pass_threshold": None,
        "holdout_interpretation": "direction, effect size, metric difference, and evaluable coverage; no post hoc PASS threshold",
    }
    write_json(PROTOCOL, protocol)
    print(json.dumps({"development_sha256": sha(DEV), "comparison_sha256": sha(COMPARISON),
                      "protocol_sha256": sha(PROTOCOL),
                      "development_counts": {y: dev["counts_by_year"][y] for y in ("2023", "2024")}},
                     ensure_ascii=False))


def holdout(verify_only: bool = False) -> None:
    frozen_inputs()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol_hash = sha(PROTOCOL)
    if (protocol["freeze_sha256"] != FREEZE_HASH
            or protocol["status"] != "FROZEN_BEFORE_2025_RESULTS"
            or protocol["source_policy_checkpoint"] != SOURCE_POLICY_CHECKPOINT):
        raise RuntimeError("holdout protocol mismatch")
    if sha(DEV) != protocol["development_artifact_sha256"] or sha(COMPARISON) != protocol["development_comparison_sha256"]:
        raise RuntimeError("development artifacts changed after holdout protocol")
    if verify_only and not HOLDOUT.exists():
        raise RuntimeError("no holdout result to verify")
    if not verify_only and HOLDOUT.exists():
        raise RuntimeError("first holdout already exists; no overwrite")
    days, mapping = meeting_map(HOLDOUT_END)
    conn = target_readonly()
    try:
        source = source_identity(conn)
        if source != protocol["source_identity"]:
            raise RuntimeError("K3 Canonical version/manifest changed after protocol")
        guards = source_guards(conn, HOLDOUT_END, days)
        replayed = replay(conn, HOLDOUT_END, days, (2025,))
        conn.rollback()
    finally:
        conn.close()
    metrics = calculate_metrics(replayed["series"], protocol["diagnostic_coefficients_2017_2022_frozen"])
    counts = replayed["counts"]["2025"]
    result = {"status": "MOTOR_A_V1_FIRST_INDEPENDENT_2025_K3_HOLDOUT",
              "freeze_sha256": FREEZE_HASH, "protocol_sha256": protocol_hash,
              "source_policy_checkpoint": SOURCE_POLICY_CHECKPOINT,
              "source_identity": source, "meeting_identity": mapping,
              "source_guards": guards, "period": protocol["evaluation_period"],
              "counts": counts, "metrics": metrics["2025"],
              "known_2025_08_12_k3_absent": replayed["known_absent_entries"],
              "replay_hashes": replayed["hashes"], "metrics_sha256": digest(metrics)}
    if verify_only:
        first = json.loads(HOLDOUT.read_text(encoding="utf-8"))
        if result != first:
            raise RuntimeError("independent second replay differs from first holdout")
        write_json(VERIFY, {"status": "PASS", "freeze_sha256": FREEZE_HASH,
                            "protocol_sha256": protocol_hash, "holdout_sha256": sha(HOLDOUT),
                            "ordered_input_sha256": replayed["hashes"]["ordered_input_sha256"],
                            "residual_dataset_sha256": replayed["hashes"]["residual_dataset_sha256"],
                            "state_features_sha256": replayed["hashes"]["state_features_sha256"],
                            "metric_sha256": result["metrics_sha256"],
                            "same_input_and_output_as_first_replay": True})
        print(json.dumps({"verification": "PASS", "holdout_sha256": sha(HOLDOUT)},
                         ensure_ascii=False))
    else:
        write_json(HOLDOUT, result)
        print(json.dumps({"holdout_sha256": sha(HOLDOUT), "protocol_sha256": protocol_hash,
                          "counts": counts, "metrics": metrics["2025"]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "holdout", "verify"))
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    else:
        holdout(verify_only=args.phase == "verify")


if __name__ == "__main__":
    main()
