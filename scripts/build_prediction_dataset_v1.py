"""Build the K3-only Prediction Dataset v1 from frozen D-1 feature methods.

The table and all rows commit together. An existing table is never replaced.
No model fit, target association, or 2025 performance calculation occurs here.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import date, timedelta
import csv
import hashlib
from io import StringIO
from itertools import chain
import json
from pathlib import Path
import re

from scripts.compare_rating_methods import ESTABLISHED, NEWCOMER_UNCERTAIN, Entry, Race
from scripts.db import target_connection
from scripts.entry_course_index_v1 import (
    COURSES, EDOGAWA_VENUE_CODE, CourseEntry, CourseRace,
    eligible as course_eligible, probabilities_from_counts, window_start,
)
from scripts.f_suspension_k3_only_probe import State, prediction_features
from scripts.motor_a_v1 import MotorIdentity, READY, NOT_EVALUABLE
from scripts.reevaluate_motor_a_v1_k3 import meeting_map
from scripts.reevaluate_rating_v1_k3 import checked_freeze, frozen_models


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'sql/migrations/0009_prediction_dataset_v1.sql'
F_SEED = ROOT / 'artifacts/f_suspension_initial_seed_k3_v1.json'
F_FREEZE = ROOT / 'artifacts/f_suspension_method_freeze_v1.json'
RESULT_VERSION = 'K3_ONLY_RESULT_V1_b68a27cf8f653602'
FIRST_DAY = date(2017, 1, 1)
END_EXCLUSIVE = date(2027, 1, 1)

EXTRACT = """
SELECT r.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
       e.motor_id,m.generation_start_year,m.generation_start_date,
       m.generation_end_date,m.motor_no,m.identity_rule_version,
       e.national_win_rate,e.national_win_rate_status,
       e.f_count_current_term_raw,e.f_count_current_term,
       b.finish_state,b.finish_position,b.actual_course,
       rs.result_state,rs.has_verified_r2_event_code,
       z.finish_position AS k3_finish_position,z.finish_raw,z.start_timing_raw,
       z.race_id IS NOT NULL AS has_k3_result,
       zb.source_table AS result_source,eb.source_table AS entry_source
FROM core.race r
JOIN core.race_entry e USING(race_id)
LEFT JOIN core.motor m ON m.motor_id=e.motor_id
LEFT JOIN core.boat_finish_state b ON b.race_id=e.race_id AND b.boat_no=e.boat_no
LEFT JOIN core.race_result_state rs ON rs.race_id=r.race_id
LEFT JOIN core.race_result z ON z.race_id=e.race_id AND z.boat_no=e.boat_no
LEFT JOIN raw.source_record zs ON zs.source_record_id=z.source_record_id
LEFT JOIN raw.source_batch zb ON zb.source_batch_id=zs.source_batch_id
JOIN raw.source_record es ON es.source_record_id=e.source_record_id
JOIN raw.source_batch eb ON eb.source_batch_id=es.source_batch_id
WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2027-01-01'
ORDER BY r.race_date,r.venue_code,r.race_no,r.race_id,e.boat_no
"""

COLUMNS = (
    'race_id race_date venue_code race_no boat_no player_id motor_id '
    'feature_cutoff_date national_win_rate national_win_rate_status '
    'rating_first_course_1_to_6 rating_exact_second_course_1_to_6 '
    'rating_overall rating_short_50 rating_player_status '
    'rating_short_50_history_count entry_course_prob_1_to_6 '
    'entry_course_status entry_course_history_count f_suspension_state '
    'has_unserved_f_suspension current_term_f_count current_term_f_count_status '
    'motor_a_base3 motor_a_base3_status base_n_meetings base_n_uses '
    'base_residual_sum motor_a_current motor_a_current_status current_n_uses '
    'label_eligible label_p1 label_p2'
).split()


def seed_states():
    freeze = json.loads(F_FREEZE.read_text(encoding='utf-8'))
    actual = hashlib.sha256(F_SEED.read_bytes()).hexdigest()
    expected = freeze['evidence']['initial_seed_artifact_sha256'].lower()
    if actual != expected or freeze['status'] != 'METHOD_FROZEN':
        raise RuntimeError('F Suspension v1 seed/freeze identity changed')
    artifact = json.loads(F_SEED.read_text(encoding='utf-8'))
    if (artifact['status'] != 'PASS' or artifact['cohort_players'] != 617
            or artifact['active'] != 48 or artifact['unresolved'] != 569):
        raise RuntimeError('F Suspension v1 seed population changed')
    return {p['player_id']: date.fromisoformat(p['latest_f_date'])
            for p in artifact['players'] if p['state'] == 'ACTIVE_UNSERVED'}


def f_evidence(row):
    if not row['has_k3_result']:
        return (0, 0, 0) if row['has_verified_r2_event_code'] else (0, 1, 0)
    token = (row['finish_raw'] or '').strip()
    if token == 'F':
        return 1, 0, 1
    if token in ('01', '02', '03', '04', '05', '06', 'L0', 'L1'):
        return 1, 0, 0
    if token.startswith('K'):
        return 0, 0, 0
    if row['start_timing_raw'] is not None and re.fullmatch(r'[0-9]{3}', row['start_timing_raw']):
        return 1, 0, 0
    return 0, 1, 0


def current_term_value(row):
    raw, parsed = row['f_count_current_term_raw'], row['f_count_current_term']
    if (row['entry_source'] != 'brd_l3' or raw is None or parsed is None
            or not re.fullmatch(r'[0-9]+', raw.strip())
            or int(raw.strip()) != parsed):
        return None
    return parsed


def label_flags(rows):
    finishes = [r['finish_position'] for r in rows]
    return (len(rows) == 6 and {r['boat_no'] for r in rows} == set(COURSES)
            and all(r['result_state'] == 'RESULT_RECORDS_PRESENT'
                    and r['has_k3_result'] and r['result_source'] == 'brd_k3'
                    and r['finish_state'] == 'NUMERIC_VALID'
                    and r['k3_finish_position'] == r['finish_position'] for r in rows)
            and sorted(finishes) == list(COURSES))


def rating_race(rows):
    first = rows[0]
    entries = tuple(Entry(r['boat_no'], r['player_id'], r['finish_state'],
                          r['finish_position'], r['actual_course'], r['has_k3_result'])
                    for r in rows)
    strict = label_flags(rows)
    return Race(first['race_id'], first['race_date'], first['venue_code'],
                first['race_no'], first['result_state'], strict, entries)


def pg_array(values):
    return '{' + ','.join(format(float(v), '.17g') for v in values) + '}'


def copy_day(cur, rows):
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    for row in rows:
        writer.writerow(['\\N' if value is None else value for value in row])
    buffer.seek(0)
    cur.copy_expert('COPY core.prediction_dataset_v1 (' + ','.join(COLUMNS)
                    + ") FROM STDIN WITH (FORMAT csv, NULL '\\N')", buffer)


class Builder:
    def __init__(self, meeting_days, seed):
        self.rating = frozen_models(checked_freeze())
        self.seen_players = set()
        self.f_states = {}
        self.f_seed = seed
        self.course_history = deque()
        self.course_totals = {boat: [0] * 6 for boat in COURSES}
        self.meeting_days = meeting_days
        self.meeting_ends = defaultdict(set)
        for (venue, _), info in meeting_days.items():
            if info.status == 'CERTIFIED' and info.end is not None:
                self.meeting_ends[info.end].add((venue, info.start))
        self.certified = {x for groups in self.meeting_ends.values() for x in groups}
        self.motor_sum = defaultdict(float)
        self.motor_n = Counter()
        self.meeting_motors = defaultdict(set)
        self.completed = defaultdict(list)
        self.last_meeting = {}
        self.counts = defaultdict(Counter)

    def process_day(self, day, races):
        if any(r['race_date'] != day for rows in races for r in rows):
            raise RuntimeError('day grouping changed')
        players = {r['player_id'] for rows in races for r in rows}
        statuses = {p: ESTABLISHED if p in self.seen_players else NEWCOMER_UNCERTAIN
                    for p in players}
        for model in self.rating:
            model.prepare_day(players, statuses)
        start = window_start(day)
        while self.course_history and self.course_history[0][0] < start:
            _, expired = self.course_history.popleft()
            for boat in COURSES:
                for course in range(6):
                    self.course_totals[boat][course] -= expired[boat][course]
        if self.course_history and self.course_history[-1][0] >= day:
            raise RuntimeError('D course result entered D prediction state')
        course_before = {boat: probabilities_from_counts(tuple(self.course_totals[boat]))
                         for boat in COURSES}
        player_rows = defaultdict(list)
        for rows in races:
            for row in rows:
                player_rows[row['player_id']].append(row)
        f_before = {}
        f_events = {}
        term_values = {}
        for player, entries in player_rows.items():
            state = self.f_states.setdefault(player, State(self.f_seed.get(player)))
            before = ('CLEAR' if state.value != 'CLEAR'
                      and (day - state.last_possible_race).days >= 30 else state.value)
            f_before[player] = prediction_features(before)
            evidence = Counter()
            for row in entries:
                confirmed, possible, f = f_evidence(row)
                evidence['confirmed'] += confirmed
                evidence['possible'] += possible
                evidence['f'] += f
            f_events[player] = evidence
            values = [current_term_value(row) for row in entries]
            term_values[player] = values[0] if (all(v is not None for v in values)
                                                 and len(set(values)) == 1) else None
        pending_motor = []
        output = []
        rating_races = []
        course_updates = {boat: [0] * 6 for boat in COURSES}
        for rows in races:
            race = rating_race(rows)
            rating_races.append(race)
            first = rows[0]
            course_race = CourseRace(day, first['venue_code'], first['result_state'],
                                     tuple(CourseEntry(r['boat_no'], r['actual_course'],
                                                       r['finish_position'], r['has_k3_result'])
                                           for r in rows))
            if first['venue_code'] != EDOGAWA_VENUE_CODE and course_eligible(course_race):
                for row in rows:
                    course_updates[row['boat_no']][row['actual_course'] - 1] += 1
            labels_ok = label_flags(rows)
            if labels_ok and len(rows) != 6:
                raise RuntimeError('eligible race is not six boats')
            for row in rows:
                boat, player = row['boat_no'], row['player_id']
                venue = row['venue_code']
                course = course_before[boat]
                if venue == EDOGAWA_VENUE_CODE:
                    course_values = [float(k == boat) for k in COURSES]
                    course_status = 'EDOGAWA_MODEL_RULE'
                else:
                    course_values = course.probabilities
                    course_status = course.status
                rating_first = [series[player] for series in self.rating[0].first]
                rating_second = [series[player] for series in self.rating[0].second]
                motor = (MotorIdentity(venue, row['generation_start_year'], row['motor_no'])
                         if row['generation_start_year'] is not None
                         and row['motor_no'] is not None else None)
                info = self.meeting_days.get((venue, day))
                if info is None:
                    raise RuntimeError(f'missing source meeting day: {venue} {day}')
                meeting = (venue, info.start) if info.current_known else None
                if motor is not None:
                    previous = self.last_meeting.get(motor)
                    if meeting is None:
                        self.completed[motor].clear()
                        self.last_meeting[motor] = None
                    elif previous != meeting:
                        if previous is not None and previous not in self.certified:
                            self.completed[motor].clear()
                        self.last_meeting[motor] = meeting
                    if meeting is not None:
                        self.meeting_motors[meeting].add(motor)
                selected = self.completed[motor][-3:] if motor is not None and meeting else []
                current_n = self.motor_n[(motor, meeting)] if motor is not None and meeting else 0
                base = sum(item[1] for item in selected) / len(selected) if selected else None
                current = (self.motor_sum[(motor, meeting)] / current_n if current_n else None)
                if (motor is not None and row['identity_rule_version'] != 'user-fixed-month-day-v1'):
                    raise RuntimeError('motor identity rule changed')
                if (motor is not None and not row['generation_start_date'] <= day
                        < row['generation_end_date']):
                    raise RuntimeError('motor generation period changed')
                if (motor is not None and row['has_k3_result']
                        and row['finish_state'] == 'NUMERIC_VALID'
                        and row['finish_position'] in range(1, 7)
                        and row['k3_finish_position'] == row['finish_position']
                        and row['national_win_rate_status'] == 'VALID'
                        and row['national_win_rate'] is not None):
                    points = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}
                    residual = points[row['finish_position']] - float(row['national_win_rate'])
                    pending_motor.append((motor, meeting, residual))
                f = f_before[player]
                term = term_values[player]
                out = (
                    row['race_id'], day.isoformat(), venue, row['race_no'], boat, player,
                    row['motor_id'], (day - timedelta(days=1)).isoformat(),
                    row['national_win_rate'], row['national_win_rate_status'],
                    pg_array(rating_first), pg_array(rating_second),
                    self.rating[1].ratings[player], self.rating[2]._current_value(player),
                    statuses[player], len(self.rating[2].history.get(player, ())),
                    pg_array(course_values) if course_values is not None else None,
                    course_status, sum(self.course_totals[boat]),
                    f['f_suspension_state'], f['has_unserved_f_suspension'],
                    term, 'VALID' if term is not None else 'UNRESOLVED',
                    base, READY if base is not None else NOT_EVALUABLE,
                    len(selected), sum(item[2] for item in selected),
                    sum(item[1] * item[2] for item in selected),
                    current, READY if current is not None else NOT_EVALUABLE,
                    current_n, labels_ok,
                    int(row['finish_position'] == 1) if labels_ok else None,
                    int(row['finish_position'] == 2) if labels_ok else None,
                )
                output.append(out)
                self.counts[day.year]['rows'] += 1
                self.counts[day.year]['label_eligible_rows'] += int(labels_ok)
                for name, missing in (
                    ('national_rate_missing', row['national_win_rate'] is None),
                    ('entry_course_missing', course_values is None),
                    ('f_unresolved', f['f_suspension_state'] == 'UNRESOLVED'),
                    ('current_term_f_missing', term is None),
                    ('motor_base_missing', base is None),
                    ('motor_current_missing', current is None),
                ):
                    self.counts[day.year][name] += int(missing)
            self.counts[day.year]['races'] += 1
            self.counts[day.year]['label_eligible_races'] += int(labels_ok)
        for player, evidence in f_events.items():
            result = self.f_states[player].day(day, evidence['confirmed'],
                                               evidence['possible'], evidence['f'])
            if result['before'] != f_before[player]['f_suspension_state']:
                raise RuntimeError('F D-1 state changed during D')
        pending_first = [self.rating[0].deltas(race) for race in rating_races
                         if self.rating[0].update_eligible(race)]
        pending_overall = [self.rating[1].deltas(race) for race in rating_races
                           if self.rating[1].update_eligible(race)]
        if pending_first:
            self.rating[0].apply(self.rating[0].combine_day(pending_first))
        if pending_overall:
            self.rating[1].apply(self.rating[1].combine_day(pending_overall))
        for model in self.rating:
            model.after_day(rating_races)
        self.seen_players.update(players)
        for motor, meeting, residual in pending_motor:
            if meeting is None:
                self.completed[motor].clear()
            else:
                self.motor_sum[(motor, meeting)] += residual
                self.motor_n[(motor, meeting)] += 1
        for meeting in self.meeting_ends.get(day, ()):
            for motor in self.meeting_motors.get(meeting, ()):
                key = (motor, meeting)
                if self.motor_n[key]:
                    self.completed[motor].append((meeting,
                        self.motor_sum[key] / self.motor_n[key], self.motor_n[key]))
        if any(self.course_totals[boat] != [sum(x[1][boat][k] for x in self.course_history)
                                               for k in range(6)] for boat in COURSES):
            raise RuntimeError('course history/totals diverged before D update')
        for boat in COURSES:
            for k in range(6):
                self.course_totals[boat][k] += course_updates[boat][k]
        self.course_history.append((day, course_updates))
        return output


def read_days(cursor):
    first = cursor.fetchone()
    if first is None:
        return
    columns = [c.name for c in cursor.description]
    current_day = current_race = None
    races, race_rows = [], []
    for values in chain((first,), cursor):
        row = dict(zip(columns, values))
        if row['has_k3_result'] and row['result_source'] != 'brd_k3':
            raise RuntimeError('non-K3 individual result in dataset input')
        if current_day is not None and row['race_date'] != current_day:
            races.append(race_rows)
            yield current_day, races
            races, race_rows = [], []
            current_race = None
        if current_race is not None and row['race_id'] != current_race:
            races.append(race_rows)
            race_rows = []
        current_day, current_race = row['race_date'], row['race_id']
        race_rows.append(row)
    if race_rows:
        races.append(race_rows)
        yield current_day, races


def verify(cur, expected):
    cur.execute("""SELECT count(*),count(DISTINCT (race_id,boat_no)),
        count(*) FILTER (WHERE feature_cutoff_date<>race_date-1)
        FROM core.prediction_dataset_v1""")
    rows, unique, leakage = cur.fetchone()
    if rows != expected or unique != expected or leakage:
        raise RuntimeError(f'dataset grain/cutoff failed: {rows}/{unique}/{leakage}')
    cur.execute("""SELECT count(*) FROM (
        SELECT race_id,count(*) AS n,sum(label_p1) AS p1,sum(label_p2) AS p2
        FROM core.prediction_dataset_v1 WHERE label_eligible
        GROUP BY race_id HAVING count(*)<>6 OR sum(label_p1)<>1 OR sum(label_p2)<>1
    ) bad""")
    if cur.fetchone()[0]:
        raise RuntimeError('eligible race six-boat/P1/P2 invariant failed')
    cur.execute("""SELECT count(*) FROM core.prediction_dataset_v1
        WHERE NOT label_eligible AND (label_p1 IS NOT NULL OR label_p2 IS NOT NULL)""")
    if cur.fetchone()[0]:
        raise RuntimeError('special or missing result became a zero label')


def main():
    seed = seed_states()
    checked_freeze()
    # Read source meeting markers using the frozen Motor A reconstruction.
    meeting_days, _ = meeting_map(END_EXCLUSIVE)
    reader = target_connection()
    writer = target_connection()
    reader.commit()
    reader.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with reader.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute("""SELECT version_id,authoritative_source,normalization_version
                FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1""")
            if cur.fetchone() != (RESULT_VERSION, 'brd_k3', 'k3-only-result-v1'):
                raise RuntimeError('K3-only result dataset version changed')
        with writer.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute("SELECT to_regclass('core.prediction_dataset_v1')")
            if cur.fetchone()[0] is not None:
                raise RuntimeError('prediction dataset already exists; refusing overwrite')
            cur.execute(MIGRATION.read_text(encoding='utf-8'))
        builder = Builder(meeting_days, seed)
        count = 0
        with reader.cursor(name='prediction_dataset_v1_scan') as scan:
            scan.itersize = 10000
            scan.execute(EXTRACT)
            with writer.cursor() as cur:
                for day, races in read_days(scan):
                    output = builder.process_day(day, races)
                    copy_day(cur, output)
                    count += len(output)
                    if day.day == 1:
                        print(json.dumps({'date': str(day), 'rows': count}), flush=True)
                verify(cur, count)
        writer.commit()
        print(json.dumps({'verdict': 'PREDICTION_DATASET_V1_READY',
                          'rows': count, 'by_year': builder.counts},
                         sort_keys=True), flush=True)
    except Exception:
        writer.rollback()
        raise
    finally:
        reader.rollback()
        reader.close()
        writer.close()


if __name__ == '__main__':
    main()
