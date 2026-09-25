"""Read-only C3/C4 timing characteristics with conservative pre-race C4 gates.

This is descriptive research, not a feature-method freeze. K3, results,
odds, and Prediction data are not inputs. The source and target transactions
are read-only. C4 values are never reassigned to another boat.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, stdev

import numpy as np

from scripts.db import source_connection, target_connection
from scripts.research_c4_carry_forward import packet_is_informative


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/pre_race_time_characteristics_v1_metrics.json"
DATES = (date(2023, 10, 31), date(2023, 11, 30),
         date(2023, 12, 31), date(2024, 1, 31),
         date(2024, 3, 31), date(2024, 6, 30),
         date(2024, 9, 30), date(2024, 12, 31))
TYPES = ("exhibition", "lap_time", "mawariashi", "chokusen")
C4_TYPES = TYPES[1:]
FIELDS = ("isshu", "hanshu", "mawariashi", "chokusen")
SLOTS = tuple(str(n) for n in range(1, 7))
STRUCTURAL_NOT_PROVIDED = {
    "lap_time": {"03"},
    "mawariashi": {"03"},
    "chokusen": {"03", "12", "13", "18"},
}
# Explicit user decision for this source packet only. This is not a numeric
# plausibility rule and does not generalize to other races or raw values.
QUARANTINED_C4_RACE = ("20240102", "16", "12")
QUARANTINED_C4_PACKET = (
    ("0005", "0000", "0000", "0000", "0000", "0000"),
    ("    ",) * 6,
    ("0675", "0675", "0683", "0674", "0691", "0680"),
    ("3727", "3740", "3737", "3767", "3833", "3783"),
)


def qrows(cur, sql, args=()):
    cur.execute(sql, args)
    names = [item.name for item in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def profile(values):
    if not values:
        return None
    a = np.asarray(values, dtype=float)
    p = np.percentile(a, [1, 5, 25, 50, 75, 95, 99])
    return {"n": len(a), "mean": float(a.mean()),
            "std_sample": float(a.std(ddof=1)) if len(a) > 1 else None,
            "min": float(a.min()), "p01": float(p[0]), "p05": float(p[1]),
            "p25": float(p[2]), "median": float(p[3]), "p75": float(p[4]),
            "p95": float(p[5]), "p99": float(p[6]), "max": float(a.max())}


def raw_seconds(value):
    if isinstance(value, str) and len(value) == 4 and value.isascii() \
            and value.isdigit() and value != "0000":
        return int(value) / 100
    return None


def key(day, venue, race_no):
    return (day, str(venue).zfill(2), str(race_no).zfill(2))


def boat_key(day, venue, race_no, boat):
    return key(day, venue, race_no) + (str(boat),)


def target_samples():
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        current, history, c3_baselines = {}, {}, {}
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("SHOW transaction_read_only")
            assert cur.fetchone()[0] == "on"
            for day in DATES:
                current[day] = qrows(cur, """
                    SELECT e.player_id,r.race_date,r.venue_code,r.race_no,
                      e.boat_no,p.exhibition_time_status,p.exhibition_time_seconds
                    FROM core.race r JOIN core.race_entry e USING(race_id)
                    LEFT JOIN core.race_boat_preinfo p
                      ON p.race_id=r.race_id AND p.boat_no=e.boat_no
                    WHERE r.race_date=%s ORDER BY r.venue_code,r.race_no,e.boat_no
                """, (day,))
                if not current[day]:
                    raise RuntimeError(f"no current entries on {day}")
                players = sorted({row["player_id"] for row in current[day]})
                history[day] = qrows(cur, """
                    SELECT player_id,race_date,venue_code,race_no,boat_no,
                      exhibition_time_status,exhibition_time_seconds FROM (
                    SELECT e.player_id,r.race_date,r.venue_code,r.race_no,e.boat_no,
                      p.exhibition_time_status,p.exhibition_time_seconds,
                      row_number() OVER (PARTITION BY e.player_id ORDER BY
                        r.race_date DESC,r.venue_code DESC,r.race_no DESC,
                        e.boat_no DESC) rn
                    FROM core.race_entry e JOIN core.race r USING(race_id)
                    LEFT JOIN core.race_boat_preinfo p
                      ON p.race_id=e.race_id AND p.boat_no=e.boat_no
                    WHERE e.player_id=ANY(%s) AND r.race_date>='2017-01-01'
                      AND r.race_date<%s) x WHERE rn<=50
                    ORDER BY player_id,rn
                """, (players, day))
                if any(row["race_date"] >= day for row in history[day]):
                    raise RuntimeError("same-day history leakage")
                cells = qrows(cur, """
                    SELECT r.venue_code,p.boat_no,count(*) AS all_n,
                      avg(p.exhibition_time_seconds) AS all_mean,
                      count(*) FILTER (WHERE r.race_date >=
                        (%s::date - INTERVAL '1 year')::date) AS year_n,
                      avg(p.exhibition_time_seconds) FILTER (WHERE r.race_date >=
                        (%s::date - INTERVAL '1 year')::date) AS year_mean
                    FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                    WHERE r.race_date>='2017-01-01' AND r.race_date<%s
                      AND p.exhibition_time_status='VALID'
                    GROUP BY r.venue_code,p.boat_no ORDER BY 1,2
                """, (day, day, day))
                c3_baselines[day] = {
                    window: {("exhibition", str(row["venue_code"]).zfill(2),
                              str(row["boat_no"])): float(row[mean_field])
                             for row in cells if row[mean_field] is not None}
                    for window, mean_field in (("all_history", "all_mean"),
                                               ("trailing_1y", "year_mean"))}
                c3_baselines[day]["counts"] = {
                    "all_history": [row["all_n"] for row in cells],
                    "trailing_1y": [row["year_n"] for row in cells]}
        return current, history, c3_baselines
    finally:
        conn.rollback()
        conn.close()


def read_prior_diagnostics():
    mapping = json.loads((ROOT / ".local/c4_mapping_readonly.json").read_text(
        encoding="utf-8"))
    carry = json.loads((ROOT / ".local/c4_carry_readonly.json").read_text(
        encoding="utf-8"))
    mapping_keys = {key(x["day"], x["venue"], x["race_no"])
                    for x in mapping["candidates"]}
    pair_keys = {(key(day, venue, before), key(day, venue, after))
                 for venue, day, before, after in carry["full_packet_pairs"]}
    if len(mapping_keys) != 79 or len(pair_keys) != 373:
        raise RuntimeError("existing diagnostics changed")
    return mapping_keys, pair_keys


def c3_zero_races(conn):
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='300s'")
        cur.execute("""SELECT DISTINCT c3.kaisai_nen||c3.kaisai_tsukihi,
            c3.kyoteijo_code,c3.race_no FROM public.brd_c3 c3
            WHERE c3.tenji_time='0000' AND EXISTS (
              SELECT 1 FROM public.brd_c4 c4
              WHERE c4.kaisai_nen=c3.kaisai_nen
                AND c4.kaisai_tsukihi=c3.kaisai_tsukihi
                AND c4.kyoteijo_code=c3.kyoteijo_code
                AND c4.race_no=c3.race_no)""")
        return {key(*row) for row in cur.fetchall()}


def c4_values(row, venue):
    _, isshu, hanshu, mawariashi, chokusen = row
    lap = hanshu if venue == "01" else isshu
    return {"lap_time": raw_seconds(lap),
            "mawariashi": raw_seconds(mawariashi),
            "chokusen": raw_seconds(chokusen)}


def source_c4(current, history, expected_mapping, expected_pairs):
    needed = set()
    for group in (current, history):
        for rows in group.values():
            for row in rows:
                needed.add(boat_key(row["race_date"].strftime("%Y%m%d"),
                                    row["venue_code"], row["race_no"], row["boat_no"]))
    conn = source_connection()
    try:
        zero_races = c3_zero_races(conn)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("""SELECT count(*),count(*) FILTER (WHERE valid_boats>0),
                count(*) FILTER (WHERE valid_boats=6),sum(valid_boats)
                FROM (SELECT count(*) FILTER (WHERE tenji_time ~ '^[0-9]{4}$'
                    AND tenji_time<>'0000') AS valid_boats
                  FROM public.brd_c3 WHERE kaisai_nen>='2017'
                  GROUP BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no) x""")
            c3_race_total, c3_race_any, c3_race_all, c3_boat_valid = cur.fetchone()
            cur.execute("SELECT min(kaisai_nen||kaisai_tsukihi),"
                        "max(kaisai_nen||kaisai_tsukihi) FROM public.brd_c4")
            period_first, period_last = cur.fetchone()
            cur.execute("""SELECT count(*),count(DISTINCT (kaisai_nen,
                kaisai_tsukihi,kyoteijo_code,race_no)) FROM public.brd_c3
                WHERE kaisai_nen||kaisai_tsukihi BETWEEN %s AND %s""",
                        (period_first, period_last))
            c3_rows_c4_period, c3_races_c4_period = cur.fetchone()
        c4_lookup = {}
        status = {}
        status_counts = Counter()
        gate_flags = Counter()
        observed_boats = Counter()
        observed_races = Counter()
        status_by_type = defaultdict(Counter)
        venue_boat = defaultdict(list)
        populations = defaultdict(list)
        baseline_acc = {d: {w: defaultdict(lambda: [0.0, 0])
                            for w in ("all_history", "trailing_1y")}
                        for d in DATES}
        detected_pairs = set()
        detected_later = set()
        prior = None
        ko_stats = Counter()
        source_races = 0
        source_boats = 0
        first_day = last_day = None
        extremes = defaultdict(dict)

        def process(race_key, rows):
            nonlocal prior, source_races, source_boats, first_day, last_day
            source_races += 1
            source_boats += len(rows)
            day, venue, number = race_key
            if first_day is None:
                first_day = day
            last_day = day
            slots = tuple(row[0] for row in rows)
            packet = tuple(tuple(row[i] for row in rows) for i in range(1, 5))
            if prior is not None:
                old_key, old_slots, old_packet = prior
                if old_key[:2] == race_key[:2] and int(number) == int(old_key[2])+1 \
                        and old_slots == SLOTS and slots == SLOTS \
                        and packet_is_informative(old_packet) and old_packet == packet:
                    detected_pairs.add((old_key, race_key))
                    detected_later.add(race_key)
            prior = (race_key, slots, packet)
            values = [(row[0], c4_values(row, venue)) for row in rows]
            basic_unsafe = slots != SLOTS or any(
                all(value is None for value in entry.values())
                for _, entry in values)
            if basic_unsafe:
                gate_flags["c4_structure"] += 1
            if race_key in zero_races:
                gate_flags["c3_0000"] += 1
            is_carry = race_key in detected_later
            if race_key == QUARANTINED_C4_RACE:
                if slots != SLOTS or packet != QUARANTINED_C4_PACKET \
                        or basic_unsafe or race_key in zero_races or is_carry:
                    raise RuntimeError("explicit quarantine source packet changed")
                gate_flags["explicit_packet_quarantine"] += 1
            if is_carry:
                gate_flags["carry_after"] += 1
            if is_carry:
                reason = "CARRY_FORWARD_INVALID"
            elif basic_unsafe:
                reason = "UNAVAILABLE_MAPPING"
            elif race_key in zero_races:
                reason = "UNAVAILABLE_MAPPING"
                gate_flags["c3_extra_after_c4_and_carry"] += 1
            elif race_key == QUARANTINED_C4_RACE:
                reason = "QUARANTINED_C4_PACKET"
            else:
                reason = "SAFE"
            status[race_key] = reason
            status_counts[reason] += 1
            if race_key in expected_mapping:
                ko_stats["mapping_total"] += 1
                ko_stats["mapping_excluded"] += reason != "SAFE"
            if venue == "16" and len(rows) == 5:
                ko_stats["kojima_five_rows"] += 1
                ko_stats["kojima_excluded"] += reason != "SAFE"
            day_date = date.fromisoformat(day[:4]+"-"+day[4:6]+"-"+day[6:])
            race_available = set()
            for boat, entry in values:
                full_key = race_key + (boat,)
                if full_key in needed and reason == "SAFE":
                    c4_lookup[full_key] = entry
                for time_type, seconds in entry.items():
                    if reason != "SAFE":
                        status_by_type[time_type][reason] += 1
                    elif venue in STRUCTURAL_NOT_PROVIDED[time_type]:
                        status_by_type[time_type]["NOT_PROVIDED"] += 1
                    elif seconds is None:
                        status_by_type[time_type]["MISSING_OTHER"] += 1
                    else:
                        status_by_type[time_type]["AVAILABLE"] += 1
                    if reason != "SAFE" or seconds is None:
                        continue
                    observed_boats[time_type] += 1
                    race_available.add(time_type)
                    raw_field = ("hanshu" if venue == "01" else "isshu") \
                        if time_type == "lap_time" else time_type
                    raw_value = rows[int(boat)-1][FIELDS.index(raw_field)+1] \
                        if slots == SLOTS else None
                    example = {"day": day, "venue": venue, "race_no": number,
                               "boat_no": boat, "source_field": raw_field,
                               "raw": raw_value, "seconds": seconds}
                    if "min" not in extremes[time_type] or \
                            seconds < extremes[time_type]["min"]["seconds"]:
                        extremes[time_type]["min"] = example
                    if "max" not in extremes[time_type] or \
                            seconds > extremes[time_type]["max"]["seconds"]:
                        extremes[time_type]["max"] = example
                    venue_boat[(time_type, venue, boat)].append(seconds)
                    populations[time_type].append(seconds)
                    for d in DATES:
                        if day_date >= d:
                            continue
                        cell = (time_type, venue, boat)
                        bucket = baseline_acc[d]["all_history"][cell]
                        bucket[0] += seconds
                        bucket[1] += 1
                        if day_date >= d.replace(year=d.year-1):
                            bucket = baseline_acc[d]["trailing_1y"][cell]
                            bucket[0] += seconds
                            bucket[1] += 1
            for time_type in race_available:
                observed_races[time_type] += 1

        with conn.cursor(name="c4_v1_stream") as cur:
            cur.itersize = 20000
            cur.execute("""SELECT kaisai_nen||kaisai_tsukihi AS day,
                kyoteijo_code,race_no,teiban,isshu,hanshu,mawariashi,chokusen
                FROM public.brd_c4 ORDER BY kaisai_nen,kaisai_tsukihi,
                  kyoteijo_code,race_no,teiban""")
            previous_key, group = None, []
            for day, venue, number, boat, *raw in cur:
                race_key = key(day, venue, number)
                if previous_key is not None and previous_key != race_key:
                    process(previous_key, group)
                    group = []
                group.append((boat, *raw))
                previous_key = race_key
            if group:
                process(previous_key, group)
        if detected_pairs != expected_pairs:
            raise RuntimeError(f"carry gate mismatch: missing={len(expected_pairs-detected_pairs)}, "
                               f"extra={len(detected_pairs-expected_pairs)}")
        after = {right for _, right in detected_pairs}
        starts = {left for left, _ in detected_pairs} - after
        by_left = {left: right for left, right in detected_pairs}
        chains = []
        for start in starts:
            length, node = 0, start
            while node in by_left:
                node = by_left[node]
                length += 1
            chains.append(length)
        if sum(chains) != 373 or len(after) != 373:
            raise RuntimeError("carry chain graph is inconsistent")
        if ko_stats != {"mapping_total": 79, "mapping_excluded": 79,
                        "kojima_five_rows": 11, "kojima_excluded": 11}:
            raise RuntimeError(f"known mapping gate failed: {ko_stats}")
        if gate_flags["c3_extra_after_c4_and_carry"] != 24:
            raise RuntimeError("C3 0000 additional exclusion is no longer 24")
        if gate_flags["explicit_packet_quarantine"] != 1 \
                or status.get(QUARANTINED_C4_RACE) != "QUARANTINED_C4_PACKET":
            raise RuntimeError("explicit quarantine was not applied exactly once")
        if (first_day, last_day) != (period_first, period_last):
            raise RuntimeError("source period changed within research snapshot")
        baselines = {}
        baseline_counts = {}
        for d in DATES:
            baselines[d] = {}
            baseline_counts[d] = {}
            for window in ("all_history", "trailing_1y"):
                cells = baseline_acc[d][window]
                baselines[d][window] = {cell: total/n for cell, (total, n)
                                        in cells.items() if n}
                baseline_counts[d][window] = {cell: n for cell, (_, n)
                                               in cells.items() if n}
        return {
            "source_races": source_races, "source_boats": source_boats,
            "source_first_day": first_day, "source_last_day": last_day,
            "c3_2017plus_races": c3_race_total,
            "c3_2017plus_races_any_valid": c3_race_any,
            "c3_2017plus_races_all_six_valid": c3_race_all,
            "c3_2017plus_valid_boats": c3_boat_valid,
            "c3_rows_in_c4_period": c3_rows_c4_period,
            "c3_races_in_c4_period": c3_races_c4_period,
            "zero_races": len(zero_races), "gate_flags": dict(gate_flags),
            "explicit_quarantine_race": list(QUARANTINED_C4_RACE),
            "status_counts": dict(status_counts), "known_audit": dict(ko_stats),
            "carry_pairs": len(detected_pairs), "carry_later_races": len(after),
            "carry_chains": dict(sorted(Counter(chains).items())),
            "carry_first_races_retained": sum(status.get(x) == "SAFE" for x in starts),
            "carry_first_race_status": dict(Counter(status.get(x) for x in starts)),
            "observed_boats": dict(observed_boats),
            "observed_races": dict(observed_races),
            "status_by_type": {t: dict(v) for t, v in status_by_type.items()},
            "population_seconds": {t: profile(v) for t, v in populations.items()},
            "extreme_seconds_examples": dict(extremes),
            "venue_boat_seconds": [
                {"time_type": t, "venue": v, "boat_no": int(b),
                 "distribution": profile(values)}
                for (t, v, b), values in sorted(venue_boat.items())],
        }, c4_lookup, baselines, baseline_counts, status
    finally:
        conn.rollback()
        conn.close()


def value_for(row, time_type, c4_lookup):
    if time_type == "exhibition":
        return float(row["exhibition_time_seconds"]) \
            if row["exhibition_time_status"] == "VALID" else None
    full_key = boat_key(row["race_date"].strftime("%Y%m%d"),
                        row["venue_code"], row["race_no"], row["boat_no"])
    entry = c4_lookup.get(full_key)
    return entry.get(time_type) if entry else None


def band(n):
    if n == 0:
        return "0"
    for lo, hi in ((1, 4), (5, 9), (10, 19), (20, 29), (30, 39), (40, 50)):
        if lo <= n <= hi:
            return f"{lo}-{hi}"
    raise ValueError(n)


def sample_characteristics(day, current, history, baselines, c4_lookup, pooled):
    prior_by_player = defaultdict(list)
    for row in history:
        prior_by_player[row["player_id"]].append(row)
    result = {}
    for time_type in TYPES:
        windows = {}
        for window in ("all_history", "trailing_1y"):
            base = baselines[window]
            history_stats = {}
            for player, races in prior_by_player.items():
                residuals = []
                for row in races:
                    seconds = value_for(row, time_type, c4_lookup)
                    cell = (time_type, str(row["venue_code"]).zfill(2),
                            str(row["boat_no"]))
                    if seconds is not None and cell in base:
                        residuals.append(seconds-base[cell])
                history_stats[player] = {
                    "history_n": len(races), "observed_n": len(residuals),
                    "mean": mean(residuals) if residuals else None,
                    "std": stdev(residuals) if len(residuals) >= 2 else None,
                }
            observed_n, availability, stds, z_values, residuals_now = [], [], [], [], []
            by_band = defaultdict(lambda: {"std": [], "z": []})
            z_by_key = {}
            z_details = []
            current_available = no_prior_two = zero_std = no_baseline = 0
            for row in current:
                stats = history_stats[row["player_id"]]
                n = stats["observed_n"]
                observed_n.append(n)
                availability.append(n/stats["history_n"] if stats["history_n"] else 0.0)
                group = by_band[band(n)]
                if window == "all_history":
                    pooled[time_type][band(n)]["boats"] += 1
                if stats["std"] is not None:
                    stds.append(stats["std"])
                    group["std"].append(stats["std"])
                    if window == "all_history":
                        pooled[time_type][band(n)]["std"].append(stats["std"])
                seconds = value_for(row, time_type, c4_lookup)
                if seconds is None:
                    continue
                current_available += 1
                cell = (time_type, str(row["venue_code"]).zfill(2),
                        str(row["boat_no"]))
                if cell not in base:
                    no_baseline += 1
                    continue
                now = seconds-base[cell]
                residuals_now.append(now)
                if stats["std"] is None:
                    no_prior_two += 1
                elif stats["std"] == 0:
                    zero_std += 1
                else:
                    z = (stats["mean"]-now)/stats["std"]
                    z_values.append(z)
                    group["z"].append(z)
                    if window == "all_history":
                        pooled[time_type][band(n)]["z"].append(z)
                    z_details.append({
                        "date": day.isoformat(), "venue": str(row["venue_code"]).zfill(2),
                        "race_no": int(row["race_no"]), "boat_no": int(row["boat_no"]),
                        "player_id": row["player_id"], "current_seconds": seconds,
                        "observed_n": n, "recent_mean_residual": stats["mean"],
                        "recent_std_residual": stats["std"], "z": z})
                    z_by_key[(row["venue_code"], row["race_no"],
                              row["boat_no"])] = z
            windows[window] = {
                "current_boats": len(current), "current_available": current_available,
                "history_rows": len(history),
                "history_n_distribution": dict(sorted(Counter(
                    history_stats[r["player_id"]]["history_n"] for r in current).items())),
                "observed_n_distribution": dict(sorted(Counter(observed_n).items())),
                "observed_n": profile(observed_n),
                "availability_rate": profile(availability),
                "residual_current_seconds": profile(residuals_now),
                "std_seconds": profile(stds),
                "std_zero_boats": sum(s == 0 for s in stds),
                "std_positive_below_0_001": sum(0 < s < .001 for s in stds),
                "std_positive_below_0_01": sum(0 < s < .01 for s in stds),
                "std_positive_below_0_05": sum(0 < s < .05 for s in stds),
                "z_no_two_prior_observations": no_prior_two,
                "z_zero_std": zero_std, "z_no_baseline": no_baseline,
                "candidate_z": profile(z_values),
                "z_abs_gt_5": sum(abs(z) > 5 for z in z_values),
                "z_abs_gt_10": sum(abs(z) > 10 for z in z_values),
                "largest_abs_z_examples": sorted(z_details,
                                                  key=lambda x: -abs(x["z"]))[:6],
                "bands": {name: {"boats_with_std": len(v["std"]),
                                  "std_seconds": profile(v["std"]),
                                  "candidate_z": profile(v["z"]),
                                  "z_abs_gt_5": sum(abs(z)>5 for z in v["z"])}
                          for name, v in sorted(by_band.items())},
            }
            windows[window]["_z_by_key"] = z_by_key
        a, b = windows["all_history"].pop("_z_by_key"), \
               windows["trailing_1y"].pop("_z_by_key")
        paired = set(a) & set(b)
        result[time_type] = {
            "windows": windows,
            "paired_candidate_z_abs_change": profile([abs(a[k]-b[k]) for k in paired]),
        }
    return result


def run():
    current, history, c3_base = target_samples()
    mapping, pairs = read_prior_diagnostics()
    c4, lookup, c4_base, c4_counts, _ = source_c4(current, history, mapping, pairs)
    samples = []
    pooled = defaultdict(lambda: defaultdict(lambda: {"boats": 0, "std": [], "z": []}))
    for d in DATES:
        base = {}
        counts = {}
        for window in ("all_history", "trailing_1y"):
            base[window] = dict(c3_base[d][window])
            base[window].update(c4_base[d][window])
            counts[window] = dict(c4_counts[d][window])
            for cell, n in zip(sorted(c3_base[d]["all_history"]),
                               c3_base[d]["counts"][window]):
                counts[window][cell] = n
        comparison = {}
        for time_type in TYPES:
            shared = {cell for cell in base["all_history"] if cell[0] == time_type} \
                     & {cell for cell in base["trailing_1y"] if cell[0] == time_type}
            comparison[time_type] = {
                "all_history_cells": sum(cell[0] == time_type for cell in base["all_history"]),
                "trailing_1y_cells": sum(cell[0] == time_type for cell in base["trailing_1y"]),
                "shared_cells": len(shared),
                "abs_cell_mean_gap_seconds": profile([
                    abs(base["all_history"][cell]-base["trailing_1y"][cell])
                    for cell in shared]),
                "all_history_cell_n": profile([
                    n for cell, n in counts["all_history"].items() if cell[0] == time_type]),
                "trailing_1y_cell_n": profile([
                    n for cell, n in counts["trailing_1y"].items() if cell[0] == time_type]),
            }
        samples.append({"day": d.isoformat(), "current_boats": len(current[d]),
                        "distinct_players": len({r["player_id"] for r in current[d]}),
                        "history_rows": len(history[d]),
                        "baseline_comparison": comparison,
                        "time_types": sample_characteristics(
                            d, current[d], history[d], base, lookup, pooled)})
    pooled_bands = {
        t: {name: {"current_boats": v["boats"],
                   "std_seconds": profile(v["std"]),
                   "candidate_z": profile(v["z"]),
                   "z_abs_gt_5": sum(abs(z)>5 for z in v["z"]),
                   "z_abs_gt_10": sum(abs(z)>10 for z in v["z"])}
            for name, v in sorted(bands.items())}
        for t, bands in pooled.items()}
    prior = json.loads((ROOT / "docs/pre_race_time_research_metrics.json").read_text(
        encoding="utf-8"))
    output = {
        "verdict": "PRE_RACE_TIME_CHARACTERISTICS_V1_RESEARCH_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only descriptive 2017+ C3 and 2023+ C4; eight sample dates through 2024; no K3/results/odds in gates or z",
        "gate": c4,
        "c3_population_seconds_prior_verified": prior["c3"]["population_seconds"],
        "c3_venue_boat_seconds_prior_verified": prior["c3"]["venue_boat_cells_seconds"],
        "sample_dates": samples,
        "pooled_observed_n_bands_all_history": pooled_bands,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str)+"\n",
                   encoding="utf-8")
    return output


if __name__ == "__main__":
    result = run()
    print(json.dumps({"output": str(OUT),
                      "source_races": result["gate"]["source_races"],
                      "safe_races": result["gate"]["status_counts"]["SAFE"],
                      "additional_c3_gate": result["gate"]["gate_flags"]["c3_extra_after_c4_and_carry"],
                      "carry_pairs": result["gate"]["carry_pairs"]}))
