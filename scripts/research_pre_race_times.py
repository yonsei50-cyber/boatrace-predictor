"""Read-only C3 timing feasibility and C4 raw-quality research.

The C4 fields are never interpreted as seconds or assigned to a different boat.
No result labels, odds, or 2025 model performance are queried.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from statistics import mean, median, stdev

from scripts.db import source_connection, target_connection


C4_FIELDS = ("isshu", "hanshu", "mawariashi", "chokusen")
VALID_RAW = re.compile(r"^[0-9]{4}$")


def fetch_dicts(cursor, sql, params=()):
    cursor.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def quantiles(values):
    if not values:
        return None
    ordered = sorted(values)

    def pct(p):
        location = (len(ordered) - 1) * p
        lo, hi = int(location), min(int(location) + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (location - lo)

    return {"n": len(ordered), "mean": mean(ordered),
            "std_sample": stdev(ordered) if len(ordered) > 1 else None,
            "min": ordered[0], "p01": pct(.01), "p05": pct(.05),
            "p25": pct(.25), "median": median(ordered), "p75": pct(.75),
            "p95": pct(.95), "p99": pct(.99), "max": ordered[-1]}


def c3_research(research_day):
    connection = target_connection()
    try:
        connection.commit()
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()[0] != "on":
                raise RuntimeError("target research transaction must be read-only")
            inventory = fetch_dicts(cur, """
                SELECT count(*) AS boat_rows,count(DISTINCT r.race_id) AS races,
                  min(r.race_date) AS first_day,max(r.race_date) AS last_day,
                  count(*) FILTER (WHERE p.exhibition_time_status='VALID') AS valid,
                  count(*) FILTER (WHERE p.exhibition_time_status='SOURCE_SENTINEL') AS sentinel,
                  count(*) FILTER (WHERE p.exhibition_time_status='MISSING') AS missing,
                  count(*) FILTER (WHERE p.exhibition_time_status='INVALID') AS invalid,
                  count(*)-count(DISTINCT (p.race_id,p.boat_no)) AS duplicate_keys
                FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                WHERE r.race_date>='2017-01-01'""")[0]
            identity = fetch_dicts(cur, """
                SELECT count(*) AS c3_boats,
                  count(*) FILTER (WHERE e.player_id IS NULL) AS missing_entry_player,
                  count(*) FILTER (WHERE e.boat_no IS NULL) AS missing_entry_boat
                FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                LEFT JOIN core.race_entry e
                  ON e.race_id=p.race_id AND e.boat_no=p.boat_no
                WHERE r.race_date>='2017-01-01'""")[0]
            population = fetch_dicts(cur, """
                SELECT count(*) AS n,avg(p.exhibition_time_seconds) AS mean,
                  stddev_samp(p.exhibition_time_seconds) AS std_sample,
                  min(p.exhibition_time_seconds) AS min,
                  percentile_cont(ARRAY[.01,.05,.25,.5,.75,.95,.99])
                    WITHIN GROUP (ORDER BY p.exhibition_time_seconds) AS quantiles,
                  max(p.exhibition_time_seconds) AS max
                FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                WHERE r.race_date>='2017-01-01'
                  AND p.exhibition_time_status='VALID'""")[0]
            cells = fetch_dicts(cur, """
                SELECT r.venue_code,p.boat_no,count(*) AS n,
                  avg(p.exhibition_time_seconds) AS mean,
                  percentile_cont(.5) WITHIN GROUP
                    (ORDER BY p.exhibition_time_seconds) AS median,
                  stddev_samp(p.exhibition_time_seconds) AS std_sample,
                  min(p.exhibition_time_seconds) AS min,
                  max(p.exhibition_time_seconds) AS max
                FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                WHERE r.race_date>='2017-01-01'
                  AND p.exhibition_time_status='VALID'
                GROUP BY r.venue_code,p.boat_no ORDER BY 1,2""")
            baseline = fetch_dicts(cur, """
                SELECT r.venue_code,p.boat_no,count(*) AS n,
                  avg(p.exhibition_time_seconds) AS mean,
                  stddev_samp(p.exhibition_time_seconds) AS std_sample
                FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
                WHERE r.race_date>='2017-01-01' AND r.race_date<%s
                  AND p.exhibition_time_status='VALID'
                GROUP BY r.venue_code,p.boat_no ORDER BY 1,2""", (research_day,))
            current = fetch_dicts(cur, """
                SELECT r.race_id,r.venue_code,r.race_no,e.boat_no,e.player_id,
                  p.exhibition_time_status,p.exhibition_time_seconds
                FROM core.race r JOIN core.race_entry e USING(race_id)
                LEFT JOIN core.race_boat_preinfo p
                  ON p.race_id=e.race_id AND p.boat_no=e.boat_no
                WHERE r.race_date=%s ORDER BY r.venue_code,r.race_no,e.boat_no""",
                (research_day,))
            if not current:
                raise ValueError(f"No entries on representative day {research_day}")
            players = sorted({row["player_id"] for row in current})
            history = fetch_dicts(cur, """
                SELECT player_id,race_date,venue_code,race_no,boat_no,
                  exhibition_time_status,exhibition_time_seconds FROM (
                  SELECT e.player_id,r.race_date,r.venue_code,r.race_no,e.boat_no,
                    p.exhibition_time_status,p.exhibition_time_seconds,
                    row_number() OVER (PARTITION BY e.player_id ORDER BY
                      r.race_date DESC,r.venue_code DESC,r.race_no DESC,e.boat_no DESC) AS rn
                  FROM core.race_entry e JOIN core.race r USING(race_id)
                  LEFT JOIN core.race_boat_preinfo p
                    ON p.race_id=e.race_id AND p.boat_no=e.boat_no
                  WHERE e.player_id=ANY(%s) AND r.race_date>='2017-01-01'
                    AND r.race_date<%s
                ) x WHERE rn<=50 ORDER BY player_id,rn""",
                (players, research_day))

        base = {(row["venue_code"], row["boat_no"]): float(row["mean"])
                for row in baseline}
        player_history = defaultdict(list)
        for row in history:
            player_history[row["player_id"]].append(row)
        player_stats = {}
        for player in players:
            rows = player_history[player]
            residuals = [float(row["exhibition_time_seconds"]) -
                         base[(row["venue_code"], row["boat_no"])]
                         for row in rows if row["exhibition_time_status"] == "VALID"
                         and (row["venue_code"], row["boat_no"]) in base]
            player_stats[player] = {"history_n_races": len(rows),
                                    "observed_n": len(residuals),
                                    "availability_rate": len(residuals) / len(rows) if rows else None,
                                    "residual_mean": mean(residuals) if residuals else None,
                                    "residual_std_sample": stdev(residuals) if len(residuals) > 1 else None}
        z_values = []
        current_valid = current_without_history = zero_std = 0
        for row in current:
            if row["exhibition_time_status"] != "VALID":
                continue
            current_valid += 1
            stat = player_stats[row["player_id"]]
            sd = stat["residual_std_sample"]
            if sd is None:
                current_without_history += 1
            elif sd == 0:
                zero_std += 1
            else:
                key = (row["venue_code"], row["boat_no"])
                if key in base:
                    residual = float(row["exhibition_time_seconds"]) - base[key]
                    z_values.append((stat["residual_mean"] - residual) / sd)
        stats = list(player_stats.values())
        observed = Counter(s["observed_n"] for s in stats)
        history_depth = Counter(s["history_n_races"] for s in stats)
        stds = [s["residual_std_sample"] for s in stats
                if s["residual_std_sample"] is not None]
        return {"inventory": inventory, "natural_key_identity": identity,
                "population_seconds": population,
                "venue_boat_cells_seconds": cells,
                "representative_day": research_day.isoformat(),
                "baseline_training_end_exclusive": research_day.isoformat(),
                "baseline_cells": baseline,
                "current_boats": len(current), "current_valid": current_valid,
                "distinct_players": len(players), "history_rows_fetched": len(history),
                "history_n_races_distribution": dict(sorted(history_depth.items())),
                "observed_n_distribution": dict(sorted(observed.items())),
                "players_under_50_history": sum(s["history_n_races"] < 50 for s in stats),
                "players_with_zero_observed": observed[0],
                "players_with_observed_below_2": sum(s["observed_n"] < 2 for s in stats),
                "players_with_zero_std": sum(s["residual_std_sample"] == 0 for s in stats),
                "residual_std_distribution": quantiles(stds),
                "player_residual_mean_distribution": quantiles([
                    s["residual_mean"] for s in stats if s["residual_mean"] is not None]),
                "players_with_std_below_0_01s": sum(0 < s["residual_std_sample"] < .01
                                                     for s in stats if s["residual_std_sample"] is not None),
                "current_without_two_observed": current_without_history,
                "current_with_zero_std": zero_std,
                "candidate_z_distribution": quantiles(z_values),
                "candidate_z_abs_above_5": sum(abs(z) > 5 for z in z_values),
                "candidate_z_abs_above_10": sum(abs(z) > 10 for z in z_values),
                "availability_rate_distribution": quantiles([
                    s["availability_rate"] for s in stats
                    if s["availability_rate"] is not None]),
                "same_day_history_excluded": all(row["race_date"] < research_day
                                                 for row in history)}
    finally:
        connection.rollback()
        connection.close()


def c4_research():
    connection = source_connection()
    try:
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()[0] != "on":
                raise RuntimeError("source research transaction must be read-only")
            inventory = fetch_dicts(cur, """
                SELECT count(*) AS boat_rows,
                  count(DISTINCT (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)) AS races,
                  min(kaisai_nen||kaisai_tsukihi) AS first_day,
                  max(kaisai_nen||kaisai_tsukihi) AS last_day,
                  count(DISTINCT kyoteijo_code) AS venues,
                  count(*)-count(DISTINCT (kaisai_nen,kaisai_tsukihi,
                    kyoteijo_code,race_no,teiban)) AS duplicate_keys
                FROM public.brd_c4 WHERE kaisai_nen>='2017'""")[0]
            race_rows = fetch_dicts(cur, """
                SELECT n AS boat_rows,count(*) AS races FROM (
                  SELECT count(*) AS n FROM public.brd_c4 WHERE kaisai_nen>='2017'
                  GROUP BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no
                ) x GROUP BY 1 ORDER BY 1""")
            incomplete = fetch_dicts(cur, """
                SELECT kaisai_nen||kaisai_tsukihi AS day,kyoteijo_code AS venue,
                  race_no,count(*) AS boat_rows,array_agg(teiban ORDER BY teiban) AS boat_slots
                FROM public.brd_c4 WHERE kaisai_nen>='2017'
                GROUP BY 1,2,3 HAVING count(*)<>6 ORDER BY 1,2,3""")
            year_venue_source = {}
            for table in ("brd_c3", "brd_c4"):
                year_venue_source[table] = fetch_dicts(cur, f"""
                    SELECT kaisai_nen AS year,kyoteijo_code AS venue,
                      count(*) AS boats,count(DISTINCT (kaisai_tsukihi,race_no)) AS races,
                      min(kaisai_nen||kaisai_tsukihi) AS first_day,
                      max(kaisai_nen||kaisai_tsukihi) AS last_day
                    FROM public.{table} WHERE kaisai_nen>='2017'
                    GROUP BY 1,2 ORDER BY 1,2""")
            identity = fetch_dicts(cur, """
                SELECT count(*) AS c4_rows,
                  count(*) FILTER (WHERE l.teiban IS NULL) AS missing_l3_boat,
                  count(*) FILTER (WHERE c3.teiban IS NULL) AS missing_c3_boat,
                  count(*) FILTER (WHERE l.toroku_bango IS NULL
                    OR btrim(l.toroku_bango)='') AS missing_l3_player
                FROM public.brd_c4 c4 LEFT JOIN public.brd_l3 l
                  ON l.kaisai_nen=c4.kaisai_nen
                  AND l.kaisai_tsukihi=c4.kaisai_tsukihi
                  AND l.kyoteijo_code=c4.kyoteijo_code
                  AND l.race_no=c4.race_no AND l.teiban=c4.teiban
                LEFT JOIN public.brd_c3 c3
                  ON c3.kaisai_nen=c4.kaisai_nen
                  AND c3.kaisai_tsukihi=c4.kaisai_tsukihi
                  AND c3.kyoteijo_code=c4.kyoteijo_code
                  AND c3.race_no=c4.race_no AND c3.teiban=c4.teiban
                WHERE c4.kaisai_nen>='2017'""")[0]
            race_observation = fetch_dicts(cur, """
                SELECT count(*) AS boat_rows,
                  count(*) FILTER (WHERE isshu ~ '^[0-9]{4}$'
                    AND isshu<>'0000') AS isshu_observed,
                  count(*) FILTER (WHERE hanshu ~ '^[0-9]{4}$'
                    AND hanshu<>'0000') AS hanshu_observed,
                  count(*) FILTER (WHERE mawariashi ~ '^[0-9]{4}$'
                    AND mawariashi<>'0000') AS mawariashi_observed,
                  count(*) FILTER (WHERE chokusen ~ '^[0-9]{4}$'
                    AND chokusen<>'0000') AS chokusen_observed
                FROM public.brd_c4 WHERE kaisai_nen>='2017'
                GROUP BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no""")
            race_obs_distributions = {f: Counter() for f in C4_FIELDS}
            for row in race_observation:
                for field in C4_FIELDS:
                    race_obs_distributions[field][row[field + "_observed"]] += 1
        groups = defaultdict(lambda: {f: Counter() for f in C4_FIELDS})
        group_codes = defaultdict(lambda: {f: Counter() for f in C4_FIELDS})
        raw_counts = {f: Counter() for f in C4_FIELDS}
        raw_codes = {f: Counter() for f in C4_FIELDS}
        day_bounds = {f: [None, None] for f in C4_FIELDS}
        with connection.cursor(name="c4_research_raw") as cur:
            cur.itersize = 20000
            cur.execute("""SELECT kaisai_nen||kaisai_tsukihi AS day,
                kyoteijo_code,teiban,isshu,hanshu,mawariashi,chokusen
                FROM public.brd_c4 WHERE kaisai_nen>='2017'""")
            for day, venue, boat, *values in cur:
                for field, value in zip(C4_FIELDS, values):
                    if value is None:
                        status = "NULL"
                    elif not value.strip():
                        status = "BLANK"
                    elif value == "0000":
                        status = "SENTINEL_0000"
                    elif VALID_RAW.fullmatch(value):
                        status = "FOUR_DIGIT_NONZERO"
                        raw_codes[field][int(value)] += 1
                        group_codes[(venue, boat)][field][int(value)] += 1
                        bounds = day_bounds[field]
                        bounds[0] = min(bounds[0], day) if bounds[0] else day
                        bounds[1] = max(bounds[1], day) if bounds[1] else day
                    else:
                        status = "OTHER"
                    raw_counts[field][status] += 1
                    raw_counts[field]["TOTAL"] += 1
                    groups[(venue, boat)][field][status] += 1
                    groups[(venue, boat)][field]["TOTAL"] += 1
        by_venue_boat = []
        for (venue, boat), fields in sorted(groups.items()):
            by_venue_boat.append({"venue": venue, "boat_no_raw": boat,
                                  "fields": {f: {"shape_counts": dict(fields[f]),
                                                 "numeric_raw_code_distribution":
                                                 quantiles(list(group_codes[(venue, boat)][f].elements()))}
                                             for f in C4_FIELDS}})
        field_summary = {}
        for field in C4_FIELDS:
            codes = raw_codes[field]
            expanded = sorted(codes.elements())
            field_summary[field] = {"shape_counts": dict(raw_counts[field]),
                                    "distinct_numeric_raw_codes": len(codes),
                                    "numeric_raw_code_distribution": quantiles(expanded),
                                    "top_numeric_raw_codes": codes.most_common(10),
                                    "first_last_numeric_raw_day": day_bounds[field]}
        return {"inventory": inventory, "boats_per_race": race_rows,
                "race_observed_boats_distribution": {f: dict(sorted(c.items()))
                                                      for f, c in race_obs_distributions.items()},
                "incomplete_races": incomplete,
                "year_venue_source_coverage": year_venue_source,
                "natural_key_identity": identity, "field_summary": field_summary,
                "venue_boat_raw_shapes": by_venue_boat}
    finally:
        connection.rollback()
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", type=date.fromisoformat, default=date(2024, 12, 31))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
              "policy": "read-only; C4 four-digit raw codes are not seconds",
              "c3": c3_research(args.day), "c4": c4_research()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "c3_current_boats": result["c3"]["current_boats"],
                      "c3_candidate_z_n": result["c3"]["candidate_z_distribution"]["n"]
                        if result["c3"]["candidate_z_distribution"] else 0,
                      "c4_rows": result["c4"]["inventory"]["boat_rows"]}))


if __name__ == "__main__":
    main()
