"""Read-only K3 Canonical replay of the unchanged Entry Course Index v1."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import date
import hashlib
import json
import math
from pathlib import Path

from scripts.db import target_connection
from scripts.entry_course_index_v1 import (
    COURSES, EDOGAWA_VENUE_CODE, NOT_EVALUABLE, CourseEntry, CourseRace,
    eligible, probabilities_from_counts, window_start,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'artifacts/entry_course_index_method_freeze_v1.json'
REFERENCE = ROOT / 'scripts/entry_course_index_v1.py'
OLD_DEV = ROOT / '.local/entry_course_development_2017_2024.json'
OLD_2025 = ROOT / 'artifacts/entry_course_index_v1_holdout_2025.json'
DEV_OUT = ROOT / 'artifacts/entry_course_index_v1_k3_2023_2024.json'
HOLDOUT_OUT = ROOT / 'artifacts/entry_course_index_v1_k3_2025.json'
COMPARISON_OUT = ROOT / 'artifacts/entry_course_index_v1_k3_comparison.json'
REPORT_OUT = ROOT / 'docs/entry_course_index_v1_k3_source_corrected_report.md'
REPLAY_OUT = ROOT / 'artifacts/entry_course_index_v1_k3_replay_identity.json'
VERIFY_OUT = ROOT / 'artifacts/entry_course_index_v1_k3_verification.json'
FREEZE_SHA256 = '00233686ff49bca92e09645eb9177aecddd83d141f1a9478a5e6365a89374453'
SOURCE_POLICY_CHECKPOINT = 'fd49bffe83b2f23443ec5f525786c0dd309abe95'
EXPECTED_RESULT_VERSION = 'K3_ONLY_RESULT_V1_b68a27cf8f653602'
EXTRACT_SQL = """
SELECT r.race_date,r.venue_code,r.race_id,e.boat_no,z.actual_course,
       z.finish_position,z.result_status,z.normalization_status,s.result_state
FROM core.race r
LEFT JOIN core.race_entry e USING (race_id)
LEFT JOIN core.race_result z ON z.race_id=e.race_id AND z.boat_no=e.boat_no
LEFT JOIN core.race_result_state s ON s.race_id=r.race_id
WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2026-01-01'
ORDER BY r.race_date,r.race_id,e.boat_no
"""
YEARS = (2023, 2024, 2025)


def digest_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                                     sort_keys=True, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_freeze():
    if sha(FREEZE) != FREEZE_SHA256:
        raise RuntimeError('frozen artifact hash changed')
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    reference = REFERENCE.read_text(encoding='utf-8').replace('\r\n', '\n').encode()
    if hashlib.sha256(reference).hexdigest() != freeze['hashes']['reference_code_sha256_lf']:
        raise RuntimeError('frozen reference code changed')
    if (freeze['freeze_id'] != 'ENTRY_COURSE_INDEX_METHOD_FREEZE_V1'
            or freeze['status'] != 'METHOD_FROZEN'
            or freeze['method']['selected_candidate_id'] != 'RECENT_1Y'
            or freeze['method']['smoothing'] != 'NONE'
            or freeze['method']['grain'] != 'boat_no x actual_course (six by six)'
            or freeze['window']['start_inclusive'] !=
            "previous calendar year's same month and day; Feb 29 maps to Feb 28"
            or freeze['window']['end_exclusive'] != 'prediction date D'
            or freeze['eligibility']['rating_strict_reused'] is not False
            or freeze['zero_history']['status'] != NOT_EVALUABLE
            or freeze['zero_history']['fallback'] != 'NONE'
            or freeze['edogawa']['venue_code'] != EDOGAWA_VENUE_CODE
            or freeze['edogawa']['national_training'] != 'EXCLUDED'
            or freeze['edogawa']['planned_prediction_rule'] != 'predicted_course = boat_no'
            or freeze['edogawa']['entry_fixed_basis'] != 'EDOGAWA_MODEL_RULE'):
        raise RuntimeError('frozen Entry Course specification mismatch')
    return freeze


def source_identity(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(),current_setting('transaction_read_only')")
        if cur.fetchone() != ('boatrace_predictor', 'on'):
            raise RuntimeError('Canonical transaction must be read only')
        cur.execute('''SELECT version_id,authoritative_source,date_start,date_end,
                      source_manifest_hash,normalization_version,result_races,result_boats
                      FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1''')
        row = cur.fetchone()
        if (not row or row[0] != EXPECTED_RESULT_VERSION or row[1] != 'brd_k3'
                or row[2] != date(2017, 1, 1) or row[3] < date(2025, 12, 31)
                or row[5] != 'k3-only-result-v1'):
            raise RuntimeError('expected K3-only Canonical result version is absent')
        version = dict(zip([d[0] for d in cur.description], row))
        version['date_start'] = version['date_start'].isoformat()
        version['date_end'] = version['date_end'].isoformat()
        cur.execute('''SELECT count(*),count(*) FILTER
            (WHERE b.source_table IS DISTINCT FROM 'brd_k3')
            FROM core.race_result z JOIN core.race r USING(race_id)
            LEFT JOIN raw.source_record s ON s.source_record_id=z.source_record_id
            LEFT JOIN raw.source_batch b USING(source_batch_id)
            WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2026-01-01' ''')
        result_boats, non_k3 = cur.fetchone()
        if non_k3:
            raise RuntimeError(f'non-K3 Canonical result lineage: {non_k3}')
        cur.execute('''SELECT count(DISTINCT r.race_id),count(e.boat_no),count(z.boat_no)
            FROM core.race r JOIN core.race_entry e USING(race_id)
            LEFT JOIN core.race_result z USING(race_id,boat_no)
            WHERE r.race_date=DATE '2025-08-12'
              AND r.venue_code IN (1,7,15,19,20)''')
        absent = cur.fetchone()
        if absent != (60, 360, 0):
            raise RuntimeError(f'known K3-absent races changed: {absent}')
    return {'result_dataset_version': version, 'result_boats_2017_2025': result_boats,
            'non_k3_result_boats': non_k3,
            'known_2025_08_12_k3_absent': dict(zip(('races', 'entries', 'results'), absent))}


class Metrics:
    """Same per-entry multiclass and 10-bin top-one definitions as v1 holdout."""
    def __init__(self):
        self.entries = 0
        self.log_sum = 0.0
        self.brier_sum = 0.0
        self.hits = 0
        self.zero_events = 0
        self.top_bins = [[0, 0.0, 0] for _ in range(10)]

    def add(self, probabilities, actual_course):
        if (len(probabilities) != 6 or actual_course not in COURSES
                or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
                or abs(sum(probabilities) - 1) >= 1e-12):
            raise RuntimeError('invalid frozen probability distribution or outcome')
        p_actual = probabilities[actual_course - 1]
        self.entries += 1
        self.zero_events += p_actual == 0
        if p_actual:
            self.log_sum -= math.log(p_actual)
        self.brier_sum += 1 - 2 * p_actual + sum(p * p for p in probabilities)
        top = max(range(6), key=probabilities.__getitem__)
        hit = top == actual_course - 1
        self.hits += hit
        bucket = self.top_bins[min(9, int(probabilities[top] * 10))]
        bucket[0] += 1
        bucket[1] += probabilities[top]
        bucket[2] += hit
        return p_actual == 0

    def result(self):
        n = self.entries
        return {'evaluated_entries': n,
                'log_loss': self.log_sum / n if n and not self.zero_events else None,
                'log_loss_status': ('FINITE' if n and not self.zero_events else
                                    'INFINITE_ZERO_PROBABILITY' if self.zero_events else 'NOT_EVALUABLE'),
                'zero_probability_actuals': self.zero_events,
                'multiclass_brier_sum': self.brier_sum / n if n else None,
                'top1_accuracy': self.hits / n if n else None,
                'top1_ece_10bin': sum(abs(b[1] - b[2]) for b in self.top_bins) / n if n else None}


def make_race(rows):
    first = rows[0]
    if any(row[:3] != first[:3] for row in rows):
        raise RuntimeError('inconsistent race grouping')
    entries = tuple(CourseEntry(row[3], row[4], row[5], row[6] is not None)
                    for row in rows if row[3] is not None)
    return first[2], CourseRace(first[0], first[1], first[8], entries)


def row_bytes(row):
    return (json.dumps([row[0].isoformat(), *row[1:]], ensure_ascii=False,
                       separators=(',', ':')) + '\n').encode()


def replay_rows(rows):
    history = deque()
    totals = {boat: [0] * 6 for boat in COURSES}
    metrics = {year: Metrics() for year in YEARS}
    by_boat = {year: {boat: Metrics() for boat in COURSES} for year in YEARS}
    counts = {year: Counter() for year in YEARS}
    audit = {year: {'min_boat_history_total': {str(boat): None for boat in COURSES},
                    'min_course_cell_count': None, 'zero_course_cell_boat_days': 0,
                    'zero_history_boat_days': 0, 'zero_probability_actuals': []}
             for year in YEARS}
    all_year_counts = Counter()
    input_digest = hashlib.sha256()
    history_digest = hashlib.sha256()
    result_digest = hashlib.sha256()
    previous_day = None
    current_day = None
    race_rows = []
    day_races = []

    def process_day(day, races):
        if day is None:
            return
        start = window_start(day)
        while history and history[0][0] < start:
            _, expired = history.popleft()
            for boat in COURSES:
                for k in range(6):
                    totals[boat][k] -= expired[boat][k]
                    if totals[boat][k] < 0:
                        raise RuntimeError('window count underflow')
        if history and history[-1][0] >= day:
            raise RuntimeError('D or future history in prediction state')
        before = tuple(tuple(totals[boat]) for boat in COURSES)
        frozen = {boat: probabilities_from_counts(before[boat - 1]) for boat in COURSES}
        year = day.year
        if year in YEARS:
            eligible_today = 0
            for _, race in races:
                counts[year]['all_races'] += 1
                if race.venue_code == EDOGAWA_VENUE_CODE:
                    counts[year]['edogawa_races'] += 1
                    if eligible(race):
                        counts[year]['edogawa_eligible_races'] += 1
                        counts[year]['edogawa_eligible_entries'] += 6
                        mismatches = sum(e.actual_course != e.boat_no for e in race.entries)
                        counts[year]['edogawa_mismatched_entries'] += mismatches
                        counts[year]['edogawa_races_with_mismatch'] += bool(mismatches)
                    else:
                        counts[year]['edogawa_excluded_races'] += 1
                    continue
                counts[year]['national_races'] += 1
                if not eligible(race):
                    counts[year]['national_excluded_races'] += 1
                    continue
                counts[year]['national_eligible_races'] += 1
                counts[year]['national_eligible_entries'] += 6
                eligible_today += 1
                for entry in race.entries:
                    prediction = frozen[entry.boat_no]
                    if prediction.status == NOT_EVALUABLE:
                        counts[year]['not_evaluable_entries'] += 1
                        continue
                    zero = metrics[year].add(prediction.probabilities, entry.actual_course)
                    by_boat[year][entry.boat_no].add(prediction.probabilities, entry.actual_course)
                    if zero:
                        audit[year]['zero_probability_actuals'].append(
                            {'date': day.isoformat(), 'race_id': _ ,
                             'boat_no': entry.boat_no, 'actual_course': entry.actual_course})
            if before != tuple(tuple(totals[boat]) for boat in COURSES):
                raise RuntimeError('same-day result changed prediction state')
            if eligible_today:
                for boat in COURSES:
                    total = sum(before[boat - 1])
                    old = audit[year]['min_boat_history_total'][str(boat)]
                    audit[year]['min_boat_history_total'][str(boat)] = total if old is None else min(old, total)
                    audit[year]['zero_history_boat_days'] += total == 0
                    for cell in before[boat - 1]:
                        old_cell = audit[year]['min_course_cell_count']
                        audit[year]['min_course_cell_count'] = cell if old_cell is None else min(old_cell, cell)
                        audit[year]['zero_course_cell_boat_days'] += cell == 0
            history_digest.update(row_bytes((day, start.isoformat(), before)))
        update = {boat: [0] * 6 for boat in COURSES}
        target = []
        for race_id, race in races:
            if race.venue_code != EDOGAWA_VENUE_CODE and eligible(race):
                all_year_counts[(day.year, 'eligible_national_races')] += 1
                for entry in race.entries:
                    update[entry.boat_no][entry.actual_course - 1] += 1
                    target.append((race_id, entry.boat_no, entry.actual_course))
        for boat in COURSES:
            for k in range(6):
                totals[boat][k] += update[boat][k]
        history.append((day, update))
        if year in YEARS:
            result_digest.update(row_bytes((day, tuple(tuple(update[b]) for b in COURSES), target)))

    def accept_race(parsed):
        nonlocal current_day, day_races
        if current_day is not None and parsed[1].race_date != current_day:
            process_day(current_day, day_races)
            day_races = []
        current_day = parsed[1].race_date
        day_races.append(parsed)

    for row in rows:
        day, race_id = row[0], row[2]
        if not date(2017, 1, 1) <= day < date(2026, 1, 1):
            raise RuntimeError('extract crossed replay bounds')
        if previous_day is not None and day < previous_day:
            raise RuntimeError('unordered source dates')
        previous_day = day
        input_digest.update(row_bytes(row))
        all_year_counts[(day.year, 'extract_rows')] += 1
        if race_rows and race_id != race_rows[0][2]:
            accept_race(make_race(race_rows))
            race_rows = []
        race_rows.append(row)
    if race_rows:
        accept_race(make_race(race_rows))
    process_day(current_day, day_races)
    output = {}
    for year in YEARS:
        c = counts[year]
        if (c['national_eligible_entries'] != metrics[year].entries + c['not_evaluable_entries']
                or c['national_races'] != c['national_eligible_races'] + c['national_excluded_races']
                or c['edogawa_races'] != c['edogawa_eligible_races'] + c['edogawa_excluded_races']
                or c['all_races'] != c['national_races'] + c['edogawa_races']
                or sum(x.entries for x in by_boat[year].values()) != metrics[year].entries):
            raise RuntimeError(f'{year} count reconciliation failed')
        output[str(year)] = {'counts': dict(sorted(c.items())), 'overall': metrics[year].result(),
                             'by_boat': {str(b): by_boat[year][b].result() for b in COURSES},
                             'zero_audit': audit[year]}
    return {'years': output, 'all_year_eligible_national_races':
            {str(year): all_year_counts[(year, 'eligible_national_races')]
             for year in range(2017, 2026)},
            'extract_rows_by_year': {str(year): all_year_counts[(year, 'extract_rows')]
                                     for year in range(2017, 2026)},
            'ordered_input_sha256': input_digest.hexdigest(),
            'history_state_sha256': history_digest.hexdigest(),
            'eligible_result_sha256': result_digest.hexdigest(),
            'metrics_sha256': digest_json(output)}


def replay_database():
    freeze = checked_freeze()
    conn = target_connection()
    conn.rollback()
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
        source = source_identity(conn)
        with conn.cursor(name='entry_course_v1_k3_replay') as cur:
            cur.itersize = 20000
            cur.execute(EXTRACT_SQL)
            result = replay_rows(cur)
        return {'source': source, 'replay': result,
                'freeze_sha256': sha(FREEZE),
                'reference_sha256_lf': freeze['hashes']['reference_code_sha256_lf'],
                'source_policy_checkpoint': SOURCE_POLICY_CHECKPOINT,
                'extract_sql_sha256': hashlib.sha256(EXTRACT_SQL.encode()).hexdigest(),
                'window': freeze['window'], 'edogawa_rule': freeze['edogawa']}
    finally:
        conn.rollback()
        conn.close()


def compare(old, new):
    if old is None or new is None:
        return {'old': old, 'new': new, 'absolute_difference': None, 'relative_difference': None}
    delta = new - old
    return {'old': old, 'new': new, 'absolute_difference': delta,
            'relative_difference': delta / old if old else None}


def comparison(result):
    # Historical aggregates are used only for old-vs-new reporting, never as replay input or a gate.
    dev = json.loads(OLD_DEV.read_text(encoding='utf-8'))
    old_holdout = json.loads(OLD_2025.read_text(encoding='utf-8'))
    fields = ('national_eligible_races', 'national_eligible_entries', 'not_evaluable_entries',
              'zero_probability_actuals', 'log_loss', 'multiclass_brier_sum',
              'top1_accuracy', 'top1_ece_10bin')
    output = {}
    for year in YEARS:
        new = result['replay']['years'][str(year)]
        if year == 2025:
            old_counts = old_holdout['counts']
            old_metrics = old_holdout['overall']
        else:
            old_counts = {'national_eligible_entries':
                          dev['evaluation']['methods']['RECENT_1Y'][str(year)]['entries']}
            old_counts['national_eligible_races'] = old_counts['national_eligible_entries'] // 6
            original = dev['evaluation']['methods']['RECENT_1Y'][str(year)]
            old_metrics = {'zero_probability_actuals': original['zero_probability_actuals'],
                           'log_loss': original['log_loss_epsilon_1e15'],
                           'multiclass_brier_sum': original['multiclass_brier_sum'],
                           'top1_accuracy': original['top1_accuracy'],
                           'top1_ece_10bin': original['calibration_ece_10bin_top1']}
        old_counts.setdefault('not_evaluable_entries', 0)
        new_values = {**new['counts'], **new['overall']}
        old_values = {**old_counts, **old_metrics}
        output[str(year)] = {key: compare(old_values.get(key, 0), new_values.get(key, 0))
                             for key in fields}
    return {'historical_baseline_only': True,
            'old_development_artifact_sha256': sha(OLD_DEV),
            'old_2025_artifact_sha256': sha(OLD_2025),
            'by_year': output}


def write_json(path, value):
    if path.exists():
        raise RuntimeError(f'refusing to overwrite {path}')
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False,
                               default=str) + '\n', encoding='utf-8')


def report(result, differences):
    lines = [
        '# Entry Course Index v1 K3-only source-corrected reevaluation', '',
        'Frozen method: NATIONAL_BOAT_NO_ACTUAL_COURSE_FREQUENCY / RECENT_1Y. '
        'The method and freeze artifact were not changed; no method reselection used 2025.', '',
        f"Source-policy checkpoint: `{SOURCE_POLICY_CHECKPOINT}`. K3 Canonical version: "
        f"`{EXPECTED_RESULT_VERSION}`. Freeze SHA-256: `{FREEZE_SHA256}`.", '',
        'The read-only replay starts on 2017-01-01. Each day D uses the preceding '
        'calendar-year same date (Feb 29 maps to Feb 28), inclusive, through D exclusive. '
        'All D races use one D-1 state; eligible results are appended after scoring D.', '',
        'Six-boat eligibility follows the freeze artifact. Edogawa is excluded from the '
        'national 6x6 counts and from all three scored cohorts. Its planned prediction '
        'rule remains predicted_course=boat_no, entry_fixed_effective=true, '
        'entry_fixed_basis=EDOGAWA_MODEL_RULE; Prediction integration is still absent.', '',
        'No smoothing or epsilon was applied. Zero cells have probability zero; zero '
        'boat history is NOT_EVALUABLE. A zero actual-outcome probability would make '
        'the unclipped log loss infinite.', '',
        '| Year | Eligible races old→new | Entries old→new | NOT_EVALUABLE old→new | '
        'Zero actual p old→new | Log loss old→new | Brier old→new | Top1 old→new | ECE old→new |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    mapping = (('national_eligible_races', 0), ('national_eligible_entries', 0),
               ('not_evaluable_entries', 0), ('zero_probability_actuals', 0),
               ('log_loss', 9), ('multiclass_brier_sum', 9),
               ('top1_accuracy', 9), ('top1_ece_10bin', 9))
    for year in YEARS:
        diff = differences['by_year'][str(year)]
        cells = []
        for key, decimals in mapping:
            pair = diff[key]
            fmt = lambda x: 'null' if x is None else f'{x:.{decimals}f}'
            cells.append(f"{fmt(pair['old'])}→{fmt(pair['new'])}")
        lines.append('| ' + str(year) + ' | ' + ' | '.join(cells) + ' |')
    lines.extend(['', 'Full absolute and relative differences are in the comparison JSON. '
                  'The old development aggregate and old 2025 holdout are historical '
                  'comparison values only, never formal K3 input or validation.', '',
                  '## Source and zero-probability audit', '',
                  f"K3-lineage result boats: {result['source']['result_boats_2017_2025']:,}; "
                  f"non-K3: {result['source']['non_k3_result_boats']}. "
                  'The known 2025-08-12 K3-absent set has 60 races, 360 entries, '
                  'and zero Canonical results; old actual_course values were not carried forward.', ''])
    for year in YEARS:
        audit = result['replay']['years'][str(year)]['zero_audit']
        lines.append(f"- {year}: boat-number minimum history totals "
                     f"{audit['min_boat_history_total']}; minimum course-cell count "
                     f"{audit['min_course_cell_count']}; zero-cell boat-days "
                     f"{audit['zero_course_cell_boat_days']}; zero-history boat-days "
                     f"{audit['zero_history_boat_days']}; actual-outcome probability-zero "
                     f"{len(audit['zero_probability_actuals'])}.")
    lines.extend(['', '## Replay identity', '',
                  f"Ordered input SHA-256: `{result['replay']['ordered_input_sha256']}`.",
                  f"History state SHA-256: `{result['replay']['history_state_sha256']}`.",
                  f"Eligible result SHA-256: `{result['replay']['eligible_result_sha256']}`.",
                  f"Metrics SHA-256: `{result['replay']['metrics_sha256']}`.", '',
                  'A separate verify run must match these hashes and all replay data '
                  'before this report is committed.', '',
                  'The source-correction effects are the changed K3 Canonical training '
                  'windows and scored outcome cohort. Prior migration recorded two '
                  '2023 actual-course corrections, added K3 results, and 60 unsupported '
                  '2025-08-12 race results removed. This replay does not consult R3 to '
                  'attribute individual score differences. Full historical publication '
                  'vintage availability remains unverified, as in the v1 freeze.'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'verify'))
    action = parser.parse_args().action
    result = replay_database()
    if action == 'run':
        differences = comparison(result)
        for path in (DEV_OUT, HOLDOUT_OUT, COMPARISON_OUT, REPORT_OUT, REPLAY_OUT):
            if path.exists():
                raise RuntimeError(f'output exists: {path}')
        shared = {key: result[key] for key in ('source', 'freeze_sha256', 'reference_sha256_lf',
                                                'source_policy_checkpoint', 'extract_sql_sha256',
                                                'window', 'edogawa_rule')}
        write_json(DEV_OUT, {**shared, 'years': {y: result['replay']['years'][y]
                                                  for y in ('2023', '2024')},
                             'replay_hashes': {key: result['replay'][key] for key in
                                               ('ordered_input_sha256', 'history_state_sha256',
                                                'eligible_result_sha256', 'metrics_sha256')}})
        write_json(HOLDOUT_OUT, {**shared, 'year': result['replay']['years']['2025'],
                                 'replay_hashes': {key: result['replay'][key] for key in
                                                   ('ordered_input_sha256', 'history_state_sha256',
                                                    'eligible_result_sha256', 'metrics_sha256')}})
        write_json(COMPARISON_OUT, {**shared, **differences})
        write_json(REPLAY_OUT, result)
        REPORT_OUT.write_text(report(result, differences), encoding='utf-8')
    else:
        recorded = json.loads(REPLAY_OUT.read_text(encoding='utf-8'))
        if recorded != result:
            raise RuntimeError('deterministic K3 replay differs')
        for path in (DEV_OUT, HOLDOUT_OUT, COMPARISON_OUT, REPORT_OUT):
            if not path.exists():
                raise RuntimeError(f'missing output: {path}')
        verification = {
            'status': 'DETERMINISTIC_REPLAY_PASS',
            'independent_database_replay': True,
            'source_policy_checkpoint': SOURCE_POLICY_CHECKPOINT,
            'freeze_sha256': FREEZE_SHA256,
            'first_run_artifact_sha256': sha(REPLAY_OUT),
            'ordered_input_sha256': result['replay']['ordered_input_sha256'],
            'history_state_sha256': result['replay']['history_state_sha256'],
            'eligible_result_sha256': result['replay']['eligible_result_sha256'],
            'metrics_sha256': result['replay']['metrics_sha256'],
            'full_replay_data_equal': True,
        }
        if VERIFY_OUT.exists():
            if json.loads(VERIFY_OUT.read_text(encoding='utf-8')) != verification:
                raise RuntimeError('existing deterministic verification differs')
        else:
            write_json(VERIFY_OUT, verification)
    print(json.dumps({'action': action, 'status': 'PASS',
                      'input_sha256': result['replay']['ordered_input_sha256'],
                      'history_sha256': result['replay']['history_state_sha256'],
                      'result_sha256': result['replay']['eligible_result_sha256'],
                      'metrics_sha256': result['replay']['metrics_sha256'],
                      'annual_eligible_races': {y: result['replay']['years'][str(y)]['counts']['national_eligible_races']
                                                for y in YEARS}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
